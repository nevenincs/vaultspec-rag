"""Integration tests for storage lifecycle ops against a real Qdrant server.

Drives the real pinned qdrant binary on an ephemeral loopback port with a
temp storage dir, creates namespaced collections directly (dummy vectors,
no GPU/model), and exercises survey / delete / prune end to end. The
managed service directory is isolated via VAULTSPEC_RAG_STATUS_DIR so the
manifest never touches the real host. No GPU: these are pure storage ops.
"""

from __future__ import annotations

import os
import socket
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from ...config import reset_config
from ...qdrant_runtime import (
    QdrantProvisionAction,
    QdrantSupervisor,
    provision,
    resolve_binary,
)
from ...storage_manifest import record_root
from ...storage_ops import (
    delete_prefix,
    gather_survey,
    migrate_collections,
    prune_orphaned,
)
from ...store import root_collection_prefix

if TYPE_CHECKING:
    from collections.abc import Iterator

    from qdrant_client import QdrantClient

pytestmark = [pytest.mark.integration]

# Valid namespacing prefixes are r + 12 hex + _ (blake2b digest_size=6).
_UNKNOWN_PREFIX = "rdeadbeefcafe_"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def _qdrant_binary() -> Path:  # pyright: ignore[reportUnusedFunction]
    reset_config()
    report = provision()
    assert report.action in (
        QdrantProvisionAction.CREATED,
        QdrantProvisionAction.UNCHANGED,
        QdrantProvisionAction.UPDATED,
    ), report.message
    resolved = resolve_binary()
    assert resolved is not None
    return resolved.path


@pytest.fixture
def ops_qdrant(_qdrant_binary: Path) -> Iterator[QdrantSupervisor]:
    """A fresh, isolated qdrant server per test (no cross-test state)."""
    tmp = Path(tempfile.mkdtemp(prefix="storage-ops-qdrant-"))
    supervisor = QdrantSupervisor(
        _qdrant_binary,
        http_port=_free_port(),
        grpc_port=_free_port(),
        storage_dir=tmp / "storage",
        log_path=tmp / "qdrant.log",
    )
    supervisor.start()
    yield supervisor
    supervisor.stop()


@pytest.fixture
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    key = "VAULTSPEC_RAG_STATUS_DIR"
    prev = os.environ.get(key)
    os.environ[key] = str(tmp_path / "managed")
    reset_config()  # manifest resolves the status dir via get_config()
    try:
        yield tmp_path / "managed"
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


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
    import os

    from qdrant_client import QdrantClient

    from ...config import EnvVar, reset_config
    from ...storage_manifest import load_manifest
    from ...store import VaultStore, root_collection_prefix

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
