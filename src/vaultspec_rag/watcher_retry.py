"""Persistent watcher retry, circuit, and convergence-intent policy.

One compact state file is stored per project root and source. The watcher keeps
exact changed paths in memory for efficient scoped reconciliation; the durable
``convergence_pending`` bit survives process loss and requests an unscoped
incremental convergence pass when those volatile paths are no longer available.
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
from typing import TYPE_CHECKING, Final, cast

from ._job_errors import JobError, JobErrorKind, classify_error_text
from ._store_locks import FileLock

if TYPE_CHECKING:
    import _thread
    from collections.abc import Generator
    from pathlib import Path
    from typing import Self

__all__ = [
    "WatcherCircuitState",
    "WatcherRetryDecision",
    "WatcherRetryPolicy",
    "WatcherRetryState",
    "WatcherRetryStateError",
    "WatcherRetryUnavailableError",
    "WatcherSource",
]

_SCHEMA_VERSION: Final = 2
_RECOVERY_MARKER_SCHEMA_VERSION: Final = 2
_MAX_ERROR_DETAIL_CHARS: Final = 2048
_MAX_STATE_BYTES: Final = 16 * 1024
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


class WatcherCircuitState(StrEnum):
    """Persistent watcher retry circuit states."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


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
    attempt_generation: int | None
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
        "_scoped_generation",
        "_source",
        "_state",
    )

    def __init__(
        self,
        path: Path,
        *,
        canonical_root: str,
        source: WatcherSource,
        base_seconds: float,
        max_seconds: float,
        jitter_fraction: float,
        failure_threshold: int,
        now: float | None = None,
    ) -> None:
        """Load or create a policy using explicit validated retry limits."""
        self._path = path
        self._base_seconds = _finite_positive("base_seconds", base_seconds)
        self._max_seconds = _finite_positive("max_seconds", max_seconds)
        if self._max_seconds < self._base_seconds:
            raise ValueError(
                "max_seconds must be greater than or equal to base_seconds"
            )
        self._jitter_fraction = _jitter_fraction(jitter_fraction)
        if type(failure_threshold) is not int or failure_threshold <= 0:
            raise ValueError("failure_threshold must be a positive integer")
        self._failure_threshold = failure_threshold
        self._root = canonical_root
        self._admission_handoff_started = False
        self._owned_attempt_token: str | None = None
        self._scoped_generation: int | None = None
        self._source = source

        timestamp = _wall_time(now)
        with _locked_state(path):
            try:
                loaded = _read_state(path) if path.exists() else None
            except OSError as exc:
                raise _state_io_failure("read", path, exc) from exc
            except ValueError as exc:
                raise WatcherRetryStateError(
                    f"watcher retry state cannot be read: {exc}"
                ) from exc
            if loaded is None:
                loaded = WatcherRetryState(
                    schema_version=_SCHEMA_VERSION,
                    canonical_root=canonical_root,
                    source=source,
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
                    attempt_generation=None,
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
            if loaded.convergence_pending and not loaded.unscoped_required:
                loaded = replace(
                    loaded,
                    unscoped_required=True,
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
                    last_error_kind=JobErrorKind.UNAVAILABLE,
                    last_error_detail=(
                        "watcher stopped before its admitted indexing attempt "
                        "recorded an outcome"
                    ),
                    last_failure_at=timestamp,
                    next_retry_at=timestamp
                    + self._retry_delay(
                        failures,
                        random_unit=random.random(),
                    ),
                    circuit_state=WatcherCircuitState.OPEN,
                    convergence_pending=True,
                    unscoped_required=True,
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
        from .config import get_config

        cfg = get_config()
        resolved_root = root.resolve()
        canonical_root = os.path.normcase(str(resolved_root))
        path = resolved_root / cfg.data_dir / _STATE_DIRECTORY / f"{source.value}.json"
        return cls(
            path,
            canonical_root=canonical_root,
            source=source,
            base_seconds=cfg.watch_retry_base_seconds,
            max_seconds=cfg.watch_retry_max_seconds,
            jitter_fraction=cfg.watch_retry_jitter_fraction,
            failure_threshold=cfg.watch_circuit_failure_threshold,
            now=now,
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
                    updated_at=timestamp,
                )
            )
            self._scoped_generation = committed.convergence_generation
            return committed

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
            os.replace(temporary, marker)
            _fsync_parent_best_effort(marker)
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
    ) -> WatcherRetryDecision:
        """Commit a token published before asynchronous worker admission."""
        timestamp = _wall_time(now)
        if attempt_token is None:
            return _decision(
                False,
                self._state,
                timestamp,
                "convergence attempt already admitted",
            )
        if not self._activate_admission_token(attempt_token):
            return _decision(
                False,
                self._state,
                timestamp,
                "admission cancelled by recovery handoff",
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
                if not state.convergence_pending:
                    self._clear_owned_admission_token(attempt_token)
                    return _decision(False, state, timestamp, "no convergence pending")
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
                        attempt_generation=attempt_generation,
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
                    unscoped_required=newer_generation_pending,
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
                    unscoped_required=True,
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
        unit = random.random() if random_unit is None else _random_unit(random_unit)
        with _locked_state(self._path):
            state = self._refresh_unlocked()
            self._require_active_attempt(state, attempt_generation)
            failures = state.consecutive_failures + 1
            error_kind, retryable = _classify_failure(error)
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
                    convergence_pending=True,
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
        exponent = min(max(0, failures - 1), 62)
        nominal = min(self._max_seconds, self._base_seconds * (2.0**exponent))
        jitter = nominal * self._jitter_fraction * ((2.0 * random_unit) - 1.0)
        return min(self._max_seconds, max(0.0, nominal + jitter))

    def _validate_authority(self, state: WatcherRetryState) -> None:
        if state.canonical_root != self._root or state.source != self._source:
            raise WatcherRetryStateError(
                "watcher retry state does not match its root/source authority"
            )

    def _refresh_unlocked(self) -> WatcherRetryState:
        try:
            state = _read_state(self._path)
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
                "circuit_state": WatcherCircuitState.OPEN,
            }
            if clears_half_open
            else {}
        )
        return replace(
            state,
            convergence_pending=True,
            unscoped_required=True,
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
        """Promote a pending generation this instance cannot scope."""
        state = self._refresh_unlocked()
        if (
            state.convergence_pending
            and not state.unscoped_required
            and state.convergence_generation != self._scoped_generation
        ):
            state = self._commit_unlocked(
                replace(
                    state,
                    unscoped_required=True,
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
    }
    return kind, retryable


def _process_identity() -> tuple[int, float]:
    import psutil

    pid = os.getpid()
    try:
        create_time = float(psutil.Process(pid).create_time())
    except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess) as exc:
        raise WatcherRetryStateError(
            "current watcher process identity cannot be established"
        ) from exc
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
    import psutil

    try:
        process = psutil.Process(pid)
        return process.is_running() and math.isclose(
            float(process.create_time()),
            create_time,
            rel_tol=0.0,
            abs_tol=0.01,
        )
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False
    except psutil.AccessDenied:
        # A failure to prove danglingness must never authorize a second writer.
        return True


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
        payload = asdict(state)
        payload["source"] = state.source.value
        payload["last_error_kind"] = (
            state.last_error_kind.value if state.last_error_kind is not None else None
        )
        payload["circuit_state"] = state.circuit_state.value
        tmp = path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as stream:
            json.dump(
                payload,
                stream,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
        _fsync_parent_best_effort(path)
    except OSError as exc:
        raise _state_io_failure("write", path, exc) from exc


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


def _fsync_parent_best_effort(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        directory_fd = os.open(path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


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
        owner_pid=_positive_int(raw, "owner_pid"),
        owner_create_time=_positive_number(raw, "owner_create_time"),
        created_at=_timestamp(raw, "created_at"),
    )
    if marker.canonical_root != canonical_root or marker.source != source:
        raise WatcherRetryStateError(
            "watcher retry recovery marker does not match its root/source authority"
        )
    return marker


def _read_state(path: Path) -> WatcherRetryState:
    if path.stat().st_size > _MAX_STATE_BYTES:
        raise ValueError("watcher retry state exceeds its size bound")
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("watcher retry state must be a JSON object")
    raw = cast("dict[str, object]", parsed)
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version != _SCHEMA_VERSION:
        raise ValueError("unsupported watcher retry state schema")
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
        convergence_pending=_required_bool(raw, "convergence_pending"),
        unscoped_required=_required_bool(raw, "unscoped_required"),
        convergence_generation=_nonnegative_int(raw, "convergence_generation"),
        attempt_generation=_optional_nonnegative_int(
            raw.get("attempt_generation"), "attempt_generation"
        ),
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
    if (
        state.circuit_state is WatcherCircuitState.HALF_OPEN
        and state.attempt_generation is None
    ):
        raise ValueError("half-open watcher circuit requires an active attempt")
    return state


def _required_text(raw: dict[str, object], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"watcher retry field {key!r} must be non-empty text")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("optional watcher retry text must be text or null")
    return value


def _optional_error_kind(value: object) -> JobErrorKind | None:
    text = _optional_text(value)
    return JobErrorKind(text) if text is not None else None


def _nonnegative_int(raw: dict[str, object], key: str) -> int:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"watcher retry field {key!r} must be a nonnegative integer")
    return value


def _optional_nonnegative_int(value: object, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"watcher retry field {key!r} must be null or nonnegative")
    return value


def _optional_positive_int(value: object, key: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"watcher retry field {key!r} must be null or positive")
    return value


def _positive_int(raw: dict[str, object], key: str) -> int:
    value = _optional_positive_int(raw.get(key), key)
    if value is None:
        raise ValueError(f"watcher retry field {key!r} must be positive")
    return value


def _optional_positive_number(value: object, key: str) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"watcher retry field {key!r} must be null or positive")
    return _finite_positive(key, float(value))


def _positive_number(raw: dict[str, object], key: str) -> float:
    value = _optional_positive_number(raw.get(key), key)
    if value is None:
        raise ValueError(f"watcher retry field {key!r} must be positive")
    return value


def _required_bool(raw: dict[str, object], key: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"watcher retry field {key!r} must be a boolean")
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


def _jitter_fraction(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("jitter_fraction must be finite and between zero and one")
    return float(value)


def _random_unit(value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("random_unit must be finite and between zero and one")
    return float(value)
