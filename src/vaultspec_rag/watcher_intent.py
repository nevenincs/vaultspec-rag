"""Operator opt-out of automatic index updates, persisted per root.

Stopping a root's automatic updates is operator intent, so it has to outlive
the watcher it stopped. Searches, reindex requests and repository enrolment
all start a root's watcher implicitly; without a durable record, the next of
any of them, or a service restart, would quietly undo the stop.

The records live in the managed status directory, never in the repository,
keyed by canonical root. Absence of a record means automatic updates are on.
Only the explicit stop verb writes a record and only the explicit start verb
removes one. Nothing else - search, reindex, enrolment, timing changes,
pruning, storage operations, restart, root deletion - sets or clears it.

A store that exists but cannot be read, or reads as anything other than a
well-formed current-version store, is unverifiable. Unverifiable is not
"enabled": it starts no new watcher for any root, and a write refuses rather
than replace a file whose contents it never saw. Watchers already running are
left alone.

The service is the only writer, so the request path reads a process-local
copy loaded once and replaced on each successful write. It costs a dict probe
per request, not file I/O. An unverifiable copy is re-read at most once per
:data:`UNVERIFIABLE_RETRY_SECONDS`, so a repaired file is noticed without a
restart and a broken one does not cost a read per request.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING, cast

from ._root_identity import canonical_root_key, canonical_root_path
from ._root_record_store import (
    RootRecordStoreError,
    read_root_records,
    write_root_records,
)

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

__all__ = [
    "UNVERIFIABLE_RETRY_SECONDS",
    "AutoUpdateDisabled",
    "AutoUpdateState",
    "auto_update_state",
    "auto_update_store_path",
    "disable_auto_update",
    "disabled_roots",
    "enable_auto_update",
    "load_auto_update_store",
]

_STORE_FILENAME = "auto-update.json"
_STORE_VERSION = 1
UNVERIFIABLE_RETRY_SECONDS = 30.0

# Serialises this process's read-modify-write and every swap of the cached
# copy. The service is the store's only writer.
_LOCK = threading.RLock()


class AutoUpdateState(StrEnum):
    """Whether implicit enrolment may start a root's watcher."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    UNVERIFIABLE = "unverifiable"


@dataclass(frozen=True, slots=True)
class AutoUpdateDisabled:
    """One root's recorded opt-out.

    Attributes:
        root: The canonical root path as recorded, for the operator to read.
        disabled_at: ISO-8601 timestamp of the stop that recorded it.
        initiator: Who asked, as the stop request named itself.
    """

    root: str
    disabled_at: str
    initiator: str

    def as_dict(self) -> dict[str, object]:
        """Return the wire and on-disk shape of this record."""
        return {
            "root": self.root,
            "auto_update": False,
            "disabled_at": self.disabled_at,
            "initiator": self.initiator,
        }


@dataclass(frozen=True, slots=True)
class _Snapshot:
    path: pathlib.Path
    records: dict[str, AutoUpdateDisabled]
    unverifiable: str | None
    loaded_at: float


_snapshot: _Snapshot | None = None


def auto_update_store_path() -> pathlib.Path:
    """Return the path of the persisted opt-out store."""
    from .config._settings import managed_status_dir

    return managed_status_dir() / _STORE_FILENAME


def _read(path: pathlib.Path) -> dict[str, AutoUpdateDisabled]:
    """Read the store at *path*; an absent store records nothing.

    A single bad record fails the whole store: dropping it would turn that
    root's opt-out back into "enabled".

    Raises:
        RootRecordStoreError: The store exists but could not be read, or any
            part of it is malformed.
    """
    records: dict[str, AutoUpdateDisabled] = {}
    for key, raw_record in read_root_records(path, version=_STORE_VERSION).items():
        record = (
            cast("dict[str, object]", raw_record)
            if isinstance(raw_record, dict)
            else {}
        )
        root = record.get("root")
        disabled_at = record.get("disabled_at")
        initiator = record.get("initiator")
        if (
            not isinstance(key, str)
            or record.get("auto_update") is not False
            or not isinstance(root, str)
            or not isinstance(disabled_at, str)
            or not isinstance(initiator, str)
        ):
            raise RootRecordStoreError(path, "malformed", f"bad record for {key!r}")
        records[key] = AutoUpdateDisabled(root, disabled_at, initiator)
    return records


