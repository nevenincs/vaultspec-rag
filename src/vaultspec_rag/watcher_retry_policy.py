"""Admission and retry decisions taken against the durable watcher state.

The state module owns what is recorded and how it is read back; this owns what
to do about it. The split follows the dependency: a decision is a pure function
of a loaded state plus the clock, so the policy reaches down to the state and
the state never reaches back.

Admission tokens live here rather than in the state file. A reservation is
process-local by construction - it fences one in-flight attempt inside this
interpreter - so persisting it would outlive the thing it fences.
"""

from __future__ import annotations

import json
import os
import random
import threading
import uuid
from contextlib import suppress
from dataclasses import asdict, dataclass, replace
from typing import TYPE_CHECKING, Final

from ._atomic_write import NotDurableError, replace_durably
from ._job_errors import JobError, JobErrorKind, classify_error_text
from .watcher_retry import (
    ABSOLUTE_STATE_MAX_BYTES,
    DEFAULT_SCOPE_MAX_BYTES,
    DEFAULT_SCOPE_MAX_PATHS,
    MAX_ERROR_DETAIL_CHARS,
    MAX_RECOVERY_MARKERS,
    RECOVERY_MARKER_SCHEMA_VERSION,
    SCHEMA_VERSION,
    STATE_DIRECTORY,
    RecoveryMarker,
    WatcherCircuitState,
    WatcherPathObservation,
    WatcherRetryDecision,
    WatcherRetryState,
    WatcherRetryStateError,
    WatcherRetryUnavailableError,
    WatcherScopeRefusal,
    WatcherSource,
    cleanup_stale_recovery_temps,
    finite_positive,
    locked_state,
    marker_owner_is_current_process,
    marker_owner_is_live,
    merge_observations,
    positive_int_option,
    process_identity,
    process_identity_is_live,
    read_recovery_marker,
    read_state,
    refuse_scope_capacity,
    restore_captured_paths,
    state_io_failure,
    state_payload_size,
    unit_interval,
    validate_path_observation,
    wall_time,
    write_state,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Self

__all__ = ["WatcherRetryPolicy"]

#: How many admission reservations one interpreter may hold at once. A
#: reservation is released on every terminal outcome, so a table that keeps
#: growing is a leak rather than load, and the bound turns it into a refusal
#: instead of unbounded memory.
_MAX_ACTIVE_ADMISSION_TOKENS: Final = 128
_ACTIVE_ADMISSION_GUARD = threading.Lock()
_ADMISSION_RESERVATIONS: dict[str, bool] = {}


@dataclass(frozen=True, slots=True)
class _WatcherRetryOptions:
    """Explicit retry-policy authority supplied by one caller."""

    canonical_root: str
    source: WatcherSource
    base_seconds: float
    max_seconds: float
    jitter_fraction: float
    failure_threshold: int
    scope_max_paths: int = DEFAULT_SCOPE_MAX_PATHS
    scope_max_bytes: int = DEFAULT_SCOPE_MAX_BYTES
    now: float | None = None


def _decision(
    admitted: bool,
    state: WatcherRetryState,
    now: float,
    reason: str,
) -> WatcherRetryDecision:
    return WatcherRetryDecision(
        admitted=admitted,
        circuit_state=state.circuit_state,
        retry_at=state.next_retry_at,
        retry_in_seconds=max(0.0, state.next_retry_at - now),
        reason=reason,
        attempt_generation=(state.attempt_generation if admitted else None),
        requires_unscoped=state.unscoped_required,
    )


def _classify_failure(error: BaseException) -> tuple[JobErrorKind, bool]:
    kind = (
        error.error_kind
        if isinstance(error, JobError)
        else classify_error_text(str(error)) or JobErrorKind.OTHER
    )
    retryable = kind in {
        JobErrorKind.TIMEOUT,
        JobErrorKind.UNAVAILABLE,
        # Contention on the shared per-root ledger clears when the peer run
        # finishes its transaction. Treating it as non-retryable opens the
        # circuit on the first occurrence and pauses automatic indexing for a
        # condition that resolves itself, which is the outcome classifying it
        # separately exists to avoid.
        JobErrorKind.LEDGER_CONTENDED,
    }
    return kind, retryable


def _finish_admission_token(token: str) -> None:
    with _ACTIVE_ADMISSION_GUARD:
        _ADMISSION_RESERVATIONS.pop(token, None)


def _same_process_marker_token_is_consumable(token: str) -> bool:
    with _ACTIVE_ADMISSION_GUARD:
        active = _ADMISSION_RESERVATIONS.get(token)
        if active is None:
            return True
        if active:
            return False
        del _ADMISSION_RESERVATIONS[token]
        return True


def _attempt_owner_is_live(state: WatcherRetryState) -> bool:
    pid = state.attempt_owner_pid
    create_time = state.attempt_owner_create_time
    if pid is None or create_time is None:
        return False
    return process_identity_is_live(pid, create_time)


def _recovery_marker_is_consumable(
    marker: RecoveryMarker,
    *,
    active_state_token: str | None,
    owned_policy_token: str | None,
) -> bool:
    token = marker.attempt_token
    if token is None or token in {active_state_token, owned_policy_token}:
        return True
    if not marker_owner_is_live(marker):
        return True
    return marker_owner_is_current_process(
        marker
    ) and _same_process_marker_token_is_consumable(token)


class WatcherRetryPolicy:
    """Atomic per-root/source retry and circuit authority."""

    __slots__ = (
        "_admission_handoff_started",
        "_base_seconds",
        "_failure_threshold",
        "_jitter_fraction",
        "_max_seconds",
        "_owned_attempt_token",
        "_path",
        "_root",
        "_scope_max_bytes",
        "_scope_max_paths",
        "_scoped_generation",
        "_source",
        "_state",
    )

    def __init__(
        self,
        path: Path,
        options: _WatcherRetryOptions,
    ) -> None:
        """Load or create a policy using explicit validated retry limits."""
        self._path = path
        self._base_seconds = finite_positive("base_seconds", options.base_seconds)
        self._max_seconds = finite_positive("max_seconds", options.max_seconds)
        if self._max_seconds < self._base_seconds:
            raise ValueError(
                "max_seconds must be greater than or equal to base_seconds"
            )
        self._jitter_fraction = unit_interval(
            "jitter_fraction", options.jitter_fraction
        )
        if type(options.failure_threshold) is not int or options.failure_threshold <= 0:
            raise ValueError("failure_threshold must be a positive integer")
        self._failure_threshold = options.failure_threshold
        self._scope_max_paths = positive_int_option(
            "scope_max_paths", options.scope_max_paths
        )
        self._scope_max_bytes = positive_int_option(
            "scope_max_bytes", options.scope_max_bytes
        )
        if self._scope_max_bytes > ABSOLUTE_STATE_MAX_BYTES:
            raise ValueError("scope_max_bytes exceeds the durable state safety bound")
        self._root = options.canonical_root
        self._admission_handoff_started = False
        self._owned_attempt_token: str | None = None
        self._scoped_generation: int | None = None
        self._source = options.source

        timestamp = wall_time(options.now)
        with locked_state(path):
            try:
                loaded = (
                    read_state(
                        path,
                        scope_max_paths=self._scope_max_paths,
                        scope_max_bytes=self._scope_max_bytes,
                    )
                    if path.exists()
                    else None
                )
            except OSError as exc:
                raise state_io_failure("read", path, exc) from exc
            except ValueError as exc:
                raise WatcherRetryStateError(
                    f"watcher retry state cannot be read: {exc}"
                ) from exc
            if loaded is None:
                loaded = WatcherRetryState(
                    schema_version=SCHEMA_VERSION,
                    canonical_root=options.canonical_root,
                    source=options.source,
                    consecutive_failures=0,
                    last_error_kind=None,
                    last_error_detail=None,
                    last_failure_at=None,
                    last_durable_progress_at=None,
                    next_retry_at=0.0,
                    circuit_state=WatcherCircuitState.CLOSED,
                    convergence_pending=False,
                    unscoped_required=False,
                    convergence_generation=0,
                    pending_paths=(),
                    captured_paths=(),
                    scope_max_paths=self._scope_max_paths,
                    scope_max_bytes=self._scope_max_bytes,
                    scope_refusal=None,
                    attempt_generation=None,
                    attempt_job_id=None,
                    attempt_token=None,
                    attempt_started_at=None,
                    attempt_owner_pid=None,
                    attempt_owner_create_time=None,
                    updated_at=timestamp,
                )
                write_state(path, loaded)
            self._validate_authority(loaded)
            loaded = self._apply_recovery_markers_unlocked(loaded, timestamp)
            state_changed = False
            if (
                loaded.convergence_pending
                and not loaded.unscoped_required
                and not loaded.pending_paths
                and not loaded.captured_paths
            ):
                loaded = replace(
                    loaded,
                    last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
                    last_error_detail=(
                        "watcher recovery lost the exact changed-path scope; "
                        "request an explicit full reindex"
                    ),
                    circuit_state=WatcherCircuitState.OPEN,
                    updated_at=timestamp,
                )
                state_changed = True
            if loaded.attempt_generation is not None and not _attempt_owner_is_live(
                loaded
            ):
                loaded, recovered_changed = self._recover_abandoned_attempt(
                    loaded, timestamp
                )
                state_changed |= recovered_changed
            if state_changed:
                write_state(self._path, loaded)
            self._state = loaded

    def _recover_abandoned_attempt(
        self, state: WatcherRetryState, timestamp: float
    ) -> tuple[WatcherRetryState, bool]:
        """Retain scoped fences for job reconciliation; refuse legacy scope loss."""
        if state.attempt_job_id is None:
            failures = state.consecutive_failures + 1
            return (
                replace(
                    state,
                    consecutive_failures=failures,
                    last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
                    last_error_detail=(
                        "watcher stopped before its admitted indexing attempt "
                        "recorded an outcome and its exact path scope was lost; "
                        "request an explicit full reindex"
                    ),
                    last_failure_at=timestamp,
                    next_retry_at=timestamp
                    + self._retry_delay(failures, random_unit=random.random()),
                    circuit_state=WatcherCircuitState.OPEN,
                    convergence_pending=True,
                    unscoped_required=False,
                    attempt_generation=None,
                    attempt_token=None,
                    attempt_started_at=None,
                    attempt_owner_pid=None,
                    attempt_owner_create_time=None,
                    updated_at=timestamp,
                ),
                True,
            )
        # The adopted token blocks admission and lets ordinary settlement consume
        # or restore the exact generation after canonical job history is checked.
        token = state.attempt_token
        if token is None:  # validated state makes this defensive only
            raise WatcherRetryStateError(
                "watcher recovery attempt has no admission token"
            )
        with _ACTIVE_ADMISSION_GUARD:
            if token in _ADMISSION_RESERVATIONS:
                raise WatcherRetryStateError(
                    "watcher recovery admission token is already owned"
                )
            self._owned_attempt_token = token
            _ADMISSION_RESERVATIONS[token] = True
        return state, False

    @classmethod
    def for_root(
        cls,
        root: Path,
        source: WatcherSource,
        *,
        now: float | None = None,
    ) -> Self:
        """Construct the configured policy for one canonical project root."""
        from .config._settings import get_config

        cfg = get_config()
        resolved_root = root.resolve()
        canonical_root = os.path.normcase(str(resolved_root))
        path = resolved_root / cfg.data_dir / STATE_DIRECTORY / f"{source.value}.json"
        return cls(
            path,
            _WatcherRetryOptions(
                canonical_root=canonical_root,
                source=source,
                base_seconds=cfg.watch_retry_base_seconds,
                max_seconds=cfg.watch_retry_max_seconds,
                jitter_fraction=cfg.watch_retry_jitter_fraction,
                failure_threshold=cfg.watch_circuit_failure_threshold,
                scope_max_paths=cfg.watch_scope_max_paths,
                scope_max_bytes=cfg.watch_scope_max_bytes,
                now=now,
            ),
        )

    @property
    def state(self) -> WatcherRetryState:
        """Return the current immutable policy state."""
        return self._state

    def mark_convergence_pending(
        self, *, now: float | None = None
    ) -> WatcherRetryState:
        """Persist a new coalesced convergence generation for an event batch."""
        timestamp = wall_time(now)
        with locked_state(self._path):
            state = self._refresh_scope_unlocked()
            committed = self._commit_unlocked(
                replace(
                    state,
                    convergence_pending=True,
                    convergence_generation=state.convergence_generation + 1,
                    last_error_kind=(
                        None
                        if state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
                        and not state.unscoped_required
                        and self._scoped_generation == state.convergence_generation
                        else state.last_error_kind
                    ),
                    last_error_detail=(
                        None
                        if state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
                        and not state.unscoped_required
                        and self._scoped_generation == state.convergence_generation
                        else state.last_error_detail
                    ),
                    consecutive_failures=(
                        0
                        if state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
                        and not state.unscoped_required
                        and self._scoped_generation == state.convergence_generation
                        else state.consecutive_failures
                    ),
                    next_retry_at=(
                        0.0
                        if state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
                        and not state.unscoped_required
                        and self._scoped_generation == state.convergence_generation
                        else state.next_retry_at
                    ),
                    circuit_state=(
                        WatcherCircuitState.CLOSED
                        if state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
                        and not state.unscoped_required
                        and self._scoped_generation == state.convergence_generation
                        else state.circuit_state
                    ),
                    updated_at=timestamp,
                )
            )
            self._scoped_generation = committed.convergence_generation
            return committed

    def mark_scope_pending(
        self,
        observations: tuple[WatcherPathObservation, ...],
        *,
        now: float | None = None,
    ) -> WatcherRetryState:
        """Durably merge one exact event batch without truncating authority."""
        if not observations:
            raise ValueError("exact watcher scope must not be empty")
        timestamp = wall_time(now)
        for observation in observations:
            validate_path_observation(observation, source=self._source)
        with locked_state(self._path):
            state = self._refresh_unlocked()
            generation = state.convergence_generation + 1
            merged = merge_observations(
                state.pending_paths,
                observations,
                generation=generation,
            )
            if len(merged) > self._scope_max_paths:
                return self._commit_unlocked(
                    refuse_scope_capacity(state, timestamp=timestamp)
                )
            candidate = replace(
                state,
                convergence_pending=True,
                convergence_generation=generation,
                pending_paths=merged,
                scope_max_paths=self._scope_max_paths,
                scope_max_bytes=self._scope_max_bytes,
                scope_refusal=None,
                unscoped_required=False,
                last_error_kind=None,
                last_error_detail=None,
                consecutive_failures=0,
                next_retry_at=0.0,
                circuit_state=WatcherCircuitState.CLOSED,
                updated_at=timestamp,
            )
            if state_payload_size(candidate) > self._scope_max_bytes:
                return self._commit_unlocked(
                    refuse_scope_capacity(state, timestamp=timestamp)
                )
            self._scoped_generation = generation
            return self._commit_unlocked(candidate)

    def refresh(self) -> WatcherRetryState:
        """Refresh this policy's cached view under the state authority lock."""
        with locked_state(self._path):
            return self._refresh_scope_unlocked()

    def write_recovery_marker(self) -> Path:
        """Durably transfer dirty intent when the main state lock is unavailable."""
        state = self._state
        with _ACTIVE_ADMISSION_GUARD:
            self._admission_handoff_started = True
            owned_token = self._owned_attempt_token
            if (
                owned_token is not None
                and _ADMISSION_RESERVATIONS.get(owned_token) is False
            ):
                del _ADMISSION_RESERVATIONS[owned_token]
        owner_pid, owner_create_time = process_identity()
        marker_state = RecoveryMarker(
            schema_version=RECOVERY_MARKER_SCHEMA_VERSION,
            canonical_root=self._root,
            source=self._source,
            observed_generation=state.convergence_generation,
            attempt_token=owned_token,
            owner_pid=owner_pid,
            owner_create_time=owner_create_time,
            created_at=wall_time(None),
        )
        marker_id = uuid.uuid4().hex
        marker = self._path.with_name(f"{self._path.stem}.recovery.{marker_id}.json")
        # The temp name is a contract, not an incidental detail: an abandoned
        # one is reaped by a sweeper that globs exactly this shape, so it is
        # spelled here rather than delegated to the shared JSON publisher.
        temporary = self._path.with_name(
            f".{self._path.stem}.recovery-write.{marker_id}.tmp"
        )
        try:
            marker.parent.mkdir(parents=True, exist_ok=True)
            with open(temporary, "x", encoding="utf-8") as stream:
                payload = asdict(marker_state)
                payload["source"] = marker_state.source.value
                json.dump(payload, stream, allow_nan=False, separators=(",", ":"))
                stream.flush()
                os.fsync(stream.fileno())
            # replace_durably owns the parent fsync on POSIX and a write-through
            # move on Windows, where the hand-rolled version simply returned.
            with suppress(NotDurableError):
                replace_durably(temporary, marker)
        except OSError as exc:
            with suppress(OSError):
                temporary.unlink()
            raise state_io_failure("write recovery marker", marker, exc) from exc
        return marker

    def reserve_admission(self) -> str | None:
        """Publish one admission token before work can move to a worker thread."""
        with _ACTIVE_ADMISSION_GUARD:
            if self._admission_handoff_started:
                raise WatcherRetryStateError(
                    "watcher admission authority has been handed off"
                )
            if self._owned_attempt_token is not None:
                return None
            if len(_ADMISSION_RESERVATIONS) >= _MAX_ACTIVE_ADMISSION_TOKENS:
                raise WatcherRetryUnavailableError(
                    "watcher admission token capacity is unavailable"
                )
            attempt_token = uuid.uuid4().hex
            self._owned_attempt_token = attempt_token
            _ADMISSION_RESERVATIONS[attempt_token] = False
            return attempt_token

    def admit(self, *, now: float | None = None) -> WatcherRetryDecision:
        """Reserve and synchronously admit one convergence attempt."""
        return self.admit_reserved(self.reserve_admission(), now=now)

    def admit_reserved(
        self,
        attempt_token: str | None,
        *,
        now: float | None = None,
        job_id: str | None = None,
    ) -> WatcherRetryDecision:
        """Commit a token published before asynchronous worker admission."""
        timestamp = wall_time(now)
        if attempt_token is None or not self._activate_admission_token(attempt_token):
            return _decision(
                False,
                self._state,
                timestamp,
                (
                    "convergence attempt already admitted"
                    if attempt_token is None
                    else "admission cancelled by recovery handoff"
                ),
            )
        try:
            with locked_state(self._path):
                state = self._refresh_scope_unlocked()
                if self._owned_attempt_token != attempt_token:
                    _finish_admission_token(attempt_token)
                    return _decision(
                        False,
                        state,
                        timestamp,
                        "admission cancelled by recovery handoff",
                    )
                terminal_scope_loss = (
                    state.last_error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
                )
                if not state.convergence_pending or terminal_scope_loss:
                    self._clear_owned_admission_token(attempt_token)
                    return _decision(
                        False,
                        state,
                        timestamp,
                        (
                            "exact changed-path scope unavailable; "
                            "full reindex required"
                            if terminal_scope_loss
                            else "no convergence pending"
                        ),
                    )
                if state.attempt_generation is not None:
                    self._clear_owned_admission_token(attempt_token)
                    return _decision(
                        False,
                        state,
                        timestamp,
                        "convergence attempt already admitted",
                    )
                if timestamp < state.next_retry_at:
                    self._clear_owned_admission_token(attempt_token)
                    return _decision(False, state, timestamp, "retry delay active")
                attempt_generation = state.convergence_generation
                owner_pid, owner_create_time = process_identity()
                circuit_state = (
                    WatcherCircuitState.HALF_OPEN
                    if state.circuit_state is WatcherCircuitState.OPEN
                    else WatcherCircuitState.CLOSED
                )
                state = self._commit_unlocked(
                    replace(
                        state,
                        circuit_state=circuit_state,
                        pending_paths=(
                            () if job_id is not None else state.pending_paths
                        ),
                        captured_paths=(
                            state.pending_paths
                            if job_id is not None
                            else state.captured_paths
                        ),
                        attempt_generation=attempt_generation,
                        attempt_job_id=job_id,
                        attempt_token=attempt_token,
                        attempt_started_at=timestamp,
                        attempt_owner_pid=owner_pid,
                        attempt_owner_create_time=owner_create_time,
                        updated_at=timestamp,
                    )
                )
                reason = (
                    "half-open convergence admitted"
                    if circuit_state is WatcherCircuitState.HALF_OPEN
                    else "closed convergence admitted"
                )
                _finish_admission_token(attempt_token)
                return _decision(True, state, timestamp, reason)
        except WatcherRetryUnavailableError:
            self._deactivate_admission_token(attempt_token)
            raise
        except BaseException:
            self._clear_owned_admission_token(attempt_token)
            raise

    def _activate_admission_token(self, token: str) -> bool:
        with _ACTIVE_ADMISSION_GUARD:
            if self._owned_attempt_token != token:
                return False
            active = _ADMISSION_RESERVATIONS.get(token)
            if active is None:
                self._owned_attempt_token = None
                return False
            if active:
                raise WatcherRetryStateError(
                    "watcher admission token is already active"
                )
            _ADMISSION_RESERVATIONS[token] = True
            return True

    def _deactivate_admission_token(self, token: str) -> None:
        with _ACTIVE_ADMISSION_GUARD:
            active = _ADMISSION_RESERVATIONS.get(token)
            if active is None:
                if self._owned_attempt_token == token:
                    self._owned_attempt_token = None
                return
            _ADMISSION_RESERVATIONS[token] = False

    def _clear_owned_admission_token(self, token: str) -> None:
        with _ACTIVE_ADMISSION_GUARD:
            if self._owned_attempt_token == token:
                self._owned_attempt_token = None
            _ADMISSION_RESERVATIONS.pop(token, None)

    def _owned_admission_token(self) -> str | None:
        with _ACTIVE_ADMISSION_GUARD:
            return self._owned_attempt_token

    def record_success(
        self,
        attempt_generation: int,
        *,
        now: float | None = None,
    ) -> WatcherRetryState:
        """Close and reset only after a completed convergence attempt."""
        timestamp = wall_time(now)
        with locked_state(self._path):
            state = self._refresh_unlocked()
            self._require_active_attempt(state, attempt_generation)
            newer_generation_pending = state.convergence_generation > attempt_generation
            committed = self._commit_unlocked(
                replace(
                    state,
                    consecutive_failures=0,
                    last_error_kind=None,
                    last_error_detail=None,
                    last_failure_at=None,
                    last_durable_progress_at=timestamp,
                    next_retry_at=0.0,
                    circuit_state=WatcherCircuitState.CLOSED,
                    convergence_pending=newer_generation_pending,
                    # A generation marked mid-attempt keeps its exact paths in
                    # the live convergence slot, so success preserves rather
                    # than forces the unscoped requirement; construction over
                    # a loaded pending bit and scope refresh still escalate
                    # for any instance that cannot scope the pending
                    # generation.
                    unscoped_required=(
                        newer_generation_pending and state.unscoped_required
                    ),
                    captured_paths=(),
                    attempt_job_id=None,
                    attempt_generation=None,
                    attempt_token=None,
                    attempt_started_at=None,
                    attempt_owner_pid=None,
                    attempt_owner_create_time=None,
                    updated_at=timestamp,
                )
            )
            owned_token = self._owned_attempt_token
            if owned_token is not None:
                self._clear_owned_admission_token(owned_token)
            return committed

    def record_interrupted(
        self,
        attempt_generation: int,
        *,
        now: float | None = None,
    ) -> WatcherRetryState:
        """Release a cancelled claim without treating operator stop as failure."""
        timestamp = wall_time(now)
        with locked_state(self._path):
            state = self._refresh_unlocked()
            self._require_active_attempt(state, attempt_generation)
            half_open = state.circuit_state is WatcherCircuitState.HALF_OPEN
            committed = self._commit_unlocked(
                replace(
                    state,
                    next_retry_at=(
                        timestamp + self._base_seconds
                        if half_open
                        else state.next_retry_at
                    ),
                    circuit_state=(
                        WatcherCircuitState.OPEN
                        if half_open
                        else WatcherCircuitState.CLOSED
                    ),
                    convergence_pending=True,
                    # An interruption in a live process - a coalesced
                    # admission or an operator cancel - leaves the exact
                    # dirty paths in the convergence slot, so the unscoped
                    # requirement is preserved, not forced. Process loss is
                    # covered elsewhere: construction over the durable
                    # pending bit and scope refresh both escalate for any
                    # instance that cannot scope the pending generation.
                    unscoped_required=state.unscoped_required,
                    pending_paths=restore_captured_paths(state),
                    captured_paths=(),
                    attempt_job_id=None,
                    attempt_generation=None,
                    attempt_token=None,
                    attempt_started_at=None,
                    attempt_owner_pid=None,
                    attempt_owner_create_time=None,
                    updated_at=timestamp,
                )
            )
            owned_token = self._owned_attempt_token
            if owned_token is not None:
                self._clear_owned_admission_token(owned_token)
            return committed

    def record_failure(
        self,
        error: BaseException,
        attempt_generation: int,
        *,
        now: float | None = None,
        random_unit: float | None = None,
    ) -> WatcherRetryState:
        """Persist classification, exponential backoff, and circuit transition."""
        timestamp = wall_time(now)
        unit = (
            random.random()
            if random_unit is None
            else unit_interval("random_unit", random_unit)
        )
        with locked_state(self._path):
            state = self._refresh_unlocked()
            self._require_active_attempt(state, attempt_generation)
            failures = state.consecutive_failures + 1
            error_kind, retryable = _classify_failure(error)
            requires_explicit_rebuild = error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
            delay = self._retry_delay(failures, random_unit=unit)
            was_half_open = state.circuit_state is WatcherCircuitState.HALF_OPEN
            open_circuit = (
                was_half_open or not retryable or failures >= self._failure_threshold
            )
            detail = str(error).strip() or type(error).__name__
            committed = self._commit_unlocked(
                replace(
                    state,
                    consecutive_failures=failures,
                    last_error_kind=error_kind,
                    last_error_detail=detail[:MAX_ERROR_DETAIL_CHARS],
                    last_failure_at=timestamp,
                    next_retry_at=timestamp + delay,
                    circuit_state=(
                        WatcherCircuitState.OPEN
                        if open_circuit
                        else WatcherCircuitState.CLOSED
                    ),
                    convergence_pending=not requires_explicit_rebuild,
                    unscoped_required=False,
                    pending_paths=(
                        ()
                        if requires_explicit_rebuild
                        else restore_captured_paths(state)
                    ),
                    captured_paths=(),
                    scope_refusal=(
                        WatcherScopeRefusal.FULL_REINDEX_REQUIRED
                        if requires_explicit_rebuild
                        else state.scope_refusal
                    ),
                    attempt_job_id=None,
                    attempt_generation=None,
                    attempt_token=None,
                    attempt_started_at=None,
                    attempt_owner_pid=None,
                    attempt_owner_create_time=None,
                    updated_at=timestamp,
                )
            )
            owned_token = self._owned_attempt_token
            if owned_token is not None:
                self._clear_owned_admission_token(owned_token)
            return committed

    def _retry_delay(self, failures: int, *, random_unit: float) -> float:
        # Failures are counted from one, so the first failure waits the base.
        # The exponent ceiling lives in the shared computation.
        from ._backoff import jittered_backoff

        return jittered_backoff(
            max(0, failures - 1),
            base=self._base_seconds,
            cap=self._max_seconds,
            fraction=self._jitter_fraction,
            random_unit=random_unit,
        )

    def _validate_authority(self, state: WatcherRetryState) -> None:
        if state.canonical_root != self._root or state.source != self._source:
            raise WatcherRetryStateError(
                "watcher retry state does not match its root/source authority"
            )
        if state.scope_max_paths != self._scope_max_paths:
            raise WatcherRetryStateError(
                "watcher scope path bound does not match configured authority"
            )
        if state.scope_max_bytes != self._scope_max_bytes:
            raise WatcherRetryStateError(
                "watcher scope byte bound does not match configured authority"
            )

    def _refresh_unlocked(self) -> WatcherRetryState:
        try:
            state = read_state(
                self._path,
                scope_max_paths=self._scope_max_paths,
                scope_max_bytes=self._scope_max_bytes,
            )
        except OSError as exc:
            raise state_io_failure("read", self._path, exc) from exc
        except ValueError as exc:
            raise WatcherRetryStateError(
                f"watcher retry state cannot be read: {exc}"
            ) from exc
        self._validate_authority(state)
        state = self._apply_recovery_markers_unlocked(state, wall_time(None))
        self._state = state
        return state

    def _load_recovery_markers(
        self,
    ) -> list[tuple[Path, RecoveryMarker]]:
        """Read every recovery marker on disk, enforcing the count bound.

        Returns an empty list when there is nothing to consume so the
        caller can return early without inspecting state.
        """
        try:
            markers = sorted(
                self._path.parent.glob(f"{self._path.stem}.recovery.*.json")
            )
        except OSError as exc:
            raise state_io_failure("list recovery markers", self._path, exc) from exc
        if not markers:
            return []
        if len(markers) > MAX_RECOVERY_MARKERS:
            raise WatcherRetryStateError(
                "watcher retry recovery marker count exceeds its bound"
            )
        try:
            return [
                (
                    marker,
                    read_recovery_marker(
                        marker,
                        canonical_root=self._root,
                        source=self._source,
                    ),
                )
                for marker in markers
            ]
        except ValueError as exc:
            raise WatcherRetryStateError(
                f"watcher retry recovery marker cannot be read: {exc}"
            ) from exc

    def _recovered_state(
        self,
        state: WatcherRetryState,
        *,
        clears_active_attempt: bool,
        clears_half_open: bool,
        observed_generation: int,
        timestamp: float,
    ) -> WatcherRetryState:
        """Rebuild state after consuming recovery markers.

        A fenced attempt clears its ownership fields; a fenced half-open
        probe reopens the circuit and re-arms its backoff.
        """
        cleared: dict[str, object] = (
            {
                "attempt_generation": None,
                "attempt_token": None,
                "attempt_started_at": None,
                "attempt_owner_pid": None,
                "attempt_owner_create_time": None,
            }
            if clears_active_attempt
            else {}
        )
        reopened: dict[str, object] = (
            {
                "next_retry_at": max(
                    state.next_retry_at, timestamp + self._base_seconds
                ),
            }
            if clears_half_open
            else {}
        )
        return replace(
            state,
            convergence_pending=True,
            unscoped_required=False,
            last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
            last_error_detail=(
                "watcher recovery handoff cannot preserve the exact changed-path "
                "scope; request an explicit full reindex"
            ),
            circuit_state=WatcherCircuitState.OPEN,
            convergence_generation=observed_generation + 1,
            updated_at=timestamp,
            **cleared,
            **reopened,
        )

    def _apply_recovery_markers_unlocked(
        self,
        state: WatcherRetryState,
        timestamp: float,
    ) -> WatcherRetryState:
        """Consume bounded cancellation handoff markers under state authority."""
        cleanup_stale_recovery_temps(self._path, timestamp)
        marker_pairs = self._load_recovery_markers()
        if not marker_pairs:
            return state
        owned_policy_token = self._owned_admission_token()
        consumable = [
            (marker_path, marker_state)
            for marker_path, marker_state in marker_pairs
            if _recovery_marker_is_consumable(
                marker_state,
                active_state_token=state.attempt_token,
                owned_policy_token=owned_policy_token,
            )
        ]
        if not consumable:
            return state
        consumed_paths = [marker_path for marker_path, _state in consumable]
        marker_states = [marker_state for _path, marker_state in consumable]
        fenced_tokens = {
            marker.attempt_token
            for marker in marker_states
            if marker.attempt_token is not None
        }
        clears_active_attempt = state.attempt_token in fenced_tokens
        observed_generation = max(
            state.convergence_generation,
            *(marker.observed_generation for marker in marker_states),
        )
        clears_half_open = (
            clears_active_attempt
            and state.circuit_state is WatcherCircuitState.HALF_OPEN
        )
        state = self._recovered_state(
            state,
            clears_active_attempt=clears_active_attempt,
            clears_half_open=clears_half_open,
            observed_generation=observed_generation,
            timestamp=timestamp,
        )
        write_state(self._path, state)
        owned_token = self._owned_admission_token()
        if owned_token is not None and owned_token in fenced_tokens:
            self._clear_owned_admission_token(owned_token)
        for marker in consumed_paths:
            try:
                marker.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise state_io_failure("remove recovery marker", marker, exc) from exc
        return state

    def _refresh_scope_unlocked(self) -> WatcherRetryState:
        """Refuse a pending generation this instance cannot scope."""
        state = self._refresh_unlocked()
        if (
            state.convergence_pending
            and not state.unscoped_required
            and not state.pending_paths
            and not state.captured_paths
            and state.convergence_generation != self._scoped_generation
        ):
            state = self._commit_unlocked(
                replace(
                    state,
                    last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
                    last_error_detail=(
                        "watcher recovery lost the exact changed-path scope; "
                        "request an explicit full reindex"
                    ),
                    circuit_state=WatcherCircuitState.OPEN,
                    updated_at=wall_time(None),
                )
            )
        return state

    def _require_active_attempt(
        self,
        state: WatcherRetryState,
        attempt_generation: int,
    ) -> None:
        if (
            state.attempt_generation != attempt_generation
            or (owned_token := self._owned_admission_token()) is None
            or state.attempt_token != owned_token
        ):
            raise WatcherRetryStateError(
                "watcher retry outcome does not match the admitted attempt"
            )

    def _commit_unlocked(self, state: WatcherRetryState) -> WatcherRetryState:
        write_state(self._path, state)
        self._state = state
        return state
