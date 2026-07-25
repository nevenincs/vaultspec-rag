"""Lightweight RSS + CUDA memory probe for index pipelines.

Gated by the ``VAULTSPEC_RAG_MEMORY_PROBE`` env var.  When enabled the
probe records resident-set size (RSS) and ``torch.cuda.memory_allocated/
reserved`` at named checkpoints and emits a structured report.

The probe is intentionally self-contained: it has no hard dependency on
any other indexer module so it can be used from tests, benchmarks, and
ad-hoc scripts without pulling the full import graph.
"""

from __future__ import annotations

import contextlib
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, cast

from ._job_errors import JobError, JobErrorKind
from ._units import bytes_to_mib, mib_to_bytes

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

logger = logging.getLogger(__name__)

__all__ = [
    "MemoryBudget",
    "MemoryBudgetSnapshot",
    "MemoryProbe",
    "MemorySample",
    "cuda_forward_peak_capture",
    "current_cuda_mb",
    "current_rss_mb",
    "is_enabled",
    "record_forward_peaks",
    "reset_cuda_peak_memory_stats",
    "resident_cuda_baseline_mb",
    "sample_resident_cuda_baseline",
    "snapshot_resource_bytes",
]


ENV_VAR = "VAULTSPEC_RAG_MEMORY_PROBE"

# Module-level caches for hot-path samplers. ``current_rss_mb`` and
# ``current_cuda_mb`` are called once per 250 ms by the background
# sampler - re-importing psutil/torch and re-instantiating
# ``psutil.Process`` on every call is wasteful. Cache on first use.
# ``Any`` is intentional: torch is an optional dependency on some
# install matrices, and ty cannot narrow our own sentinel probe.
_psutil_process: Any = None
_torch_module: Any = None
_torch_probed: bool = False
_torch_has_cuda: bool = False


def is_enabled() -> bool:
    """Return ``True`` when the memory probe is active.

    The probe activates when ``VAULTSPEC_RAG_MEMORY_PROBE`` is set to a
    non-empty, non-``0`` value.
    """
    value = os.environ.get(ENV_VAR, "")
    return bool(value) and value != "0"


def _measure_rss_mb() -> float | None:
    """Return current process RSS in MiB, or ``None`` when unavailable."""
    global _psutil_process
    try:
        import psutil
    except ImportError:
        return None
    try:
        if _psutil_process is None:
            _psutil_process = psutil.Process(os.getpid())
        return bytes_to_mib(_psutil_process.memory_info().rss)
    except (
        psutil.NoSuchProcess,
        psutil.AccessDenied,
        psutil.ZombieProcess,
    ):
        # Drop the cached handle so a subsequent call can re-probe
        # (the PID may legitimately have changed across a fork).
        _psutil_process = None
        return None


def current_rss_mb() -> float:
    """Return current process RSS in megabytes.

    ``psutil`` is a hard dependency of the RAG package so this is
    always available; the import is deferred only to keep cold-path
    startup cheap when the probe is disabled. The ``psutil.Process``
    handle is cached on first call because this function runs at
    250 ms cadence from the background sampler.

    Returns ``0.0`` (rather than raising) on any psutil failure -
    the sampler thread must survive transient errors so a single
    bad reading does not silently kill RSS tracking for the rest
    of the run.
    """
    measured = _measure_rss_mb()
    return measured if measured is not None else 0.0


def _measure_cuda_mb() -> tuple[float, float] | None:
    """Return CUDA allocated/reserved MiB, or ``None`` when unavailable."""
    global _torch_module, _torch_probed, _torch_has_cuda
    if not _torch_probed:
        # Set _torch_probed last so a transient failure from
        # is_available() (e.g. driver hiccup on first touch) does
        # not get cached as "no CUDA forever". If the import fails
        # we intentionally do cache the negative result because
        # missing torch is a permanent condition.
        try:
            import torch as _torch
        except ImportError:
            _torch_module = None
            _torch_has_cuda = False
            _torch_probed = True
        else:
            try:
                has_cuda = _torch.cuda.is_available()
            except (RuntimeError, AssertionError):
                return None
            _torch_module = _torch
            _torch_has_cuda = has_cuda
            _torch_probed = True
    if _torch_module is None or not _torch_has_cuda:
        return None
    try:
        allocated = bytes_to_mib(_torch_module.cuda.memory_allocated())
        reserved = bytes_to_mib(_torch_module.cuda.memory_reserved())
    except (RuntimeError, AssertionError):
        return None
    return (allocated, reserved)


