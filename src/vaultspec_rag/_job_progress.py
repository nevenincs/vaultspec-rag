"""Progress sampling, rate baselines, and the encode telemetry a run reports.

A run reports far more often than a reader needs, so what lands on a record is
sampled and rate-limited here rather than at every call site. The rate window
and its baseline live beside that sampling because they are computed from the
same observations: a collapse is only visible against the median a run has
already sustained.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from statistics import median
from typing import cast

from ._job_registry_state import _lock, _persist_active_snapshot, _records, logger
from .logging_config import log_event

# Progress-rate sampling. The window rides on its own record, so it is
# evicted with that record by the ring and needs no second bound.
#
# The window is per-step and is discarded whenever the step changes,
# because an index job's steps have very different per-unit costs:
# a rate carried over from discovery into embedding predicts embedding
# badly, and a wrong estimate is worse than none.
PROGRESS_WINDOW_KEY = "progress_window"
_PROGRESS_WINDOW_SAMPLES = 16
# Two samples milliseconds apart divide a small count by a smaller
# interval and yield a rate off by orders of magnitude. Refusing to
# answer until the window spans a real interval costs one refresh.
_MIN_RATE_SPAN_SECONDS = 1.0
# Retained samples are spaced by at least this interval. Chunk production
# reports per file and measures ~385 reports/second on a real tree, so a
# window bounded only by sample count holds ~40ms of history and can never
# satisfy the span guard above - the two bounds cancel and the rate is
# never available. Coalescing every report that lands inside the interval
# into the newest sample keeps the window bounded by count while still
# spanning a real interval, without discarding the current count: the
# newest sample always carries it.
_PROGRESS_SAMPLE_MIN_INTERVAL_SECONDS = 0.25
# Run-spanning throughput baseline. The window above answers "how fast right
# now" and, by construction, holds only the last seconds of a fast step: a run
# whose throughput collapses refills it with the collapsed rate within
# seconds, after which nothing on the record remembers the run was ever
# faster. The baseline is the second reading that keeps a collapse visible.
# The window rate is retained at a coarse interval across the step, so the
# median of what the run has actually sustained survives long after the
# window has moved on. Derived from the samples already taken - no second
# sampler - and bounded by both count and spacing, so an hour of history
# costs one small deque of floats per job.
PROGRESS_RATE_HISTORY_KEY = "progress_rate_history"
_PROGRESS_RATE_HISTORY_SAMPLES = 120
_PROGRESS_RATE_HISTORY_MIN_INTERVAL_SECONDS = 30.0
# A median over a handful of observations describes a moment, not a run.
# Eight spaced observations are four minutes of sustained reporting, which is
# the point at which comparing the current rate against the run's own history
# says something an operator can act on instead of flapping on one slow slice.
_PROGRESS_RATE_HISTORY_MIN_OBSERVATIONS = 8
# Mid-step progress writes are throttled per output, never gated on the step
# name changing: a step-name gate admits exactly one write per phase, at the
# instant the counter is zero by construction, so no advancing count ever
# reaches the log or the durable snapshot. The two outputs want different
# rates. The log line is one formatted string and ticks every few seconds,
# giving a minutes-long phase a continuous signal at a bounded volume
# (~12 lines/minute regardless of how fast the step reports). The snapshot
# is an fsynced atomic file write, so it earns a longer interval: half a
# minute bounds how much restored progress a daemon death can lose while
# capping durable writes at two per minute per job. A step transition still
# writes both immediately.
_PROGRESS_LOG_MIN_INTERVAL_SECONDS = 5.0
_PROGRESS_PERSIST_MIN_INTERVAL_SECONDS = 30.0
# Last write times for the throttles above. Rides on the record like the
# rate window, and is dropped from every copied projection the same way.
PROGRESS_EMIT_KEY = "progress_emitted"
# Bounded backend-liveness probe for degradation evidence. The count runs on
# its own daemon thread and the caller waits at most the timeout, so a dead or
# wedged backend can never wedge the jobs surface that is reporting on it. The
# short cache keeps a polling operator view (the TUI refreshes every couple of
# seconds) from stacking one probe thread per poll against a backend that has


def _sample_progress(
    record: dict[str, object],
    *,
    step: str,
    previous_step: object,
    completed: int,
    at: float,
) -> None:
    """Record one progress observation on *record* (caller holds the lock).

    The window is discarded when the step changes, and when the count moves
    backwards - a resumed attempt replays committed units, so measuring
    across that reset would report a negative rate or a wildly low one.

    Reports arriving faster than
    :data:`_PROGRESS_SAMPLE_MIN_INTERVAL_SECONDS` are coalesced into the
    newest sample rather than appended, so a bounded window spans a real
    interval however fast the step reports.
    """
    window = record.get(PROGRESS_WINDOW_KEY)
    samples: deque[tuple[float, int]] = (
        cast("deque[tuple[float, int]]", window)
        if isinstance(window, deque)
        else deque(maxlen=_PROGRESS_WINDOW_SAMPLES)
    )
    if previous_step != step or (samples and completed < samples[-1][1]):
        samples.clear()
        # The baseline describes one step's sustained throughput, so it is
        # discarded wherever the window is: a rate carried across a step
        # change or a replay reset would be a baseline for different work.
        record.pop(PROGRESS_RATE_HISTORY_KEY, None)
    # Measured against the last committed sample, never the newest one: the
    # newest is overwritten in place, so comparing against it would hold the
    # window open forever and turn the rate into a whole-step average that
    # cannot track a slowdown.
    if (
        len(samples) >= 2
        and at - samples[-2][0] < _PROGRESS_SAMPLE_MIN_INTERVAL_SECONDS
    ):
        samples[-1] = (at, completed)
    else:
        samples.append((at, completed))
    record[PROGRESS_WINDOW_KEY] = samples
    _retain_rate_observation(record, at=at)


def _retain_rate_observation(record: dict[str, object], *, at: float) -> None:
    """Retain the current window rate as one run-baseline observation.

    Reads the window the caller has just updated, so the baseline costs no
    second measurement. Observations are spaced by interval rather than by
    report, so a step reporting hundreds of times a second contributes at the
    same cadence as one reporting every few seconds, and the deque bounds how
    much of the run is remembered.
    """
    window = record.get(PROGRESS_WINDOW_KEY)
    if not isinstance(window, deque):
        return
    rate = _window_rate(cast("deque[tuple[float, int]]", window))
    if rate is None:
        return
    raw_history = record.get(PROGRESS_RATE_HISTORY_KEY)
    history: deque[tuple[float, float]] = (
        cast("deque[tuple[float, float]]", raw_history)
        if isinstance(raw_history, deque)
        else deque(maxlen=_PROGRESS_RATE_HISTORY_SAMPLES)
    )
    if history and at - history[-1][0] < _PROGRESS_RATE_HISTORY_MIN_INTERVAL_SECONDS:
        return
    history.append((at, rate))
    record[PROGRESS_RATE_HISTORY_KEY] = history


def _window_rate(samples: deque[tuple[float, int]]) -> float | None:
    """Return the completion rate per second across *samples*, or ``None``.

    Declines to answer rather than guessing: a single sample measures no
    interval, a short span divides by near-zero, and a flat count over a
    real span is a stall the caller should not convert into an estimate.
    """
    if len(samples) < 2:
        return None
    first_at, first_completed = samples[0]
    last_at, last_completed = samples[-1]
    span = last_at - first_at
    advanced = last_completed - first_completed
    if span < _MIN_RATE_SPAN_SECONDS or advanced <= 0:
        return None
    return advanced / span


def _record_window_rate(record: dict[str, object]) -> float | None:
    """The windowed completion rate *record* holds (caller holds the lock)."""
    window = record.get(PROGRESS_WINDOW_KEY)
    if not isinstance(window, deque):
        return None
    return _window_rate(cast("deque[tuple[float, int]]", window))


def _record_baseline_rate(record: dict[str, object]) -> float | None:
    """The median of *record*'s retained observations (caller holds the lock).

    The run's own baseline, against which the windowed rate says whether
    throughput has collapsed. The median rather than the mean because a run
    passes through regimes and a single stalled window must not move the
    reference.
    """
    history = record.get(PROGRESS_RATE_HISTORY_KEY)
    if not isinstance(history, deque):
        return None
    rates = [rate for _at, rate in cast("deque[tuple[float, float]]", history)]
    if len(rates) < _PROGRESS_RATE_HISTORY_MIN_OBSERVATIONS:
        return None
    return median(rates)


def progress_rates(record_id: str) -> tuple[float | None, float | None]:
    """Return one job's windowed rate and its own baseline, under one read.

    What the job is achieving now and the median of what it has sustained on
    this step are two readings of the same record, written by the same
    reporter thread. Taken under one lock acquisition they describe one
    moment, so the ratio between them is a number the record actually held;
    taken separately they can straddle a write, and the comparison would then
    describe no state the job was ever in.

    Either member is ``None`` where the service declines to state it: the job
    is unknown, has not reported twice within one step, has not advanced, or
    has not yet spaced enough observations for a median to describe a run
    rather than a moment. Neither ever means zero.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] != record_id:
                continue
            return _record_window_rate(record), _record_baseline_rate(record)
    return None, None


