"""Evidence for how a machine and its jobs are actually doing.

GPU and CPU pressure, device load, backend reachability, forward-pass
progress, and the degradation verdict composed from them. Every function here
reports what it observed and says when it could not observe anything - an
absent measurement and a measured zero are different answers, and the callers
that render them have to be able to tell.
"""

from __future__ import annotations

import os
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from ._job_values import count, flag, measurement
from .registry import get_registry

if TYPE_CHECKING:
    from collections.abc import Callable

    import psutil

# stopped answering.
_BACKEND_PROBE_TIMEOUT_SECONDS = 2.0
_BACKEND_PROBE_CACHE_SECONDS = 5.0
backend_probe_lock = threading.Lock()
backend_probe_cache: dict[tuple[str, str], tuple[float, dict[str, object]]] = {}
# The whole-machine GPU pressure reading served on the jobs listing, held a
# few seconds so a polling operator view does not pay the probe per poll.
_GPU_SNAPSHOT_CACHE_SECONDS = 5.0
_gpu_snapshot_lock = threading.Lock()
_gpu_snapshot_cache: tuple[float, dict[str, object]] | None = None
# The device-load admission reading served on the jobs listing, held the same
# few seconds and by the same rationale: the same open operator views poll
# this route at the same cadence as the GPU pressure block above, and a
# per-poll device read is exactly the cost that block's own cache exists to
# avoid.
_DEVICE_LOAD_SNAPSHOT_CACHE_SECONDS = 5.0
_device_load_snapshot_lock = threading.Lock()
_device_load_snapshot_cache: tuple[float, dict[str, object] | None] | None = None
# Service-process CPU utilisation for degradation evidence. ``cpu_percent``
# measures the interval since its own previous call, so one persistent
# process handle is kept and the reading is cached for a few seconds: polls
# inside the window reuse the reading, and the gap between real samples is
# what gives the measurement a meaningful span.
_CPU_SNAPSHOT_CACHE_SECONDS = 5.0
_cpu_snapshot_lock = threading.Lock()
_cpu_snapshot_cache: tuple[float, dict[str, object]] | None = None
_cpu_probe_process: psutil.Process | None = None


#: The conditional evidence sections, each as the readers its members are
#: narrowed through. Encode state is counted work and rate readings are
#: measurements, which is the whole of the difference between them.
ENCODE_EVIDENCE_READERS: dict[str, Callable[[object], object]] = {
    "token_budget": count,
    "bucket_items": count,
    "items_done": count,
    "items_total": count,
    "oom_count": count,
}
RATE_EVIDENCE_READERS: dict[str, Callable[[object], object]] = {
    "recent_per_second": measurement,
    "median_per_second": measurement,
    "ratio": measurement,
}


def _forward_evidence(
    forward: dict[str, object] | None,
    *,
    now: float,
) -> dict[str, object]:
    """Shape one job's forward telemetry into its evidence block.

    ``age_seconds`` is how long the current forward has been running when one
    is in flight, otherwise how long ago the last one finished. Thread
    liveness distinguishes a starved-but-alive encode (thread alive, forward
    in flight) from a genuinely dead worker.
    """
    if forward is None:
        return {
            "in_flight": False,
            "age_seconds": None,
            "slice_ordinal": None,
            "items": None,
            "thread_alive": None,
        }
    entered = forward.get("entered_at")
    exited = forward.get("exited_at")
    entered_at = float(entered) if isinstance(entered, int | float) else None
    exited_at = float(exited) if isinstance(exited, int | float) else None
    in_flight = entered_at is not None and exited_at is None
    reference = entered_at if in_flight else exited_at
    ident = forward.get("thread_ident")
    thread_alive = (
        any(thread.ident == ident for thread in threading.enumerate())
        if isinstance(ident, int) and not isinstance(ident, bool)
        else None
    )
    return {
        "in_flight": in_flight,
        "age_seconds": max(0.0, now - reference) if reference is not None else None,
        "slice_ordinal": forward.get("slice_ordinal"),
        "items": forward.get("items"),
        "thread_alive": thread_alive,
    }


def gpu_pressure_snapshot(*, now: float | None = None) -> dict[str, object]:
    """The machine-wide GPU pressure block, cached for a few seconds.

    The jobs listing is polled every couple of seconds by every open operator
    view, and each poll would otherwise pay the probe again for a reading
    that cannot meaningfully change between polls. The block is the same
    shape the degradation evidence carries, sampled through the same
    read-only probe, so a header and an evidence block can never disagree
    about what was measured.

    Args:
        now: The moment cache freshness is judged against; defaults to the
            wall clock. Injectable so freshness is testable without sleeping.

    Returns:
        ``{"available", "utilization_percent", "memory_used_mib",
        "memory_total_mib"}``, every measurement ``None`` where this host
        cannot measure it. Callers receive a copy; mutating it cannot
        poison the cache.
    """
    global _gpu_snapshot_cache
    moment = time.time() if now is None else now
    with _gpu_snapshot_lock:
        cached = _gpu_snapshot_cache
        if (
            cached is not None
            and 0.0 <= moment - cached[0] < _GPU_SNAPSHOT_CACHE_SECONDS
        ):
            return dict(cached[1])
    snapshot = _gpu_evidence()
    with _gpu_snapshot_lock:
        _gpu_snapshot_cache = (moment, snapshot)
    return dict(snapshot)