def cuda_device_total_mb() -> float | None:
    """Return the active CUDA device's total memory in MiB, or ``None``.

    A guarded probe, not a hard gate: it returns ``None`` on a torch-absent or
    CPU-only host rather than raising, so the ceiling derivation degrades to its
    profile fallback off the GPU compute path and never forces torch onto a
    service-client or worker path. Shares the cached module probe with
    :func:`_measure_cuda_mb`.
    """
    _measure_cuda_mb()
    if _torch_module is None or not _torch_has_cuda:
        return None
    try:
        props = _torch_module.cuda.get_device_properties(
            _torch_module.cuda.current_device()
        )
        return bytes_to_mib(props.total_memory)
    except (RuntimeError, AssertionError):
        return None


def cuda_free_memory_mb() -> float | None:
    """Return the active CUDA device's free memory in MiB, or ``None``.

    A guarded probe, not a hard gate: it returns ``None`` on a torch-absent or
    CPU-only host rather than raising, so the ceiling derivation degrades to
    its total-memory (or profile) fallback off the GPU compute path and never
    forces torch onto a service-client or worker path. Shares the cached
    module probe with :func:`_measure_cuda_mb`.
    """
    _measure_cuda_mb()
    if _torch_module is None or not _torch_has_cuda:
        return None
    try:
        return bytes_to_mib(_torch_module.cuda.mem_get_info()[0])
    except (RuntimeError, AssertionError):
        return None


def resolve_index_cuda_ceiling_mb(
    *,
    configured_mb: float,
    headroom_mb: float,
    profile_cuda_mb: float,
    baseline_mb: float,
) -> float:
    """Resolve the effective indexing CUDA ceiling in MiB.

    A positive ``configured_mb`` is an authoritative operator override that wins
    in either direction - it may raise the ceiling above the profile figure as
    well as lower it below, replacing the former one-way ``min`` clamp. When it
    is unset (zero or negative), the ceiling is derived from the real device as
    an ABSOLUTE figure: ``min(baseline_mb + free - headroom_mb,
    total - headroom_mb)``. Free memory is sampled after the resident models
    loaded, so it already excludes them - and enforcement compares peak and
    ceiling net of the resident baseline, so ``baseline_mb`` must be added back
    here. A bare ``free - headroom`` ceiling would charge the resident models
    twice (once inside the free reading, once via the baseline-net comparison)
    and falsely reject legitimate forwards. When the free reading is
    unavailable the derivation falls back to ``total - headroom_mb``; off the
    GPU compute path the device total is also unavailable, so it falls back to
    ``profile_cuda_mb`` - the profile figure becomes a default rather than a
    hard cap.
    """
    return cuda_ceiling_from_observation(
        device_total_mb=cuda_device_total_mb(),
        free_mb=cuda_free_memory_mb(),
        configured_mb=configured_mb,
        headroom_mb=headroom_mb,
        profile_cuda_mb=profile_cuda_mb,
        baseline_mb=baseline_mb,
    )


def cuda_ceiling_from_observation(
    *,
    device_total_mb: float | None,
    free_mb: float | None,
    configured_mb: float,
    headroom_mb: float,
    profile_cuda_mb: float,
    baseline_mb: float,
) -> float:
    """Derive the ceiling from one device observation.

    The arithmetic and the measurement are separate concerns: what a given
    pair of readings should yield does not depend on how they were obtained.
    Keeping them apart means the derivation can be exercised over the readings
    that matter - an absent total, an absent free figure, a device smaller
    than the profile - without a machine that happens to present them.

    ``None`` means the corresponding probe had nothing to report.
    """
    if configured_mb and configured_mb > 0:
        return float(configured_mb)
    if device_total_mb is None:
        return float(profile_cuda_mb)
    total_capped = max(0.0, device_total_mb - headroom_mb)
    if free_mb is None:
        return total_capped
    return max(0.0, min(baseline_mb + free_mb - headroom_mb, total_capped))


def current_cuda_mb() -> tuple[float, float]:
    """Return ``(allocated_mb, reserved_mb)`` for the active CUDA device.

    Returns zeros when torch is not importable or CUDA is unavailable -
    the probe must never crash host code. The torch module reference
    and the CUDA availability flag are cached on first call so the
    background sampler does not pay repeated import / probe costs.
    """
    measured = _measure_cuda_mb()
    return measured if measured is not None else (0.0, 0.0)