def _progress_emit_stamps(record: dict[str, object]) -> dict[str, float]:
    """The write-throttle stamps *record* holds (caller holds the lock)."""
    stamps = record.get(PROGRESS_EMIT_KEY)
    if isinstance(stamps, dict):
        return cast("dict[str, float]", stamps)
    return {}


def _due_for_emit(
    stamps: dict[str, float],
    key: str,
    *,
    moment: float,
    min_interval: float,
    step_changed: bool,
) -> bool:
    """Whether the write *key* throttles is due, stamping it when it is.

    A step transition always releases the throttle: the transition is the
    one moment a reader cannot reconstruct from the counter alone.
    """
    last = stamps.get(key)
    if step_changed or last is None or moment - last >= min_interval:
        stamps[key] = moment
        return True
    return False


def _apply_progress_update(
    record: dict[str, object],
    *,
    step: str,
    completed: int,
    total: int | None,
    moment: float,
) -> tuple[dict[str, object] | None, bool]:
    """Fold one progress report into *record* (caller holds the lock).

    Returns the fields of the log line to emit - or ``None`` where the log
    line is throttled - and whether the durable snapshot is due. Both
    writes happen outside the lock, so neither is performed here.
    """
    progress = record.get("progress")
    previous_step = (
        cast("dict[str, object]", progress).get("step")
        if isinstance(progress, dict)
        else None
    )
    record["progress"] = {
        "step": step,
        "completed": completed,
        "total": total,
        "last_updated": moment,
    }
    _sample_progress(
        record,
        step=step,
        previous_step=previous_step,
        completed=completed,
        at=moment,
    )
    step_changed = previous_step != step
    stamps = _progress_emit_stamps(record)
    log_fields: dict[str, object] | None = None
    if _due_for_emit(
        stamps,
        "logged_at",
        moment=moment,
        min_interval=_PROGRESS_LOG_MIN_INTERVAL_SECONDS,
        step_changed=step_changed,
    ):
        log_fields = {
            "job_id": record["id"],
            "source": record.get("source"),
            "trigger": record.get("trigger"),
            "phase": record.get("phase"),
            "step": step,
            "completed": completed,
            "total": total,
        }
    persist = _due_for_emit(
        stamps,
        "persisted_at",
        moment=moment,
        min_interval=_PROGRESS_PERSIST_MIN_INTERVAL_SECONDS,
        step_changed=step_changed,
    )
    record[PROGRESS_EMIT_KEY] = stamps
    return log_fields, persist