def device_load_snapshot(*, now: float | None = None) -> dict[str, object] | None:
    """The device-load admission verdict, cached the same way as the GPU block.

    A different fact from :func:`gpu_pressure_snapshot`: that block reports
    utilization and memory *usage*, sampled purely for display and for the
    hysteresis-folded ``pressure`` tier beside it - nothing acts on either.
    This is the synchronous, fail-fast predicate a model load is actually
    admitted or refused against right now, against the configured floor. The
    two must stay visibly distinct so a later reader does not collapse a
    display reading into the load-bearing gate, or vice versa.

    Cached rather than read fresh per poll for the same reason
    :func:`gpu_pressure_snapshot` is: the jobs listing is polled every couple
    of seconds by every open operator view, and this route must not turn each
    of those polls into its own device probe.

    Args:
        now: The moment cache freshness is judged against; defaults to the
            wall clock. Injectable so freshness is testable without sleeping.

    Returns:
        The ``device_load`` wire shape (``free_mib``, ``total_mib``,
        ``own_mib``, ``floor_mib``, ``admitted``, ``reason``), or ``None``
        when this host's
        reading could not be taken - absent, never raised, so an older reader
        expecting no such key is unaffected. Callers receive a copy; mutating
        it cannot poison the cache.
    """
    global _device_load_snapshot_cache
    moment = time.time() if now is None else now
    with _device_load_snapshot_lock:
        cached = _device_load_snapshot_cache
        if (
            cached is not None
            and 0.0 <= moment - cached[0] < _DEVICE_LOAD_SNAPSHOT_CACHE_SECONDS
        ):
            return dict(cached[1]) if cached[1] is not None else None
    from ._gpu_admission import device_load_reading

    reading = device_load_reading()
    with _device_load_snapshot_lock:
        _device_load_snapshot_cache = (moment, reading)
    return dict(reading) if reading is not None else None


def _gpu_evidence() -> dict[str, object]:
    """Sample machine-wide GPU pressure through the read-only probe.

    ``available`` is ``False`` on a torch-free host, a CPU-only build, or a
    process whose CUDA context is not initialized - the probe reports absence
    rather than raising or initializing anything.
    """
    from .memory_probe import cuda_pressure

    utilization, used_mib, total_mib = cuda_pressure()
    return {
        "available": total_mib is not None,
        "utilization_percent": utilization,
        "memory_used_mib": round(used_mib, 1) if used_mib is not None else None,
        "memory_total_mib": round(total_mib, 1) if total_mib is not None else None,
    }


def _process_cpu_evidence(*, now: float | None = None) -> dict[str, object]:
    """Sample this process's CPU utilisation for the evidence block.

    A CPU- or I/O-bound step runs no forward pass, so during one the encode
    window is structurally silent and its absence proves nothing. The service
    process burning CPU is the liveness signal that is valid in every step,
    and this is where it is measured. ``utilization_percent`` is relative to
    one core and exceeds 100 when the process uses several. The first sample
    only primes the counter and reports no reading rather than a fabricated
    zero; ``available`` is ``False`` only when the process cannot be probed
    at all.

    Args:
        now: The moment cache freshness is judged against; defaults to the
            wall clock. Injectable so freshness is testable without sleeping.
    """
    global _cpu_snapshot_cache, _cpu_probe_process
    moment = time.time() if now is None else now
    with _cpu_snapshot_lock:
        cached = _cpu_snapshot_cache
        if (
            cached is not None
            and 0.0 <= moment - cached[0] < _CPU_SNAPSHOT_CACHE_SECONDS
        ):
            return dict(cached[1])
        import psutil

        reading: dict[str, object]
        try:
            process = _cpu_probe_process
            primed = process is not None
            if process is None:
                process = psutil.Process()
                _cpu_probe_process = process
            percent = process.cpu_percent(interval=None)
        except Exception:
            reading = {"available": False, "utilization_percent": None}
        else:
            reading = {
                "available": True,
                "utilization_percent": round(float(percent), 1) if primed else None,
            }
        _cpu_snapshot_cache = (moment, reading)
        return dict(reading)


