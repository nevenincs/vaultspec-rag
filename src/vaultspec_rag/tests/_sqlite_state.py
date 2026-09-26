"""Logical snapshots of SQLite databases for no-mutation guards.

A guard that a code path left a database untouched compares what SQLite holds,
never the bytes of the file. The byte image changes without any logical write:
a write-ahead-logged database keeps committed rows in its ``-wal`` companion
until the last connection closes and checkpoints them into the main file, so a
connection the collector reclaims mid-test moves pages the code under test
never wrote. The byte image also misses real writes: one that stays in the
``-wal`` companion leaves the main file identical.

The snapshot reads through a read-only connection that sees the write-ahead
log, and covers the journal mode, the user version, the schema and every row.
"""

from __future__ import annotations

import difflib
import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["assert_sqlite_unchanged", "sqlite_contents"]

#: Changed lines reported before the rest are elided. A rebuild that rewrites
#: every row would otherwise print the whole database into the CI log.
_MAX_REPORTED_CHANGES = 40


def sqlite_contents(path: Path) -> list[str]:
    """Return the durable logical state of *path* as SQL statements.

    The journal mode is part of the state: converting a rollback-journal file
    to write-ahead logging changes how every later writer behaves while leaving
    rows and schema identical.
    """
    uri = f"{path.resolve().as_uri()}?mode=ro"
    with closing(sqlite3.connect(uri, uri=True)) as connection:
        (journal_mode,) = connection.execute("PRAGMA journal_mode").fetchone()
        (user_version,) = connection.execute("PRAGMA user_version").fetchone()
        return [
            f"PRAGMA journal_mode = {journal_mode};",
            f"PRAGMA user_version = {user_version};",
            *connection.iterdump(),
        ]


def assert_sqlite_unchanged(path: Path, before: list[str]) -> None:
    """Fail naming only the statements that differ from *before*."""
    after = sqlite_contents(path)
    matcher = difflib.SequenceMatcher(a=before, b=after, autojunk=False)
    changes: list[str] = []
    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        changes.extend(f"- {line}" for line in before[before_start:before_end])
        changes.extend(f"+ {line}" for line in after[after_start:after_end])
    if not changes:
        return
    reported = changes[:_MAX_REPORTED_CHANGES]
    if len(changes) > len(reported):
        reported.append(f"... {len(changes) - len(reported)} more changed lines")
    pytest.fail(f"{path} changed logically:\n" + "\n".join(reported))
