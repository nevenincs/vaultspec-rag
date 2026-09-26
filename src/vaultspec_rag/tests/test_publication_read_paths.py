"""Read-only paths treat every unreadable publication proof as absence."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from .._index_breadth import acquire_code_breadth_snapshot_if_proven
from .._index_integrity import acquire_index_integrity_snapshot_if_proven
from .._source_types import PublicSourceType
from .._store_writes import workspace_volume_path
from ..indexer._publication_proof import ProofReadConflictError
from ..indexer._run_ledger_models import SCHEMA_VERSION, index_run_ledger_path
from ._sqlite_state import assert_sqlite_unchanged, sqlite_contents

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

pytestmark = pytest.mark.unit


def _old_schema_ledger(root: Path) -> Path:
    """Write the ledger an older build left behind: tables at a prior version."""
    path = index_run_ledger_path(workspace_volume_path(root.resolve()))
    path.parent.mkdir(parents=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        connection.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 3}")
    return path


def test_an_old_ledger_leaves_a_search_unfenced_rather_than_failing(
    tmp_path: Path,
) -> None:
    # A root indexed by an older build keeps a ledger this build refuses to
    # open. The serving path read that refusal as an internal server error on
    # every search, so no project indexed before the schema moved could be
    # searched at all. Mutation: narrowing either helper back to the proof
    # errors alone raises the ledger's rebuild refusal here instead.
    ledger = _old_schema_ledger(tmp_path)
    before = sqlite_contents(ledger)

    assert (
        acquire_index_integrity_snapshot_if_proven(tmp_path, PublicSourceType.VAULT)
        is None
    )
    assert acquire_code_breadth_snapshot_if_proven(tmp_path) is None
    assert_sqlite_unchanged(ledger, before)


def _code_integrity_if_proven(root: Path) -> object:
    return acquire_index_integrity_snapshot_if_proven(root, PublicSourceType.CODE)


@pytest.mark.parametrize(
    ("target", "helper"),
    [
        (
            "vaultspec_rag._index_integrity.acquire_index_integrity_snapshot",
            _code_integrity_if_proven,
        ),
        (
            "vaultspec_rag._index_breadth.acquire_code_breadth_snapshot",
            acquire_code_breadth_snapshot_if_proven,
        ),
    ],
)
def test_an_update_publishing_leaves_a_search_unfenced_rather_than_failing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target: str,
    helper: Callable[[Path], object],
) -> None:
    # An index run holds its publication receipt open while it publishes, and
    # certifying proof under an open receipt raises a read conflict. Unhandled,
    # every search issued during an automatic update failed. Mutation: leaving
    # the read conflict out of the unreadable set raises it here.
    def publishing(*_args: object) -> None:
        raise ProofReadConflictError("an open receipt prevents proof certification")

    monkeypatch.setattr(target, publishing)

    assert helper(tmp_path) is None
