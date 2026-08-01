"""Concrete job-manager responsibility owner."""

from __future__ import annotations

import logging
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from types import EllipsisType

from .. import job_persistence as _job_persistence
from ..job_models import (
    DesiredJobState,
    JobAttempt,
    JobOutcome,
    JobOutcomeStatus,
    JobSnapshot,
    JobState,
    JobTimestamps,
)
from ..job_models import (
    capabilities_for_state as _capabilities_for_state,
)
from ..logging_config import log_event
from .state import (
    UNOWNED_RUNTIME,
    JobManagerState,
    ManagedJob,
    ManagerStateBackup,
    assign_runtime_owner,
)

logger = logging.getLogger("vaultspec_rag.jobs")

# Progress-only publications defer their durable write onto this budget: the
# mutation lands in memory immediately, and the next publish after the budget
# expires (or any synchronous transition persist, whichever comes first)
# carries it to disk. A full state persist measures ~5.5 ms on a near-empty
# state file, so an unbatched loop publishing per item would otherwise pay a
# per-call fsync; at this budget the durable cost is at most five writes per
# second however fast callers publish. 0.2 s matches the tick budget the
# hashing loops already batch on, keeping one coalescing cadence across layers.
#
# Crash staleness bound: every publish arriving more than one budget after the
# last durable write triggers a flush, so the progress on disk lags the newest
# published progress by less than one budget (plus at most one in-flight write
# skipped by the single-flight guard). That is acceptable because an
# interrupted job's exact progress number is advisory - restore surfaces the
# job as interrupted and the next attempt reconciles from durable checkpoints -
# while its state transitions, which are the contract, always persist
# synchronously before their call returns.
PROGRESS_FLUSH_BUDGET_SECONDS = 0.2

# What a set-aside state file is named for, spelled once each. The name is the
# only diagnosis left once the log has rotated and the operator is looking at a
# directory listing months later, so it states which of the two conditions put
# the file there rather than asserting damage in both.
_INVALID_SUFFIX = "invalid"
_NEWER_BUILD_SUFFIX = "from-newer-build"


