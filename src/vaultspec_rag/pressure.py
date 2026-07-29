"""Machine-wide pressure tier evaluated over already-sampled telemetry.

The per-job degradation verdict answers "is this job healthy"; the tier here
answers the machine question beside it: is this host under resource pressure.
It is computed in the service domain from readings other modules already
sample - the forward-pass window, the read-only GPU probe, the bounded
backend probe, and the encode-admission queue - and is surfaced on the jobs
envelope for every adapter to render. Surfacing is all it does: nothing
defers, shrinks, yields, or refuses work based on the tier.

Torch-free and store-free by design: this module receives measurements and
never probes anything itself, so every service call path can import it.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

from ._job_errors import DEGRADED_THRESHOLD_SECONDS
from .logging_config import log_event

__all__ = [
    "PRESSURE_TIERS",
    "MachinePressureSignals",
    "PressureEvaluator",
    "get_pressure_evaluator",
    "reset_pressure_evaluator",
]

logger = logging.getLogger(__name__)

#: The tier vocabulary, ordered from healthy to worst. Index order is the
#: severity order the evaluator ratchets across.
PRESSURE_TIERS: tuple[str, ...] = ("nominal", "elevated", "critical")

_NOMINAL, _ELEVATED, _CRITICAL = range(len(PRESSURE_TIERS))

#: Samples closer together than this are folded into the previous one. The
#: GPU and backend readings feeding the evaluator are served from caches
#: with windows of this order, so a faster clock would only resample the
#: caches - and would let the number of concurrent pollers, rather than
#: elapsed time, decide how fast the tier can move.
_SAMPLE_INTERVAL_SECONDS = 5.0

#: Consecutive over-threshold samples required to escalate. Three samples at
#: the cadence above is an attack window in the tens of seconds: long enough
#: that one flaky probe or one slow slice cannot flip the tier, short enough
#: that real pressure is named while an operator is still deciding what is
#: wrong.
_ESCALATION_SAMPLES = 3

#: The card counts as saturated only when utilization AND device memory are
#: both at or above this fraction. Either axis alone is a busy card doing
#: its job; both pinned together is the contention signature under which
#: forwards stretch from seconds to minutes.
_GPU_SATURATION_FRACTION = 0.9

#: An answered backend probe slower than this fraction of its own time bound
#: is an early sign the store is struggling: the probe is a single count, so
#: burning half its bound on one is far outside the healthy band.
_BACKEND_SLOW_FRACTION = 0.5

#: A verdict nothing has refreshed for this long lapses to ``nominal``. The
#: asset protected here is the availability of foreground work, not data, so
#: uncertainty must release the verdict rather than extend it - the inverse
#: of a protection clock. Three missed samples is the shortest gap that
#: cannot be one slow render on a surface that is still polling.
_STALE_AFTER_SECONDS = _SAMPLE_INTERVAL_SECONDS * 3

#: Store-side failures that make a machine ``critical`` on one sighting. A
#: full or preflight-refused disk is neither transient nor recoverable by
#: waiting, and - the reason the probe cannot stand alone here - a backend
#: whose disk is full still answers a read probe perfectly well.
_CRITICAL_STORE_FAILURES: frozenset[str] = frozenset(
    {"disk_full", "disk_preflight_failed"}
)

#: Failures that are critical only in repetition: either can be one transient
#: blip, so a single sighting must not outrank a working store.
_REPEATED_STORE_FAILURES: frozenset[str] = frozenset({"timeout", "unavailable"})
_REPEATED_STORE_FAILURE_MINIMUM = 2


@dataclass(frozen=True, slots=True)
class MachinePressureSignals:
    """One sample of the machine-level readings the tier is computed from.

    Every field tolerates absence: a reading that could not be taken is
    ``None`` (or ``False`` for ``backend_probed``), and an absent reading
    never escalates the tier - only measured evidence does.
    """

    forward_in_flight: bool = False
    forward_age_seconds: float | None = None
    forward_thread_alive: bool | None = None
    gpu_utilization_percent: float | None = None
    gpu_memory_used_mb: float | None = None
    gpu_memory_total_mb: float | None = None
    backend_probed: bool = False
    backend_alive: bool | None = None
    backend_latency_seconds: float | None = None
    backend_probe_bound_seconds: float | None = None
    encode_waiters: int | None = None
    #: Typed failure kinds recorded by jobs that finished recently, one entry
    #: per failed job. Read as store-side evidence the live probe cannot
    #: give: a job already killed by a full disk is a harder fact about the
    #: store than a read that still answers.
    store_failures: tuple[str, ...] = field(default_factory=tuple)


def _gpu_saturated(signals: MachinePressureSignals) -> bool:
    utilization = signals.gpu_utilization_percent
    used = signals.gpu_memory_used_mb
    total = signals.gpu_memory_total_mb
    if utilization is None or used is None or total is None or total <= 0:
        return False
    return (
        utilization / 100.0 >= _GPU_SATURATION_FRACTION
        and used / total >= _GPU_SATURATION_FRACTION
    )


def _backend_slow(signals: MachinePressureSignals) -> bool:
    if not signals.backend_probed or signals.backend_alive is not True:
        return False
    latency = signals.backend_latency_seconds
    bound = signals.backend_probe_bound_seconds
    if latency is None or bound is None or bound <= 0:
        return False
    return latency >= bound * _BACKEND_SLOW_FRACTION


def _critical_findings(signals: MachinePressureSignals) -> tuple[str, ...]:
    """Store-side failure or dead work: the only grounds for ``critical``.

    GPU-side signals are deliberately absent here. A saturated card under a
    long forward is healthy work starved by foreign load - it finishes once
    the card frees - so the GPU can raise the tier to ``elevated`` and no
    further. Only an unanswered or failed store, or an encode worker that
    has died under an open forward window, makes the machine critical.
    """
    findings: list[str] = []
    if signals.backend_probed and signals.backend_alive is not True:
        findings.append(
            "backend_unanswered" if signals.backend_alive is None else "backend_failed"
        )
    if signals.forward_in_flight and signals.forward_thread_alive is False:
        findings.append("encode_thread_dead")
    findings.extend(sorted(_store_failure_findings(signals)))
    return tuple(findings)


def _store_failure_findings(signals: MachinePressureSignals) -> set[str]:
    """Typed job failures that make the store's condition critical."""
    findings: set[str] = set()
    repeated: dict[str, int] = {}
    for kind in signals.store_failures:
        if kind in _CRITICAL_STORE_FAILURES:
            findings.add(f"store_{kind}")
        elif kind in _REPEATED_STORE_FAILURES:
            repeated[kind] = repeated.get(kind, 0) + 1
    findings.update(
        f"store_{kind}_repeated"
        for kind, count in repeated.items()
        if count >= _REPEATED_STORE_FAILURE_MINIMUM
    )
    return findings


