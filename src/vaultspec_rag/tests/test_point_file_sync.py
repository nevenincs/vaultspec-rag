"""The harness opens a local store's point file with device syncing off.

The on-disk Qdrant backend commits once per point, and SQLite forces each
commit to the device, so how long a store-heavy test takes follows the disk it
runs on. The root conftest turns that syncing off for the one file the backend
keeps points in, leaves every other SQLite file as it was opened, and hands a
``durable`` test the real setting.

No doubles: the dependency's own persistence class opens a real file, which is
also what notices the dependency renaming it.

MUTATION PROOF, in one uninterrupted sequence and restored: with the root
conftest matching no file name, ``test_a_point_file_opens_with_syncing_off``
fails on its level assertion; with it matching every file name,
``test_another_sqlite_file_keeps_its_setting`` fails on its level assertion;
with the ``durable`` exception removed,
``test_a_durable_test_gets_the_point_file_synced`` fails on its level
assertion; restoring passes all three.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest
from qdrant_client.local.persistence import CollectionPersistence

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit

_SYNCING_OFF = 0


def _level(connection: sqlite3.Connection) -> int:
    row: tuple[int] | None = connection.execute("PRAGMA synchronous").fetchone()
    assert row is not None
    return row[0]


def _point_file_level(tmp_path: Path) -> int:
    persistence = CollectionPersistence(str(tmp_path / "collection"))
    try:
        return _level(persistence.storage)
    finally:
        persistence.close()


def _ordinary_level(tmp_path: Path) -> int:
    with closing(sqlite3.connect(tmp_path / "ordinary.sqlite")) as connection:
        return _level(connection)


def test_a_point_file_opens_with_syncing_off(tmp_path: Path) -> None:
    assert _point_file_level(tmp_path) == _SYNCING_OFF


def test_another_sqlite_file_keeps_its_setting(tmp_path: Path) -> None:
    """Syncing is what SQLite does unasked, so off is never the untouched level."""
    assert _ordinary_level(tmp_path) != _SYNCING_OFF


# The mark's own exception is the thing under test: the level read back here
# is the one the harness changes, so the real setting is what this observes.
@pytest.mark.durable
def test_a_durable_test_gets_the_point_file_synced(tmp_path: Path) -> None:
    assert _point_file_level(tmp_path) == _ordinary_level(tmp_path)