def record_progress(
    record_id: str,
    step: str,
    completed: int = 0,
    total: int | None = None,
    *,
    now: float | None = None,
) -> None:
    """Update progress for an active running job.

    Every call updates the in-memory record. The log line and the durable
    snapshot are written immediately on a step transition and are otherwise
    rate-limited independently, so an advancing counter stays visible in the
    log and survives a daemon death without paying an fsync per batch.

    Args:
        record_id: The id returned by :func:`record_start`.
        step: Name of the current phase/step (e.g. "queued", "discover", "embed").
        completed: Count of items processed so far in this step.
        total: Total number of items to process, if known.
        now: The moment the write throttles are judged against; defaults to
            the wall clock. Injectable so throttling is testable without
            sleeping.
    """
    log_fields: dict[str, object] | None = None
    persist = False
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                log_fields, persist = _apply_progress_update(
                    record,
                    step=step,
                    completed=completed,
                    total=total,
                    moment=time.time() if now is None else now,
                )
                break
    if persist:
        _persist_active_snapshot()
    if log_fields is not None:
        log_event(logger, "service.job", "progress", fields=log_fields)


def record_forward_entry(record_id: str, *, ordinal: int, items: int) -> None:
    """Publish that the encode thread is entering one model forward pass.

    Written before the forward begins, so a pass that runs for minutes under
    GPU contention is visible as an in-flight forward (``exited_at`` still
    ``None``) rather than as silence. Progress only ticks at slice
    boundaries; this is the only signal inside one. The calling thread's
    identity is recorded so the read surface can report whether the encode
    thread is still alive while the pass looks stuck.

    *items* is the slice's own item count, and means the same thing at
    every boundary the window is reopened at, so a reader who finds the
    window open never has to ask which moment the number was written at.
    Sub-slice progress through those items is a different quantity and is
    published as its own pair on the encode block.
    """
    now = time.time()
    thread = threading.current_thread()
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                record["forward"] = {
                    "entered_at": now,
                    "exited_at": None,
                    "slice_ordinal": ordinal,
                    "items": items,
                    "thread_ident": thread.ident,
                    "thread_name": thread.name,
                }
                break


