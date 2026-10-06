"""Persisted inventory through real managed files and the stopped-service bridge."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import urllib.parse
from typing import TYPE_CHECKING, cast

import pytest

from ..config._types import EnvVar
from ..monitor_inventory import read_inventory
from ..storage_manifest import manifest_path, record_root
from .conftest import managed_env
from .test_monitor_browser import _read
from .test_monitor_browser import browser_bridge as browser_bridge
from .test_monitor_logs import monitor_http as monitor_http

pytestmark = pytest.mark.unit

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


@pytest.fixture(autouse=True)
def inventory_storage(tmp_path: Path) -> Iterator[Path]:
    storage = tmp_path / "storage"
    with managed_env(**{EnvVar.QDRANT_STORAGE_DIR.value: str(storage)}):
        yield storage


def _collection(directory: Path, name: str, contents: bytes) -> None:
    target = directory / name
    target.mkdir(parents=True)
    (target / "payload.bin").write_bytes(contents)


def _files(directory: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(directory)): path.read_bytes()
        for path in directory.rglob("*")
        if path.is_file()
    }


def _seed_inventory(tmp_path: Path) -> tuple[Path, Path, str, str, Path]:
    root = tmp_path / "project"
    root.mkdir()
    gone = tmp_path / "gone"
    prefix = record_root(
        root, backend="server", last_indexed="2026-10-01T09:00:00Z"
    ).prefix
    gone_prefix = record_root(gone, backend="server").prefix
    storage = tmp_path / "storage"
    collections = storage / "collections"
    _collection(collections, prefix + "codebase_docs_g1234", b"indexed")
    _collection(collections, gone_prefix + "vault_docs", b"orphan")
    _collection(collections, "rffffffffffff_vault_docs", b"unknown")
    (collections / "ignored-file").write_text("not a collection", encoding="utf-8")
    return root, gone, prefix, gone_prefix, storage


@pytest.mark.parametrize("discovery", ["missing", "stale"])
def test_stopped_bridge_reads_attributed_disk_inventory_without_writes(
    browser_bridge: tuple[str, Path], tmp_path: Path, discovery: str
) -> None:
    access, status_directory = browser_bridge
    root, gone, prefix, gone_prefix, storage = _seed_inventory(tmp_path)
    discovery_path = status_directory / "service.json"
    if discovery == "missing":
        discovery_path.unlink()
    else:
        with socket.socket() as unused:
            unused.bind(("127.0.0.1", 0))
            absent_port = int(unused.getsockname()[1])
        discovery_path.write_text(
            json.dumps({"port": absent_port, "service_token": "private"}),
            encoding="utf-8",
        )
    before_status = _files(status_directory)
    before_storage = _files(storage)
    status, inventory = _read(access, "/repositories?limit=100")
    assert status == 200
    assert inventory["source"] == "persisted"
    assert inventory["live_available"] is False
    assert inventory["seats"] is None
    rows = cast("list[dict[str, object]]", inventory["repositories"])
    by_root = {row["root"]: row for row in rows}
    assert by_root[str(root)]["status"] == "live"
    assert by_root[str(gone)]["status"] == "orphaned"
    assert by_root[str(root)]["last_indexed"] == "2026-10-01T09:00:00Z"
    assert all(row["watching"] is None and row["resident"] is None for row in rows)
    with managed_env(**{EnvVar.QDRANT_STORAGE_DIR.value: str(storage)}):
        status, survey = _read(access, "/storage/survey?limit=100")
        assert status == 200
        assert survey["source"] == "disk"
        assert survey["live_available"] is False
        namespaces = cast("list[dict[str, object]]", survey["namespaces"])
        classified = {row["prefix"]: row for row in namespaces}
        assert classified[prefix]["status"] == "live"
        assert classified[gone_prefix]["status"] == "orphaned"
        assert classified["rffffffffffff_"]["status"] == "unknown"
        assert classified[prefix]["collections"] == [prefix + "codebase_docs_g1234"]
        assert classified[prefix]["footprint_bytes"] == len(b"indexed")
        assert all(
            row["points"] is None and row["points_verified"] is False
            for row in namespaces
        )
        totals = cast("dict[str, object]", survey["totals"])
        assert totals["points"] is None
        assert totals["total_bytes"] == len(b"indexed") + len(b"orphan") + len(
            b"unknown"
        )
        filtered = read_inventory("storage/survey", {"root": str(root), "limit": "1"})
        assert filtered["total"] == 1
        assert filtered["queried_root"] == {"root": str(root), "prefix": prefix}
    # Adding a file write in read_inventory fails the unchanged-file assertion;
    # restoration passes it. Counts and live slots stay absent, never zero.
    assert _files(status_directory) == before_status
    assert _files(storage) == before_storage


def test_persisted_repository_reader_expands_git_worktrees(
    isolated_status_dir: Path, tmp_path: Path
) -> None:
    del isolated_status_dir
    root = tmp_path / "repository"
    sibling = tmp_path / "worktree"
    sibling.mkdir()
    registration = root / ".git" / "worktrees" / "sibling"
    registration.mkdir(parents=True)
    (registration / "gitdir").write_text(str(sibling / ".git"), encoding="utf-8")
    (registration / "commondir").write_text("../..", encoding="utf-8")
    (sibling / ".git").write_text(f"gitdir: {registration}", encoding="utf-8")
    record_root(root, backend="server")
    result = read_inventory("repositories", {"root": str(root), "limit": "10"})
    rows = cast("list[dict[str, object]]", result["repositories"])
    assert result["total"] == 2
    assert {row["root"] for row in rows} == {str(root), str(sibling)}
    worktree = next(row for row in rows if row["root"] == str(sibling))
    assert worktree["repository_root"] == str(root)
    assert worktree["is_worktree"] is True
    assert worktree["enrolled"] is False


def test_inventory_module_is_torch_free_and_preserves_manifest(
    isolated_status_dir: Path, tmp_path: Path
) -> None:
    """Injecting torch into the reader's import state fails the subprocess
    assertion; restoration passes. Both inventory operations run before it.
    """
    _seed_inventory(tmp_path)
    before = _files(isolated_status_dir)
    before_storage = _files(tmp_path / "storage")
    script = (
        "import sys; from vaultspec_rag.monitor_inventory import read_inventory; "
        "read_inventory('repositories', {}); "
        "read_inventory('storage/survey', {}); "
        "assert 'torch' not in sys.modules; "
        "assert 'vaultspec_rag.cli' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, timeout=15
    )
    assert result.returncode == 0, result.stderr
    assert _files(isolated_status_dir) == before
    assert _files(tmp_path / "storage") == before_storage
    assert manifest_path().is_file()


def test_stopped_bridge_reports_unavailable_storage(
    browser_bridge: tuple[str, Path],
) -> None:
    access, directory = browser_bridge
    (directory / "service.json").unlink()
    status, result = _read(access, "/storage/survey")
    assert status == 503
    assert result["error"] == "inventory_unavailable"


@pytest.mark.parametrize(
    "query", [{"root": " "}, {"status": "invalid"}, {"command": "start"}]
)
def test_stopped_bridge_preserves_validation(
    browser_bridge: tuple[str, Path], query: dict[str, str]
) -> None:
    access, directory = browser_bridge
    (directory / "service.json").unlink()
    status, result = _read(access, "/storage/survey?" + urllib.parse.urlencode(query))
    assert status == 400
    assert result["error"] == "bad_request"
