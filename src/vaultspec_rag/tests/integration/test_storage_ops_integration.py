"""Integration tests for storage lifecycle ops against a real Qdrant server.

Drives the real pinned qdrant binary on an ephemeral loopback port with a
temp storage dir, creates namespaced collections directly (dummy vectors,
no GPU/model), and exercises survey / delete / prune end to end. The
managed service directory is isolated via VAULTSPEC_RAG_STATUS_DIR so the
manifest never touches the real host. No GPU: these are pure storage ops.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from ..._store_models import root_collection_prefix
from ..._sync_vocabulary import ProvisionAction
from ...config import reset_config
from ...qdrant_runtime._provision import provision
from ...qdrant_runtime._resolve import resolve_binary
from ...qdrant_runtime._supervise import QdrantSupervisor
from ...storage_manifest import record_root
from ...storage_ops import (
    delete_prefix,
    gather_survey,
    migrate_collections,
    prune_orphaned,
)
from .._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from qdrant_client import QdrantClient

pytestmark = [pytest.mark.integration]

# Valid namespacing prefixes are r + 12 hex + _ (blake2b digest_size=6).
_UNKNOWN_PREFIX = "rdeadbeefcafe_"


@pytest.fixture(scope="module")
def _qdrant_binary() -> Path:  # pyright: ignore[reportUnusedFunction]
    reset_config()
    report = provision()
    assert report.action in (
        ProvisionAction.CREATED,
        ProvisionAction.UNCHANGED,
        ProvisionAction.UPDATED,
    ), report.message
    resolved = resolve_binary()
    assert resolved is not None
    return resolved.path


@pytest.fixture
def ops_qdrant(_qdrant_binary: Path, tmp_path: Path) -> Iterator[QdrantSupervisor]:
    """A fresh, isolated qdrant server per test (no cross-test state).

    Uses ``tmp_path`` so pytest reclaims the storage on teardown; a raw
    ``mkdtemp`` here leaked its directory on every run.
    """
    supervisor = QdrantSupervisor(
        _qdrant_binary,
        http_port=free_loopback_port(),
        grpc_port=free_loopback_port(),
        storage_dir=tmp_path / "storage",
        log_path=tmp_path / "qdrant.log",
    )
    supervisor.start()
    yield supervisor
    supervisor.stop()


def _make_collection(client: QdrantClient, name: str) -> None:
    from qdrant_client import models

    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
    )
    client.upsert(
        collection_name=name,
        points=[models.PointStruct(id=1, vector=[0.1, 0.2, 0.3, 0.4], payload={})],
        wait=True,
    )


@pytest.mark.usefixtures("isolated_status_dir")
def test_survey_classifies_live_orphaned_unknown(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=ops_qdrant.url)
    try:
        live_root = tmp_path / "live"
        live_root.mkdir()
        gone_root = tmp_path / "gone"
        gone_root.mkdir()

        live_pref = root_collection_prefix(live_root)
        gone_pref = root_collection_prefix(gone_root)
        record_root(live_root, backend="server")
        record_root(gone_root, backend="server")
        gone_root.rmdir()  # now orphaned

        _make_collection(client, f"{live_pref}vault_docs")
        _make_collection(client, f"{gone_pref}vault_docs")
        _make_collection(client, f"{_UNKNOWN_PREFIX}codebase_docs")  # unknown

        storage = ops_qdrant.storage_dir / "collections"
        surveys = {s.prefix: s for s in gather_survey(client, storage)}
        assert surveys[live_pref].status == "live"
        assert surveys[gone_pref].status == "orphaned"
        assert surveys[_UNKNOWN_PREFIX].status == "unknown"
        assert surveys[live_pref].points == 1
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_delete_refuses_unknown_then_prune_keeps_it(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=ops_qdrant.url)
    try:
        gone_root = tmp_path / "gone2"
        gone_root.mkdir()
        gone_pref = root_collection_prefix(gone_root)
        record_root(gone_root, backend="server")
        gone_root.rmdir()  # orphaned

        _make_collection(client, f"{gone_pref}vault_docs")
        _make_collection(client, f"{_UNKNOWN_PREFIX}vault_docs")  # unknown

        # delete refuses an unknown prefix without allow_unknown.
        res = delete_prefix(client, _UNKNOWN_PREFIX, dry_run=False)
        assert res.status == "skipped"
        assert res.reason == "unknown_namespace"
        assert client.collection_exists(f"{_UNKNOWN_PREFIX}vault_docs")

        # dry-run prune previews the orphaned target, deletes nothing.
        preview = prune_orphaned(client, dry_run=True)
        assert any(r.status == "would_remove" for r in preview.results)
        assert client.collection_exists(f"{gone_pref}vault_docs")

        # real prune removes the orphaned namespace, keeps the unknown one.
        applied = prune_orphaned(client, dry_run=False)
        assert any(r.status == "removed" for r in applied.results)
        assert _UNKNOWN_PREFIX in applied.skipped_unknown
        assert not client.collection_exists(f"{gone_pref}vault_docs")
        assert client.collection_exists(f"{_UNKNOWN_PREFIX}vault_docs")
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_prune_removes_only_orphaned_never_live_or_unknown(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """The out-of-scope-protection invariant: with live, orphaned, and unknown
    namespaces all present, prune removes only the orphaned one - the live and
    unknown namespaces survive untouched."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=ops_qdrant.url)
    try:
        live_root = tmp_path / "live"
        gone_root = tmp_path / "gone"
        live_root.mkdir()
        gone_root.mkdir()
        live_pref = root_collection_prefix(live_root)
        gone_pref = root_collection_prefix(gone_root)
        record_root(live_root, backend="server")
        record_root(gone_root, backend="server")
        gone_root.rmdir()  # orphaned

        _make_collection(client, f"{live_pref}vault_docs")
        _make_collection(client, f"{gone_pref}vault_docs")
        _make_collection(client, f"{_UNKNOWN_PREFIX}vault_docs")  # unknown

        applied = prune_orphaned(client, dry_run=False)

        # Only the orphaned namespace was removed.
        assert [r.prefix for r in applied.results if r.status == "removed"] == [
            gone_pref
        ]
        assert _UNKNOWN_PREFIX in applied.skipped_unknown
        # Live and unknown both survive; orphaned is gone.
        assert client.collection_exists(f"{live_pref}vault_docs"), "live must survive"
        assert client.collection_exists(f"{_UNKNOWN_PREFIX}vault_docs"), (
            "unknown must survive"
        )
        assert not client.collection_exists(f"{gone_pref}vault_docs")
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_ensure_table_records_manifest_and_survey_shows_live(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """Opening a server-mode store and ensuring its table records the root in
    the manifest, so a subsequent survey classifies it live (not unknown)."""

    from qdrant_client import QdrantClient

    from ..._store_models import root_collection_prefix
    from ...config import EnvVar, reset_config
    from ...storage_manifest import load_manifest
    from ...store import VaultStore

    root = tmp_path / "live-project"
    root.mkdir()
    prev = os.environ.get(EnvVar.QDRANT_URL.value)
    os.environ[EnvVar.QDRANT_URL.value] = ops_qdrant.url
    reset_config()
    try:
        store = VaultStore(root)
        try:
            assert store._server_mode is True
            store.ensure_table()
        finally:
            store.close()

        prefix = root_collection_prefix(root)
        assert prefix in load_manifest(), "ensure_table must record the manifest"

        client = QdrantClient(url=ops_qdrant.url)
        try:
            surveys = {s.prefix: s for s in gather_survey(client)}
            assert surveys[prefix].status == "live"
            assert surveys[prefix].root == str(root.resolve())
        finally:
            client.close()
    finally:
        if prev is None:
            os.environ.pop(EnvVar.QDRANT_URL.value, None)
        else:
            os.environ[EnvVar.QDRANT_URL.value] = prev
        reset_config()


@pytest.mark.usefixtures("isolated_status_dir")
def test_migrate_remaps_name_and_copies_points(
    ops_qdrant: QdrantSupervisor,
) -> None:
    from qdrant_client import QdrantClient

    client = QdrantClient(url=ops_qdrant.url)
    try:
        _make_collection(client, "vault_docs")  # bare local-style source
        name_map = {"vault_docs": "rdeadbeefcafe_vault_docs"}

        # dry-run: plans, copies nothing.
        preview = migrate_collections(client, client, name_map, dry_run=True)
        assert preview[0].status == "would_migrate"
        assert preview[0].points == 1
        assert not client.collection_exists("rdeadbeefcafe_vault_docs")

        # apply: target created with the remapped name and matching count.
        applied = migrate_collections(client, client, name_map, dry_run=False)
        assert applied[0].status == "migrated"
        assert applied[0].points == 1
        assert client.collection_exists("rdeadbeefcafe_vault_docs")
        assert client.collection_exists("vault_docs")  # source left intact

        # re-running skips an existing target (never overwrites).
        again = migrate_collections(client, client, name_map, dry_run=False)
        assert again[0].status == "skipped"
        assert again[0].reason == "target_exists"

        # a missing source is reported, not an error.
        missing = migrate_collections(
            client, client, {"nope_docs": "rfeedfeedfeed_docs"}, dry_run=False
        )
        assert missing[0].status == "skipped"
        assert missing[0].reason == "no_such_source"
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_reconcile_drops_stale_manifest_against_live_server(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """Reconcile drops a manifest entry whose root and data are both gone, and
    keeps an orphan whose collections still exist, against the real server."""
    from qdrant_client import QdrantClient

    from ...storage_manifest import load_manifest, reconcile_manifest

    client = QdrantClient(url=ops_qdrant.url)
    try:
        # stale: root gone, no backing collection.
        stale_root = tmp_path / "stale"
        stale_root.mkdir()
        stale_pref = root_collection_prefix(stale_root)
        record_root(stale_root, backend="server")
        stale_root.rmdir()

        # kept: root gone, but its collection still lives on the server.
        kept_root = tmp_path / "kept"
        kept_root.mkdir()
        kept_pref = root_collection_prefix(kept_root)
        record_root(kept_root, backend="server")
        kept_root.rmdir()
        _make_collection(client, f"{kept_pref}vault_docs")

        names = [c.name for c in client.get_collections().collections]
        import re

        prefix_re = re.compile(r"^(r[0-9a-f]{12}_)")
        known = {m.group(1) for n in names if (m := prefix_re.match(n))}

        result = reconcile_manifest(known)

        assert stale_pref in result.dropped
        assert kept_pref in result.kept
        loaded = load_manifest()
        assert stale_pref not in loaded
        assert kept_pref in loaded
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_migrate_then_rekey_manifest_records_new_backend(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """After a server->server name-remap migrate, re-keying the manifest stamps
    the new backend so a later survey attributes the moved data correctly."""
    from qdrant_client import QdrantClient

    from ...storage_manifest import load_manifest, record_root, rekey_prefix

    client = QdrantClient(url=ops_qdrant.url)
    try:
        root = tmp_path / "movable"
        root.mkdir()
        prefix = root_collection_prefix(root)
        record_root(root, backend="server")
        assert load_manifest()[prefix].backend == "server"

        # Migrate the root's data (here a single collection round-trip on one
        # server, exercising the real copy path), then re-key to local.
        source = f"{prefix}vault_docs"
        target = f"{prefix}codebase_docs"
        _make_collection(client, source)
        results = migrate_collections(client, client, {source: target}, dry_run=False)
        assert results[0].status == "migrated"

        rekey_prefix(prefix, root=root, backend="local")
        assert load_manifest()[prefix].backend == "local"
        assert load_manifest()[prefix].root == str(root.resolve())
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
@pytest.mark.parametrize("bad_prefix", ["", "r", "rdeadbeef", "notaprefix"])
def test_delete_rejects_noncanonical_prefix_even_with_allow_unknown(
    ops_qdrant: QdrantSupervisor,
    bad_prefix: str,
) -> None:
    """H1: a non-canonical / empty prefix is refused before any deletion, even
    with allow_unknown, so a crafted prefix can never startswith-match and wipe
    foreign roots."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=ops_qdrant.url)
    try:
        _make_collection(client, "raaaaaaaaaaaa_vault_docs")
        _make_collection(client, "rbbbbbbbbbbbb_vault_docs")

        res = delete_prefix(client, bad_prefix, dry_run=False, allow_unknown=True)
        assert res.status == "skipped"
        assert res.reason == "invalid_prefix"
        # Nothing was touched.
        assert client.collection_exists("raaaaaaaaaaaa_vault_docs")
        assert client.collection_exists("rbbbbbbbbbbbb_vault_docs")
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_migrate_copies_multiple_pages(
    ops_qdrant: QdrantSupervisor,
) -> None:
    """M6: migrate pages through more points than one batch and count-verifies."""
    from qdrant_client import QdrantClient, models

    client = QdrantClient(url=ops_qdrant.url)
    try:
        src = "raaaaaaaaaaaa_vault_docs"
        client.create_collection(
            collection_name=src,
            vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
        )
        client.upsert(
            collection_name=src,
            points=[
                models.PointStruct(
                    id=i, vector=[0.1, 0.2, 0.3, float(i)], payload={"n": i}
                )
                for i in range(1, 6)
            ],
            wait=True,
        )
        name_map = {src: "rbbbbbbbbbbbb_vault_docs"}
        results = migrate_collections(
            client, client, name_map, dry_run=False, batch_size=2
        )
        assert results[0].status == "migrated"
        assert results[0].points == 5
        assert client.count(collection_name="rbbbbbbbbbbbb_vault_docs").count == 5
    finally:
        client.close()


# -- geometry reconcile -----------------------------------------------------
#
# Collections created before per-collection preallocation was bounded keep
# their original segment target forever, because creation is the only place
# the bound was applied and it returns early for an existing collection. These
# tests drive the real optimizer: only a real server can prove that the merge
# reclaims bytes, preserves points, and leaves answers unchanged.


def _dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def _make_legacy_collection(
    client: QdrantClient,
    name: str,
    *,
    segments: int = 6,
    points: int = 0,
) -> None:
    """Create a collection carrying the pre-bound (drifted) geometry.

    ``default_segment_number`` is set explicitly rather than left at the
    server default, because the default derives from host CPU count and the
    test must model the same drift on any machine.
    """
    import random

    from qdrant_client import models

    client.create_collection(
        collection_name=name,
        vectors_config={
            "dense": models.VectorParams(size=64, distance=models.Distance.COSINE)
        },
        sparse_vectors_config={"sparse": models.SparseVectorParams()},
        optimizers_config=models.OptimizersConfigDiff(default_segment_number=segments),
    )
    for field_name in ("path", "language"):
        client.create_payload_index(
            collection_name=name,
            field_name=field_name,
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    if not points:
        return
    rng = random.Random(7)
    client.upsert(
        collection_name=name,
        points=[
            models.PointStruct(
                id=i,
                vector={
                    "dense": [rng.random() for _ in range(64)],
                    "sparse": models.SparseVector(
                        indices=sorted({i % 97, (i * 5 + 1) % 97}),
                        values=[0.5, 0.25][: len(sorted({i % 97, (i * 5 + 1) % 97}))],
                    ),
                },
                payload={"path": f"src/m{i % 20}.py", "language": "python"},
            )
            for i in range(points)
        ],
        wait=True,
    )


def _dense_probe(client: QdrantClient, name: str) -> list[list[int]]:
    import random

    rng = random.Random(31)
    return [
        [
            int(hit.id)
            for hit in client.query_points(
                collection_name=name,
                query=[rng.random() for _ in range(64)],
                using="dense",
                limit=8,
            ).points
        ]
        for _ in range(5)
    ]


@pytest.mark.usefixtures("isolated_status_dir")
def test_reconcile_reclaims_bytes_and_preserves_data(
    ops_qdrant: QdrantSupervisor,
) -> None:
    """The whole value proposition, proven against the real optimizer."""
    from qdrant_client import QdrantClient

    from ...storage_ops import reconcile_collections

    client = QdrantClient(url=ops_qdrant.url, timeout=600)
    try:
        name = "rfeedfacefeed_codebase_docs"
        _make_legacy_collection(client, name, segments=6, points=200)
        storage = ops_qdrant.storage_dir / "collections"

        before_bytes = _dir_size(storage / name)
        before_hits = _dense_probe(client, name)

        batch = reconcile_collections(
            client, storage_dir=storage, cap=10, budget_s=300.0
        )

        assert len(batch.results) == 1
        result = batch.results[0]
        assert result.status == "reconciled", result.reason
        assert batch.drifted_remaining == 0

        # Data is untouched: same points, same answers.
        assert client.count(name, exact=True).count == 200
        assert _dense_probe(client, name) == before_hits

        # And the preallocation is actually gone from disk.
        assert result.bytes_after is not None
        assert result.bytes_after < before_bytes
        assert result.reclaimed_bytes > 0
        assert _dir_size(storage / name) < before_bytes
        assert result.segments_after is not None
        assert result.segments_after <= 2
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_reconcile_is_idempotent_on_a_converged_backend(
    ops_qdrant: QdrantSupervisor,
) -> None:
    """A converged backend selects nothing, so the cycle stops doing work."""
    from qdrant_client import QdrantClient

    from ...storage_ops import reconcile_collections

    client = QdrantClient(url=ops_qdrant.url, timeout=600)
    try:
        name = "rfeedfacefeed_vault_docs"
        _make_legacy_collection(client, name, segments=6, points=50)
        storage = ops_qdrant.storage_dir / "collections"

        first = reconcile_collections(
            client, storage_dir=storage, cap=10, budget_s=300.0
        )
        assert [r.status for r in first.results] == ["reconciled"]

        second = reconcile_collections(
            client, storage_dir=storage, cap=10, budget_s=300.0
        )

        assert second.results == []
        assert second.drifted_remaining == 0
        assert second.reclaimed_bytes == 0
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_unwaited_reconcile_never_reports_a_reclaim_figure(
    ops_qdrant: QdrantSupervisor,
) -> None:
    """Mid-flight numbers are meaningless, so none are published.

    The optimizer transiently inflates both size and segment count while
    restructuring - a 20,000-point collection measured larger mid-merge than
    it started - so a reconcile that has not been observed to converge
    reports the state it is in and no reclamation at all. The setting still
    persists, so the collection converges on its own and a later pass
    correctly finds no drift left to fix.
    """
    import time

    from qdrant_client import QdrantClient

    from ...storage_ops import reconcile_collections

    client = QdrantClient(url=ops_qdrant.url, timeout=600)
    try:
        name = "rfeedfacefeed_codebase_docs"
        _make_legacy_collection(client, name, segments=6, points=100)
        storage = ops_qdrant.storage_dir / "collections"
        before_bytes = _dir_size(storage / name)

        batch = reconcile_collections(
            client, storage_dir=storage, cap=10, budget_s=300.0, wait=False
        )

        result = batch.results[0]
        assert result.status == "converging"
        assert result.reason == "not_awaited"
        assert result.bytes_after is None
        assert result.reclaimed_bytes == 0
        assert batch.reclaimed_bytes == 0

        # The target persisted, so no further pass is needed: the optimizer
        # converges on its own and the backend reports no remaining drift.
        deadline = time.monotonic() + 300.0
        while time.monotonic() < deadline:
            if _dir_size(storage / name) < before_bytes:
                break
            time.sleep(1.0)
        assert _dir_size(storage / name) < before_bytes

        again = reconcile_collections(
            client, storage_dir=storage, cap=10, budget_s=300.0
        )
        assert again.results == []
        assert again.drifted_remaining == 0
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_reconcile_dry_run_changes_nothing(ops_qdrant: QdrantSupervisor) -> None:
    from qdrant_client import QdrantClient

    from ...storage_ops import read_geometry, reconcile_collections

    client = QdrantClient(url=ops_qdrant.url, timeout=600)
    try:
        name = "rfeedfacefeed_vault_docs"
        _make_legacy_collection(client, name, segments=6)
        storage = ops_qdrant.storage_dir / "collections"

        batch = reconcile_collections(
            client, storage_dir=storage, cap=10, budget_s=300.0, dry_run=True
        )

        assert [r.status for r in batch.results] == ["would_reconcile"]
        assert batch.reclaimed_bytes == 0
        assert batch.drifted_remaining == 1
        # The live geometry is untouched by a preview.
        assert read_geometry(client, storage)[0].segment_target == 6
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_reconcile_cap_defers_remaining_collections(
    ops_qdrant: QdrantSupervisor,
) -> None:
    from qdrant_client import QdrantClient

    from ...storage_ops import reconcile_collections

    client = QdrantClient(url=ops_qdrant.url, timeout=600)
    try:
        storage = ops_qdrant.storage_dir / "collections"
        for suffix in ("vault_docs", "codebase_docs"):
            _make_legacy_collection(client, f"rfeedfacefeed_{suffix}", segments=6)

        batch = reconcile_collections(
            client, storage_dir=storage, cap=1, budget_s=300.0
        )

        assert len(batch.results) == 1
        assert batch.drifted_remaining == 1
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_archive_manifest_carries_identity_from_the_real_manifest(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """A real archive preserves what produced the vectors it snapshots.

    The drop that follows a successful data-tier archive destroys the live
    manifest entry the record lived in, so this is the only copy a restore
    could ever be judged against.

    Mutation it catches: building the snapshot manifest's collection entries
    without reading ``collection_identity``, which archives point counts and
    loses provenance.
    """
    import json

    from qdrant_client import QdrantClient

    from ...storage_manifest import record_collection_identity, snapshot_manifest_path
    from ...storage_ops import archive_prefix
    from ...store_schema import STORAGE_SCHEMA_VERSION, CollectionIdentity

    client = QdrantClient(url=ops_qdrant.url)
    try:
        root = tmp_path / "archived"
        root.mkdir()
        prefix = root_collection_prefix(root)
        name = f"{prefix}vault_docs"
        record_root(root, backend="server")
        _make_collection(client, name)
        record_collection_identity(
            root,
            backend="server",
            collection=name,
            identity=CollectionIdentity(
                dense_model="superseded/dense",
                sparse_model=None,
                dense_dim=4,
                distance="Cosine",
                dense_vector_name="dense",
                sparse_vector_name="sparse",
                storage_schema_version=STORAGE_SCHEMA_VERSION,
            ),
        )

        archive_dir = tmp_path / "archive"
        archive_prefix(
            client,
            prefix,
            snapshots_dir=ops_qdrant.storage_dir.parent / "snapshots",
            archive_dir=archive_dir,
        )

        payload = json.loads(
            snapshot_manifest_path(archive_dir / prefix.rstrip("_")).read_text(
                encoding="utf-8"
            )
        )
        entry = next(item for item in payload["collections"] if item["name"] == name)
        # Asserted present before it is read, so losing the record fails here
        # rather than raising on a null lookup further down.
        assert entry.get("identity") is not None
        assert entry["identity"]["dense_model"] == "superseded/dense"
        assert entry["identity"]["sparse_model"] is None
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_real_migrate_then_carry_stamps_the_remapped_target(
    ops_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """The copy and the carry compose over real, remapped collection names.

    The migrate creates its target through the raw client, which stamps
    nothing, so without the carry a genuinely copied namespace reads
    unverifiable. Asserted against the real remap because the identity homes
    are keyed by collection name and the names differ across the move - the
    failure this closes is a record carried under a key nothing looks up.
    """
    from qdrant_client import QdrantClient

    from ...storage_identity import load_identity, record_identity
    from ...storage_ops import carry_migrated_identity
    from ...store_schema import STORAGE_SCHEMA_VERSION, CollectionIdentity

    client = QdrantClient(url=ops_qdrant.url)
    try:
        root = tmp_path / "moved"
        local_dir = root / ".vaultspec-rag" / "qdrant"
        local_dir.mkdir(parents=True)
        prefix = root_collection_prefix(root)
        target = f"{prefix}vault_docs"
        _make_collection(client, "vault_docs")
        record_identity(
            root,
            backend="local",
            collection="vault_docs",
            identity=CollectionIdentity(
                dense_model="superseded/dense",
                sparse_model=None,
                dense_dim=4,
                distance="Cosine",
                dense_vector_name="dense",
                sparse_vector_name="sparse",
                storage_schema_version=STORAGE_SCHEMA_VERSION,
            ),
            local_dir=local_dir,
        )

        name_map = {"vault_docs": target}
        results = migrate_collections(client, client, name_map, dry_run=False)
        assert results[0].status == "migrated"
        assert load_identity(root, backend="server", collection=target) is None

        carried = carry_migrated_identity(
            root,
            name_map=name_map,
            to_backend="server",
            local_dir=local_dir,
            results=results,
        )

        assert carried == [target]
        got = load_identity(root, backend="server", collection=target)
        assert got is not None
        assert got.dense_model == "superseded/dense"
    finally:
        client.close()