def record_forward_exit(record_id: str, *, ordinal: int, items: int) -> None:
    """Close the in-flight forward window ``record_forward_entry`` opened."""
    now = time.time()
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                forward = record.get("forward")
                if isinstance(forward, dict):
                    data = cast("dict[str, object]", forward)
                    data["exited_at"] = now
                    data["slice_ordinal"] = ordinal
                    data["items"] = items
                break


def _encode_block(record: dict[str, object]) -> dict[str, object]:
    """Return one record's encode state, creating it absent (caller locked).

    Every member starts absent rather than at a plausible-looking value: a
    budget of zero and a budget nobody has reported are different findings,
    and only the retry count has a truthful starting value.
    """
    existing = record.get("encode")
    if isinstance(existing, dict):
        return cast("dict[str, object]", existing)
    block: dict[str, object] = {
        "token_budget": None,
        "bucket_items": None,
        "items_done": None,
        "items_total": None,
        "oom_count": 0,
    }
    record["encode"] = block
    return block


def record_encode_bucket(
    record_id: str,
    *,
    token_budget: int | None,
    bucket_items: int | None,
    items_done: int | None,
    items_total: int | None,
) -> None:
    """Publish what one encode-bucket boundary observed.

    *token_budget* is the current per-batch token ceiling and *bucket_items*
    the size of the batch it most recently produced. Together they are what
    turns a collapsed throughput reading into an attributable cause: a run
    encoding a handful of items per batch is bounded by its own memory
    ceiling, not by a stuck forward pass.

    *items_done* and *items_total* are the encode call's own sub-slice
    progress, and are published as a pair because neither means anything
    alone: a lone completed count reads as a size to whoever renders it,
    which is the ambiguity that put the climb here instead of on the
    forward window's slice-scoped item count.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                block = _encode_block(record)
                block["token_budget"] = token_budget
                block["bucket_items"] = bucket_items
                block["items_done"] = items_done
                block["items_total"] = items_total
                break


def record_encode_oom(record_id: str) -> None:
    """Count one out-of-memory encode retry against this job.

    The count is per job and never resets within a run: a ceiling that
    collides repeatedly is the finding, and a gauge that forgets the earlier
    collisions cannot show it.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                block = _encode_block(record)
                count = block.get("oom_count")
                block["oom_count"] = (
                    count + 1
                    if isinstance(count, int) and not isinstance(count, bool)
                    else 1
                )
                break


def telemetry_block(record_id: str, name: str) -> dict[str, object] | None:
    """Return a detached copy of one job's newest *name* telemetry block.

    ``forward`` is the newest forward-pass window, ``encode`` the budget,
    sub-slice progress and retry state the encode stage is working under.
    Both are read the same way, so they are read by the same code: a
    hardening applied to one block that skipped the other would be a
    difference nothing in the record justifies.

    ``None`` means the job is unknown or its run never reported that block.
    The read surface treats that as no signal at all - never as a stall, and
    never as a budget of nothing.
    """
    with _lock:
        for record in reversed(_records):
            if record["id"] == record_id:
                block = record.get(name)
                if isinstance(block, dict):
                    return dict(cast("dict[str, object]", block))
                return None
    return None
