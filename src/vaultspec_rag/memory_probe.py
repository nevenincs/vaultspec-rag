"""Lightweight RSS + CUDA memory probe for index pipelines.

Gated by the ``VAULTSPEC_RAG_MEMORY_PROBE`` env var, which spells its two
states the way every flag in this project does.  When enabled the probe
records resident-set size (RSS) and ``torch.cuda.memory_allocated/
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
from typing import TYPE_CHECKING, Any, Literal, overload

from ._env_values import BOOL_SHAPE, parse_bool, rejection
from ._job_errors import JobError, JobErrorKind
from ._units import bytes_to_mib, mib_to_bytes

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

logger = logging.getLogger(__name__)

__all__ = [
    "CudaCeilingObservation",
    "CudaDeviceMemory",
    "MemoryBudget",
    "MemoryBudgetSnapshot",
    "MemoryProbe",
    "MemorySample",
    "cuda_device_memory",
    "cuda_forward_peak_capture",
    "cuda_pressure",
    "current_cuda_mib",
    "current_rss_mib",
    "is_enabled",
    "rebase_resident_cuda_baseline",
    "record_forward_peaks",
    "reset_cuda_peak_memory_stats",
    "resident_cuda_baseline_mib",
    "route_forward_peak_mib",
    "sample_resident_cuda_baseline",
    "snapshot_resource_bytes",
]


#: Restated rather than imported from the settings module on purpose: this
#: module is reachable from spawn workers, which re-import their whole chain,
#: and the settings module pulls the vaultspec-core config package with it. A
#: guard test asserts this string still equals the settings enum member, so the
#: copy cannot drift. Only the *name* is restated - the spellings it accepts
#: come from the shared table, which is stdlib-only and costs a worker nothing.
ENV_VAR = "VAULTSPEC_RAG_MEMORY_PROBE"

# Module-level caches for hot-path samplers. ``current_rss_mib`` and
# ``current_cuda_mib`` are called once per 250 ms by the background
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

    The switch spells its two states the way every flag in this project does:
    ``1``, ``true``, ``yes`` and ``on`` turn the probe on, ``0``, ``false``,
    ``no`` and ``off`` turn it off, and an unset or empty value leaves it off.

    A word that spells neither state is rejected rather than guessed at. This
    switch is set once, by hand, by an operator who wants the sampler; reading
    a typo as either state hides the mistake behind whichever behaviour the
    guess produced, and the sampler is exactly the kind of diagnostic whose
    absence goes unnoticed for a long time.

    Raises:
        ValueError: If the variable is set to a value spelling neither state.
    """
    raw = os.environ.get(ENV_VAR, "")
    enabled = parse_bool(raw)
    if enabled is None:
        raise rejection(ENV_VAR, BOOL_SHAPE, raw)
    return enabled


def _measure_rss_mib() -> float | None:
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


