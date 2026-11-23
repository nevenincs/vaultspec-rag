"""Split the suite into shards several machines measure between them.

A file, never a single test, is the unit: module-scoped state and the ports a
file reserves stay inside one process, exactly as ``--dist loadfile`` keeps
them on one worker. Every file belongs to exactly one shard of a given count,
so the shards of that count together run every test once.
"""

from __future__ import annotations

import hashlib
from pathlib import PureWindowsPath
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

#: ``INDEX/COUNT``, one-based: run only the files of that shard.
SHARD_ENV = "VAULTSPEC_RAG_TEST_SHARD"


def shard_of(nodeid: str, count: int) -> int:
    """Return the one-based shard, out of *count*, that *nodeid*'s file is in.

    The digest is of the file's path as pytest reports it, with forward
    slashes, so every platform agrees on the split.
    """
    path = PureWindowsPath(nodeid.split("::", 1)[0]).as_posix()
    digest = hashlib.sha256(path.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % count + 1


def selected_shard(environ: Mapping[str, str]) -> tuple[int, int] | None:
    """Return ``(index, count)`` when *environ* selects one shard of the suite.

    Raises:
        ValueError: When the value is not ``INDEX/COUNT`` with
            ``1 <= INDEX <= COUNT``. A malformed value must not run the whole
            suite, or nothing: either reads as a pass that measured the wrong
            thing.
    """
    raw = environ.get(SHARD_ENV, "").strip()
    if not raw:
        return None
    index, _, count = raw.partition("/")
    if not (index.isdecimal() and count.isdecimal()) or not (
        1 <= int(index) <= int(count)
    ):
        raise ValueError(
            f"{SHARD_ENV}={raw!r} is not INDEX/COUNT with 1 <= INDEX <= COUNT"
        )
    return int(index), int(count)
