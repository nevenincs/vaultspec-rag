"""An explicit rebuild sets aside a run ledger this build refuses to open."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from typing import TYPE_CHECKING, cast

import pytest

from .._store_writes import workspace_volume_path
from ..indexer._codebase_indexer import CodebaseIndexer
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._run_ledger_models import (
    SCHEMA_VERSION,
    RunAuthority,
    index_run_ledger_path,
)
from ..indexer._run_ledger_runtime import RunLedger, set_aside_unsupported_ledger
from ..indexer._vault_indexer import VaultIndexer
from ..progress import NullProgressReporter
from ._sqlite_state import assert_sqlite_unchanged, sqlite_contents

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._content_discovery import CodeIndexPreflight
    from ..store_runtime import VaultStore

type _Run = Callable[[], object]
type _Build = Callable[[Path, pytest.MonkeyPatch, RunAuthority], _Run]

pytestmark = pytest.mark.unit


def _write_old_ledger(path: Path) -> None:
    """Write the ledger an older build left: its tables at a prior version."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(path)) as connection, connection:
        connection.execute("CREATE TABLE old_runs (value TEXT NOT NULL)")
        connection.execute("INSERT INTO old_runs VALUES ('preserve-me')")
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 3}")


def _set_aside_siblings(path: Path) -> list[Path]:
    return sorted(path.parent.glob(f"{path.name}.unsupported-*"))


def test_an_old_ledger_is_moved_aside_intact_with_its_journal(
    tmp_path: Path,
) -> None:
    # Nothing migrates an old ledger and opening never alters one, so without
    # this an explicit rebuild refused with the very error naming the rebuild
    # as the remedy. Mutation: dropping the companion move leaves the old
    # write-ahead log beside the fresh ledger and fails the companion assertion.
    path = tmp_path / "data" / "index_runs.sqlite3"
    _write_old_ledger(path)
    before = sqlite_contents(path)
    for suffix in ("-wal", "-shm"):
        (tmp_path / "data" / f"{path.name}{suffix}").write_bytes(b"")

    moved = set_aside_unsupported_ledger(path)

    assert moved is not None
    assert not path.exists()
    assert_sqlite_unchanged(moved, before)
    for suffix in ("-wal", "-shm"):
        assert not (path.parent / f"{path.name}{suffix}").exists()
        assert (moved.parent / f"{moved.name}{suffix}").exists()
    RunLedger(path)
    assert set_aside_unsupported_ledger(path) is None


def test_a_current_ledger_is_left_in_place(tmp_path: Path) -> None:
    path = tmp_path / "data" / "index_runs.sqlite3"
    path.parent.mkdir(parents=True)
    RunLedger(path)
    before = sqlite_contents(path)

    assert set_aside_unsupported_ledger(path) is None

    assert_sqlite_unchanged(path, before)
    assert _set_aside_siblings(path) == []


def test_an_absent_ledger_is_not_created(tmp_path: Path) -> None:
    path = tmp_path / "data" / "index_runs.sqlite3"

    assert set_aside_unsupported_ledger(path) is None

    assert not path.exists()


class _ReachedError(Exception):
    """Raised by the stub standing in for the step after the ledger step."""


def _stop(*_args: object, **_kwargs: object) -> None:
    raise _ReachedError


def _code(root: Path, monkeypatch: pytest.MonkeyPatch, authority: RunAuthority) -> _Run:
    indexer = CodebaseIndexer(
        root, cast("EmbeddingModel", object()), cast("VaultStore", object())
    )
    monkeypatch.setattr(indexer, "_accept_preflight", _stop)
    return lambda: indexer.full_index(
        reporter=NullProgressReporter(),
        preflight=cast("CodeIndexPreflight", object()),
        authority=authority,
    )


def _document(
    root: Path, monkeypatch: pytest.MonkeyPatch, authority: RunAuthority
) -> _Run:
    indexer = DocumentIndexer(
        root, cast("EmbeddingModel", object()), cast("VaultStore", object())
    )
    monkeypatch.setattr(indexer, "_accept_preflight", _stop)
    return lambda: indexer.full_index(
        reporter=NullProgressReporter(), authority=authority
    )


def _vault(
    root: Path, monkeypatch: pytest.MonkeyPatch, authority: RunAuthority
) -> _Run:
    indexer = VaultIndexer(
        root, cast("EmbeddingModel", object()), cast("VaultStore", object())
    )
    monkeypatch.setattr(indexer, "_memory_telemetry", _stop)
    return lambda: indexer.full_index(
        reporter=NullProgressReporter(), authority=authority
    )


_INDEXERS = pytest.mark.parametrize("build", [_code, _document, _vault])


@_INDEXERS
def test_a_rebuild_sets_the_old_ledger_aside_before_it_reads_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    build: _Build,
) -> None:
    # Every domain's full index reads the root's ledger before it writes
    # anything, so the set-aside has to come first in each of them. Mutation:
    # removing the call from any one indexer fails its set-aside assertion.
    root = tmp_path.resolve()
    path = index_run_ledger_path(workspace_volume_path(root))
    _write_old_ledger(path)
    run = build(root, monkeypatch, RunAuthority.REBUILD)

    with pytest.raises(_ReachedError):
        run()

    assert not path.exists()
    assert len(_set_aside_siblings(path)) == 1


@_INDEXERS
def test_publication_authority_never_sets_a_ledger_aside(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    build: _Build,
) -> None:
    root = tmp_path.resolve()
    path = index_run_ledger_path(workspace_volume_path(root))
    _write_old_ledger(path)
    before = sqlite_contents(path)
    run = build(root, monkeypatch, RunAuthority.PUBLICATION)

    with pytest.raises(_ReachedError):
        run()

    # Mutation: dropping the rebuild-authority condition moves the ledger here.
    assert _set_aside_siblings(path) == []
    assert_sqlite_unchanged(path, before)
