"""Persistent watcher retry, circuit, and convergence-intent policy.

One compact state file is stored per project root and source. The watcher keeps
exact changed paths in memory for efficient scoped reconciliation. If process
loss separates durable convergence intent from that path authority, recovery
fails closed and requires an explicit full reindex instead of widening scope.
"""

from __future__ import annotations

import errno
import json
import math
import os
import random
import threading
import time
import uuid
import weakref
from contextlib import contextmanager, suppress
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from itertools import islice
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, cast

from . import _typed_fields
from ._atomic_write import (
    JsonWriteOptions,
    NotDurableError,
    replace_durably,
    write_json_atomically,
)
from ._job_errors import JobError, JobErrorKind, classify_error_text
from ._process_probe import pid_alive, pid_is_zombie, pid_start_time
from ._store_locks import FileLock

if TYPE_CHECKING:
    import _thread
    from collections.abc import Callable, Generator
    from pathlib import Path
    from typing import Self

__all__ = [
    "WatcherCircuitState",
    "WatcherPathEvent",
    "WatcherPathObservation",
    "WatcherRetryDecision",
    "WatcherRetryPolicy",
    "WatcherRetryState",
    "WatcherRetryStateError",
    "WatcherRetryUnavailableError",
    "WatcherScopeRefusal",
    "WatcherSource",
]

_SCHEMA_VERSION: Final = 3
_LEGACY_SCHEMA_VERSION: Final = 2
_RECOVERY_MARKER_SCHEMA_VERSION: Final = 2
_MAX_ERROR_DETAIL_CHARS: Final = 2048
_DEFAULT_SCOPE_MAX_PATHS: Final = 100_000
_DEFAULT_SCOPE_MAX_BYTES: Final = 8 * 1024 * 1024
_ABSOLUTE_STATE_MAX_BYTES: Final = 64 * 1024 * 1024
_MAX_RECOVERY_MARKER_BYTES: Final = 4 * 1024
_STATE_DIRECTORY: Final = "watcher-retry"
_STATE_LOCK_TIMEOUT_SECONDS: Final = 2.0
_STATE_LOCK_POLL_SECONDS: Final = 0.01
_MAX_RECOVERY_MARKERS: Final = 128
_MAX_RECOVERY_TEMPS: Final = 128
_MAX_RECOVERY_TEMP_SCAN_PER_PASS: Final = 1024
_RECOVERY_TEMP_GRACE_SECONDS: Final = 60 * 60
_MAX_ACTIVE_ADMISSION_TOKENS: Final = 128
_STATE_LOCKS_GUARD = threading.Lock()
_ACTIVE_ADMISSION_GUARD = threading.Lock()
_ADMISSION_RESERVATIONS: dict[str, bool] = {}
_STATE_TRANSACTION_LOCKS: weakref.WeakValueDictionary[str, _thread.LockType] = (
    weakref.WeakValueDictionary()
)


class WatcherRetryStateError(RuntimeError):
    """Raised when durable watcher retry authority cannot be used safely."""


class WatcherRetryUnavailableError(WatcherRetryStateError):
    """Raised when a retry-state transaction is transiently unavailable."""


class WatcherSource(StrEnum):
    """Index sources independently governed by one watcher."""

    VAULT = "vault"
    CODE = "code"
    DOCUMENT = "document"