def _elevated_findings(signals: MachinePressureSignals) -> tuple[str, ...]:
    findings: list[str] = []
    age = signals.forward_age_seconds
    # An in-flight forward at least this old is pressure evidence, at exactly
    # the threshold the per-job verdict calls a job degraded, so the two
    # vocabularies can never disagree about when a stretch begins.
    if (
        signals.forward_in_flight
        and age is not None
        and age >= DEGRADED_THRESHOLD_SECONDS
    ):
        findings.append("forward_stretched")
    if _gpu_saturated(signals):
        findings.append("gpu_saturated")
    if _backend_slow(signals):
        findings.append("backend_slow")
    if signals.encode_waiters is not None and signals.encode_waiters > 0:
        findings.append("encode_waiters")
    return tuple(findings)


def _classify(signals: MachinePressureSignals) -> tuple[int, tuple[str, ...]]:
    """One sample's raw tier and the condition names that produced it."""
    critical = _critical_findings(signals)
    if critical:
        return _CRITICAL, critical
    elevated = _elevated_findings(signals)
    if elevated:
        return _ELEVATED, elevated
    return _NOMINAL, ()


class PressureEvaluator:
    """Folds raw per-sample tiers into a stable verdict with hysteresis.

    Fast attack, slow release: escalation needs consecutive over-threshold
    samples, and clearing needs a continuous quiet window per rung, stepped
    down one tier at a time. A tier that flaps is worse than none - every
    later consumer of the tier assumes it is stable enough to act on - so
    both directions are damped and the release side is the slower one.
    Thread-safe; the clock is injected so behaviour is testable without
    sleeping.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tier = _NOMINAL
        self._entered_at: float | None = None
        self._last_sample_at: float | None = None
        self._streak_tier = _NOMINAL
        self._streak_count = 0
        self._clear_started_at: float | None = None

    def observe(
        self,
        signals: MachinePressureSignals,
        *,
        now: float,
    ) -> dict[str, object]:
        """Ingest one sample and return the current verdict.

        Calls closer together than the sample interval return the standing
        verdict without consuming a sample, so several concurrent pollers
        cannot make the tier move faster than one. A verdict nothing has
        refreshed for longer than the staleness window lapses to ``nominal``
        before this sample is taken: an unwatched machine is an unmeasured
        one, and an unmeasured one is not under a verdict.
        """
        with self._lock:
            if self._stale(now):
                self._lapse(now)
            if self._accepts(now):
                self._last_sample_at = now
                if self._entered_at is None:
                    self._entered_at = now
                raw, findings = _classify(signals)
                self._ingest(raw, findings, now=now)
            return {
                "tier": PRESSURE_TIERS[self._tier],
                "entered_at": self._entered_at,
            }

    def _stale(self, now: float) -> bool:
        """Whether too long has passed since the standing verdict was fed.

        A clock that went backwards is stale for the same reason a long gap
        is: the elapsed time since the last sample is unknowable, and an
        unknowable gap must release the verdict rather than preserve it.
        """
        last = self._last_sample_at
        if last is None:
            return False
        return now < last or now - last >= _STALE_AFTER_SECONDS

    def _lapse(self, now: float) -> None:
        """Drop a verdict nothing refreshed back to ``nominal``."""
        if self._tier != _NOMINAL:
            self._transition(_NOMINAL, now, ("evidence_stale",))
        self._streak_count = 0
        self._streak_tier = _NOMINAL
        self._clear_started_at = None

    def _accepts(self, now: float) -> bool:
        last = self._last_sample_at
        if last is None or now < last:
            # First sample, or the clock went backwards; refusing samples
            # until the old stamp is reached again would freeze the tier.
            return True
        return now - last >= _SAMPLE_INTERVAL_SECONDS

    def _ingest(self, raw: int, findings: tuple[str, ...], *, now: float) -> None:
        if raw > self._tier:
            self._clear_started_at = None
            self._streak_tier = (
                raw if self._streak_count == 0 else min(self._streak_tier, raw)
            )
            self._streak_count += 1
            if self._streak_count >= _ESCALATION_SAMPLES:
                # Escalate to the worst tier every sample in the streak
                # supported - the minimum, so one critical sample among
                # elevated ones cannot drag the verdict past its evidence.
                self._transition(self._streak_tier, now, findings)
                self._streak_count = 0
            return
        self._streak_count = 0
        if raw == self._tier:
            self._clear_started_at = None
            return
        if self._clear_started_at is None:
            self._clear_started_at = now
            return
        # A tier clears one rung only after this long of continuously calmer
        # samples, and any sample back at or above the tier restarts the clock
        # above, so a race can only extend the verdict and never shorten it.
        # The window that makes a job's silence reportable is the same order of
        # quiet that makes a machine's recovery believable.
        if now - self._clear_started_at >= DEGRADED_THRESHOLD_SECONDS:
            self._transition(self._tier - 1, now, findings)
            # One rung per window: a further drop restarts the clock rather
            # than cascading, so release stays slow all the way down.
            self._clear_started_at = now if raw < self._tier else None

    def _transition(self, tier: int, now: float, findings: tuple[str, ...]) -> None:
        previous = self._tier
        held_for = (
            None if self._entered_at is None else round(now - self._entered_at, 3)
        )
        self._tier = tier
        self._entered_at = now
        # Transitions land in the service log as parseable events so tier
        # history can be read back against job outcomes - that history is
        # what makes the thresholds deferred here settable later.
        log_event(
            logger,
            "service.pressure",
            "tier_changed",
            previous=PRESSURE_TIERS[previous],
            tier=PRESSURE_TIERS[tier],
            held_seconds=held_for,
            findings=",".join(findings) if findings else None,
        )


_evaluator_lock = threading.Lock()
_evaluator: PressureEvaluator | None = None


def get_pressure_evaluator() -> PressureEvaluator:
    """Return the process-wide evaluator; the daemon is the machine singleton."""
    global _evaluator
    evaluator = _evaluator
    if evaluator is None:
        with _evaluator_lock:
            evaluator = _evaluator
            if evaluator is None:
                evaluator = PressureEvaluator()
                _evaluator = evaluator
    return evaluator


def reset_pressure_evaluator() -> None:
    """Drop the process evaluator so the next caller starts fresh (tests only)."""
    global _evaluator
    with _evaluator_lock:
        _evaluator = None