def _forward_pass_expected(step: str | None) -> bool | None:
    """Whether the reported step runs model forward passes at all.

    Encoding steps carry "embed" in their published names; every other step
    is CPU- or I/O-bound work (scanning, hashing, purging, metadata writes)
    in which an absent forward pass is the expected shape of the phase, not
    evidence of a stall. ``None`` when the job has not reported a step, so a
    renderer keeps the conservative reading rather than suppressing the
    signal on no information.
    """
    if not isinstance(step, str) or not step.strip():
        return None
    return "embed" in step


def _probe_backend_once(root: Path, source: str) -> dict[str, object]:
    """Run one time-bounded store count against *root*'s backend.

    The count is the cheapest read that proves the whole write path's
    substrate is answering: it reaches the same client, collection, and
    retry policy the indexer writes through. A warm project slot's store is
    reused; the probe never runs on the caller's thread past the bound.
    """
    outcome: dict[str, object] = {}
    started = time.perf_counter()

    def _count() -> None:
        try:
            with get_registry().lease_store(root) as store:
                if source == "code":
                    store.count_code()
                elif source == "document":
                    store.count_document()
                else:
                    store.count()
        except Exception as exc:  # any backend failure is the finding itself
            outcome["alive"] = False
            outcome["detail"] = str(exc) or type(exc).__name__
        else:
            outcome["alive"] = True
            outcome["detail"] = None
        outcome["latency_seconds"] = round(time.perf_counter() - started, 3)

    probe = threading.Thread(target=_count, name="jobs-backend-probe", daemon=True)
    probe.start()
    probe.join(_BACKEND_PROBE_TIMEOUT_SECONDS)
    if probe.is_alive():
        # The thread may still settle later; never read its dict again. An
        # unanswered probe is reported as unknown, not dead: the backend may
        # be alive but blocked behind a long write.
        return {
            "alive": None,
            "latency_seconds": round(time.perf_counter() - started, 3),
            "detail": (f"no response within {_BACKEND_PROBE_TIMEOUT_SECONDS:.1f}s"),
        }
    return outcome


def _backend_evidence(project_root: str | None, source: str) -> dict[str, object]:
    """Return cached-or-fresh backend liveness for one job's store."""
    if not project_root:
        return {
            "alive": None,
            "latency_seconds": None,
            "detail": "the job records no project root to probe",
        }
    key = (os.path.normcase(project_root), source)
    now = time.monotonic()
    with backend_probe_lock:
        cached = backend_probe_cache.get(key)
        if cached is not None and now - cached[0] < _BACKEND_PROBE_CACHE_SECONDS:
            return dict(cached[1])
    result = _probe_backend_once(Path(project_root), source)
    with backend_probe_lock:
        backend_probe_cache[key] = (time.monotonic(), result)
    return dict(result)


def _conditional_evidence(
    block: dict[str, object] | None,
    readers: dict[str, Callable[[object], object]],
) -> dict[str, object] | None:
    """Shape one conditional evidence section, or ``None`` when unreported.

    The encode section says what bounds the encode stage rather than only
    that it is slow: a run planning tiny batches under a clamped token
    budget, with a retry count that keeps climbing, is bounded by its own
    memory ceiling - a different finding, and a different remedy, from a
    starved card or a stalled store. The rate section is the finding that
    names a collapse: what the job is doing now against what it has proved
    it can do, and the factor between them.

    A section whose every member is unreadable is returned as ``None``, so a
    renderer is never handed a block of nulls to caption.
    """
    if block is None:
        return None
    section: dict[str, object] = {
        key: read(block.get(key)) for key, read in readers.items()
    }
    return section if any(value is not None for value in section.values()) else None


@dataclass(frozen=True, slots=True)
class DegradationInputs:
    """One job's record-side facts, read at one moment, for its evidence.

    Carried as one value rather than re-listed at every call: they are all
    reads of the same record, and the evidence block gains a finding
    whenever the service learns to measure one.
    """

    source: str
    project_root: str | None = None
    step: str | None = None
    forward: dict[str, object] | None = None
    encode: dict[str, object] | None = None
    rate_baseline: dict[str, object] | None = None