def current_rss_mib() -> float:
    """Return current process RSS in mebibytes.

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
    measured = _measure_rss_mib()
    return measured if measured is not None else 0.0


def _measure_cuda_mib() -> tuple[float, float] | None:
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


def cuda_device_total_mib() -> float | None:
    """Return the active CUDA device's total memory in MiB, or ``None``.

    A guarded probe, not a hard gate: it returns ``None`` on a torch-absent or
    CPU-only host rather than raising, so the ceiling derivation degrades to its
    profile fallback off the GPU compute path and never forces torch onto a
    service-client or worker path. Shares the cached module probe with
    :func:`_measure_cuda_mib`.
    """
    _measure_cuda_mib()
    if _torch_module is None or not _torch_has_cuda:
        return None
    try:
        props = _torch_module.cuda.get_device_properties(
            _torch_module.cuda.current_device()
        )
        return bytes_to_mib(props.total_memory)
    except (RuntimeError, AssertionError):
        return None


def cuda_free_memory_mib() -> float | None:
    """Return the active CUDA device's free memory in MiB, or ``None``.

    A guarded probe, not a hard gate: it returns ``None`` on a torch-absent or
    CPU-only host rather than raising, so the ceiling derivation degrades to
    its total-memory (or profile) fallback off the GPU compute path and never
    forces torch onto a service-client or worker path. Shares the cached
    module probe with :func:`_measure_cuda_mib`.
    """
    _measure_cuda_mib()
    if _torch_module is None or not _torch_has_cuda:
        return None
    try:
        return bytes_to_mib(_torch_module.cuda.mem_get_info()[0])
    except (RuntimeError, AssertionError):
        return None


@dataclass(frozen=True, slots=True)
class CudaDeviceMemory:
    """One device-wide CUDA memory observation, and what made it possible.

    The presence flags travel with the figures because absence has two distinct
    causes a caller may have to tell apart - torch is not installed at all, or
    it is installed without a usable device - and a pair of ``None`` readings
    cannot say which. Both figures are ``None`` whenever ``cuda_present`` is
    false, and either may be ``None`` on a device whose driver refused the
    query.
    """

    torch_present: bool
    cuda_present: bool
    free_mib: float | None
    total_mib: float | None


def cuda_device_memory() -> CudaDeviceMemory:
    """Return one guarded reading of device-wide free and total memory.

    Composes the two guarded probes above rather than reading
    ``mem_get_info`` a second time, so the device keeps exactly one reader,
    and adds the presence distinction a caller needs when an absent torch and
    a CPU-only build must produce different outcomes. Like its parts it never
    raises: a torch-free host, a CPU-only build, and a driver that refuses the
    query all report absence.
    """
    _measure_cuda_mib()
    # A completed probe holding no module means the import itself failed, which
    # is permanent. An incomplete probe means the import succeeded and only the
    # availability query misfired, so torch IS present on this host.
    torch_present = _torch_module is not None or not _torch_probed
    if _torch_module is None or not _torch_has_cuda:
        return CudaDeviceMemory(
            torch_present=torch_present,
            cuda_present=False,
            free_mib=None,
            total_mib=None,
        )
    return CudaDeviceMemory(
        torch_present=True,
        cuda_present=True,
        free_mib=cuda_free_memory_mib(),
        total_mib=cuda_device_total_mib(),
    )


def cuda_pressure() -> tuple[float | None, float | None, float | None]:
    """Machine-wide GPU pressure: ``(utilization %, used MiB, total MiB)``.

    A read-only observability probe, never a gate and never a consumer. Every
    element is ``None`` on a torch-free host, a CPU-only build, or a process
    whose CUDA context is not already initialized - the probe reports absence
    rather than initializing a context the calling path does not own. The
    memory figures are device-wide (``mem_get_info``), so they see pressure
    from every process on the card, not just this one. Utilization degrades
    independently: it needs the NVML bindings, whose absence must not blank
    the memory figures that are still measurable.
    """
    utilization: float | None = None
    used_mib: float | None = None
    total_mib: float | None = None
    _measure_cuda_mib()
    if _torch_module is None or not _torch_has_cuda:
        return (utilization, used_mib, total_mib)
    try:
        if _torch_module.cuda.is_initialized():
            free_bytes, total_bytes = _torch_module.cuda.mem_get_info()
            total_mib = bytes_to_mib(int(total_bytes))
            used_mib = bytes_to_mib(int(total_bytes) - int(free_bytes))
    except (RuntimeError, AssertionError):
        used_mib = None
        total_mib = None
    if total_mib is not None:
        try:
            utilization = float(_torch_module.cuda.utilization())
        except Exception:  # NVML may be absent entirely or refuse the query
            utilization = None
    return (utilization, used_mib, total_mib)


def resolve_index_cuda_ceiling_mib(
    *,
    configured_mib: float,
    headroom_mib: float,
    profile_cuda_mib: float,
    baseline_mib: float,
) -> float:
    """Resolve the effective indexing CUDA ceiling in MiB.

    A positive ``configured_mib`` is an authoritative operator override that wins
    in either direction - it may raise the ceiling above the profile figure as
    well as lower it below, replacing the former one-way ``min`` clamp. When it
    is unset (zero or negative), the ceiling is derived from the real device as
    an ABSOLUTE figure: ``min(baseline_mib + free - headroom_mib,
    total - headroom_mib)``. Free memory is sampled after the resident models
    loaded, so it already excludes them - and enforcement compares peak and
    ceiling net of the resident baseline, so ``baseline_mib`` must be added back
    here. A bare ``free - headroom`` ceiling would charge the resident models
    twice (once inside the free reading, once via the baseline-net comparison)
    and falsely reject legitimate forwards. When the free reading is
    unavailable the derivation falls back to ``total - headroom_mib``; off the
    GPU compute path the device total is also unavailable, so it falls back to
    ``profile_cuda_mib`` - the profile figure becomes a default rather than a
    hard cap.
    """
    return cuda_ceiling_from_observation(
        CudaCeilingObservation(
            device_total_mib=cuda_device_total_mib(),
            free_mib=cuda_free_memory_mib(),
            configured_mib=configured_mib,
            headroom_mib=headroom_mib,
            profile_cuda_mib=profile_cuda_mib,
            baseline_mib=baseline_mib,
        )
    )


@dataclass(frozen=True, slots=True)
class CudaCeilingObservation:
    """One fixed CUDA capacity observation used to derive an index ceiling."""

    device_total_mib: float | None
    free_mib: float | None
    configured_mib: float
    headroom_mib: float
    profile_cuda_mib: float
    baseline_mib: float


def cuda_ceiling_from_observation(
    observation: CudaCeilingObservation,
) -> float:
    """Derive the ceiling from one device observation.

    The arithmetic and the measurement are separate concerns: what a given
    pair of readings should yield does not depend on how they were obtained.
    Keeping them apart means the derivation can be exercised over the readings
    that matter - an absent total, an absent free figure, a device smaller
    than the profile - without a machine that happens to present them.

    ``None`` means the corresponding probe had nothing to report.
    """
    if observation.configured_mib and observation.configured_mib > 0:
        return float(observation.configured_mib)
    if observation.device_total_mib is None:
        return float(observation.profile_cuda_mib)
    total_capped = max(0.0, observation.device_total_mib - observation.headroom_mib)
    if observation.free_mib is None:
        return total_capped
    return max(
        0.0,
        min(
            observation.baseline_mib + observation.free_mib - observation.headroom_mib,
            total_capped,
        ),
    )


def current_cuda_mib() -> tuple[float, float]:
    """Return ``(allocated_mib, reserved_mib)`` for the active CUDA device.

    Returns zeros when torch is not importable or CUDA is unavailable -
    the probe must never crash host code. The torch module reference
    and the CUDA availability flag are cached on first call so the
    background sampler does not pay repeated import / probe costs.
    """
    measured = _measure_cuda_mib()
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
    measured = _measure_cuda_mib()
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
    measured = _measure_cuda_mib()
    if measured is None or _torch_module is None:
        return False
    try:
        _torch_module.cuda.reset_peak_memory_stats()
    except (RuntimeError, AssertionError):
        return False
    return True


def _read_cuda_peak_allocated_mib() -> float | None:
    """Return the allocated high-water in MiB since the last rebase.

    This is the single sanctioned reader of the process-global peak counter,
    and it is only meaningful inside the GPU-lock-held capture bracket that
    just rebased it; enforcement paths consume the captured value, never
    this counter directly.
    """
    measured = _measure_cuda_mib()
    if measured is None or _torch_module is None:
        return None
    try:
        return bytes_to_mib(_torch_module.cuda.max_memory_allocated())
    except (RuntimeError, AssertionError):
        return None


_resident_baseline_lock = threading.Lock()
_resident_baseline_mib: float = 0.0


def sample_resident_cuda_baseline() -> float:
    """Record the resident-model CUDA allocation as a monotonic baseline.

    Called after each shared model finishes loading - the embedding stack
    eagerly, the reranker lazily on first use - so a late lazy load raises
    the recorded baseline instead of leaving it understated. The baseline
    only ever grows here: a transient dip (eviction mid-run) must not shrink the
    figure an in-flight job's budget was constructed against. A definitive
    release is the other case and is not a dip;
    :func:`rebase_resident_cuda_baseline` owns it.

    Returns:
        The updated baseline in MiB (``0.0`` off the GPU path).
    """
    global _resident_baseline_mib
    measured = _measure_cuda_mib()
    if measured is None:
        return resident_cuda_baseline_mib()
    allocated = measured[0]
    with _resident_baseline_lock:
        if allocated > _resident_baseline_mib:
            _resident_baseline_mib = allocated
        return _resident_baseline_mib


def rebase_resident_cuda_baseline() -> float:
    """Re-establish the baseline after resident models are released.

    The recorded figure only ratchets while models load, which is right for a
    transient dip but wrong for a definitive release: a registry that closes
    its stack leaves the baseline describing memory nothing holds. Enforcement
    clamps a job's peak net of that figure at zero, so an overstated baseline
    does not merely skew the comparison - it puts every ceiling out of reach
    and silently retires the guard for the rest of the process.

    Measuring rather than subtracting is what makes this safe: whatever remains
    allocated is genuinely resident, whether that is a sibling registry's stack
    or nothing at all. In-flight jobs are unaffected, because each budget
    captures the baseline it enforces against when it is constructed.

    Callers must release their references AND collect first; a model held only
    by a reference cycle is still allocated when this measures, which would
    re-adopt the very figure the release was meant to retire.

    Returns:
        The re-established baseline in MiB (unchanged off the GPU path).
    """
    global _resident_baseline_mib
    # A release is also what retires the standing load-admission verdict: that
    # verdict was taken against the device as it was before these models
    # loaded, so it describes a state that no longer exists once they are gone,
    # and the next load must be admitted against what the card actually holds.
    # Cleared unconditionally, before the reading: an over-clear costs one
    # extra reading, while an under-clear rides a stale verdict for the life of
    # the process.
    from ._gpu_admission import clear_gpu_admission_latch

    clear_gpu_admission_latch()
    measured = _measure_cuda_mib()
    if measured is None:
        return resident_cuda_baseline_mib()
    with _resident_baseline_lock:
        _resident_baseline_mib = measured[0]
        return _resident_baseline_mib


def resident_cuda_baseline_mib() -> float:
    """Return the recorded resident-model CUDA baseline in MiB."""
    with _resident_baseline_lock:
        return _resident_baseline_mib


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


def route_forward_peak_mib(peak_mib: float | None) -> bool:
    """Credit one captured forward peak to this thread's recorder.

    The routing rule, stated over a reading rather than over the allocator:
    a peak belongs to the recorder registered on the thread that captured
    it, and is dropped when that thread has none - a capture taken outside
    a job's recorder context has no owner, and crediting it to whichever
    recorder ran last would attribute one job's demand to another. A
    recorder that raises loses its capture rather than propagating out of
    the bracket, which would surface as a failure of the forward itself.

    Args:
        peak_mib: The captured high-water in MiB, or ``None`` when the
            allocator could not be read.

    Returns:
        True when the reading reached a recorder.
    """
    recorder = getattr(_forward_peak_recorder, "value", None)
    if peak_mib is None or recorder is None:
        return False
    try:
        recorder(peak_mib)
    except Exception:
        logger.warning(
            "forward peak recorder failed; capture dropped",
            exc_info=True,
        )
        return False
    return True


@contextlib.contextmanager
def cuda_forward_peak_capture() -> Generator[None]:
    """Bracket one model forward with a job-local peak capture.

    Must run inside the GPU-lock hold that serialises the forward: the
    critical section is what makes the reading job-local. The peak counter
    is rebased on entry and read on exit while no sibling forward can run,
    so the captured value is this forward's own demand (resident baseline
    included) and never a concurrent job's. The read also happens on an
    exceptional exit so an allocator OOM still records the demand that
    triggered it. This bracket probes; :func:`route_forward_peak_mib` owns
    what the reading then means.
    """
    armed = _reset_cuda_peak_stats_bare()
    try:
        yield
    finally:
        if armed:
            route_forward_peak_mib(_read_cuda_peak_allocated_mib())


@dataclass
class MemorySample:
    """A single checkpoint recorded by :class:`MemoryProbe`.

    Attributes:
        label: Human-readable checkpoint name (e.g. ``"after dense
            encode batch 3"``).
        rss_mib: Process resident-set size at the checkpoint.
        cuda_allocated_mib: Live ``torch.cuda.memory_allocated`` value.
        cuda_reserved_mib: Live ``torch.cuda.memory_reserved`` value.
        wall_s: Seconds since the probe was constructed.
    """

    label: str
    rss_mib: float
    cuda_allocated_mib: float
    cuda_reserved_mib: float
    wall_s: float


@dataclass(frozen=True, slots=True)
class MemoryBudgetSnapshot:
    """One immutable view of enforced process and CUDA memory state.

    ``rss_ceiling_mib`` and ``cuda_ceiling_mib`` are absolute process readings
    frozen by admission.  A caller enforcing per-run headroom adds its admitted
    baseline before constructing :class:`MemoryBudget`.  A reading exactly at
    its ceiling is admitted; only a reading above the ceiling is a violation.
    """

    label: str
    rss_mib: float
    rss_available: bool
    peak_rss_mib: float
    rss_ceiling_mib: float | None
    cuda_allocated_mib: float
    cuda_available: bool
    peak_cuda_allocated_mib: float
    cuda_reserved_mib: float
    peak_cuda_reserved_mib: float
    cuda_ceiling_mib: float | None


@dataclass(frozen=True, slots=True)
class _MemoryBudgetReading:
    """One normalized memory observation retained by a budget."""

    label: str
    rss_mib: float
    rss_available: bool
    cuda_allocated_mib: float
    cuda_reserved_mib: float
    cuda_peak_allocated_mib: float
    cuda_peak_reserved_mib: float
    cuda_available: bool


def held_budget_snapshot(budget: MemoryBudget | None) -> MemoryBudgetSnapshot | None:
    """Return a held budget's latest reading, or ``None`` when none is held.

    A run holds a budget only while it is indexing, so every reader has to
    answer the not-yet-started case as well as the reading. Stating that once
    keeps the two runs that publish a snapshot from answering it differently.
    """
    return budget.snapshot if budget is not None else None


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
        mib_to_bytes(snapshot.peak_rss_mib),
        mib_to_bytes(snapshot.peak_cuda_allocated_mib),
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
        "_captured_cuda_peak_mib",
        "_cuda_baseline_mib",
        "_cuda_ceiling_mib",
        "_failure",
        "_lock",
        "_rss_ceiling_mib",
        "_snapshot",
    )

    _captured_cuda_peak_mib: float
    _cuda_baseline_mib: float | None
    _cuda_ceiling_mib: float | None
    _failure: tuple[JobErrorKind, str] | None
    _lock: threading.Lock
    _rss_ceiling_mib: float | None
    _snapshot: MemoryBudgetSnapshot | None

    def __init__(
        self,
        *,
        rss_ceiling_mib: float | None = None,
        cuda_ceiling_mib: float | None = None,
        cuda_baseline_mib: float | None = None,
    ) -> None:
        object.__setattr__(
            self,
            "_rss_ceiling_mib",
            _valid_memory_mib(
                "rss_ceiling_mib",
                rss_ceiling_mib,
                optional=True,
            ),
        )
        object.__setattr__(
            self,
            "_cuda_ceiling_mib",
            _valid_memory_mib(
                "cuda_ceiling_mib",
                cuda_ceiling_mib,
                optional=True,
            ),
        )
        object.__setattr__(
            self,
            "_cuda_baseline_mib",
            _valid_memory_mib(
                "cuda_baseline_mib",
                cuda_baseline_mib,
                optional=True,
            ),
        )
        object.__setattr__(self, "_captured_cuda_peak_mib", 0.0)
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
    def rss_ceiling_mib(self) -> float | None:
        """Return the immutable admitted process RSS ceiling."""
        return self._rss_ceiling_mib

    @property
    def cuda_ceiling_mib(self) -> float | None:
        """Return the immutable admitted CUDA allocated-high-water ceiling."""
        return self._cuda_ceiling_mib

    @property
    def cuda_baseline_mib(self) -> float | None:
        """Return the admitted resident-model baseline, if one was frozen."""
        return self._cuda_baseline_mib

    @property
    def captured_cuda_peak_mib(self) -> float:
        """Return the maximum lock-bracketed forward peak recorded so far."""
        with self._lock:
            return self._captured_cuda_peak_mib

    def record_forward_peak_mib(self, peak_mib: float) -> None:
        """Accumulate one lock-bracketed forward peak as this job's maximum.

        Fed by the GPU-lock-held capture bracket; the retained value is the
        job's own demand across all of its forwards, so checkpoints enforce
        against work this job genuinely did rather than a process-wide
        high-water shared with concurrent jobs.
        """
        value = _valid_memory_mib("peak_mib", peak_mib)
        with self._lock:
            if value > self._captured_cuda_peak_mib:
                object.__setattr__(self, "_captured_cuda_peak_mib", value)

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
        :meth:`record_forward_peak_mib` - never the process-global allocator
        high-water, whose since-reset span covers every concurrent job. The
        live allocated/reserved readings taken here remain process-global
        diagnostics and do not decide outcome.
        """
        self._raise_if_latched()
        measured_rss = _measure_rss_mib()
        measured_cuda = (
            _measure_cuda_mib() if self.cuda_ceiling_mib is not None else None
        )
        return self.sample_readings(
            label=label,
            rss_mib=measured_rss,
            cuda_mib=measured_cuda,
        )

    def sample_readings(
        self,
        *,
        label: str,
        rss_mib: float | None,
        cuda_mib: tuple[float, float] | None,
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
        measured_rss = rss_mib
        measured_cuda = cuda_mib
        return self._record(
            _MemoryBudgetReading(
                label=label,
                rss_mib=measured_rss if measured_rss is not None else 0.0,
                rss_available=measured_rss is not None,
                cuda_allocated_mib=measured_cuda[0]
                if measured_cuda is not None
                else 0.0,
                cuda_reserved_mib=measured_cuda[1]
                if measured_cuda is not None
                else 0.0,
                cuda_peak_allocated_mib=(
                    self.captured_cuda_peak_mib if measured_cuda is not None else 0.0
                ),
                cuda_peak_reserved_mib=(
                    measured_cuda[1] if measured_cuda is not None else 0.0
                ),
                cuda_available=measured_cuda is not None,
            )
        )

    def observe(
        self,
        *,
        label: str,
        rss_mib: float,
        cuda_allocated_mib: float,
        cuda_reserved_mib: float,
    ) -> MemoryBudgetSnapshot:
        """Record known measurements and raise on the first crossed ceiling.

        The comparison is strict (``current > ceiling``), all values are MiB,
        and RSS takes deterministic precedence over CUDA for a simultaneous
        breach.  Peak values include the violating observation.
        """
        self._raise_if_latched()
        rss = _valid_memory_mib("rss_mib", rss_mib)
        allocated = _valid_memory_mib("cuda_allocated_mib", cuda_allocated_mib)
        reserved = _valid_memory_mib("cuda_reserved_mib", cuda_reserved_mib)
        return self._record(
            _MemoryBudgetReading(
                label=label,
                rss_mib=rss,
                rss_available=True,
                cuda_allocated_mib=allocated,
                cuda_reserved_mib=reserved,
                cuda_peak_allocated_mib=allocated,
                cuda_peak_reserved_mib=reserved,
                cuda_available=True,
            )
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

    def _record(self, reading: _MemoryBudgetReading) -> MemoryBudgetSnapshot:
        """Atomically retain one observation and latch its first violation."""
        if not reading.label.strip():
            msg = "memory budget sample label must not be empty"
            raise ValueError(msg)

        with self._lock:
            if self._failure is not None:
                failure = self._failure
                snapshot = None
            else:
                previous = self._snapshot
                snapshot = MemoryBudgetSnapshot(
                    label=reading.label,
                    rss_mib=reading.rss_mib,
                    rss_available=reading.rss_available,
                    peak_rss_mib=max(
                        reading.rss_mib if reading.rss_available else 0.0,
                        previous.peak_rss_mib if previous else 0.0,
                    ),
                    rss_ceiling_mib=self.rss_ceiling_mib,
                    cuda_allocated_mib=reading.cuda_allocated_mib,
                    cuda_available=reading.cuda_available,
                    peak_cuda_allocated_mib=max(
                        reading.cuda_peak_allocated_mib
                        if reading.cuda_available
                        else 0.0,
                        previous.peak_cuda_allocated_mib if previous else 0.0,
                    ),
                    cuda_reserved_mib=reading.cuda_reserved_mib,
                    peak_cuda_reserved_mib=max(
                        reading.cuda_peak_reserved_mib
                        if reading.cuda_available
                        else 0.0,
                        previous.peak_cuda_reserved_mib if previous else 0.0,
                    ),
                    cuda_ceiling_mib=self.cuda_ceiling_mib,
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
        if self.rss_ceiling_mib is not None:
            if not snapshot.rss_available:
                return (
                    JobErrorKind.RSS_MEMORY_CEILING,
                    _measurement_unavailable_detail(
                        label=snapshot.label,
                        measure="RSS",
                        ceiling_mib=self.rss_ceiling_mib,
                    ),
                )
            if snapshot.rss_mib > self.rss_ceiling_mib:
                return (
                    JobErrorKind.RSS_MEMORY_CEILING,
                    _ceiling_detail(
                        label=snapshot.label,
                        measure="RSS",
                        current_mib=snapshot.rss_mib,
                        ceiling_mib=self.rss_ceiling_mib,
                    ),
                )
        if self.cuda_ceiling_mib is not None:
            if not snapshot.cuda_available:
                return (
                    JobErrorKind.CUDA_MEMORY_CEILING,
                    _measurement_unavailable_detail(
                        label=snapshot.label,
                        measure="CUDA",
                        ceiling_mib=self.cuda_ceiling_mib,
                    ),
                )
            # Baseline-consistent comparison: a captured peak is absolute
            # (a post-rebase counter starts at the resident models), so the
            # baseline must come off the peak and the ceiling on the SAME
            # side. Subtracting it from only one side double-counts the
            # resident models and turns the ceiling into a covert tightening.
            baseline = self._cuda_baseline_mib or 0.0
            peak_above_baseline = max(
                0.0,
                snapshot.peak_cuda_allocated_mib - baseline,
            )
            ceiling_above_baseline = max(0.0, self.cuda_ceiling_mib - baseline)
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
                        current_mib=peak_above_baseline,
                        ceiling_mib=ceiling_above_baseline,
                    ),
                )
        return None


@overload
def _valid_memory_mib(
    name: str, value: float | None, *, optional: Literal[False] = False
) -> float: ...
@overload
def _valid_memory_mib(
    name: str, value: float | None, *, optional: Literal[True]
) -> float | None: ...
def _valid_memory_mib(
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
    current_mib: float,
    ceiling_mib: float,
) -> str:
    """Render stable diagnostic detail for a typed ceiling breach."""
    return (
        f"{measure} {current_mib:.1f} MiB exceeded the {ceiling_mib:.1f} MiB "
        f"ceiling at {label}"
    )


def _measurement_unavailable_detail(
    *,
    label: str,
    measure: str,
    ceiling_mib: float,
) -> str:
    """Render stable diagnostic detail when an enforced reading is absent."""
    return (
        f"{measure} measurement was unavailable while enforcing the "
        f"{ceiling_mib:.1f} MiB ceiling at {label}"
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
    start_rss_mib: float = 0.0
    peak_rss_mib: float = 0.0
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
        self.start_rss_mib = current_rss_mib()
        self.peak_rss_mib = self.start_rss_mib
        self._start_sampler()

    def _start_sampler(self) -> None:
        def _run() -> None:
            # The sampler must survive transient errors. A single
            # bad sample (psutil hiccup, signal interruption) is
            # logged once and the loop continues so peak_rss_mib
            # keeps tracking.
            while not self._sampler_stop.wait(0.25):
                try:
                    rss = current_rss_mib()
                except Exception:  # defensive sampler - must not die
                    logger.warning(
                        "memory-probe %s sample failed; continuing",
                        self.name,
                        exc_info=True,
                    )
                    continue
                with self._lock:
                    if rss > self.peak_rss_mib:
                        self.peak_rss_mib = rss

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
        rss = current_rss_mib()
        allocated, reserved = current_cuda_mib()
        with self._lock:
            if rss > self.peak_rss_mib:
                self.peak_rss_mib = rss
        sample = MemorySample(
            label=label,
            rss_mib=rss,
            cuda_allocated_mib=allocated,
            cuda_reserved_mib=reserved,
            wall_s=time.perf_counter() - self._t0,
        )
        self.samples.append(sample)
        logger.info(
            "[memory-probe %s] %s rss=%.0fMiB cuda_alloc=%.0fMiB "
            "cuda_reserved=%.0fMiB t=%.2fs",
            self.name,
            label,
            sample.rss_mib,
            sample.cuda_allocated_mib,
            sample.cuda_reserved_mib,
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
            f"[memory-probe {self.name}] start_rss={self.start_rss_mib:.0f}MiB "
            f"peak_rss={self.peak_rss_mib:.0f}MiB delta="
            f"{self.peak_rss_mib - self.start_rss_mib:+.0f}MiB",
        ]
        prev_rss = self.start_rss_mib
        for s in self.samples:
            delta = s.rss_mib - prev_rss
            lines.append(
                f"  {s.wall_s:6.2f}s  rss={s.rss_mib:7.0f}MiB "
                f"({delta:+6.0f})  cuda_alloc={s.cuda_allocated_mib:6.0f}MiB  "
                f"reserved={s.cuda_reserved_mib:6.0f}MiB  {s.label}"
            )
            prev_rss = s.rss_mib
        return "\n".join(lines)