def reset_cuda_peak_memory_stats() -> bool:
    """Release the allocator cache and rebase peak counters at job admission.

    Invoked once per admitted indexing run, after models are resident and
    before dispatch. Enforcement no longer reads the process-global peak
    counters - each job enforces its own lock-bracketed forward captures -
    so this reset is allocator hygiene: the cache release defragments the
    retention history a long-lived process accumulates before a new run
    starts allocating.
    """
    measured = _measure_cuda_mb()
    if measured is None or _torch_module is None:
        return False
    try:
        _torch_module.cuda.empty_cache()
        _torch_module.cuda.reset_peak_memory_stats()
    except (RuntimeError, AssertionError):
        return False
    return True


def _reset_cuda_peak_stats_bare() -> bool:
    """Rebase the allocator peak counters without flushing the cache.

    The per-forward capture bracket runs inside the GPU-lock hold; flushing
    the allocator cache there would add a device synchronisation to every
    encode sub-batch, so this reset deliberately omits ``empty_cache`` (the
    per-run admission reset keeps that job).
    """
    measured = _measure_cuda_mb()
    if measured is None or _torch_module is None:
        return False
    try:
        _torch_module.cuda.reset_peak_memory_stats()
    except (RuntimeError, AssertionError):
        return False
    return True


def _read_cuda_peak_allocated_mb() -> float | None:
    """Return the allocated high-water in MiB since the last rebase.

    This is the single sanctioned reader of the process-global peak counter,
    and it is only meaningful inside the GPU-lock-held capture bracket that
    just rebased it; enforcement paths consume the captured value, never
    this counter directly.
    """
    measured = _measure_cuda_mb()
    if measured is None or _torch_module is None:
        return None
    try:
        return bytes_to_mib(_torch_module.cuda.max_memory_allocated())
    except (RuntimeError, AssertionError):
        return None


_resident_baseline_lock = threading.Lock()
_resident_baseline_mb: float = 0.0


def sample_resident_cuda_baseline() -> float:
    """Record the resident-model CUDA allocation as a monotonic baseline.

    Called after each shared model finishes loading - the embedding stack
    eagerly, the reranker lazily on first use - so a late lazy load raises
    the recorded baseline instead of leaving it understated. The baseline
    only ever grows: a transient dip (eviction mid-run) must not shrink the
    figure an in-flight job's budget was constructed against.

    Returns:
        The updated baseline in MiB (``0.0`` off the GPU path).
    """
    global _resident_baseline_mb
    measured = _measure_cuda_mb()
    if measured is None:
        return resident_cuda_baseline_mb()
    allocated = measured[0]
    with _resident_baseline_lock:
        if allocated > _resident_baseline_mb:
            _resident_baseline_mb = allocated
        return _resident_baseline_mb


def resident_cuda_baseline_mb() -> float:
    """Return the recorded resident-model CUDA baseline in MiB."""
    with _resident_baseline_lock:
        return _resident_baseline_mb


_forward_peak_recorder = threading.local()


@contextlib.contextmanager
def record_forward_peaks(
    recorder: Callable[[float], None],
) -> Generator[None]:
    """Route this thread's captured forward peaks to *recorder*.

    Attribution is by thread: every GPU forward a job issues runs on the
    thread that entered this context (the job's own consumer thread), so a
    capture bracket completing on this thread belongs to this job and no
    other. Nested contexts restore the previous recorder on exit.
    """
    previous = getattr(_forward_peak_recorder, "value", None)
    _forward_peak_recorder.value = recorder
    try:
        yield
    finally:
        _forward_peak_recorder.value = previous


@contextlib.contextmanager
def cuda_forward_peak_capture() -> Generator[None]:
    """Bracket one model forward with a job-local peak capture.

    Must run inside the GPU-lock hold that serialises the forward: the
    critical section is what makes the reading job-local. The peak counter
    is rebased on entry and read on exit while no sibling forward can run,
    so the captured value is this forward's own demand (resident baseline
    included) and never a concurrent job's. The read also happens on an
    exceptional exit so an allocator OOM still records the demand that
    triggered it.
    """
    armed = _reset_cuda_peak_stats_bare()
    try:
        yield
    finally:
        if armed:
            peak = _read_cuda_peak_allocated_mb()
            recorder = getattr(_forward_peak_recorder, "value", None)
            if peak is not None and recorder is not None:
                try:
                    recorder(peak)
                except Exception:
                    logger.warning(
                        "forward peak recorder failed; capture dropped",
                        exc_info=True,
                    )


