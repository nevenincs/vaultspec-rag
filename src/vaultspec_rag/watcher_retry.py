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
import threading
import time
import weakref
from contextlib import contextmanager
from dataclasses import asdict, dataclass, replace
from enum import StrEnum
from itertools import islice
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Final, cast

from . import _typed_fields
from ._atomic_write import (
    JsonWriteOptions,
    write_json_atomically,
)
from ._job_errors import JobErrorKind
from ._process_probe import pid_alive, pid_is_zombie, pid_start_time
from ._store_locks import FileLock

if TYPE_CHECKING:
    import _thread
    from collections.abc import Callable, Generator
    from pathlib import Path

__all__ = [
    "ABSOLUTE_STATE_MAX_BYTES",
    "DEFAULT_SCOPE_MAX_BYTES",
    "DEFAULT_SCOPE_MAX_PATHS",
    "MAX_ERROR_DETAIL_CHARS",
    "MAX_RECOVERY_MARKERS",
    "RECOVERY_MARKER_SCHEMA_VERSION",
    "STATE_DIRECTORY",
    "RecoveryMarker",
    "WatcherCircuitState",
    "WatcherPathEvent",
    "WatcherPathObservation",
    "WatcherRetryDecision",
    "WatcherRetryState",
    "WatcherRetryStateError",
    "WatcherRetryUnavailableError",
    "WatcherScopeRefusal",
    "WatcherSource",
    "cleanup_stale_recovery_temps",
    "finite_nonnegative",
    "finite_positive",
    "is_valid_watcher_relative_path",
    "locked_state",
    "marker_owner_is_current_process",
    "marker_owner_is_live",
    "merge_observations",
    "positive_int_option",
    "process_identity",
    "process_identity_is_live",
    "read_recovery_marker",
    "read_state",
    "refuse_scope_capacity",
    "restore_captured_paths",
    "state_io_failure",
    "state_payload_size",
    "unit_interval",
    "validate_path_observation",
    "wall_time",
    "write_state",
]

SCHEMA_VERSION: Final = 3
_LEGACY_SCHEMA_VERSION: Final = 2
RECOVERY_MARKER_SCHEMA_VERSION: Final = 2
MAX_ERROR_DETAIL_CHARS: Final = 2048
DEFAULT_SCOPE_MAX_PATHS: Final = 100_000
DEFAULT_SCOPE_MAX_BYTES: Final = 8 * 1024 * 1024
ABSOLUTE_STATE_MAX_BYTES: Final = 64 * 1024 * 1024
_MAX_RECOVERY_MARKER_BYTES: Final = 4 * 1024
STATE_DIRECTORY: Final = "watcher-retry"
_STATE_LOCK_TIMEOUT_SECONDS: Final = 2.0
_STATE_LOCK_POLL_SECONDS: Final = 0.01
MAX_RECOVERY_MARKERS: Final = 128
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


def is_valid_watcher_relative_path(value: str) -> bool:
    """Return whether a path is canonical, non-empty, and root-relative."""
    path = PurePosixPath(value)
    return bool(
        value
        and not path.is_absolute()
        and not path.parts[0].endswith(":")
        and "\\" not in value
        and all(part not in ("", ".", "..") for part in path.parts)
    )


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
class RecoveryMarker:
    """One fenced cancellation handoff outside the contended state lock."""

    schema_version: int
    canonical_root: str
    source: WatcherSource
    observed_generation: int
    attempt_token: str | None
    owner_pid: int
    owner_create_time: float
    created_at: float


def process_identity() -> tuple[int, float]:
    pid = os.getpid()
    create_time = pid_start_time(pid)
    if create_time <= 0.0:
        raise WatcherRetryStateError(
            "current watcher process identity cannot be established"
        )
    return pid, finite_positive("process create time", create_time)


def marker_owner_is_live(marker: RecoveryMarker) -> bool:
    return process_identity_is_live(marker.owner_pid, marker.owner_create_time)


def marker_owner_is_current_process(marker: RecoveryMarker) -> bool:
    pid, create_time = process_identity()
    return marker.owner_pid == pid and math.isclose(
        marker.owner_create_time,
        create_time,
        rel_tol=0.0,
        abs_tol=0.01,
    )


def process_identity_is_live(pid: int, create_time: float) -> bool:
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
def locked_state(path: Path) -> Generator[None]:
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
            raise state_io_failure("prepare", path, exc) from exc
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
                raise state_io_failure("lock", lock_path, lock_error) from lock_error
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


def write_state(path: Path, state: WatcherRetryState) -> None:
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
        raise state_io_failure("write", path, exc) from exc


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


def state_payload_size(state: WatcherRetryState) -> int:
    return _encoded_payload_size(_state_payload(state))


