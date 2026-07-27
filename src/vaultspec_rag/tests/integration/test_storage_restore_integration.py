"""Real-Qdrant contract coverage for archived namespace restoration."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._store_models import root_collection_prefix
from ...storage_manifest import (
    load_manifest,
    record_collection_identity,
    record_root,
    remove_prefix,
)
from ...storage_reclamation import archive_prefix
from ...storage_restore import RestoreRequest, restore_archive
from ...store_schema import STORAGE_SCHEMA_VERSION, CollectionIdentity
from ._helpers import provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from qdrant_client import QdrantClient

    from ...qdrant_runtime._supervise import QdrantSupervisor

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module")
def restore_qdrant_binary() -> Path:
    """Provision the pinned Qdrant binary used by the real restore cases."""
    return provisioned_qdrant_binary()


@pytest.fixture
def restore_qdrant(
    restore_qdrant_binary: Path,
    tmp_path: Path,
) -> Iterator[QdrantSupervisor]:
    """Run a fresh, isolated real Qdrant server for one restore contract."""
    yield from serve_qdrant(restore_qdrant_binary, tmp_path / "qdrant")


def _create_collection(client: QdrantClient, name: str) -> None:
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


def _archive_namespace(
    client: QdrantClient,
    supervisor: QdrantSupervisor,
    root: Path,
    names: tuple[str, ...],
) -> Path:
    prefix = root_collection_prefix(root)
    record_root(root, backend="server")
    for name in names:
        _create_collection(client, name)
    archive_root = root.parent / "archive"
    archive_prefix(
        client,
        prefix,
        snapshots_dir=supervisor.storage_dir.parent / "snapshots",
        archive_dir=archive_root,
    )
    for name in names:
        client.delete_collection(collection_name=name)
    remove_prefix(prefix)
    return archive_root / prefix.rstrip("_")


@pytest.mark.usefixtures("isolated_status_dir")
def test_restore_preview_and_recovery_carry_archived_identity(
    restore_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """A real snapshot restores only after preview and keeps its provenance."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=restore_qdrant.url, timeout=60)
    try:
        source_root = tmp_path / "source"
        source_root.mkdir()
        source_prefix = root_collection_prefix(source_root)
        source_name = f"{source_prefix}vault_docs"
        record_root(source_root, backend="server")
        _create_collection(client, source_name)
        identity = CollectionIdentity(
            dense_model="archive/dense-v1",
            sparse_model=None,
            dense_dim=4,
            distance="Cosine",
            dense_vector_name="dense",
            sparse_vector_name="sparse",
            storage_schema_version=STORAGE_SCHEMA_VERSION,
        )
        record_collection_identity(
            source_root,
            backend="server",
            collection=source_name,
            identity=identity,
        )
        archive_dir = tmp_path / "archive"
        archive_prefix(
            client,
            source_prefix,
            snapshots_dir=restore_qdrant.storage_dir.parent / "snapshots",
            archive_dir=archive_dir,
        )
        client.delete_collection(collection_name=source_name)
        remove_prefix(source_prefix)

        destination_root = tmp_path / "destination"
        destination_root.mkdir()
        request = RestoreRequest(
            archive_dir=archive_dir / source_prefix.rstrip("_"),
            destination_root=destination_root,
            local_mode=False,
            dry_run=True,
        )
        preview = restore_archive(client, request)
        destination_prefix = root_collection_prefix(destination_root)
        destination_name = f"{destination_prefix}vault_docs"
        assert preview.status == "would_restore"
        assert preview.collections == (destination_name,)
        assert not client.collection_exists(destination_name)

        restored = restore_archive(
            client,
            RestoreRequest(
                archive_dir=request.archive_dir,
                destination_root=destination_root,
                local_mode=False,
                dry_run=False,
            ),
        )
        assert restored.status == "restored"
        assert int(client.count(collection_name=destination_name).count) == 1
        entry = load_manifest()[destination_prefix]
        assert entry.storage_schema_version == STORAGE_SCHEMA_VERSION
        assert entry.collections == (destination_name,)
        assert entry.collection_identity[destination_name] == identity
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_restore_refuses_local_mode_and_a_populated_destination(
    restore_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """Refusals leave the real target collection untouched."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=restore_qdrant.url, timeout=60)
    try:
        source_root = tmp_path / "source"
        source_root.mkdir()
        source_prefix = root_collection_prefix(source_root)
        archive = _archive_namespace(
            client,
            restore_qdrant,
            source_root,
            (f"{source_prefix}vault_docs",),
        )
        destination_root = tmp_path / "destination"
        destination_root.mkdir()
        destination_name = f"{root_collection_prefix(destination_root)}vault_docs"
        _create_collection(client, destination_name)

        populated = restore_archive(
            client,
            RestoreRequest(
                archive,
                destination_root,
                local_mode=False,
                dry_run=False,
            ),
        )
        assert populated.status == "refused"
        assert populated.reason == "destination_exists"
        assert int(client.count(collection_name=destination_name).count) == 1

        local = restore_archive(
            client,
            RestoreRequest(
                archive,
                destination_root,
                local_mode=True,
                dry_run=False,
            ),
        )
        assert local.status == "refused"
        assert local.reason == "local_mode_unsupported"
        assert int(client.count(collection_name=destination_name).count) == 1
    finally:
        client.close()


@pytest.mark.usefixtures("isolated_status_dir")
def test_restore_rolls_back_after_a_real_corrupt_snapshot_failure(
    restore_qdrant: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """A later Qdrant recovery error removes an earlier recovered collection."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=restore_qdrant.url, timeout=60)
    try:
        source_root = tmp_path / "source"
        source_root.mkdir()
        source_prefix = root_collection_prefix(source_root)
        first = f"{source_prefix}aaa"
        second = f"{source_prefix}zzz"
        archive = _archive_namespace(
            client, restore_qdrant, source_root, (first, second)
        )
        (archive / f"{second}.snapshot").write_bytes(b"corrupt snapshot")
        destination_root = tmp_path / "destination"
        destination_root.mkdir()
        destination_prefix = root_collection_prefix(destination_root)

        from qdrant_client.http.exceptions import (
            ResponseHandlingException,
            UnexpectedResponse,
        )

        with pytest.raises((ResponseHandlingException, UnexpectedResponse)):
            restore_archive(
                client,
                RestoreRequest(
                    archive,
                    destination_root,
                    local_mode=False,
                    dry_run=False,
                ),
            )

        assert not client.collection_exists(f"{destination_prefix}aaa")
        assert not client.collection_exists(f"{destination_prefix}zzz")
    finally:
        client.close()
