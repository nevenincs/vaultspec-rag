"""Unit tests for the persisted prefix-to-root storage manifest.

Pure filesystem logic: no GPU, no Qdrant, no service. The managed
service directory is isolated to a temp path through the real
``VAULTSPEC_RAG_STATUS_DIR`` environment seam (no monkeypatch), exactly
how the integration suite isolates runtime state.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest

from .._store_models import root_collection_prefix
from ..storage_manifest import (
    SnapshotCollection,
    StorageSnapshotManifest,
    classify_root,
    load_manifest,
    manifest_path,
    reconcile_manifest,
    record_root,
    rekey_prefix,
    remove_root,
    reverse_map,
    write_snapshot_manifest,
)
from ..store_schema import STORAGE_SCHEMA_VERSION, CollectionIdentity

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def isolate_manifest_dir(isolated_status_dir: Path) -> None:
    """Resolve the manifest under a temp managed dir for every test here.

    Autouse so no test in this module can reach the real managed dir; the
    relocation itself is the shared ``isolated_status_dir`` fixture.
    """
    del isolated_status_dir


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
    # A root whose anchor cannot be confirmed (an absent root on an
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


def test_snapshot_manifest_records_the_stamped_identity(tmp_path: Path) -> None:
    """An archive must carry what produced the vectors it preserves.

    The drop that follows a successful archive destroys the live entry holding
    that record, so an archive without it can only ever be restored as
    unverifiable.

    Mutation it catches: omitting ``identity`` from the per-collection payload
    ``write_snapshot_manifest`` writes.
    """
    written = write_snapshot_manifest(
        tmp_path / "archive" / "rdeadbeefcafe",
        StorageSnapshotManifest(
            prefix="rdeadbeefcafe_",
            root=str(tmp_path / "proj"),
            storage_schema_version=STORAGE_SCHEMA_VERSION,
            collections=(
                SnapshotCollection(
                    name="rdeadbeefcafe_vault_docs",
                    snapshot_file="vault.snapshot",
                    points=7,
                    identity=CollectionIdentity(
                        dense_model="acme/dense-v1",
                        sparse_model="acme/sparse-v1",
                        dense_dim=1024,
                        distance="Cosine",
                        dense_vector_name="dense",
                        sparse_vector_name="sparse",
                        storage_schema_version=STORAGE_SCHEMA_VERSION,
                    ),
                ),
            ),
        ),
    )

    payload = json.loads(written.read_text(encoding="utf-8"))
    collection = payload["collections"][0]
    # Asserted before the lookup so dropping the field fails here rather than
    # raising a KeyError, which reads as a broken test instead of a lost record.
    assert "identity" in collection
    assert collection["identity"]["dense_model"] == "acme/dense-v1"
    assert collection["identity"]["dense_dim"] == 1024


def test_snapshot_manifest_writes_absent_identity_as_null(tmp_path: Path) -> None:
    """A pre-stamping archive says so, rather than omitting the question.

    Mutation it catches: substituting a current identity when the collection
    carried none, which would let a restore of unattributable data present as
    conforming.
    """
    written = write_snapshot_manifest(
        tmp_path / "archive" / "rdeadbeefcafe",
        StorageSnapshotManifest(
            prefix="rdeadbeefcafe_",
            root=None,
            storage_schema_version=STORAGE_SCHEMA_VERSION,
            collections=(
                SnapshotCollection(
                    name="rdeadbeefcafe_vault_docs",
                    snapshot_file="vault.snapshot",
                    points=7,
                ),
            ),
        ),
    )

    payload = json.loads(written.read_text(encoding="utf-8"))
    assert payload["collections"][0]["identity"] is None


def test_snapshot_manifest_stamps_its_own_completion_time(tmp_path: Path) -> None:
    """An archive age begins at manifest publication, not copied-file mtime.

    Mutation it catches: removing ``completed_at`` or substituting an archive
    artifact's pre-existing modification time makes the written timestamp fall
    outside the real write interval below.
    """
    archive_dir = tmp_path / "archive" / "rdeadbeefcafe"
    copied_metadata = archive_dir / "document-metadata.json"
    copied_metadata.parent.mkdir(parents=True)
    copied_metadata.write_text("{}", encoding="utf-8")
    old_mtime = (datetime.now(UTC) - timedelta(days=31)).timestamp()
    os.utime(copied_metadata, (old_mtime, old_mtime))

    before = datetime.now(UTC)
    written = write_snapshot_manifest(
        archive_dir,
        StorageSnapshotManifest(
            prefix="rdeadbeefcafe_",
            root=None,
            storage_schema_version=STORAGE_SCHEMA_VERSION,
            collections=(),
        ),
    )
    after = datetime.now(UTC)

    payload = json.loads(written.read_text(encoding="utf-8"))
    completed_at = payload.get("completed_at")
    assert isinstance(completed_at, str)
    stamped = datetime.fromisoformat(completed_at)
    assert stamped.tzinfo is not None
    assert stamped.utcoffset() == timedelta(0)
    assert before <= stamped <= after
