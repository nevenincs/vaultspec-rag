"""On-disk storage-format provenance for the managed Qdrant store.

The wire-API pin couples the server binary to the ``qdrant-client`` minor
line. That says nothing about whether a binary can open a storage
directory the *previous* binary wrote. Upstream guarantees compatibility
only between two consecutive minor versions, forbids skipping a minor on
upgrade, and does not support downgrading at all - storage migrations to a
newer format are irreversible.

Nothing else records which binary opened a storage directory from inside
that directory. The identity sidecar is a sibling of the storage dir and is
machine-global, so it does not travel with the data and says nothing once
the data is copied or restored elsewhere. This module keeps a stamp *inside*
the storage dir naming the binary version that last opened it successfully,
and judges a candidate version against it before a spawn is attempted.

The judgement exists to keep a whole-store format incompatibility from
presenting as a handful of independently corrupt collections. The
collection-load failure parser keys on collection names appearing beside a
failure marker, which is exactly the shape an incompatible-format abort
produces; without this gate that abort reads as per-collection corruption
and each named collection is moved aside in turn.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, cast

from .._atomic_write import replace_atomically
from ..store_schema import CONFORMING, NONCONFORMING, UNVERIFIABLE

if TYPE_CHECKING:
    from pathlib import Path

    from ._resolve import QdrantIdentity

logger = logging.getLogger(__name__)

__all__ = [
    "StoreFormatStamp",
    "StoreFormatVerdict",
    "judge_store_format",
    "list_quarantined_collections",
    "read_store_format",
    "store_format_path",
    "write_store_format",
]

#: Name of the stamp file, kept inside the storage dir so it travels with
#: the data. Dot-prefixed and namespaced so it is legible as ours next to
#: the engine's own ``collections/`` and ``raft_state.json``.
_STAMP_FILENAME = ".vaultspec-store-format.json"

#: Directory the load-failure recovery path moves a collection aside to. A
#: sibling of ``collections/`` so the engine does not try to load it.
QUARANTINE_DIRNAME = "quarantine"


@dataclass(frozen=True)
class StoreFormatStamp:
    """The binary version last known to have opened a storage dir.

    Attributes:
        version: The Qdrant server version that opened this storage
            directory and served from it successfully.
        stamped_at: ISO-8601 UTC timestamp of the stamp, for forensics
            only; no decision reads it.
    """

    version: str
    stamped_at: str = ""


@dataclass(frozen=True)
class StoreFormatVerdict:
    """Whether a candidate binary may open a storage dir, and why.

    Attributes:
        verdict: ``conforming``, ``nonconforming``, or ``unverifiable`` -
            the same three-way vocabulary storage conformance uses, for the
            same reason: the absence of evidence is its own answer and must
            not be scored as a pass or as a failure.
        stored_version: The version the store is stamped with, empty when
            unknown.
        provenance: Where ``stored_version`` came from - ``"stamp"`` (the
            in-store stamp), ``"identity"`` (the sidecar, used only when it
            names this same storage path), ``"empty"`` (no data to be
            incompatible with), or ``""`` when nothing was found.
        reason: Operator-facing explanation, always populated.
        migrates_store: Whether opening the store carries it across a server
            version change. True only for a permitted upgrade onto a
            data-bearing store of known provenance - never for a same-version
            open, an empty store, or a refusal. The open rewrites the stamp to
            the new version, so this is the only moment the crossing is
            observable, and it matters past that moment: the migration is
            irreversible and the binary that wrote the store can no longer
            read it.
    """

    verdict: str
    stored_version: str
    provenance: str
    reason: str
    migrates_store: bool = False

    @property
    def may_spawn(self) -> bool:
        """Whether a spawn onto this store is permitted at all."""
        return self.verdict != NONCONFORMING

    @property
    def may_auto_quarantine(self) -> bool:
        """Whether a load failure here may be blamed on one collection.

        Only a store whose format provenance is established may have a load
        failure attributed to a single collection and recovered by moving
        that collection aside. Where the provenance is unknown, the failure
        is equally consistent with a whole-store incompatibility, and moving
        collections aside on that guess is the silent data-stranding this
        gate exists to prevent.
        """
        return self.verdict == CONFORMING


def store_format_path(storage_dir: Path) -> Path:
    """Path of the store-format stamp inside *storage_dir*."""
    return storage_dir / _STAMP_FILENAME


def read_store_format(storage_dir: Path) -> StoreFormatStamp | None:
    """Read the store-format stamp, or ``None`` when absent or unreadable.

    A missing stamp (a store written before stamping existed, or one never
    opened successfully) and a malformed one are both "no record" rather
    than errors: the caller's ``unverifiable`` branch is the honest answer
    and raising here would fail a start over a corrupt forensic file.
    """
    path = store_format_path(storage_dir)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        logger.debug("qdrant store-format stamp unreadable at %s: %s", path, exc)
        return None
    if not isinstance(data, dict):
        logger.debug("qdrant store-format stamp at %s is not a dict", path)
        return None
    d = cast("dict[str, object]", data)
    version = str(d.get("version", "")).strip()
    if not version:
        logger.debug("qdrant store-format stamp at %s names no version", path)
        return None
    return StoreFormatStamp(
        version=version,
        stamped_at=str(d.get("stamped_at", "")),
    )


def write_store_format(storage_dir: Path, version: str) -> Path:
    """Stamp *storage_dir* with the *version* that just opened it.

    Written via a ``.tmp`` sibling and ``os.replace`` so a concurrent reader
    never sees a half-written record. Called only after the server has
    served from this directory, so the stamp records a proven open rather
    than an intent.

    Returns:
        The path the stamp was written to.
    """
    path = store_format_path(storage_dir)
    from .._test_isolation import enforce_pytest_managed_singleton_containment

    enforce_pytest_managed_singleton_containment(
        operation="write the managed Qdrant store-format stamp",
        targets=(path,),
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(
            {
                "version": version,
                "stamped_at": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    replace_atomically(tmp, path)
    logger.debug("stamped qdrant store format at %s as version %s", path, version)
    return path


def list_quarantined_collections(storage_dir: Path) -> list[str]:
    """Return the quarantine entries under *storage_dir*, newest name last.

    Each entry is a ``{collection}.{timestamp}`` directory the load-failure
    recovery path moved out of the active set. A non-empty result means that
    much indexed data is not being served, which no other signal reports.
    """
    quarantine = storage_dir / QUARANTINE_DIRNAME
    try:
        return sorted(entry.name for entry in quarantine.iterdir() if entry.is_dir())
    except OSError:
        return []


def _store_holds_data(storage_dir: Path) -> bool:
    """Whether *storage_dir* holds at least one collection to be lost."""
    collections = storage_dir / "collections"
    try:
        return any(
            entry.is_dir() and not entry.name.startswith(".")
            for entry in collections.iterdir()
        )
    except OSError:
        return False


def _parse_version(raw: str) -> tuple[int, int, int] | None:
    """Parse ``major.minor.patch`` into a comparable triple, else ``None``.

    Trailing pre-release or build detail on the patch component is dropped
    (``1.18.2-rc1`` reads as ``1.18.2``); anything that does not yield three
    integers is unparseable, which the caller reports as ``unverifiable``
    rather than guessing an ordering.
    """
    parts = raw.strip().lstrip("v").split(".")
    if len(parts) < 3:
        return None
    head = parts[0], parts[1], parts[2].split("-")[0].split("+")[0]
    try:
        major, minor, patch = (int(part) for part in head)
    except ValueError:
        return None
    return major, minor, patch


def _known_store_version(
    storage_dir: Path,
    identity: QdrantIdentity | None,
) -> tuple[str, str]:
    """Resolve the version known to have opened *storage_dir*, with provenance.

    The in-store stamp wins. Absent one, the identity sidecar is consulted,
    but only when it names this same storage path - it is machine-global and
    a record for a different directory says nothing about this one. That
    fallback is what gives a store written before stamping existed a real
    answer instead of an unknown on the first start after an upgrade, which
    is precisely the start that most needs the gate.
    """
    stamp = read_store_format(storage_dir)
    if stamp is not None:
        return stamp.version, "stamp"
    if identity is None or not identity.version:
        return "", ""
    same_store = os.path.normcase(os.path.normpath(identity.storage_path)) == (
        os.path.normcase(os.path.normpath(str(storage_dir)))
    )
    if not same_store:
        return "", ""
    return identity.version, "identity"


def judge_store_format(
    storage_dir: Path,
    *,
    spawning_version: str,
    identity: QdrantIdentity | None = None,
) -> StoreFormatVerdict:
    """Judge whether *spawning_version* may open *storage_dir*.

    Upstream guarantees compatibility only between two consecutive minor
    versions, so a skipped minor, a changed major, and any downgrade are all
    refused. A patch bump and a single-minor step are permitted, which is
    the whole of the supported upgrade path.

    An empty store is always permitted: there is nothing there to be
    incompatible with, and refusing a first-ever start would be absurd. A
    data-bearing store with no recoverable provenance is ``unverifiable`` -
    permitted to open, because refusing would brick every host whose store
    predates stamping, but not permitted to have a load failure blamed on a
    single collection.

    Args:
        storage_dir: The managed storage directory under judgement.
        spawning_version: The binary version about to be started on it.
        identity: The managed-Qdrant identity sidecar, consulted only as a
            provenance fallback for a store with no stamp.
    """
    if not _store_holds_data(storage_dir):
        return StoreFormatVerdict(
            verdict=CONFORMING,
            stored_version="",
            provenance="empty",
            reason="the managed store holds no collections yet",
        )
    stored, provenance = _known_store_version(storage_dir, identity)
    if not stored:
        return StoreFormatVerdict(
            verdict=UNVERIFIABLE,
            stored_version="",
            provenance="",
            reason=(
                "the managed store holds collections but records no Qdrant "
                "version that opened it, so its on-disk format cannot be "
                "attributed to a binary version"
            ),
        )
    if stored == spawning_version:
        return StoreFormatVerdict(
            verdict=CONFORMING,
            stored_version=stored,
            provenance=provenance,
            reason=f"the managed store was opened by this same version ({stored})",
        )
    old = _parse_version(stored)
    new = _parse_version(spawning_version)
    if old is None or new is None:
        return StoreFormatVerdict(
            verdict=UNVERIFIABLE,
            stored_version=stored,
            provenance=provenance,
            reason=(
                f"cannot compare the recorded store version {stored!r} against "
                f"the starting version {spawning_version!r}; one of them is not "
                "a three-part version"
            ),
        )
    return _judge_parsed(
        old,
        new,
        stored=stored,
        spawning=spawning_version,
        provenance=provenance,
    )


def _judge_parsed(
    old: tuple[int, int, int],
    new: tuple[int, int, int],
    *,
    stored: str,
    spawning: str,
    provenance: str,
) -> StoreFormatVerdict:
    """Apply the upstream compatibility window to two parsed versions."""

    def refuse(reason: str) -> StoreFormatVerdict:
        return StoreFormatVerdict(
            verdict=NONCONFORMING,
            stored_version=stored,
            provenance=provenance,
            reason=reason,
        )

    if new < old:
        return refuse(
            f"the managed store was written by Qdrant {stored}, which is newer "
            f"than the {spawning} binary being started; downgrading is not "
            "supported and a storage format already migrated forward cannot be "
            "read back by an older binary"
        )
    if new[0] != old[0]:
        return refuse(
            f"the managed store was written by Qdrant {stored} and the binary "
            f"being started is {spawning}; a major version change carries no "
            "storage compatibility guarantee"
        )
    if new[1] - old[1] > 1:
        return refuse(
            f"the managed store was written by Qdrant {stored} and the binary "
            f"being started is {spawning}, which skips at least one minor "
            "version; compatibility is guaranteed only between consecutive "
            "minor versions, so the intermediate migrations would not run"
        )
    return StoreFormatVerdict(
        verdict=CONFORMING,
        stored_version=stored,
        provenance=provenance,
        reason=(
            f"the managed store was written by Qdrant {stored} and {spawning} "
            "is within the supported consecutive-minor upgrade window"
        ),
        migrates_store=True,
    )