class JobManagerPersistence(JobManagerState):
    def _restore_snapshot_locked(self, snapshot: JobSnapshot, *, now: float) -> None:
        """Restore one validated snapshot with no live execution resources."""
        resumable = snapshot.state.is_idle
        restored_runtime = (
            self._process_runtime_snapshot()
            if resumable
            else replace(
                snapshot.runtime,
                task_active=False,
                worker_active=False,
            )
        )
        managed = ManagedJob(
            snapshot=replace(
                snapshot,
                runtime=restored_runtime,
                resources=replace(
                    snapshot.resources,
                    index_capacity_held=False,
                    project_lease_held=False,
                    writer_lock_held=False,
                    pipeline_active=False,
                ),
            ),
            runtime=UNOWNED_RUNTIME,
        )
        if resumable:
            self._active[snapshot.id] = managed
            return
        if snapshot.state.is_live_attempt:
            self._active[snapshot.id] = managed
            self._replace_snapshot_locked(
                managed,
                SnapshotTransition(
                    state=JobState.INTERRUPTED,
                    desired_state=snapshot.desired_state,
                    now=now,
                    finished_at=now,
                    result="The service stopped before the attempt acknowledged.",
                    error_kind="interrupted",
                ),
            )
            self._archive_terminal_locked(managed)
            return
        self._terminal.append(managed)

    def _restore_jobs_locked(
        self,
        restored_jobs: tuple[JobSnapshot, ...],
        *,
        now: float,
    ) -> None:
        """Restore terminal history before active and interrupted resources."""
        restore_order = [
            *(job for job in restored_jobs if job.state.is_terminal),
            *(job for job in restored_jobs if not job.state.is_terminal),
        ]
        for snapshot in restore_order:
            self._restore_snapshot_locked(snapshot, now=now)

    def _trim_restored_history_locked(self) -> None:
        """Apply the configured terminal bound to restored history."""
        while len(self._terminal) > self._max_terminal_history:
            evicted = self._terminal.popleft()
            self._forget_idempotency_locked(evicted.snapshot.id)

    def _restore_bindings_locked(
        self,
        restored_bindings: tuple[
            tuple[str, _job_persistence.IdempotencyBinding],
            ...,
        ],
    ) -> None:
        """Restore only bindings whose target survived configured retention."""
        retained_ids = {
            *self._active,
            *(managed.snapshot.id for managed in self._terminal),
        }
        for key, binding in restored_bindings:
            if binding.job_id in retained_ids:
                self._bind_idempotency_locked(
                    key,
                    binding.signature,
                    binding.job_id,
                )

    def restore_persisted(self) -> JobOutcome:
        """Restore durable jobs without partially applying an invalid state file."""
        command = "restore_jobs"
        loaded = self._load_restore_state(command)
        if isinstance(loaded, JobOutcome):
            return loaded
        persisted = loaded

        restored_jobs = persisted.jobs
        restored_bindings = persisted.bindings
        with self._lock:
            if self._active or self._terminal:
                return self._error(
                    command,
                    "manager_not_empty",
                    "Persisted state can only be restored into an empty manager.",
                )
            backup = self._capture_state_locked()
            now = time.time()
            self._restore_jobs_locked(restored_jobs, now=now)
            self._trim_restored_history_locked()
            self._restore_bindings_locked(restored_bindings)
            self._report_restored_capacity_locked()

            persistence_error = self._persist_locked()
            if persistence_error is not None:
                if not persistence_error.published:
                    self._restore_state_locked(backup)
                return self._persistence_error(command, persistence_error)
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="job_state_restored",
                message=(
                    f"Restored {len(self._active)} nonterminal jobs and "
                    f"{len(self._terminal)} interrupted records."
                ),
            )

    def _report_restored_capacity_locked(self) -> None:
        """Report durable nonterminal work outnumbering the admission bound.

        The configured bound limits admission of *new* work; it is not a cap
        on state a previous service life already recorded. Lowering it below
        what that life had queued must not cost the daemon its start: the
        file is valid and its contents are real queued and paused work, so
        refusing it would brick every subsequent start over a setting change
        and leave no way back that does not involve editing state by hand.
        Dropping the excess is equally wrong, because nonterminal jobs are
        controllable resources an operator can still pause, resume, cancel or
        delete, and silently evicting them discards intent nobody withdrew.

        So every restored job is kept and the excess is carried openly:
        creation and retry already refuse admission while the active set is
        at or above the bound, which drains the overflow without destroying
        any of it. This records the condition for the operator who has to
        understand why new work is being refused.

        Startup dispatches every restored queued job, so an overflow becomes
        a larger dispatch burst than the current bound would allow. That is
        bookkeeping load rather than a compute stampede - attempt-level
        limiters still serialise execution - and the count can only be as
        large as the capacity a previous life admitted under.
        """
        restored = len(self._active)
        if restored <= self._max_nonterminal:
            return
        log_event(
            logger,
            "service.job",
            "restored_over_capacity",
            severity=logging.WARNING,
            restored_nonterminal=restored,
            configured_capacity=self._max_nonterminal,
            admission="refused until restored work drains",
        )

    def _load_restore_state(
        self,
        command: str,
    ) -> _job_persistence.PersistedManagerState | JobOutcome:
        """Load the all-or-nothing restoration input or its stable outcome."""
        path = self._state_path
        if path is None:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="persistence_disabled",
                message="This job manager has no persistence path.",
            )
        try:
            return _job_persistence.load_persisted_state(path)
        except FileNotFoundError:
            return JobOutcome(
                command=command,
                status=JobOutcomeStatus.OK,
                code="no_persisted_jobs",
                message="No persisted job state exists.",
            )
        except OSError as exc:
            # The bytes could not be read at all. That is an environment
            # fault (permissions, disk, a directory at the path), not a bad
            # file, and continuing would mask it: the same fault would break
            # every later persist. Fail startup loudly instead.
            return self._persistence_error(
                command,
                str(exc),
                code="job_state_unreadable",
            )
        except _job_persistence.NewerStateVersionError as exc:
            # Ahead of the general clause on purpose: this is a subclass of
            # ValueError, so the broad tuple below would otherwise swallow an
            # intact file into the corrupt-content diagnosis.
            return self._preserve_newer_state(command, path, exc)
        except (UnicodeError, KeyError, TypeError, ValueError) as exc:
            return self._quarantine_invalid_state(command, path, exc)

    def _quarantine_invalid_state(
        self,
        command: str,
        path: Path,
        reason: Exception,
    ) -> JobOutcome:
        """Move an undecodable state file aside so startup proceeds history-less.

        The file holds job history - observability data - while the index
        itself lives in vector storage, so refusing to start over it would
        destroy availability to protect a record of past work. Absent history
        is already a successful restore outcome; unreadable history joins it
        by being preserved for diagnosis under a timestamped sibling name,
        never deleted and never partially applied.
        """
        moved = self._set_state_aside(
            command,
            path,
            suffix=_INVALID_SUFFIX,
            reason=f"invalid content: {reason}",
            failure_code="job_state_quarantine_failed",
        )
        if isinstance(moved, JobOutcome):
            return moved
        log_event(
            logger,
            "service.job",
            "state_quarantined",
            severity=logging.ERROR,
            source=path,
            destination=moved,
            error=str(reason),
            job_history="lost",
            index_data="unaffected",
        )
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.OK,
            code="job_state_quarantined",
            message=(
                f"Invalid persisted job state was quarantined to {moved}; "
                f"job history was lost, index data is unaffected: {reason}"
            ),
        )

    def _preserve_newer_state(
        self,
        command: str,
        path: Path,
        reason: _job_persistence.NewerStateVersionError,
    ) -> JobOutcome:
        """Set aside intact state this build is too old to interpret, and say so.

        Nothing is wrong with this file. A newer build wrote it, a downgrade
        put an older reader in front of it, and a build that knows the layout
        would load every record in it. Reporting that as damage is a false
        diagnosis an operator acts on, and a name asserting damage outlives
        every log that could have corrected it.

        The disposition is still to move it. Leaving it in place would not
        preserve it: the first lifecycle transition after a history-less start
        rewrites the state file unconditionally, so the one option that looks
        like restraint is the one that destroys the data. Renaming keeps the
        bytes, and keeps them under a name that says a newer build wrote them.
        """
        moved = self._set_state_aside(
            command,
            path,
            suffix=_NEWER_BUILD_SUFFIX,
            reason=str(reason),
            failure_code="job_state_preserve_failed",
        )
        if isinstance(moved, JobOutcome):
            return moved
        log_event(
            logger,
            "service.job",
            "state_from_newer_build",
            severity=logging.WARNING,
            source=path,
            destination=moved,
            declared_version=reason.declared_version,
            reads_versions=f"{reason.minimum_readable} to {reason.maximum_readable}",
            job_state="intact and preserved",
            index_data="unaffected",
        )
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.OK,
            code="job_state_from_newer_build",
            message=(
                f"Persisted job state declares version {reason.declared_version}, "
                f"written by a newer build; this build reads versions "
                f"{reason.minimum_readable} to {reason.maximum_readable}. The file "
                f"is intact and was preserved unchanged at {moved}; move it back "
                f"into place to read it under a build that supports its version."
            ),
        )

    def _set_state_aside(
        self,
        command: str,
        path: Path,
        *,
        suffix: str,
        reason: str,
        failure_code: str,
    ) -> Path | JobOutcome:
        """Move the state file to a fresh sibling, or report what stopped it.

        One move serves every condition that keeps this build from reading the
        file, because the disposition never differs: the next lifecycle
        transition rewrites the state file unconditionally, so a file left in
        place is a file about to be overwritten. Only the name it lands under
        and the diagnosis the caller then reports are per-condition.

        A failed move means the state directory itself is not dependable, and
        that fault aborts startup rather than being masked by continuing
        without persistence.
        """
        destination = _preserved_destination(path, suffix)
        try:
            path.rename(destination)
        except OSError as exc:
            return self._persistence_error(
                command,
                (
                    f"job state ({reason}) could not be moved aside to "
                    f"{destination}: {exc}"
                ),
                code=failure_code,
            )
        return destination

    def _replace_snapshot_locked(
        self, managed: ManagedJob, transition: SnapshotTransition, /
    ) -> None:
        """Advance one job to its next revision under the manager lock.

        Args:
            managed: The job whose snapshot this revision replaces.
            transition: The next state, its desired state, the stamp the
                revision carries, and the optional attempt, clocks and
                outcome fields. A clock left unset keeps its previous
                value; passing ``None`` clears it.
        """
        previous = managed.snapshot
        timestamps = previous.timestamps
        now = ordered_stamp(timestamps, transition.now, job_id=previous.id)
        managed.snapshot = replace(
            previous,
            revision=previous.revision + 1,
            state=transition.state,
            desired_state=transition.desired_state,
            capabilities=_capabilities_for_state(previous.spec, transition.state),
            attempt=transition.attempt or previous.attempt,
            timestamps=replace(
                timestamps,
                state_changed_at=now,
                started_at=_revision_stamp(
                    transition.started_at, timestamps.started_at, now
                ),
                # Admission is a per-attempt fact: any transition that
                # rewrites the start clock (a fresh start, a requeued
                # resume) discards the previous attempt's admission stamp.
                admission_acquired_at=(
                    timestamps.admission_acquired_at
                    if transition.started_at is ...
                    else None
                ),
                control_requested_at=_revision_stamp(
                    transition.control_requested_at,
                    timestamps.control_requested_at,
                    now,
                ),
                control_acknowledged_at=_revision_stamp(
                    transition.control_acknowledged_at,
                    timestamps.control_acknowledged_at,
                    now,
                ),
                finished_at=_revision_stamp(
                    transition.finished_at, timestamps.finished_at, now
                ),
            ),
            result=(previous.result if transition.result is ... else transition.result),
            error_kind=(
                previous.error_kind
                if transition.error_kind is ...
                else transition.error_kind
            ),
            reuse=(previous.reuse if transition.reuse is ... else transition.reuse),
        )

    def _get_terminal_locked(self, job_id: str) -> ManagedJob | None:
        for managed in reversed(self._terminal):
            if managed.snapshot.id == job_id:
                return managed
        return None

    def _capture_state_locked(self) -> ManagerStateBackup:
        managed_jobs = [*self._active.values(), *self._terminal]
        return ManagerStateBackup(
            active=dict(self._active),
            terminal=deque(self._terminal),
            snapshots={job.snapshot.id: job.snapshot for job in managed_jobs},
            runtimes={job.snapshot.id: job.runtime for job in managed_jobs},
            idempotency=OrderedDict(self._idempotency),
            job_idempotency_keys={
                job_id: set(keys) for job_id, keys in self._job_idempotency_keys.items()
            },
            dispatchers=dict(self._dispatchers),
            persistence_dirty=self._persistence_dirty,
        )

    def _restore_state_locked(self, backup: ManagerStateBackup) -> None:
        """Roll one failed generation back to its captured predecessor.

        Rolling a job back to an owner that never held the current ticket puts
        that ticket beyond reach, so restoration replaces owners through the
        one assignment that releases what it drops.
        """
        for managed in [*backup.active.values(), *backup.terminal]:
            job_id = managed.snapshot.id
            snapshot = backup.snapshots.get(job_id)
            runtime = backup.runtimes.get(job_id)
            if snapshot is not None:
                managed.snapshot = snapshot
            if runtime is not None:
                assign_runtime_owner(managed, runtime)
        self._active = backup.active
        self._terminal = backup.terminal
        self._idempotency = OrderedDict(backup.idempotency)
        self._job_idempotency_keys = backup.job_idempotency_keys
        self._dispatchers = backup.dispatchers
        self._persistence_dirty = backup.persistence_dirty

    def _persisted_generation_locked(self) -> _job_persistence.PersistedManagerState:
        """Serialize the complete current manager generation for one write."""
        retained_ids = {
            *self._active,
            *(managed.snapshot.id for managed in self._terminal),
        }
        return _job_persistence.PersistedManagerState(
            jobs=tuple(
                self._snapshot_locked(managed)
                for managed in [*self._active.values(), *self._terminal]
            ),
            bindings=tuple(
                (key, binding)
                for key, binding in self._idempotency.items()
                if binding.job_id in retained_ids
            ),
        )

    def _persist_locked(
        self,
    ) -> _job_persistence.PersistenceWriteError | None:
        """Synchronously write the full current generation before returning.

        Every lifecycle transition funnels through here, so a transition is
        durable before its call returns and unconditionally carries any
        progress mutation still deferred inside the flush budget. The write
        lock orders this write after any in-flight deferred progress flush;
        waiting on it is bounded by that single write.
        """
        path = self._state_path
        if path is None:
            self._persistence_dirty = False
            self._flushed_generation = self._state_generation
            return None
        persisted = self._persisted_generation_locked()
        with self._write_lock:
            try:
                _job_persistence.save_persisted_state(path, persisted)
            except _job_persistence.PersistenceWriteError as exc:
                self._persistence_dirty = True
                logger.error("job state persistence failed: %s", exc)
                return exc
        self._persistence_dirty = False
        self._flushed_generation = self._state_generation
        self._last_flush_monotonic = time.monotonic()
        return None

    def _note_progress_mutation_locked(self) -> None:
        """Advance the in-memory generation past the last durable write."""
        self._state_generation = self._state_generation + 1

    def _begin_progress_flush_locked(self) -> PendingProgressFlush | None:
        """Claim and serialize one deferred progress flush, or decline.

        Called with the manager lock held, immediately after a progress-only
        mutation. Declines while nothing needs flushing, while the budget has
        not expired, and while another thread's write is in flight (the
        single-flight guard: that write's serialization predates this
        mutation, so the pending bookkeeping stays behind and a later publish
        retries). On a claim the write lock is acquired *before* the manager
        lock is released, so no newer generation can reach the file first and
        then be replaced by this older serialization.
        """
        path = self._state_path
        if path is None:
            return None
        if (
            not self._persistence_dirty
            and self._flushed_generation == self._state_generation
        ):
            return None
        if (
            time.monotonic() - self._last_flush_monotonic
            < PROGRESS_FLUSH_BUDGET_SECONDS
        ):
            return None
        if not self._write_lock.acquire(blocking=False):
            return None
        return PendingProgressFlush(
            path=path,
            state=self._persisted_generation_locked(),
            generation=self._state_generation,
        )

    def _complete_progress_flush(
        self,
        pending: PendingProgressFlush,
    ) -> _job_persistence.PersistenceWriteError | None:
        """Write one claimed serialization outside the manager lock.

        The caller must have released the manager lock; the write lock claimed
        by ``_begin_progress_flush_locked`` is released here in every path,
        before the manager lock is retaken for bookkeeping, preserving the
        manager-then-write acquisition order. Success never clears
        ``_persistence_dirty``: that flag can record durability doubt about a
        write that began after this serialization, and only the synchronous
        paths own clearing it.
        """
        error: _job_persistence.PersistenceWriteError | None = None
        try:
            _job_persistence.save_persisted_state(pending.path, pending.state)
        except _job_persistence.PersistenceWriteError as exc:
            error = exc
        finally:
            self._write_lock.release()
        with self._lock:
            if error is None:
                if pending.generation > self._flushed_generation:
                    self._flushed_generation = pending.generation
                self._last_flush_monotonic = time.monotonic()
            elif self._flushed_generation < pending.generation:
                self._persistence_dirty = True
                logger.error("deferred job progress flush failed: %s", error)
        return error

    @staticmethod
    def _persistence_error(
        command: str,
        detail: str | _job_persistence.PersistenceWriteError,
        job: JobSnapshot | None = None,
        *,
        code: str = "job_persistence_failed",
    ) -> JobOutcome:
        return JobOutcome(
            command=command,
            status=JobOutcomeStatus.ERROR,
            code=code,
            message=f"Job state could not be persisted: {detail}",
            job=job,
        )