def degradation_evidence(
    *,
    now: float,
    inputs: DegradationInputs,
) -> dict[str, object]:
    """Attach sampled cause attribution to one unhealthy job verdict.

    Four findings are always present: the forward-pass window and encode
    thread (is the work alive), the service process's own CPU utilisation
    (is anything running at all), machine-wide GPU pressure (is the card
    starved), and a bounded backend probe (is the store answering). Each
    degrades to explicit absence on hosts or processes that cannot answer it,
    so those four keep a stable shape for every renderer.

    Two findings are conditional, because they describe work not every job
    performs: the encode budget and retry count, and the run's throughput
    against its own baseline. Both are omitted rather than nulled - a job
    that never encoded published no budget, which is a different statement
    from a budget of nothing, and an omitted section costs a renderer no line.

    The forward section is phase-aware: ``expected`` says whether the
    reported step performs forward passes at all, so a CPU-bound phase is
    never judged by the absence of a signal it structurally cannot produce -
    the CPU section is the liveness reading that remains valid there.
    """
    evidence: dict[str, object] = {
        "forward": {
            **_forward_evidence(inputs.forward, now=now),
            "expected": _forward_pass_expected(inputs.step),
        },
        "cpu": _process_cpu_evidence(now=now),
        "gpu": _gpu_evidence(),
        "backend": _backend_evidence(inputs.project_root, inputs.source),
    }
    encode_section = _conditional_evidence(inputs.encode, ENCODE_EVIDENCE_READERS)
    if encode_section is not None:
        evidence["encode"] = encode_section
    rate_section = _conditional_evidence(inputs.rate_baseline, RATE_EVIDENCE_READERS)
    if rate_section is not None:
        evidence["rate"] = rate_section
    return evidence


def _worst_forward_evidence(
    forwards: list[dict[str, object] | None],
    *,
    now: float,
) -> dict[str, object]:
    """Shape and pick the machine's worst forward window.

    A dead encode thread under an open window outranks everything; among
    live in-flight forwards the oldest wins; a machine with no in-flight
    forward reports the newest exit it has. One job's block is chosen whole
    rather than merged, so the evidence stays a real observation.
    """
    worst = _forward_evidence(None, now=now)
    worst_rank = (-1, -1.0)
    for forward in forwards:
        evidence = _forward_evidence(forward, now=now)
        in_flight = evidence["in_flight"] is True
        dead = in_flight and evidence["thread_alive"] is False
        age = measurement(evidence["age_seconds"])
        rank = (2 if dead else 1 if in_flight else 0, age if age is not None else -1.0)
        if rank > worst_rank:
            worst_rank, worst = rank, evidence
    return worst


def machine_pressure(
    *,
    now: float,
    forwards: list[dict[str, object] | None],
    project_root: str | None,
    source: str,
    store_failures: tuple[str, ...] = (),
) -> dict[str, object]:
    """The machine-wide pressure block served on the jobs envelope.

    Samples the same seams the degradation evidence reads - the forward
    window, the cached read-only GPU probe, the bounded backend probe -
    plus the encode-admission queue and the typed failures of jobs that
    died recently, and folds them through the hysteresis evaluator into one
    tier. The backend is probed only when running work names a store
    (*project_root*), so an idle machine pays no probe and an unprobed
    store reads as absence, never as a verdict. Surfacing only: nothing
    consumes the tier to defer, shrink, or refuse work.
    """
    from .concurrency import limiter_stats
    from .pressure import MachinePressureSignals, get_pressure_evaluator

    forward_block = _worst_forward_evidence(forwards, now=now)
    gpu = gpu_pressure_snapshot(now=now)
    probed = bool(project_root)
    backend: dict[str, object] = {
        "probed": probed,
        **_backend_evidence(project_root, source),
    }
    if not probed:
        # The declined-probe reading is shaped by the same reader, so only
        # the reason differs: on this axis no job named a store, rather than
        # one job having failed to record one.
        backend["detail"] = "no running index job names a store to probe"
    raw_waiting = limiter_stats()["encode"].get("waiting")
    waiting = (
        raw_waiting
        if isinstance(raw_waiting, int) and not isinstance(raw_waiting, bool)
        else None
    )
    signals = MachinePressureSignals(
        forward_in_flight=forward_block["in_flight"] is True,
        forward_age_seconds=measurement(forward_block["age_seconds"]),
        forward_thread_alive=flag(forward_block["thread_alive"]),
        gpu_utilization_percent=measurement(gpu.get("utilization_percent")),
        gpu_memory_used_mib=measurement(gpu.get("memory_used_mib")),
        gpu_memory_total_mib=measurement(gpu.get("memory_total_mib")),
        backend_probed=probed,
        backend_alive=flag(backend.get("alive")),
        backend_latency_seconds=measurement(backend.get("latency_seconds")),
        backend_probe_bound_seconds=_BACKEND_PROBE_TIMEOUT_SECONDS if probed else None,
        encode_waiters=waiting,
        store_failures=store_failures,
    )
    verdict = get_pressure_evaluator().observe(signals, now=now)
    return {
        "tier": verdict["tier"],
        "entered_at": verdict["entered_at"],
        "evidence": {
            "forward": forward_block,
            "gpu": gpu,
            "backend": backend,
            "encode_waiters": waiting,
            "store_failures": list(store_failures),
        },
    }