def state_io_failure(
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


def cleanup_stale_recovery_temps(path: Path, timestamp: float) -> None:
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
        raise state_io_failure("list recovery temporaries", path, exc) from exc

    retained = 0
    for candidate in candidates:
        try:
            modified_at = candidate.stat().st_mtime
        except FileNotFoundError:
            continue
        except OSError as exc:
            raise state_io_failure(
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
            raise state_io_failure(
                "remove stale recovery temporary", candidate, exc
            ) from exc


def read_recovery_marker(
    path: Path,
    *,
    canonical_root: str,
    source: WatcherSource,
) -> RecoveryMarker:
    """Read one current-schema marker and verify its retry authority."""
    try:
        if path.stat().st_size > _MAX_RECOVERY_MARKER_BYTES:
            raise ValueError("watcher retry recovery marker exceeds its size bound")
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise state_io_failure("read recovery marker", path, exc) from exc
    if not isinstance(parsed, dict):
        raise WatcherRetryStateError(
            "watcher retry recovery marker must be a JSON object"
        )
    raw = cast("dict[str, object]", parsed)
    schema_version = raw.get("schema_version")
    if (
        type(schema_version) is not int
        or schema_version != RECOVERY_MARKER_SCHEMA_VERSION
    ):
        raise WatcherRetryStateError("unsupported watcher retry recovery marker schema")
    marker = RecoveryMarker(
        schema_version=RECOVERY_MARKER_SCHEMA_VERSION,
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


def read_state(
    path: Path,
    *,
    scope_max_paths: int,
    scope_max_bytes: int,
) -> WatcherRetryState:
    file_size = path.stat().st_size
    if file_size > ABSOLUTE_STATE_MAX_BYTES:
        raise ValueError("watcher retry state exceeds its size bound")
    parsed: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("watcher retry state must be a JSON object")
    raw = cast("dict[str, object]", parsed)
    schema_version = raw.get("schema_version")
    if type(schema_version) is not int or schema_version not in {
        _LEGACY_SCHEMA_VERSION,
        SCHEMA_VERSION,
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
        else _optional_enum(raw.get("scope_refusal"), WatcherScopeRefusal)
    )
    state = WatcherRetryState(
        schema_version=SCHEMA_VERSION,
        canonical_root=_required_text(raw, "canonical_root"),
        source=WatcherSource(_required_text(raw, "source")),
        consecutive_failures=_nonnegative_int(raw, "consecutive_failures"),
        last_error_kind=_optional_enum(raw.get("last_error_kind"), JobErrorKind),
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
        validate_path_observation(observation, source=state.source)
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
    for item in cast("list[object]", value):
        if not isinstance(item, dict):
            raise ValueError(f"watcher retry field {field_name!r} has a malformed path")
        raw = cast("dict[str, object]", item)
        event_values = raw.get("event_kinds")
        if not isinstance(event_values, list) or not event_values:
            raise ValueError("watcher path event_kinds must be a non-empty list")
        event_kinds = cast("list[object]", event_values)
        observations.append(
            WatcherPathObservation(
                relative_path=_required_text(raw, "relative_path"),
                source=WatcherSource(_required_text(raw, "source")),
                first_observed_at=_timestamp(raw, "first_observed_at"),
                latest_observed_at=_timestamp(raw, "latest_observed_at"),
                event_kinds=frozenset(
                    WatcherPathEvent(
                        _typed_fields.required_str(
                            event_value,
                            on_invalid=lambda: ValueError(
                                "watcher path event kind must be non-empty text"
                            ),
                        )
                    )
                    for event_value in event_kinds
                ),
                generation=_required_positive(
                    raw, "generation", _optional_positive_int
                ),
            )
        )
    return tuple(observations)


def validate_path_observation(
    observation: WatcherPathObservation,
    *,
    source: WatcherSource,
) -> None:
    if not is_valid_watcher_relative_path(observation.relative_path):
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


def merge_observations(
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


def restore_captured_paths(
    state: WatcherRetryState,
) -> tuple[WatcherPathObservation, ...]:
    restored = {
        (item.source, item.relative_path): item
        for item in state.captured_paths + state.pending_paths
    }
    return tuple(sorted(restored.values(), key=lambda item: item.relative_path))


def refuse_scope_capacity(
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


def positive_int_option(name: str, value: int) -> int:
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


def _optional_enum[T: StrEnum](value: object, enum_type: type[T]) -> T | None:
    text = _optional_text(value)
    return enum_type(text) if text is not None else None


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
    return finite_positive(key, float(value))


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
    return finite_nonnegative(key, float(value))


def _optional_timestamp(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError("optional watcher retry timestamp must be numeric or null")
    return finite_nonnegative("timestamp", float(value))


def wall_time(value: float | None) -> float:
    return finite_nonnegative("now", time.time() if value is None else value)


def finite_positive(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value <= 0.0:
        raise ValueError(f"{name} must be a finite positive number")
    return float(value)


def finite_nonnegative(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or value < 0.0:
        raise ValueError(f"{name} must be a finite nonnegative number")
    return float(value)


def unit_interval(name: str, value: float) -> float:
    if isinstance(value, bool) or not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be finite and between zero and one")
    return float(value)