@dataclass
class MemorySample:
    """A single checkpoint recorded by :class:`MemoryProbe`.

    Attributes:
        label: Human-readable checkpoint name (e.g. ``"after dense
            encode batch 3"``).
        rss_mb: Process resident-set size at the checkpoint.
        cuda_allocated_mb: Live ``torch.cuda.memory_allocated`` value.
        cuda_reserved_mb: Live ``torch.cuda.memory_reserved`` value.
        wall_s: Seconds since the probe was constructed.
    """

    label: str
    rss_mb: float
    cuda_allocated_mb: float
    cuda_reserved_mb: float
    wall_s: float


@dataclass(frozen=True, slots=True)
class MemoryBudgetSnapshot:
    """One immutable view of enforced process and CUDA memory state.

    ``rss_ceiling_mb`` and ``cuda_ceiling_mb`` are absolute process readings
    frozen by admission.  A caller enforcing per-run headroom adds its admitted
    baseline before constructing :class:`MemoryBudget`.  A reading exactly at
    its ceiling is admitted; only a reading above the ceiling is a violation.
    """

    label: str
    rss_mb: float
    rss_available: bool
    peak_rss_mb: float
    rss_ceiling_mb: float | None
    cuda_allocated_mb: float
    cuda_available: bool
    peak_cuda_allocated_mb: float
    cuda_reserved_mb: float
    peak_cuda_reserved_mb: float
    cuda_ceiling_mb: float | None


def snapshot_resource_bytes(snapshot: MemoryBudgetSnapshot) -> tuple[int, int]:
    """Project a snapshot's high-water readings into corpus-limit bytes.

    Returns ``(rss_bytes, cuda_bytes)`` for the resource-measurement dimensions
    the support limits are denominated in.

    The CUDA dimension carries the allocated high-water - real demand - and
    never the reserved one. Reserved ratchets with the allocator's retention
    history rather than with the work, so a profile limit that equals the
    enforcement ceiling would fail well-sized jobs on nothing but fragmentation
    inherited from earlier runs. Every indexer projects through here so that
    choice is made once and cannot drift between them.
    """
    return (
        mib_to_bytes(snapshot.peak_rss_mb),
        mib_to_bytes(snapshot.peak_cuda_allocated_mb),
    )