class WatcherCircuitState(StrEnum):
    """Persistent watcher retry circuit states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class WatcherPathEvent(StrEnum):
    """Durable filesystem evidence retained for an exact path."""

    ADDED = "added"
    MODIFIED = "modified"
    DELETED = "deleted"


class WatcherScopeRefusal(StrEnum):
    """Typed reasons durable exact scope cannot authorize automatic work."""

    FULL_REINDEX_REQUIRED = "full_reindex_required"
    SCOPE_STATE_INVALID = "scope_state_invalid"
    SCOPE_CAPACITY_EXCEEDED = "scope_capacity_exceeded"
    CONTROLLER_SCHEMA_UNSUPPORTED = "controller_schema_unsupported"


@dataclass(frozen=True, slots=True)
class WatcherPathObservation:
    """Canonical source-qualified root-relative path observation."""

    relative_path: str
    source: WatcherSource
    first_observed_at: float
    latest_observed_at: float
    event_kinds: frozenset[WatcherPathEvent]
    generation: int


@dataclass(frozen=True, slots=True)
class WatcherRetryState:
    """Immutable persistent watcher retry state."""

    schema_version: int
    canonical_root: str
    source: WatcherSource
    consecutive_failures: int
    last_error_kind: JobErrorKind | None
    last_error_detail: str | None
    last_failure_at: float | None
    last_durable_progress_at: float | None
    next_retry_at: float
    circuit_state: WatcherCircuitState
    convergence_pending: bool
    unscoped_required: bool
    convergence_generation: int
    pending_paths: tuple[WatcherPathObservation, ...]
    captured_paths: tuple[WatcherPathObservation, ...]
    scope_max_paths: int
    scope_max_bytes: int
    scope_refusal: WatcherScopeRefusal | None
    attempt_generation: int | None
    attempt_job_id: str | None
    attempt_token: str | None
    attempt_started_at: float | None
    attempt_owner_pid: int | None
    attempt_owner_create_time: float | None
    updated_at: float


@dataclass(frozen=True, slots=True)
class WatcherRetryDecision:
    """Result of checking whether an idle tick may dispatch indexing."""

    admitted: bool
    circuit_state: WatcherCircuitState
    retry_at: float
    retry_in_seconds: float
    reason: str
    attempt_generation: int | None
    requires_unscoped: bool


@dataclass(frozen=True, slots=True)
class _RecoveryMarker:
    """One fenced cancellation handoff outside the contended state lock."""

    schema_version: int
    canonical_root: str
    source: WatcherSource
    observed_generation: int
    attempt_token: str | None
    owner_pid: int
    owner_create_time: float
    created_at: float


@dataclass(frozen=True, slots=True)
class _WatcherRetryOptions:
    """Explicit retry-policy authority supplied by one caller."""

    canonical_root: str
    source: WatcherSource
    base_seconds: float
    max_seconds: float
    jitter_fraction: float
    failure_threshold: int
    scope_max_paths: int = _DEFAULT_SCOPE_MAX_PATHS
    scope_max_bytes: int = _DEFAULT_SCOPE_MAX_BYTES
    now: float | None = None


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
        self._base_seconds = _finite_positive("base_seconds", options.base_seconds)
        self._max_seconds = _finite_positive("max_seconds", options.max_seconds)
        if self._max_seconds < self._base_seconds:
            raise ValueError(
                "max_seconds must be greater than or equal to base_seconds"
            )
        self._jitter_fraction = _unit_interval(
            "jitter_fraction", options.jitter_fraction
        )
        if type(options.failure_threshold) is not int or options.failure_threshold <= 0:
            raise ValueError("failure_threshold must be a positive integer")
        self._failure_threshold = options.failure_threshold
        self._scope_max_paths = _positive_int_option(
            "scope_max_paths", options.scope_max_paths
        )
        self._scope_max_bytes = _positive_int_option(
            "scope_max_bytes", options.scope_max_bytes
        )
        if self._scope_max_bytes > _ABSOLUTE_STATE_MAX_BYTES:
            raise ValueError("scope_max_bytes exceeds the durable state safety bound")
        self._root = options.canonical_root
        self._admission_handoff_started = False
        self._owned_attempt_token: str | None = None
        self._scoped_generation: int | None = None
        self._source = options.source

        timestamp = _wall_time(options.now)
        with _locked_state(path):
            try:
                loaded = (
                    _read_state(
                        path,
                        scope_max_paths=self._scope_max_paths,
                        scope_max_bytes=self._scope_max_bytes,
                    )
                    if path.exists()
                    else None
                )
            except OSError as exc:
                raise _state_io_failure("read", path, exc) from exc
            except ValueError as exc:
                raise WatcherRetryStateError(
                    f"watcher retry state cannot be read: {exc}"
                ) from exc
            if loaded is None:
                loaded = WatcherRetryState(
                    schema_version=_SCHEMA_VERSION,
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
                _write_state(path, loaded)
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
                # An admitted attempt with no recorded outcome means its process
                # vanished. Treat recovery as the next unavailable failure so a
                # restart cannot collapse an established exponential delay.
                failures = loaded.consecutive_failures + 1
                loaded = replace(
                    loaded,
                    consecutive_failures=failures,
                    last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
                    last_error_detail=(
                        "watcher stopped before its admitted indexing attempt "
                        "recorded an outcome and its exact path scope was lost; "
                        "request an explicit full reindex"
                    ),
                    last_failure_at=timestamp,
                    next_retry_at=timestamp
                    + self._retry_delay(
                        failures,
                        random_unit=random.random(),
                    ),
                    circuit_state=WatcherCircuitState.OPEN,
                    convergence_pending=True,
                    unscoped_required=False,
                    attempt_generation=None,
                    attempt_token=None,
                    attempt_started_at=None,
                    attempt_owner_pid=None,
                    attempt_owner_create_time=None,
                    updated_at=timestamp,
                )
                state_changed = True
            if state_changed:
                _write_state(self._path, loaded)
            self._state = loaded

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
        path = resolved_root / cfg.data_dir / _STATE_DIRECTORY / f"{source.value}.json"
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
        timestamp = _wall_time(now)
        with _locked_state(self._path):
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
        timestamp = _wall_time(now)
        for observation in observations:
            _validate_path_observation(observation, source=self._source)
        with _locked_state(self._path):
            state = self._refresh_unlocked()
            generation = state.convergence_generation + 1
            merged = _merge_observations(
                state.pending_paths,
                observations,
                generation=generation,
            )
            if len(merged) > self._scope_max_paths:
                return self._commit_unlocked(
                    _refuse_scope_capacity(state, timestamp=timestamp)
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
            if _state_payload_size(candidate) > self._scope_max_bytes:
                return self._commit_unlocked(
                    _refuse_scope_capacity(state, timestamp=timestamp)
                )
            self._scoped_generation = generation
            return self._commit_unlocked(candidate)

    def refresh(self) -> WatcherRetryState:
        """Refresh this policy's cached view under the state authority lock."""
        with _locked_state(self._path):
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
        owner_pid, owner_create_time = _process_identity()
        marker_state = _RecoveryMarker(
            schema_version=_RECOVERY_MARKER_SCHEMA_VERSION,
            canonical_root=self._root,
            source=self._source,
            observed_generation=state.convergence_generation,
            attempt_token=owned_token,
            owner_pid=owner_pid,
            owner_create_time=owner_create_time,
            created_at=_wall_time(None),
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
            raise _state_io_failure("write recovery marker", marker, exc) from exc
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
        timestamp = _wall_time(now)
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
            with _locked_state(self._path):
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
                owner_pid, owner_create_time = _process_identity()
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
        timestamp = _wall_time(now)
        with _locked_state(self._path):
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
        timestamp = _wall_time(now)
        with _locked_state(self._path):
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
                    pending_paths=_restore_captured_paths(state),
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
        timestamp = _wall_time(now)
        unit = (
            random.random()
            if random_unit is None
            else _unit_interval("random_unit", random_unit)
        )
        with _locked_state(self._path):
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
                    last_error_detail=detail[:_MAX_ERROR_DETAIL_CHARS],
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
                        else _restore_captured_paths(state)
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
            state = _read_state(
                self._path,
                scope_max_paths=self._scope_max_paths,
                scope_max_bytes=self._scope_max_bytes,
            )
        except OSError as exc:
            raise _state_io_failure("read", self._path, exc) from exc
        except ValueError as exc:
            raise WatcherRetryStateError(
                f"watcher retry state cannot be read: {exc}"
            ) from exc
        self._validate_authority(state)
        state = self._apply_recovery_markers_unlocked(state, _wall_time(None))
        self._state = state
        return state

    def _load_recovery_markers(
        self,
    ) -> list[tuple[Path, _RecoveryMarker]]:
        """Read every recovery marker on disk, enforcing the count bound.

        Returns an empty list when there is nothing to consume so the
        caller can return early without inspecting state.
        """
        try:
            markers = sorted(
                self._path.parent.glob(f"{self._path.stem}.recovery.*.json")
            )
        except OSError as exc:
            raise _state_io_failure("list recovery markers", self._path, exc) from exc
        if not markers:
            return []
        if len(markers) > _MAX_RECOVERY_MARKERS:
            raise WatcherRetryStateError(
                "watcher retry recovery marker count exceeds its bound"
            )
        try:
            return [
                (
                    marker,
                    _read_recovery_marker(
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
        _cleanup_stale_recovery_temps(self._path, timestamp)
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
        _write_state(self._path, state)
        owned_token = self._owned_admission_token()
        if owned_token is not None and owned_token in fenced_tokens:
            self._clear_owned_admission_token(owned_token)
        for marker in consumed_paths:
            try:
                marker.unlink()
            except FileNotFoundError:
                continue
            except OSError as exc:
                raise _state_io_failure("remove recovery marker", marker, exc) from exc
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
                    updated_at=_wall_time(None),
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
        _write_state(self._path, state)
        self._state = state
        return state


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


def _process_identity() -> tuple[int, float]:
    pid = os.getpid()
    create_time = pid_start_time(pid)
    if create_time <= 0.0:
        raise WatcherRetryStateError(
            "current watcher process identity cannot be established"
        )
    return pid, _finite_positive("process create time", create_time)


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
    return _process_identity_is_live(pid, create_time)


def _marker_owner_is_live(marker: _RecoveryMarker) -> bool:
    return _process_identity_is_live(marker.owner_pid, marker.owner_create_time)


def _marker_owner_is_current_process(marker: _RecoveryMarker) -> bool:
    pid, create_time = _process_identity()
    return marker.owner_pid == pid and math.isclose(
        marker.owner_create_time,
        create_time,
        rel_tol=0.0,
        abs_tol=0.01,
    )


def _recovery_marker_is_consumable(
    marker: _RecoveryMarker,
    *,
    active_state_token: str | None,
    owned_policy_token: str | None,
) -> bool:
    token = marker.attempt_token
    if token is None or token in {active_state_token, owned_policy_token}:
        return True
    if not _marker_owner_is_live(marker):
        return True
    return _marker_owner_is_current_process(
        marker
    ) and _same_process_marker_token_is_consumable(token)


def _process_identity_is_live(pid: int, create_time: float) -> bool:
    """Return whether *pid* is still the exact recorded owner incarnation.

    The recorded time came back through a persisted JSON record rather than
    from a fresh read, so this passes the wider tolerance the round-trip
    needs instead of the exact-match default.

    An unreadable owner fails OPEN (live): a failure to prove danglingness
    must never authorize a second writer. That is the opposite default from
    the reap paths, which fail closed rather than kill on an unproven
    witness - both are "never act on what you could not confirm", pointed at
    the action each path would otherwise take wrongly.
    """
    if not pid_alive(pid) or pid_is_zombie(pid):
        return False
    live_start = pid_start_time(pid)
    if live_start <= 0.0:
        return True
    return math.isclose(live_start, create_time, rel_tol=0.0, abs_tol=0.01)


@contextmanager
def _locked_state(path: Path) -> Generator[None]:
    """Serialize each retry-state transaction across threads and processes."""
    deadline = time.monotonic() + _STATE_LOCK_TIMEOUT_SECONDS
    thread_lock = _thread_lock_for(path, deadline=deadline)
    remaining = deadline - time.monotonic()
    if remaining <= 0.0 or not thread_lock.acquire(timeout=remaining):
        raise WatcherRetryUnavailableError(
            f"watcher retry thread lock timed out: {path}"
        )
    try:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise _state_io_failure("prepare", path, exc) from exc
        lock_path = path.with_name(f"{path.name}.lock")
        while True:
            lock = FileLock(lock_path)
            if lock.acquire():
                break
            lock_error = lock.last_error
            if lock_error is None:
                raise WatcherRetryStateError(
                    f"watcher retry lock failed without an OS error: {lock_path}"
                )
            if not (
                lock.last_error_stage == "lock"
                and _lock_error_is_contention(lock_error)
            ):
                raise _state_io_failure("lock", lock_path, lock_error) from lock_error
            remaining = deadline - time.monotonic()
            if remaining <= 0.0:
                raise WatcherRetryUnavailableError(
                    f"watcher retry state lock timed out: {path}"
                )
            time.sleep(min(_STATE_LOCK_POLL_SECONDS, remaining))
        try:
            yield
        finally:
            lock.release()
    finally:
        thread_lock.release()


def _thread_lock_for(path: Path, *, deadline: float) -> _thread.LockType:
    """Return one weakly retained path lock within the transaction deadline."""
    remaining = deadline - time.monotonic()
    if remaining <= 0.0 or not _STATE_LOCKS_GUARD.acquire(timeout=remaining):
        raise WatcherRetryUnavailableError(
            f"watcher retry lock registry timed out: {path}"
        )
    try:
        key = os.path.normcase(os.path.abspath(path))
        lock = _STATE_TRANSACTION_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _STATE_TRANSACTION_LOCKS[key] = lock
        return lock
    finally:
        _STATE_LOCKS_GUARD.release()


def _write_state(path: Path, state: WatcherRetryState) -> None:
    try:
        payload = _state_payload(state)
        if _encoded_payload_size(payload) > state.scope_max_bytes:
            raise WatcherRetryStateError(
                "scope_capacity_exceeded: watcher retry state exceeds configured bytes"
            )
        write_json_atomically(
            path,
            payload,
            JsonWriteOptions(sort_keys=True, compact=True, durable=True),
        )
    except OSError as exc:
        raise _state_io_failure("write", path, exc) from exc


def _state_payload(state: WatcherRetryState) -> dict[str, object]:
    payload = asdict(state)
    payload["source"] = state.source.value
    payload["last_error_kind"] = (
        state.last_error_kind.value if state.last_error_kind is not None else None
    )
    payload["circuit_state"] = state.circuit_state.value
    payload["scope_refusal"] = (
        state.scope_refusal.value if state.scope_refusal is not None else None
    )
    for key in ("pending_paths", "captured_paths"):
        raw_observations = cast("list[dict[str, object]]", payload[key])
        for observation in raw_observations:
            observation["source"] = str(observation["source"])
            observation["event_kinds"] = sorted(
                str(kind) for kind in cast("list[object]", observation["event_kinds"])
            )
    return cast("dict[str, object]", payload)


def _encoded_payload_size(payload: dict[str, object]) -> int:
    return len(
        json.dumps(
            payload,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )


def _state_payload_size(state: WatcherRetryState) -> int:
    return _encoded_payload_size(_state_payload(state))


def _state_io_failure(
    action: str,
    path: Path,
    error: OSError,
) -> WatcherRetryStateError:
    """Classify only explicit retryable filesystem outcomes as unavailable."""
    retryable_errnos = {
        errno.EAGAIN,
        errno.EBUSY,
        errno.EINTR,
        errno.ETIMEDOUT,
    }
    retryable_winerrors = {32, 33}
    error_type: type[WatcherRetryStateError] = (
        WatcherRetryUnavailableError
        if error.errno in retryable_errnos
        or getattr(error, "winerror", None) in retryable_winerrors
        else WatcherRetryStateError
    )
    return error_type(f"watcher retry state {action} failed for {path}: {error}")


def _lock_error_is_contention(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK} or getattr(
        error, "winerror", None
    ) in {32, 33}


def _cleanup_stale_recovery_temps(path: Path, timestamp: float) -> None:
    """Remove only time-confirmed abandoned marker temporaries within a cap."""
    try:
        pattern = f".{path.stem}.recovery-write.*.tmp"
        candidates = list(
            islice(
                path.parent.glob(pattern),
                _MAX_RECOVERY_TEMP_SCAN_PER_PASS,
            )
        )
    except OSError as exc:
        raise _state_io_failure("list recovery temporaries", path, exc) from exc

    retained = 0
    for candidate in candidates:
        try:
            modified_at = candidate.stat().st_mtime
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _state_io_failure(
                "inspect recovery temporary", candidate, exc
            ) from exc
        if timestamp - modified_at < _RECOVERY_TEMP_GRACE_SECONDS:
            retained += 1
            if retained > _MAX_RECOVERY_TEMPS:
                raise WatcherRetryStateError(
                    "watcher retry live recovery temporary count exceeds its bound"
                )
            continue
        try:
            candidate.unlink()
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise _state_io_failure(
                "remove stale recovery temporary", candidate, exc
            ) from exc


def _read_recovery_marker(
    path: Path,
    *,
    canonical_root: str,
    source: WatcherSource,
) -> _RecoveryMarker:
    """Read one current-schema marker and verify its retry authority."""
    try:
        if path.stat().st_size > _MAX_RECOVERY_MARKER_BYTES:
            raise ValueError("watcher retry recovery marker exceeds its size bound")
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise _state_io_failure("read recovery marker", path, exc) from exc
    if not isinstance(parsed, dict):
        raise WatcherRetryStateError(
            "watcher retry recovery marker must be a JSON object"
        )
    raw = cast("dict[str, object]", parsed)
    schema_version = raw.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version != _RECOVERY_MARKER_SCHEMA_VERSION
    ):
        raise WatcherRetryStateError("unsupported watcher retry recovery marker schema")
    marker = _RecoveryMarker(
        schema_version=_RECOVERY_MARKER_SCHEMA_VERSION,
        canonical_root=_required_text(raw, "canonical_root"),
        source=WatcherSource(_required_text(raw, "source")),
        observed_generation=_nonnegative_int(raw, "observed_generation"),
        attempt_token=_optional_text(raw.get("attempt_token")),
        owner_pid=_required_positive(raw, "owner_pid", _optional_positive_int),
        owner_create_time=_required_positive(
            raw,
            "owner_create_time",
            _optional_positive_number,
        ),
        created_at=_timestamp(raw, "created_at"),
    )
    if marker.canonical_root != canonical_root or marker.source != source:
        raise WatcherRetryStateError(
            "watcher retry recovery marker does not match its root/source authority"
        )
    return marker


def _read_state(
    path: Path,
    *,
    scope_max_paths: int,
    scope_max_bytes: int,
) -> WatcherRetryState:
    file_size = path.stat().st_size
    if file_size > _ABSOLUTE_STATE_MAX_BYTES:
        raise ValueError("watcher retry state exceeds its size bound")
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("watcher retry state must be a JSON object")
    raw = cast("dict[str, object]", parsed)
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version not in {
        _LEGACY_SCHEMA_VERSION,
        _SCHEMA_VERSION,
    }:
        raise ValueError(
            "controller_schema_unsupported: unsupported watcher retry state schema"
        )
    legacy = schema_version == _LEGACY_SCHEMA_VERSION
    pending_paths = (
        () if legacy else _path_observations(raw.get("pending_paths"), "pending_paths")
    )
    captured_paths = (
        ()
        if legacy
        else _path_observations(raw.get("captured_paths"), "captured_paths")
    )
    convergence_pending = _required_bool(raw, "convergence_pending")
    scope_refusal = (
        WatcherScopeRefusal.FULL_REINDEX_REQUIRED
        if legacy and convergence_pending
        else _optional_scope_refusal(raw.get("scope_refusal"))
    )
    state = WatcherRetryState(
        schema_version=_SCHEMA_VERSION,
        canonical_root=_required_text(raw, "canonical_root"),
        source=WatcherSource(_required_text(raw, "source")),
        consecutive_failures=_nonnegative_int(raw, "consecutive_failures"),
        last_error_kind=_optional_error_kind(raw.get("last_error_kind")),
        last_error_detail=_optional_text(raw.get("last_error_detail")),
        last_failure_at=_optional_timestamp(raw.get("last_failure_at")),
        last_durable_progress_at=_optional_timestamp(
            raw.get("last_durable_progress_at")
        ),
        next_retry_at=_timestamp(raw, "next_retry_at"),
        circuit_state=WatcherCircuitState(_required_text(raw, "circuit_state")),
        convergence_pending=convergence_pending,
        unscoped_required=_required_bool(raw, "unscoped_required"),
        convergence_generation=_nonnegative_int(raw, "convergence_generation"),
        pending_paths=pending_paths,
        captured_paths=captured_paths,
        scope_max_paths=scope_max_paths,
        scope_max_bytes=scope_max_bytes,
        scope_refusal=scope_refusal,
        attempt_generation=_optional_int_at_least(
            raw.get("attempt_generation"), "attempt_generation", 0
        ),
        attempt_job_id=(None if legacy else _optional_text(raw.get("attempt_job_id"))),
        attempt_token=_optional_text(raw.get("attempt_token")),
        attempt_started_at=_optional_timestamp(raw.get("attempt_started_at")),
        attempt_owner_pid=_optional_positive_int(
            raw.get("attempt_owner_pid"), "attempt_owner_pid"
        ),
        attempt_owner_create_time=_optional_positive_number(
            raw.get("attempt_owner_create_time"), "attempt_owner_create_time"
        ),
        updated_at=_timestamp(raw, "updated_at"),
    )
    _validate_loaded_state(
        state,
        file_size=file_size,
        scope_max_paths=scope_max_paths,
        scope_max_bytes=scope_max_bytes,
    )
    return state


def _validate_loaded_state(
    state: WatcherRetryState,
    *,
    file_size: int,
    scope_max_paths: int,
    scope_max_bytes: int,
) -> None:
    attempt_fields = (
        state.attempt_generation,
        state.attempt_token,
        state.attempt_started_at,
        state.attempt_owner_pid,
        state.attempt_owner_create_time,
    )
    active_field_count = sum(value is not None for value in attempt_fields)
    if active_field_count not in (0, len(attempt_fields)):
        raise ValueError("watcher attempt identity must be wholly present or absent")
    if state.unscoped_required and not state.convergence_pending:
        raise ValueError("unscoped watcher convergence requires pending intent")
    if state.attempt_generation is not None:
        if not state.convergence_pending:
            raise ValueError("active watcher attempt requires pending convergence")
        if state.attempt_generation > state.convergence_generation:
            raise ValueError("watcher attempt generation exceeds convergence")
    _validate_loaded_scope(
        state,
        file_size=file_size,
        scope_max_paths=scope_max_paths,
        scope_max_bytes=scope_max_bytes,
    )
    if (
        state.circuit_state is WatcherCircuitState.HALF_OPEN
        and state.attempt_generation is None
    ):
        raise ValueError("half-open watcher circuit requires an active attempt")


def _validate_loaded_scope(
    state: WatcherRetryState,
    *,
    file_size: int,
    scope_max_paths: int,
    scope_max_bytes: int,
) -> None:
    observations = state.pending_paths + state.captured_paths
    for observation in observations:
        _validate_path_observation(observation, source=state.source)
        if observation.generation > state.convergence_generation:
            raise ValueError("watcher path generation exceeds convergence")
    identities = [
        (observation.source, observation.relative_path)
        for observation in state.pending_paths
    ]
    if len(identities) != len(set(identities)):
        raise ValueError("pending watcher paths must be unique")
    if len(observations) > scope_max_paths:
        raise ValueError("scope_capacity_exceeded: watcher path count exceeds bound")
    if file_size > scope_max_bytes:
        raise ValueError("scope_capacity_exceeded: watcher state exceeds byte bound")
    if state.captured_paths and (
        state.attempt_generation is None or state.attempt_job_id is None
    ):
        raise ValueError("captured watcher scope requires complete attempt/job fencing")


def _required_field[T](
    raw: dict[str, object],
    key: str,
    narrow: _typed_fields.Narrower[T],
    expectation: str,
) -> T:
    """Read one required state field, naming what it had to be."""
    return narrow(
        raw.get(key),
        on_invalid=lambda: ValueError(
            f"watcher retry field {key!r} must be {expectation}"
        ),
    )


def _required_text(raw: dict[str, object], key: str) -> str:
    """Bind the non-empty-text expectation to the two-argument reader shape."""
    return _required_field(raw, key, _typed_fields.required_str, "non-empty text")


def _required_bool(raw: dict[str, object], key: str) -> bool:
    """Bind the boolean expectation to the two-argument reader shape."""
    return _required_field(raw, key, _typed_fields.required_bool, "a boolean")


def _path_observations(
    value: object, field_name: str
) -> tuple[WatcherPathObservation, ...]:
    if not isinstance(value, list):
        raise ValueError(f"watcher retry field {field_name!r} must be a list")
    observations: list[WatcherPathObservation] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError(f"watcher retry field {field_name!r} has a malformed path")
        raw = cast("dict[str, object]", item)
        event_values = raw.get("event_kinds")
        if not isinstance(event_values, list) or not event_values:
            raise ValueError("watcher path event_kinds must be a non-empty list")
        observations.append(
            WatcherPathObservation(
                relative_path=_required_text(raw, "relative_path"),
                source=WatcherSource(_required_text(raw, "source")),
                first_observed_at=_timestamp(raw, "first_observed_at"),
                latest_observed_at=_timestamp(raw, "latest_observed_at"),
                event_kinds=frozenset(
                    WatcherPathEvent(
                        _typed_fields.required_str(
                            value,
                            on_invalid=lambda: ValueError(
                                "watcher path event kind must be non-empty text"
                            ),
                        )
                    )
                    for value in event_values
                ),
                generation=_required_positive(
                    raw, "generation", _optional_positive_int
                ),
            )
        )
    return tuple(observations)


def _optional_scope_refusal(value: object) -> WatcherScopeRefusal | None:
    text = _optional_text(value)
    return WatcherScopeRefusal(text) if text is not None else None


def _validate_path_observation(
    observation: WatcherPathObservation,
    *,
    source: WatcherSource,
) -> None:
    path = PurePosixPath(observation.relative_path)
    if (
        not observation.relative_path
        or path.is_absolute()
        or path.parts[0].endswith(":")
        or "\\" in observation.relative_path
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ValueError("scope_state_invalid: watcher path must be root-relative")
    if observation.source is not source:
        raise ValueError(
            "scope_state_invalid: watcher path has foreign source authority"
        )
    if observation.generation < 1 or not observation.event_kinds:
        raise ValueError("scope_state_invalid: watcher path evidence is incomplete")
    if (
        not math.isfinite(observation.first_observed_at)
        or not math.isfinite(observation.latest_observed_at)
        or observation.first_observed_at < 0
        or observation.latest_observed_at < observation.first_observed_at
    ):
        raise ValueError("scope_state_invalid: watcher path timestamps are invalid")


def _merge_observations(
    current: tuple[WatcherPathObservation, ...],
    incoming: tuple[WatcherPathObservation, ...],
    *,
    generation: int,
) -> tuple[WatcherPathObservation, ...]:
    merged = {(item.source, item.relative_path): item for item in current}
    for item in incoming:
        key = (item.source, item.relative_path)
        previous = merged.get(key)
        merged[key] = replace(
            item,
            first_observed_at=(
                min(previous.first_observed_at, item.first_observed_at)
                if previous is not None
                else item.first_observed_at
            ),
            event_kinds=(
                previous.event_kinds | item.event_kinds
                if previous is not None
                else item.event_kinds
            ),
            generation=generation,
        )
    return tuple(sorted(merged.values(), key=lambda item: item.relative_path))


def _restore_captured_paths(
    state: WatcherRetryState,
) -> tuple[WatcherPathObservation, ...]:
    restored = {
        (item.source, item.relative_path): item
        for item in state.captured_paths + state.pending_paths
    }
    return tuple(sorted(restored.values(), key=lambda item: item.relative_path))


def _refuse_scope_capacity(
    state: WatcherRetryState,
    *,
    timestamp: float,
) -> WatcherRetryState:
    return replace(
        state,
        convergence_pending=True,
        scope_refusal=WatcherScopeRefusal.SCOPE_CAPACITY_EXCEEDED,
        last_error_kind=JobErrorKind.FULL_REINDEX_REQUIRED,
        last_error_detail=(
            "scope_capacity_exceeded: exact watcher scope exceeds configured capacity"
        ),
        circuit_state=WatcherCircuitState.OPEN,
        updated_at=timestamp,
    )


def _positive_int_option(name: str, value: int) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _optional_text(value: object) -> str | None:
    return _typed_fields.optional_str(
        value,
        on_invalid=lambda: ValueError(
            "optional watcher retry text must be text or null"
        ),
    )


def _optional_error_kind(value: object) -> JobErrorKind | None:
    text = _optional_text(value)
    return JobErrorKind(text) if text is not None else None


def _nonnegative_int(raw: dict[str, object], key: str) -> int:
    return _typed_fields.required_int(
        raw.get(key),
        minimum=0,
        on_invalid=lambda: ValueError(
            f"watcher retry field {key!r} must be a nonnegative integer"
        ),
    )


def _optional_int_at_least(value: object, key: str, minimum: int) -> int | None:
    return _typed_fields.optional_int(
        value,
        minimum=minimum,
        on_invalid=lambda: ValueError(
            f"watcher retry field {key!r} must be null or at least {minimum}"
        ),
    )


def _optional_positive_int(value: object, key: str) -> int | None:
    """Bind the positive bound to the two-argument reader shape."""
    return _optional_int_at_least(value, key, 1)


def _optional_positive_number(value: object, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"watcher retry field {key!r} must be null or positive")
    return _finite_positive(key, float(value))


def _required_positive[T: (int, float)](
    raw: dict[str, object],
    key: str,
    optional: Callable[[object, str], T | None],
) -> T:
    value = optional(raw.get(key), key)
    if value is None:
        raise ValueError(f"watcher retry field {key!r} must be positive")
    return value


def _timestamp(raw: dict[str, object], key: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"watcher retry field {key!r} must be a finite timestamp")
    return _finite_nonnegative(key, float(value))


def _optional_timestamp(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("optional watcher retry timestamp must be numeric or null")
    return _finite_nonnegative("timestamp", float(value))


def _wall_time(value: float | None) -> float:
    return _finite_nonnegative("now", time.time() if value is None else value)


def _finite_positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def _finite_nonnegative(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return float(value)


def _unit_interval(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between zero and one")
    return float(value)
