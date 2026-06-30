"""Corrupt-collection resilience for the shared Qdrant store (real FS, real subprocess).

Exercises the detect-quarantine-retry recovery from the
``qdrant-store-resilience`` ADR with no mocks: quarantine is a real directory
move, detection runs against a real on-disk collection set, and the bounded
retry drives a real ``QdrantSupervisor`` against a fake binary that always aborts
after naming a collection - so the loop quarantines under its bound and then
fails loudly, exactly as a pathological store should.
"""

from __future__ import annotations

import json
import os
import sys
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..config import EnvVar, reset_config
from ..qdrant_runtime._supervise import (
    _MAX_QUARANTINES_PER_START,  # pyright: ignore[reportPrivateUsage]
    QdrantSupervisor,
    _corrupt_collection_from_output,  # pyright: ignore[reportPrivateUsage]
    _list_on_disk_collections,  # pyright: ignore[reportPrivateUsage]
    _quarantine_collection,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _make_collection(storage: Path, name: str) -> Path:
    """Create a non-empty collection directory under ``collections/``."""
    col = storage / "collections" / name
    col.mkdir(parents=True, exist_ok=True)
    (col / "segment.bin").write_bytes(b"data")
    return col


class TestQuarantine:
    """The quarantine primitive moves a collection aside reversibly (QR2)."""

    def test_quarantine_moves_collection_out_of_the_load_set(
        self, tmp_path: Path
    ) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        healthy = _make_collection(tmp_path, "r0def_vault_docs")

        dest = _quarantine_collection(tmp_path, "r0abc_vault_docs")

        assert dest.exists()
        assert dest.parent == tmp_path / "quarantine"
        assert (dest / "segment.bin").read_bytes() == b"data"  # preserved, not deleted
        assert not (tmp_path / "collections" / "r0abc_vault_docs").exists()
        assert healthy.exists()  # the healthy collection is untouched

    def test_quarantine_dir_is_a_sibling_of_collections(self, tmp_path: Path) -> None:
        """The quarantine dir must be a sibling of collections/ (Qdrant loads it)."""
        _make_collection(tmp_path, "r0abc_vault_docs")
        dest = _quarantine_collection(tmp_path, "r0abc_vault_docs")
        assert dest.parent == tmp_path / "quarantine"
        assert "collections" not in dest.relative_to(tmp_path).parts


class TestDetection:
    """Detection keys on the on-disk set, and abstains when unsure (QR1/QR4)."""

    def test_names_the_on_disk_collection_on_a_load_panic(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        tail = (
            "thread 'main' panicked: cannot load collection "
            "r0abc_vault_docs: corrupt segment"
        )
        assert _corrupt_collection_from_output(tail, tmp_path) == "r0abc_vault_docs"

    def test_abstains_without_a_load_failure_marker(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        # Names the collection but no load-failure marker -> do not quarantine.
        tail = "INFO serving collection r0abc_vault_docs on port 6333"
        assert _corrupt_collection_from_output(tail, tmp_path) is None

    def test_abstains_when_no_on_disk_collection_is_named(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        # A bind failure: has a marker word but names no on-disk collection.
        tail = "panicked: address already in use; failed to bind 127.0.0.1:6333"
        assert _corrupt_collection_from_output(tail, tmp_path) is None

    def test_prefers_the_longest_matching_name(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        _make_collection(tmp_path, "r0abc_vault_docs_codebase")
        tail = "panic: corrupt segment in r0abc_vault_docs_codebase"
        # The shorter name is a substring of the longer; the longer is the culprit.
        assert (
            _corrupt_collection_from_output(tail, tmp_path)
            == "r0abc_vault_docs_codebase"
        )

    def test_empty_tail_is_no_culprit(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        assert _corrupt_collection_from_output("   ", tmp_path) is None

    def test_list_excludes_dot_dirs(self, tmp_path: Path) -> None:
        _make_collection(tmp_path, "r0abc_vault_docs")
        (tmp_path / "collections" / ".quarantine").mkdir(parents=True, exist_ok=True)
        assert _list_on_disk_collections(tmp_path) == {"r0abc_vault_docs"}


# Fake binary: read the storage path, name the first on-disk collection in a
# panic line (so detection identifies a real culprit), then abort. It never
# becomes ready, so the supervised start quarantines under its bound and fails.
_FAKE_QDRANT = """
import os, pathlib, sys

storage = pathlib.Path(os.environ["QDRANT__STORAGE__STORAGE_PATH"])
cols = sorted(
    p.name
    for p in (storage / "collections").iterdir()
    if p.is_dir() and not p.name.startswith(".")
)
if cols:
    sys.stdout.write(
        "thread 'main' panicked: cannot load collection %s: corrupt segment\\n"
        % cols[0]
    )
    sys.stdout.flush()
sys.exit(1)
"""


def _fake_binary(tmp_path: Path) -> Path:
    """Write a fake qdrant 'binary' the supervisor can exec as ``[binary]``."""
    script = tmp_path / "fake_qdrant.py"
    script.write_text(_FAKE_QDRANT, encoding="utf-8")
    if sys.platform == "win32":
        launcher = tmp_path / "fake_qdrant.bat"
        launcher.write_text(f'@"{sys.executable}" "{script}"\r\n', encoding="utf-8")
        return launcher
    launcher = tmp_path / "fake_qdrant.sh"
    launcher.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{script}"\n', encoding="utf-8"
    )
    launcher.chmod(0o755)
    return launcher


class TestBoundedRetry:
    """The supervised start quarantines under its bound, then fails loudly (QR3)."""

    def test_perpetually_corrupt_store_quarantines_up_to_the_bound_then_raises(
        self, tmp_path: Path
    ) -> None:
        storage = tmp_path / "qdrant-server" / "storage"
        # More collections than the quarantine bound, so the loop must stop.
        for i in range(_MAX_QUARANTINES_PER_START + 2):
            _make_collection(storage, f"r{i:04d}_vault_docs")

        binary = _fake_binary(tmp_path)
        sup = QdrantSupervisor(
            binary,
            http_port=8990,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
        )
        try:
            with pytest.raises(RuntimeError, match="failed to become ready"):
                sup.start(timeout=10.0)
        finally:
            sup.stop()

        # Exactly the bound's worth of collections were quarantined, no more.
        quarantined = list((storage / "quarantine").iterdir())
        assert len(quarantined) == _MAX_QUARANTINES_PER_START
        remaining = _list_on_disk_collections(storage)
        assert len(remaining) == 2  # the two beyond the bound are untouched

    def test_auto_quarantine_disabled_never_touches_the_store(
        self, tmp_path: Path
    ) -> None:
        storage = tmp_path / "qdrant-server" / "storage"
        _make_collection(storage, "r0000_vault_docs")
        binary = _fake_binary(tmp_path)
        sup = QdrantSupervisor(
            binary,
            http_port=8991,
            storage_dir=storage,
            log_path=tmp_path / "qdrant.log",
        )
        try:
            with pytest.raises(RuntimeError, match="failed to become ready"):
                sup.start(timeout=10.0, auto_quarantine=False)
        finally:
            sup.stop()
        assert not (storage / "quarantine").exists()
        assert _list_on_disk_collections(storage) == {"r0000_vault_docs"}


_runner = CliRunner()


@pytest.fixture
def isolated_storage(tmp_path: Path) -> Iterator[Path]:
    """Point VAULTSPEC_RAG_QDRANT_STORAGE_DIR at a temp store for the CLI verb."""
    key = EnvVar.QDRANT_STORAGE_DIR.value
    prev = os.environ.get(key)
    storage = tmp_path / "qdrant-server" / "storage"
    os.environ[key] = str(storage)
    reset_config()
    try:
        yield storage
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


class TestQuarantineCli:
    """The `server qdrant quarantine` escape-hatch verb lists and moves (QR5)."""

    def test_list_dry_run_refuse_then_quarantine(self, isolated_storage: Path) -> None:
        _make_collection(isolated_storage, "r0abc_vault_docs")
        _make_collection(isolated_storage, "r0def_codebase_docs")

        listing = _runner.invoke(app, ["server", "qdrant", "quarantine", "--json"])
        assert listing.exit_code == 0
        names = json.loads(listing.stdout)["data"]["collections"]
        assert set(names) == {"r0abc_vault_docs", "r0def_codebase_docs"}

        # --dry-run does not move the collection.
        preview = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "r0abc_vault_docs", "--dry-run"]
        )
        assert preview.exit_code == 0
        assert (isolated_storage / "collections" / "r0abc_vault_docs").exists()

        # Without --yes the move is refused.
        refused = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "r0abc_vault_docs"]
        )
        assert refused.exit_code == 1
        assert (isolated_storage / "collections" / "r0abc_vault_docs").exists()

        # With --yes it is quarantined; the healthy collection stays.
        moved = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "r0abc_vault_docs", "--yes"]
        )
        assert moved.exit_code == 0
        assert not (isolated_storage / "collections" / "r0abc_vault_docs").exists()
        assert list((isolated_storage / "quarantine").iterdir())
        assert _list_on_disk_collections(isolated_storage) == {"r0def_codebase_docs"}

    def test_unknown_collection_exits_nonzero(self, isolated_storage: Path) -> None:
        _make_collection(isolated_storage, "r0abc_vault_docs")
        result = _runner.invoke(
            app, ["server", "qdrant", "quarantine", "does_not_exist", "--yes"]
        )
        assert result.exit_code == 1
        assert not (isolated_storage / "quarantine").exists()