class MemoryBudget:
    """Enforce frozen RSS and CUDA ceilings at explicit safe checkpoints.

    Safety is never gated by :func:`is_enabled`; constructing a budget enables
    it.  :meth:`sample` deliberately acquires no GPU lock and must be called at
    boundaries outside ``gpu_lock`` (before/after forward calls, after durable
    commits, and during prolonged waits).  :meth:`observe` contains the pure,
    deterministic threshold policy so callers and tests can evaluate a known
    production reading without replacing the process samplers.

    The CUDA ceiling is enforced against the allocated high-water reading -
    the demand of the admitted work.  Reserved (the caching allocator's
    retained pool) is sampled and reported as a fragmentation diagnostic but
    never decides job outcome: it ratchets with process retention history,
    so enforcing it fails well-sized jobs for work they did not do.  The
    first RSS breach wins when host and device ceilings are crossed in the
    same observation; otherwise the allocated high-water produces
    ``cuda_memory_ceiling``.  The
    first violating observation and outcome are latched atomically before the
    typed error is raised; every subsequent observation raises that outcome.
    """

    __slots__ = (
        "_captured_cuda_peak_mb",
        "_cuda_baseline_mb",
        "_cuda_ceiling_mb",
        "_failure",
        "_lock",
        "_rss_ceiling_mb",
        "_snapshot",
    )

    _captured_cuda_peak_mb: float
    _cuda_baseline_mb: float | None
    _cuda_ceiling_mb: float | None
    _failure: tuple[JobErrorKind, str] | None
    _lock: threading.Lock
    _rss_ceiling_mb: float | None
    _snapshot: MemoryBudgetSnapshot | None

    def __init__(
        self,
        *,
        rss_ceiling_mb: float | None = None,
        cuda_ceiling_mb: float | None = None,
        cuda_baseline_mb: float | None = None,
    ) -> None:
        object.__setattr__(
            self,
            "_rss_ceiling_mb",
            _valid_memory_mb(
                "rss_ceiling_mb",
                rss_ceiling_mb,
                optional=True,
            ),
        )
        object.__setattr__(
            self,
            "_cuda_ceiling_mb",
            _valid_memory_mb(
                "cuda_ceiling_mb",
                cuda_ceiling_mb,
                optional=True,
            ),
        )
        object.__setattr__(
            self,
            "_cuda_baseline_mb",
            _valid_memory_mb(
                "cuda_baseline_mb",
                cuda_baseline_mb,
                optional=True,
            ),
        )
        object.__setattr__(self, "_captured_cuda_peak_mb", 0.0)
        object.__setattr__(self, "_snapshot", None)
        object.__setattr__(self, "_failure", None)
        object.__setattr__(self, "_lock", threading.Lock())

    def __setattr__(self, name: str, value: object) -> None:
        """Reject ordinary mutation of admitted limits and enforcement state."""
        del value
        msg = f"{type(self).__name__}.{name} is read-only"
        raise AttributeError(msg)

    def __delattr__(self, name: str) -> None:
        """Reject deletion of admitted limits and enforcement state."""
        msg = f"{type(self).__name__}.{name} is read-only"
        raise AttributeError(msg)

    @property
    def rss_ceiling_mb(self) -> float | None:
        """Return the immutable admitted process RSS ceiling."""
        return self._rss_ceiling_mb

    @property
    def cuda_ceiling_mb(self) -> float | None:
        """Return the immutable admitted CUDA allocated-high-water ceiling."""
        return self._cuda_ceiling_mb

    @property
    def cuda_baseline_mb(self) -> float | None:
        """Return the admitted resident-model baseline, if one was frozen."""
        return self._cuda_baseline_mb

    @property
    def captured_cuda_peak_mb(self) -> float:
        """Return the maximum lock-bracketed forward peak recorded so far."""
        with self._lock:
            return self._captured_cuda_peak_mb

    def record_forward_peak_mb(self, peak_mb: float) -> None:
        """Accumulate one lock-bracketed forward peak as this job's maximum.

        Fed by the GPU-lock-held capture bracket; the retained value is the
        job's own demand across all of its forwards, so checkpoints enforce
        against work this job genuinely did rather than a process-wide
        high-water shared with concurrent jobs.
        """
        value = cast("float", _valid_memory_mb("peak_mb", peak_mb))
        with self._lock:
            if value > self._captured_cuda_peak_mb:
                object.__setattr__(self, "_captured_cuda_peak_mb", value)

    @property
    def snapshot(self) -> MemoryBudgetSnapshot | None:
        """Return the most recent immutable current/peak/ceiling view."""
        with self._lock:
            return self._snapshot

    def sample(self, label: str) -> MemoryBudgetSnapshot:
        """Measure and enforce the budget outside ``gpu_lock``.

        This method never acquires or accepts the GPU lock.  Callers own the
        architectural invariant that it runs before or after, never inside, a
        model forward critical section. The CUDA peak it enforces is the
        job's own captured forward maximum - fed from inside the lock via
        :meth:`record_forward_peak_mb` - never the process-global allocator
        high-water, whose since-reset span covers every concurrent job. The
        live allocated/reserved readings taken here remain process-global
        diagnostics and do not decide outcome.
        """
        self._raise_if_latched()
        measured_rss = _measure_rss_mb()
        measured_cuda = _measure_cuda_mb() if self.cuda_ceiling_mb is not None else None
        return self.sample_readings(
            label=label,
            rss_mb=measured_rss,
            cuda_mb=measured_cuda,
        )

    def sample_readings(
        self,
        *,
        label: str,
        rss_mb: float | None,
        cuda_mb: tuple[float, float] | None,
    ) -> MemoryBudgetSnapshot:
        """Enforce the budget over readings the caller already holds.

        What a set of readings means for enforcement does not depend on how
        they were obtained, and the distinction this method carries is the
        load-bearing one: the enforced CUDA peak is the job's own captured
        forward maximum, while the live allocated and reserved figures stay
        diagnostics. A process-global reading taken while a sibling holds the
        device must therefore not decide this job's outcome.

        ``None`` means the corresponding probe had nothing to report.
        """
        self._raise_if_latched()
        measured_rss = rss_mb
        measured_cuda = cuda_mb
        return self._record(
            label=label,
            rss_mb=measured_rss if measured_rss is not None else 0.0,
            rss_available=measured_rss is not None,
            cuda_allocated_mb=measured_cuda[0] if measured_cuda is not None else 0.0,
            cuda_reserved_mb=measured_cuda[1] if measured_cuda is not None else 0.0,
            cuda_peak_allocated_mb=(
                self.captured_cuda_peak_mb if measured_cuda is not None else 0.0
            ),
            cuda_peak_reserved_mb=(
                measured_cuda[1] if measured_cuda is not None else 0.0
            ),
            cuda_available=measured_cuda is not None,
        )

    def observe(
        self,
        *,
        label: str,
        rss_mb: float,
        cuda_allocated_mb: float,
        cuda_reserved_mb: float,
    ) -> MemoryBudgetSnapshot:
        """Record known measurements and raise on the first crossed ceiling.

        The comparison is strict (``current > ceiling``), all values are MiB,
        and RSS takes deterministic precedence over CUDA for a simultaneous
        breach.  Peak values include the violating observation.
        """
        self._raise_if_latched()
        rss = cast("float", _valid_memory_mb("rss_mb", rss_mb))
        allocated = cast(
            "float",
            _valid_memory_mb("cuda_allocated_mb", cuda_allocated_mb),
        )
        reserved = cast(
            "float",
            _valid_memory_mb("cuda_reserved_mb", cuda_reserved_mb),
        )
        return self._record(
            label=label,
            rss_mb=rss,
            rss_available=True,
            cuda_allocated_mb=allocated,
            cuda_reserved_mb=reserved,
            cuda_peak_allocated_mb=allocated,
            cuda_peak_reserved_mb=reserved,
            cuda_available=True,
        )

    def fail_cuda_oom(self, *, label: str, detail: str) -> None:
        """Latch allocator exhaustion as the canonical CUDA ceiling outcome."""
        snapshot = self.sample(label)
        failure = (
            JobErrorKind.CUDA_MEMORY_CEILING,
            f"CUDA allocator exhausted at {snapshot.label}: {detail}",
        )
        with self._lock:
            if self._failure is None:
                object.__setattr__(self, "_failure", failure)
            else:
                failure = self._failure
        raise JobError(*failure)

    def _raise_if_latched(self) -> None:
        """Raise the first terminal budget failure, if one has been recorded."""
        with self._lock:
            failure = self._failure
        if failure is not None:
            raise JobError(*failure)

    def _record(
        self,
        *,
        label: str,
        rss_mb: float,
        rss_available: bool,
        cuda_allocated_mb: float,
        cuda_reserved_mb: float,
        cuda_peak_allocated_mb: float,
        cuda_peak_reserved_mb: float,
        cuda_available: bool,
    ) -> MemoryBudgetSnapshot:
        """Atomically retain one observation and latch its first violation."""
        if not label.strip():
            msg = "memory budget sample label must not be empty"
            raise ValueError(msg)

        with self._lock:
            if self._failure is not None:
                failure = self._failure
                snapshot = None
            else:
                previous = self._snapshot
                snapshot = MemoryBudgetSnapshot(
                    label=label,
                    rss_mb=rss_mb,
                    rss_available=rss_available,
                    peak_rss_mb=max(
                        rss_mb if rss_available else 0.0,
                        previous.peak_rss_mb if previous else 0.0,
                    ),
                    rss_ceiling_mb=self.rss_ceiling_mb,
                    cuda_allocated_mb=cuda_allocated_mb,
                    cuda_available=cuda_available,
                    peak_cuda_allocated_mb=max(
                        cuda_peak_allocated_mb if cuda_available else 0.0,
                        previous.peak_cuda_allocated_mb if previous else 0.0,
                    ),
                    cuda_reserved_mb=cuda_reserved_mb,
                    peak_cuda_reserved_mb=max(
                        cuda_peak_reserved_mb if cuda_available else 0.0,
                        previous.peak_cuda_reserved_mb if previous else 0.0,
                    ),
                    cuda_ceiling_mb=self.cuda_ceiling_mb,
                )
                failure = self._classify_failure(snapshot)
                object.__setattr__(self, "_snapshot", snapshot)
                if failure is not None:
                    object.__setattr__(self, "_failure", failure)

        if failure is not None:
            raise JobError(*failure)
        if snapshot is None:
            msg = "memory budget latch invariant violated"
            raise RuntimeError(msg)
        return snapshot

    def _classify_failure(
        self,
        snapshot: MemoryBudgetSnapshot,
    ) -> tuple[JobErrorKind, str] | None:
        """Return the deterministic typed failure for one locked observation."""
        if self.rss_ceiling_mb is not None:
            if not snapshot.rss_available:
                return (
                    JobErrorKind.RSS_MEMORY_CEILING,
                    _measurement_unavailable_detail(
                        label=snapshot.label,
                        measure="RSS",
                        ceiling_mb=self.rss_ceiling_mb,
                    ),
                )
            if snapshot.rss_mb > self.rss_ceiling_mb:
                return (
                    JobErrorKind.RSS_MEMORY_CEILING,
                    _ceiling_detail(
                        label=snapshot.label,
                        measure="RSS",
                        current_mb=snapshot.rss_mb,
                        ceiling_mb=self.rss_ceiling_mb,
                    ),
                )
        if self.cuda_ceiling_mb is not None:
            if not snapshot.cuda_available:
                return (
                    JobErrorKind.CUDA_MEMORY_CEILING,
                    _measurement_unavailable_detail(
                        label=snapshot.label,
                        measure="CUDA",
                        ceiling_mb=self.cuda_ceiling_mb,
                    ),
                )
            # Baseline-consistent comparison: a captured peak is absolute
            # (a post-rebase counter starts at the resident models), so the
            # baseline must come off the peak and the ceiling on the SAME
            # side. Subtracting it from only one side double-counts the
            # resident models and turns the ceiling into a covert tightening.
            baseline = self._cuda_baseline_mb or 0.0
            peak_above_baseline = max(
                0.0,
                snapshot.peak_cuda_allocated_mb - baseline,
            )
            ceiling_above_baseline = max(0.0, self.cuda_ceiling_mb - baseline)
            if peak_above_baseline > ceiling_above_baseline:
                measure = "CUDA allocated high-water"
                if baseline > 0.0:
                    measure = (
                        "CUDA allocated high-water above the "
                        f"{baseline:.1f} MiB resident baseline"
                    )
                return (
                    JobErrorKind.CUDA_MEMORY_CEILING,
                    _ceiling_detail(
                        label=snapshot.label,
                        measure=measure,
                        current_mb=peak_above_baseline,
                        ceiling_mb=ceiling_above_baseline,
                    ),
                )
        return None