def ordered_stamp(
    timestamps: JobTimestamps,
    candidate: float,
    *,
    job_id: str,
) -> float:
    """Return a stamp for the next revision that never precedes the record's own.

    Every stamp on a job comes from the wall clock, and the wall clock is free
    to move backwards: a corrective time sync, a restored virtual-machine
    snapshot, a container clock resync, an operator setting it by hand. A
    revision stamped after such a step records a job finishing before it
    started, or changing state before it was created. The reader refuses that
    record, and it refuses the whole file with it, so one job's stamps cost the
    operator every job's history on the next start - over an event nobody
    caused and nothing else reports.

    Flooring the new stamp at the record's last one keeps each record ordered
    against itself, which is exactly what is validated: records are never
    ordered against each other, so two jobs' stamps may still disagree across a
    step and neither history is distorted to hide it.

    This is not manufacturing a chronology the clock did not support. The order
    is the part that is known: these transitions happen in sequence, in one
    process, under one lock. The stamps are the unreliable part. A record
    asserting a finish before its own start asserts something false about the
    world; flooring records the weakest true statement left, that the
    transition did not precede the one before it.

    The cost is real and paid deliberately. A floored stamp is no longer the
    wall-clock instant of its event, so the interval it closes reads as zero
    instead of as the negative duration the raw clocks describe - an operator
    reading it learns the ordering but not the duration. The distortion is
    bounded by the size of the step and confined to the transitions that fall
    inside it, against a whole history otherwise lost, and the served views
    already floor a negative elapsed at zero, so the recorded value is the one
    an operator was going to be shown either way. The step itself is not
    swallowed: this is the only place that can see it, so it is reported here.
    """
    floor = timestamps.state_changed_at
    if candidate >= floor:
        return candidate
    log_event(
        logger,
        "service.job",
        "clock_stepped_back",
        severity=logging.WARNING,
        job_id=job_id,
        backwards_seconds=floor - candidate,
        wall_clock=candidate,
        recorded=floor,
        stamps="floored to the previous state change",
    )
    return floor


