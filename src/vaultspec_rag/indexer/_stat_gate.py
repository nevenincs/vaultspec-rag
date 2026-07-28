"""Advisory stat-evidence gate over content rehashing.

Change detection proves a file unchanged by rehashing it, which prices an
unscoped convergence pass at the total byte count of the corpus. This gate
remembers the ``(size, mtime_ns)`` a file had when its content hash was last
computed and answers "may that hash be reused" from a stat call alone, so the
pass costs stat calls plus the bytes that actually changed.

The content hash stays the sole indexing authority. The gate is advisory in
both directions: a missing, stale, corrupt, or unwritable sidecar only ever
causes extra hashing, never a skipped one, and a reused hash is still diffed
against the published manifest exactly like a freshly computed one. The one
deliberate acceptance is the standard stat-cache limitation: content replaced
while ``(size, mtime_ns)`` is byte-identically restored is indistinguishable
from no change until any stat-visible difference appears.

Trust requires the recorded mtime to predate the recorded hashing instant by
a safety window, so a file hashed while it was being written - where a
coarse filesystem timestamp can survive a second write unchanged - is never
trusted and is rehashed on the next pass.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Self, cast

from .._atomic_write import JsonWriteOptions, write_json_atomically

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Collection

__all__ = [
    "StatEvidenceGate",
    "sidecar_for",
]

logger = logging.getLogger(__name__)

#: A recorded mtime must be at least this much older than the instant the
#: hash was computed before the entry may be trusted. Two seconds absorbs the
#: coarsest real filesystem timestamp granularity (FAT's 2s) plus timer
#: batching, so a write landing in the same timestamp tick as the hashed read
#: can never satisfy the gate.
_RACY_WINDOW_NS: Final = 2_000_000_000

#: Reserved sidecar key carrying the schema version. Dot-free relative paths
#: never start with ``__``, so it cannot collide with an entry key.
_SCHEMA_KEY: Final = "__stat_gate_schema__"
_SCHEMA_VERSION: Final = "1"

_WRITE_OPTIONS: Final = JsonWriteOptions(sort_keys=True, compact=True)


@dataclass(frozen=True, slots=True)
class _StatEvidence:
    """The stat identity one content hash was computed against."""

    size: int
    mtime_ns: int
    content_hash: str
    hashed_at_ns: int


def sidecar_for(meta_path: pathlib.Path) -> pathlib.Path:
    """Return the gate sidecar path derived from a domain's meta sidecar."""
    return meta_path.with_name(f"{meta_path.name}.statgate.json")


class StatEvidenceGate:
    """One load-use-persist cycle of stat evidence for a hashing loop.

    Not thread-safe; each indexing run loads its own instance under the
    domain's writer lock, uses it for one hashing loop, and persists it.
    """

    __slots__ = ("_dirty", "_entries", "_path", "rehashed", "reused")

    def __init__(
        self,
        path: pathlib.Path,
        entries: dict[str, _StatEvidence],
    ) -> None:
        self._path = path
        self._entries = entries
        self._dirty = False
        self.reused = 0
        self.rehashed = 0

    @classmethod
    def load(cls, path: pathlib.Path) -> Self:
        """Load the sidecar, treating every defect as an empty gate.

        A corrupt or partially valid sidecar is discarded whole rather than
        salvaged entry by entry: the only cost of discarding is rehashing,
        while trusting a file that failed validation once invites trusting
        whatever corrupted it.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path, {})
        entries = _validated_entries(raw)
        if entries is None:
            logger.debug("stat gate sidecar %s invalid; rehashing instead", path)
            return cls(path, {})
        return cls(path, entries)

    def hash_file(self, key: str, path: pathlib.Path) -> str:
        """Return *path*'s content hash, reading it only when evidence demands.

        Raises:
            OSError: The file could not be statted or read, exactly as the
                ungated ``hashlib.file_digest`` call would have raised.
        """
        stat = os.stat(path)
        entry = self._entries.get(key)
        if (
            entry is not None
            and entry.size == stat.st_size
            and entry.mtime_ns == stat.st_mtime_ns
            and entry.mtime_ns + _RACY_WINDOW_NS <= entry.hashed_at_ns
        ):
            self.reused += 1
            return entry.content_hash
        hashed_at_ns = time.time_ns()
        with open(path, "rb") as stream:
            digest = hashlib.file_digest(stream, "blake2b").hexdigest()
        self._entries[key] = _StatEvidence(
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            content_hash=digest,
            hashed_at_ns=hashed_at_ns,
        )
        self._dirty = True
        self.rehashed += 1
        return digest

    def prune(self, keep: Collection[str]) -> None:
        """Drop evidence for every key outside *keep*.

        Only a caller that hashed the full current membership may prune; a
        scoped pass sees a subset and must leave the rest alone.
        """
        stale = [key for key in self._entries if key not in keep]
        for key in stale:
            del self._entries[key]
        if stale:
            self._dirty = True

    def persist(self) -> None:
        """Publish accumulated evidence atomically; advisory, so never raise.

        Written even after a run that later fails to publish its index: an
        entry binds a hash to the stat identity it was computed against, which
        holds regardless of what the run did with the hash afterwards.
        """
        if not self._dirty:
            return
        payload: dict[str, object] = {_SCHEMA_KEY: _SCHEMA_VERSION}
        for key, entry in self._entries.items():
            payload[key] = [
                entry.size,
                entry.mtime_ns,
                entry.content_hash,
                entry.hashed_at_ns,
            ]
        try:
            write_json_atomically(self._path, payload, _WRITE_OPTIONS)
        except OSError:
            logger.warning(
                "stat gate sidecar %s could not be written; the next pass "
                "rehashes what this one proved",
                self._path,
                exc_info=True,
            )


def _validated_entries(raw: object) -> dict[str, _StatEvidence] | None:
    """Parse a raw sidecar payload, refusing the whole file on any defect."""
    if not isinstance(raw, dict):
        return None
    mapping = cast("dict[object, object]", raw)
    if mapping.get(_SCHEMA_KEY) != _SCHEMA_VERSION:
        return None
    entries: dict[str, _StatEvidence] = {}
    for key, value in mapping.items():
        if key == _SCHEMA_KEY:
            continue
        if not isinstance(key, str) or not key:
            return None
        entry = _validated_entry(value)
        if entry is None:
            return None
        entries[key] = entry
    return entries


def _validated_entry(value: object) -> _StatEvidence | None:
    """Parse one raw sidecar row, rejecting anything but its exact shape.

    ``bool`` is checked explicitly because it satisfies ``isinstance(_, int)``
    while being a shape defect a hand-edited or corrupted row could carry.
    """
    if not isinstance(value, list):
        return None
    row = cast("list[object]", value)
    if len(row) != 4:
        return None
    size, mtime_ns, content_hash, hashed_at_ns = row
    if (
        type(size) is not int
        or type(mtime_ns) is not int
        or type(hashed_at_ns) is not int
        or not isinstance(content_hash, str)
    ):
        return None
    if size < 0 or not content_hash:
        return None
    return _StatEvidence(
        size=size,
        mtime_ns=mtime_ns,
        content_hash=content_hash,
        hashed_at_ns=hashed_at_ns,
    )