def _valid_memory_mb(
    name: str,
    value: float | None,
    *,
    optional: bool = False,
) -> float | None:
    """Return one finite, non-negative MiB reading or ceiling."""
    if value is None:
        if optional:
            return None
        msg = f"{name} must be a finite, non-negative number"
        raise ValueError(msg)
    if isinstance(value, bool):
        msg = f"{name} must be a finite, non-negative number, got {value!r}"
        raise ValueError(msg)
    result = float(value)
    if not math.isfinite(result) or result < 0.0:
        msg = f"{name} must be a finite, non-negative number, got {value!r}"
        raise ValueError(msg)
    return result


def _ceiling_detail(
    *,
    label: str,
    measure: str,
    current_mb: float,
    ceiling_mb: float,
) -> str:
    """Render stable diagnostic detail for a typed ceiling breach."""
    return (
        f"{measure} {current_mb:.1f} MiB exceeded the {ceiling_mb:.1f} MiB "
        f"ceiling at {label}"
    )


def _measurement_unavailable_detail(
    *,
    label: str,
    measure: str,
    ceiling_mb: float,
) -> str:
    """Render stable diagnostic detail when an enforced reading is absent."""
    return (
        f"{measure} measurement was unavailable while enforcing the "
        f"{ceiling_mb:.1f} MiB ceiling at {label}"
    )