def load_auto_update_store() -> AutoUpdateState:
    """Load the store into the process-local copy and report its health.

    Returns ``UNVERIFIABLE`` when the store could not be read, ``ENABLED``
    otherwise. Never raises for a damaged store: the copy records why.
    """
    global _snapshot
    path = auto_update_store_path()
    with _LOCK:
        try:
            records = _read(path)
        except RootRecordStoreError as exc:
            logger.warning(
                "automatic update opt-out %s; no new automatic updates will start",
                exc,
            )
            _snapshot = _Snapshot(
                path, {}, f"{exc.kind}: {exc.detail}", time.monotonic()
            )
            return AutoUpdateState.UNVERIFIABLE
        _remember(path, records)
    return AutoUpdateState.ENABLED


def _current() -> _Snapshot:
    """Return the process-local copy for the configured store path."""
    snapshot = _snapshot
    path = auto_update_store_path()
    if (
        snapshot is None
        or snapshot.path != path
        or (
            snapshot.unverifiable is not None
            and time.monotonic() - snapshot.loaded_at >= UNVERIFIABLE_RETRY_SECONDS
        )
    ):
        load_auto_update_store()
        snapshot = _snapshot
        assert snapshot is not None
    return snapshot


def auto_update_state(root: pathlib.Path | str) -> AutoUpdateState:
    """Return whether implicit enrolment may start *root*'s watcher."""
    snapshot = _current()
    if snapshot.unverifiable is not None:
        return AutoUpdateState.UNVERIFIABLE
    if canonical_root_key(root) in snapshot.records:
        return AutoUpdateState.DISABLED
    return AutoUpdateState.ENABLED


def disabled_roots() -> tuple[tuple[AutoUpdateDisabled, ...], str | None]:
    """Return every recorded opt-out, and why the store is unverifiable if it is.

    The records are sorted by root path so a bounded page is stable.
    """
    snapshot = _current()
    records = sorted(snapshot.records.values(), key=lambda record: record.root)
    return tuple(records), snapshot.unverifiable


def _remember(path: pathlib.Path, records: dict[str, AutoUpdateDisabled]) -> None:
    """Replace the copy with records just read from or written to *path*."""
    global _snapshot
    _snapshot = _Snapshot(path, dict(records), None, time.monotonic())


def _write(path: pathlib.Path, records: dict[str, AutoUpdateDisabled]) -> None:
    write_root_records(
        path,
        {key: record.as_dict() for key, record in records.items()},
        version=_STORE_VERSION,
    )
    _remember(path, records)


def disable_auto_update(
    root: pathlib.Path | str,
    *,
    initiator: str,
) -> AutoUpdateDisabled:
    """Record that the operator turned automatic updates off for *root*.

    Recording an already-recorded root keeps the first record: the opt-out
    dates from when updates were first stopped.

    Raises:
        RootRecordStoreError: The store exists but could not be read as a
            current store. Nothing is written.
        OSError: The store could not be written.
    """
    key = canonical_root_key(root)
    path = auto_update_store_path()
    with _LOCK:
        records = _read(path)
        existing = records.get(key)
        if existing is not None:
            _remember(path, records)
            return existing
        record = AutoUpdateDisabled(
            root=str(canonical_root_path(root)),
            disabled_at=datetime.now(UTC).isoformat(),
            initiator=initiator,
        )
        records[key] = record
        _write(path, records)
    return record


def enable_auto_update(root: pathlib.Path | str) -> bool:
    """Drop *root*'s opt-out; ``False`` when it had none.

    Raises:
        RootRecordStoreError: The store exists but could not be read as a
            current store. Nothing is written.
        OSError: The store could not be written.
    """
    key = canonical_root_key(root)
    path = auto_update_store_path()
    with _LOCK:
        records = _read(path)
        if key not in records:
            _remember(path, records)
            return False
        del records[key]
        _write(path, records)
    return True
