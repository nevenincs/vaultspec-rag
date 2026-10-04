"""Real SQLite and subprocess handles close at indexing-pass teardown."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import sys
import time
from contextlib import closing
from typing import TYPE_CHECKING

import pytest

from ..indexer._codebase_indexer import CodebaseIndexer
from ..indexer._document_file import DocumentFileMetadata
from ..indexer._document_indexer import DocumentIndexer
from ..indexer._preprocess_runner import _drain_and_wait, _PreprocessSkipError
from ..indexer._stat_gate import (
    StatEvidenceGate,
    StatEvidenceStore,
    record_computed_hashes,
)
from ..indexer._vault_indexer import VaultIndexer
from ..job_control import CancelRequested, RunControlToken
from ..progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


class _ObservedStore(StatEvidenceStore):
    """Retain real pass handles so closure is observable without garbage collection."""

    def __init__(self, path: Path, *, read_only: bool) -> None:
        super().__init__(path)
        self.gates: list[StatEvidenceGate] = []
        self.read_only = read_only

    def acquire(self) -> StatEvidenceGate:
        gate = super().acquire()
        self.gates.append(gate)
        if self.read_only:
            gate._connection.execute("PRAGMA query_only = ON")
        return gate


def _assert_closed(gate: StatEvidenceGate) -> None:
    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        gate._connection.execute("SELECT 1")


@pytest.mark.parametrize("owner", ["code", "document", "vault", "record"])
@pytest.mark.parametrize("persist_fails", [False, True])
def test_actual_acquisition_owners_close_after_success_or_persist_failure(
    tmp_path: Path, owner: str, persist_fails: bool
) -> None:
    """Removing any owner's context fails the retained handle's closed assertion.

    Mutation-proven for all four callers and the gate's close implementation.
    """
    source = tmp_path / "source.py"
    source.write_text("value = 1\n", encoding="utf-8")
    stat = source.stat()
    os.utime(source, (stat.st_atime, stat.st_mtime - 60))
    store = _ObservedStore(tmp_path / "evidence.sqlite", read_only=persist_fails)

    def invoke() -> None:
        if owner == "code":
            indexer = object.__new__(CodebaseIndexer)
            indexer.root_dir = tmp_path
            indexer._stat_gate_cache = store
            indexer._hash_changed_paths(
                {"source.py": source}, NullProgressReporter(), full_membership=True
            )
        elif owner == "document":
            document = object.__new__(DocumentIndexer)
            document.root_dir = tmp_path
            document._stat_gate_cache = store
            assert document._select_incremental_paths((source,), {}, scoped=False) == {
                "source.py"
            }
        elif owner == "vault":
            vault = object.__new__(VaultIndexer)
            vault._stat_gate_cache = store
            vault._hash_documents(
                {"source.py": source}, NullProgressReporter(), full_membership=True
            )
        else:
            record_computed_hashes(
                store,
                [("source.py", source, "computed-digest")],
                computed_not_before_ns=time.time_ns(),
                keep={"source.py"},
            )

    if persist_fails:
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            invoke()
    else:
        invoke()
    assert len(store.gates) == 1
    _assert_closed(store.gates[0])
    with closing(sqlite3.connect(store._path)) as connection:
        rows = connection.execute("SELECT path FROM stat_evidence").fetchall()
    assert rows == ([] if persist_fails or owner == "document" else [("source.py",)])


@pytest.mark.parametrize("owner", ["code", "vault"])
def test_hash_pass_closes_when_real_control_cancels_after_acquisition(
    tmp_path: Path, owner: str
) -> None:
    token = RunControlToken()

    class CancellingStore(_ObservedStore):
        def acquire(self) -> StatEvidenceGate:
            gate = super().acquire()
            token.request_cancel()
            return gate

    store = CancellingStore(tmp_path / "cancel.sqlite", read_only=False)
    with pytest.raises(CancelRequested):
        if owner == "code":
            indexer = object.__new__(CodebaseIndexer)
            indexer._stat_gate_cache = store
            indexer._hash_changed_paths({}, NullProgressReporter(), run_control=token)
        else:
            vault = object.__new__(VaultIndexer)
            vault._stat_gate_cache = store
            vault._hash_documents({}, NullProgressReporter(), run_control=token)
    assert len(store.gates) == 1
    _assert_closed(store.gates[0])


def test_document_selection_closes_when_an_existing_source_cannot_be_read(
    tmp_path: Path,
) -> None:
    store = _ObservedStore(tmp_path / "missing.sqlite", read_only=False)
    document = object.__new__(DocumentIndexer)
    document.root_dir = tmp_path
    document._stat_gate_cache = store
    metadata = DocumentFileMetadata("gone.pdf", "old-digest", ("old-point",))
    with pytest.raises(FileNotFoundError):
        document._select_incremental_paths(
            (tmp_path / "gone.pdf",), {"gone.pdf": metadata}, scoped=False
        )
    assert len(store.gates) == 1
    _assert_closed(store.gates[0])


def test_failed_schema_initialization_closes_the_real_connection(
    tmp_path: Path,
) -> None:
    """Mutation-proven: omitting failed-load close leaves this handle usable."""
    path = tmp_path / "unsupported.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version = 999")
    handles: list[StatEvidenceGate] = []

    class ObservedGate(StatEvidenceGate):
        def _ensure_schema(self) -> None:
            handles.append(self)
            super()._ensure_schema()

    with pytest.raises(RuntimeError, match="requires a rebuild"):
        ObservedGate.load(path)
    assert len(handles) == 1
    _assert_closed(handles[0])


@pytest.mark.parametrize("exit_kind", ["success", "timeout", "cancel"])
def test_real_preprocessor_child_and_pipes_close_on_every_exit(exit_kind: str) -> None:
    """Mutation-proven: removing child ownership fails the closed-pipe assertions."""
    command = (
        "import time; time.sleep(30)"
        if exit_kind != "success"
        else ("import sys; print('payload'); print('diagnostic', file=sys.stderr)")
    )
    handle = subprocess.Popen(
        [sys.executable, "-c", command], stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    token = RunControlToken()
    if exit_kind == "cancel":
        token.request_cancel()
    try:
        if exit_kind == "success":
            assert _drain_and_wait(handle, 5, 1024) == (
                0,
                f"payload{os.linesep}".encode(),
                "diagnostic",
            )
        elif exit_kind == "timeout":
            with pytest.raises(_PreprocessSkipError, match="timed out"):
                _drain_and_wait(handle, 0.1, 1024)
        else:
            with pytest.raises(CancelRequested):
                _drain_and_wait(handle, 5, 1024, token.checkpoint)
        assert handle.poll() is not None
        assert handle.stdout is not None and handle.stdout.closed
        assert handle.stderr is not None and handle.stderr.closed
    finally:
        if handle.poll() is None:
            handle.kill()
        handle.wait()
        if handle.stdout is not None:
            handle.stdout.close()
        if handle.stderr is not None:
            handle.stderr.close()