@dataclass
class MemoryProbe:
    """Record RSS + CUDA memory checkpoints during an index pipeline.

    The probe is a no-op when :func:`is_enabled` returns ``False``.  It
    also runs a background sampler that tracks peak RSS between
    checkpoints so that transient spikes (e.g. during a single encode
    batch) are captured even if the caller only adds coarse-grained
    markers.
    """

    name: str = "indexer"
    samples: list[MemorySample] = field(default_factory=list)
    start_rss_mb: float = 0.0
    peak_rss_mb: float = 0.0
    _t0: float = 0.0
    _enabled: bool = False
    _sampler_thread: threading.Thread | None = None
    _sampler_stop: threading.Event = field(default_factory=threading.Event)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __post_init__(self) -> None:
        # Snapshot the enabled flag once so the probe's lifecycle is
        # deterministic: if the env var changes mid-run we neither
        # silently stop recording nor suddenly start recording without
        # a baseline sample or a running sampler thread.
        self._enabled = is_enabled()
        if not self._enabled:
            return
        self._t0 = time.perf_counter()
        self.start_rss_mb = current_rss_mb()
        self.peak_rss_mb = self.start_rss_mb
        self._start_sampler()

    def _start_sampler(self) -> None:
        def _run() -> None:
            # The sampler must survive transient errors. A single
            # bad sample (psutil hiccup, signal interruption) is
            # logged once and the loop continues so peak_rss_mb
            # keeps tracking.
            while not self._sampler_stop.wait(0.25):
                try:
                    rss = current_rss_mb()
                except Exception:  # defensive sampler - must not die
                    logger.warning(
                        "memory-probe %s sample failed; continuing",
                        self.name,
                        exc_info=True,
                    )
                    continue
                with self._lock:
                    if rss > self.peak_rss_mb:
                        self.peak_rss_mb = rss

        thread = threading.Thread(
            target=_run,
            name=f"memory-probe-{self.name}",
            daemon=True,
        )
        thread.start()
        self._sampler_thread = thread

    def checkpoint(self, label: str) -> MemorySample | None:
        """Record a checkpoint and return the sample.

        Returns ``None`` when the probe is disabled.
        """
        if not self._enabled:
            return None
        rss = current_rss_mb()
        allocated, reserved = current_cuda_mb()
        with self._lock:
            if rss > self.peak_rss_mb:
                self.peak_rss_mb = rss
        sample = MemorySample(
            label=label,
            rss_mb=rss,
            cuda_allocated_mb=allocated,
            cuda_reserved_mb=reserved,
            wall_s=time.perf_counter() - self._t0,
        )
        self.samples.append(sample)
        logger.info(
            "[memory-probe %s] %s rss=%.0fMB cuda_alloc=%.0fMB "
            "cuda_reserved=%.0fMB t=%.2fs",
            self.name,
            label,
            sample.rss_mb,
            sample.cuda_allocated_mb,
            sample.cuda_reserved_mb,
            sample.wall_s,
        )
        return sample

    @contextlib.contextmanager
    def phase(self, label: str):
        """Context manager wrapping a phase with enter/exit checkpoints."""
        self.checkpoint(f"enter:{label}")
        try:
            yield
        finally:
            self.checkpoint(f"exit:{label}")

    def __enter__(self) -> MemoryProbe:
        return self

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        # Always tear down the background sampler so a failing pipeline
        # never leaks the probe thread.
        self.stop()

    def stop(self) -> None:
        """Stop the background sampler thread.

        Idempotent - safe to call from both ``__exit__`` and an
        explicit ``stop()`` invocation. Logs a warning if the sampler
        did not terminate cleanly within the join timeout so silent
        cleanup failures are observable in the logs.
        """
        thread = self._sampler_thread
        if thread is None:
            return
        self._sampler_stop.set()
        thread.join(timeout=1.0)
        if thread.is_alive():
            logger.warning(
                "memory-probe %s sampler thread did not terminate "
                "within 1s - continuing, but the thread will keep "
                "sampling until process exit",
                self.name,
            )
        self._sampler_thread = None

    def report(self) -> str:
        """Render a human-readable report of recorded checkpoints."""
        if not self.samples:
            return f"[memory-probe {self.name}] disabled or no samples"
        lines = [
            f"[memory-probe {self.name}] start_rss={self.start_rss_mb:.0f}MB "
            f"peak_rss={self.peak_rss_mb:.0f}MB delta="
            f"{self.peak_rss_mb - self.start_rss_mb:+.0f}MB",
        ]
        prev_rss = self.start_rss_mb
        for s in self.samples:
            delta = s.rss_mb - prev_rss
            lines.append(
                f"  {s.wall_s:6.2f}s  rss={s.rss_mb:7.0f}MB "
                f"({delta:+6.0f})  cuda_alloc={s.cuda_allocated_mb:6.0f}MB  "
                f"reserved={s.cuda_reserved_mb:6.0f}MB  {s.label}"
            )
            prev_rss = s.rss_mb
        return "\n".join(lines)
