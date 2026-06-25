"""Unit tests for the persisted prefix-to-root storage manifest.

Pure filesystem logic: no GPU, no Qdrant, no service. The managed
service directory is isolated to a temp path through the real
``VAULTSPEC_RAG_STATUS_DIR`` environment seam (no monkeypatch), exactly
how the integration suite isolates runtime state.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ..config import reset_config
from ..storage_manifest import (
    classify_root,
    load_manifest,
    manifest_path,
    reconcile_manifest,
    record_root,
    rekey_prefix,
    remove_root,
    reverse_map,
)
from ..store import root_collection_prefix

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def isolated_status_dir(tmp_path: Path) -> Iterator[None]:
    """Point the manifest's managed dir at a temp path via the env seam.

    Autouse so every test in this module resolves the manifest under an
    isolated temp directory; tests never touch the real managed dir.
    """
    key = "VAULTSPEC_RAG_STATUS_DIR"
    prev = os.environ.get(key)
    os.environ[key] = str(tmp_path / "managed")
    reset_config()  # manifest resolves the status dir via get_config()
    try:
        yield
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


def test_record_and_load_round_trips(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    entry = record_root(root, backend="server", last_indexed="2026-06-18T00:00:00")

    loaded = load_manifest()
    assert entry.prefix in loaded
    got = loaded[entry.prefix]
    assert got.root == str(root.resolve())
    assert got.backend == "server"
    assert got.last_indexed == "2026-06-18T00:00:00"


def test_prefix_matches_store_namespacing(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    entry = record_root(root, backend="server")
    assert entry.prefix == root_collection_prefix(root)


def test_reverse_map_known_and_unknown(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    entry = record_root(root, backend="server")
    assert reverse_map(entry.prefix) == str(root.resolve())
    assert reverse_map("rdeadbeefdead_") is None


def test_record_preserves_other_entries(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    ea = record_root(a, backend="server")
    eb = record_root(b, backend="server")
    loaded = load_manifest()
    assert ea.prefix in loaded
    assert eb.prefix in loaded
    assert ea.prefix != eb.prefix


def test_remove_root_drops_entry(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    record_root(root, backend="server")
    assert remove_root(root) is True
    assert load_manifest() == {}
    # Removing a missing root is a no-op, not an error.
    assert remove_root(root) is False


def test_classify_live_then_orphaned(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    entry = record_root(root, backend="server")
    assert classify_root(entry) == "live"
    # Simulate a removed worktree: the recorded root no longer exists, but its
    # drive/anchor is still reachable -> a true orphan.
    root.rmdir()
    refreshed = load_manifest()[entry.prefix]
    assert classify_root(refreshed) == "orphaned"


def test_classify_unverifiable_when_anchor_unknown() -> None:
    # H2: a root whose anchor cannot be confirmed (an absent root on an
    # unreachable drive/share; here exercised via an anchorless root) is
    # unverifiable, never orphaned - so prune never deletes a live-but-offline
    # index on a disconnected volume.
    from ..storage_manifest import ManifestEntry

    entry = ManifestEntry(
        prefix="raaaaaaaaaaaa_",
        root="this-is-a-relative-nonexistent-root/x",
        backend="server",
    )
    assert classify_root(entry) == "unverifiable"


def test_missing_manifest_is_empty() -> None:
    assert not manifest_path().exists()
    assert load_manifest() == {}


def test_corrupt_manifest_is_treated_as_empty() -> None:
    path = manifest_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{ not valid json", encoding="utf-8")
    assert load_manifest() == {}


def test_write_leaves_no_tmp_sibling(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    root.mkdir()
    record_root(root, backend="server")
    path = manifest_path()
    assert path.exists()
    assert not path.with_suffix(path.suffix + ".tmp").exists()


def test_reconcile_drops_orphan_with_no_data(tmp_path: Path) -> None:
    """An entry whose root is gone AND whose data is gone is dropped."""
    gone_root = tmp_path / "gone"
    gone_root.mkdir()
    entry = record_root(gone_root, backend="server")
    gone_root.rmdir()  # root vanished -> orphaned

    # The server backs no collection with this prefix, so the entry is stale.
    result = reconcile_manifest(known_prefixes=set())

    assert entry.prefix in result.dropped
    assert entry.prefix not in load_manifest()


def test_reconcile_keeps_live_root(tmp_path: Path) -> None:
    """A live root is kept even when the server reports no collections yet."""
    live_root = tmp_path / "live"
    live_root.mkdir()
    entry = record_root(live_root, backend="server")

    result = reconcile_manifest(known_prefixes=set())

    assert entry.prefix in result.kept
    assert entry.prefix in load_manifest()


def test_reconcile_keeps_orphan_whose_data_still_exists(tmp_path: Path) -> None:
    """An orphaned root whose collections still exist is preserved.

    The source root moved/vanished but its stored data is still on the
    server, so dropping the manifest entry would mislabel that live data as
    unknown. Reconcile only clears entries where BOTH the root and the data
    are gone.
    """
    gone_root = tmp_path / "moved"
    gone_root.mkdir()
    entry = record_root(gone_root, backend="server")
    gone_root.rmdir()  # orphaned, but data still backed below

    result = reconcile_manifest(known_prefixes={entry.prefix})

    assert entry.prefix in result.kept
    assert entry.prefix in load_manifest()


def test_reconcile_preserves_unrelated_entries(tmp_path: Path) -> None:
    """Reconcile drops only the stale entry, never a sibling."""
    live_root = tmp_path / "live"
    gone_root = tmp_path / "gone"
    live_root.mkdir()
    gone_root.mkdir()
    live = record_root(live_root, backend="server")
    gone = record_root(gone_root, backend="server")
    gone_root.rmdir()

    reconcile_manifest(known_prefixes=set())

    loaded = load_manifest()
    assert live.prefix in loaded
    assert gone.prefix not in loaded


def test_rekey_changes_backend_in_place(tmp_path: Path) -> None:
    """Re-keying with the same root updates the backend under the same prefix."""
    root = tmp_path / "proj"
    root.mkdir()
    record_root(root, backend="server", last_indexed="2026-06-18T00:00:00")
    prefix = root_collection_prefix(root)

    rekey_prefix(prefix, root=root, backend="local")

    loaded = load_manifest()
    assert prefix in loaded
    assert loaded[prefix].backend == "local"
    assert loaded[prefix].root == str(root.resolve())


def test_rekey_moves_stale_key(tmp_path: Path) -> None:
    """Re-keying from a different old prefix drops the old key entirely."""
    root = tmp_path / "proj"
    root.mkdir()
    new_prefix = root_collection_prefix(root)
    stale_prefix = "rdeadbeefdead_"
    record_root(root, backend="server")
    # Simulate a stale alias that should be cleared on re-key.
    rekey_prefix(stale_prefix, root=root, backend="local")

    loaded = load_manifest()
    assert stale_prefix not in loaded
    assert loaded[new_prefix].backend == "local"
