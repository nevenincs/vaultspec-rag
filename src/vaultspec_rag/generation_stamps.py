"""Persisted grace clocks for superseded code generations.

A generation becomes droppable only after it has been continuously
unreferenced for a window. That window has to survive a daemon restart, or
every restart would hand each generation a fresh clock and nothing would ever
be reclaimed - so the observation is written down rather than held in memory.

Kept out of the storage manifest deliberately. The manifest is keyed by
namespace prefix and carries one record per root; these clocks are keyed by
individual collection, several of which can live under one prefix. Folding a
per-collection map into a per-prefix record would either change that record's
shape for every writer or smuggle a second key space into it.

Losing this file is safe in the only direction that matters: every clock
restarts, so a generation waits out its window again. Protection can only be
extended by a loss here, never shortened.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, cast

from ._atomic_write import replace_atomically

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Mapping

logger = logging.getLogger(__name__)

_STAMPS_FILENAME = "generation-grace.json"

__all__ = ["load_generation_stamps", "record_generation_stamps", "stamps_path"]


def stamps_path() -> pathlib.Path:
    """Return the path of the persisted generation grace clocks."""
    from .storage_manifest import manifest_path

    return manifest_path().parent / _STAMPS_FILENAME


def load_generation_stamps() -> dict[str, str]:
    """Return the persisted collection-to-first-seen map.

    An absent, unreadable or malformed file yields an empty map, which restarts
    every window. That is the safe direction: a lost clock delays a drop, it
    never licenses one.
    """
    path = stamps_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("generation grace stamps %s unreadable: %s", path, exc)
        return {}
    if not isinstance(raw, dict):
        return {}
    entries = cast("dict[object, object]", raw)
    return {
        name: seen
        for name, seen in entries.items()
        if isinstance(name, str) and isinstance(seen, str) and name and seen
    }


def record_generation_stamps(stamps: Mapping[str, str]) -> None:
    """Persist the advanced clocks, replacing the previous map wholesale.

    Written to a temporary file and moved into place, so a crash mid-write
    leaves the previous map intact rather than a half-written one that would
    read as a set of restarted clocks.
    """
    path = stamps_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(dict(stamps), indent=2), encoding="utf-8")
    replace_atomically(tmp_path, path)