def _revision_stamp(
    supplied: float | EllipsisType | None,
    carried: float | None,
    floor: float,
) -> float | None:
    """Carry forward, clear, or floor one optional clock a revision may set.

    Ellipsis keeps the previous value and ``None`` clears it; anything else is
    a stamp this revision is taking now, and shares the revision's floor. Every
    call site supplies the revision's own ``now`` here, so the floor changes a
    value only when that ``now`` was itself floored.
    """
    if supplied is ...:
        return carried
    if supplied is None:
        return None
    return max(supplied, floor)


def _preserved_destination(path: Path, suffix: str) -> Path:
    """Pick a timestamped sibling name that never overwrites earlier evidence.

    A second set-aside under the same suffix within the same second takes a
    counter instead of replacing the first, so evidence accumulates rather
    than the newest arrival erasing the oldest. Only plain files are stepped
    around: any other obstacle at a candidate name is an anomaly in the state
    directory, and the rename is left to fail loudly on it rather than
    guessing a way past.

    No name this produces can be reclaimed as an abandoned temporary, for
    either suffix. Reclamation only ever names a candidate that both begins
    with a dot and ends in ``.tmp``; every name here begins with the state
    file's own name and ends in a timestamp or a counter. Both halves fail,
    so exclusion is structural rather than a matter of the pattern happening
    not to collide.
    """
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    candidate = path.with_name(f"{path.name}.{suffix}-{stamp}")
    counter = 1
    while candidate.is_file():
        candidate = path.with_name(f"{path.name}.{suffix}-{stamp}-{counter}")
        counter += 1
    return candidate


@dataclass(frozen=True, slots=True)
class PendingProgressFlush:
    """One claimed, serialized generation awaiting its out-of-lock write."""

    path: Path
    state: _job_persistence.PersistedManagerState
    generation: int


@dataclass(frozen=True, slots=True)
class SnapshotTransition:
    """Everything one snapshot revision needs beyond the job it replaces.

    One grouped shape rather than a spread of keywords, so a transition that
    gains an input gains it here and every call site is re-checked against
    the field's real type. The clock and outcome fields default to ellipsis
    meaning "carry the previous value forward"; ``None`` clears instead.
    """

    state: JobState
    desired_state: DesiredJobState
    now: float
    attempt: JobAttempt | None = None
    started_at: float | EllipsisType | None = ...
    control_requested_at: float | EllipsisType | None = ...
    control_acknowledged_at: float | EllipsisType | None = ...
    finished_at: float | EllipsisType | None = ...
    result: str | EllipsisType | None = ...
    error_kind: str | EllipsisType | None = ...
    reuse: dict[str, object] | EllipsisType | None = ...
