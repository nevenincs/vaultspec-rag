"""Real-store document migration and maintenance contracts."""

from __future__ import annotations

import os
import socket
from typing import TYPE_CHECKING

import pytest

from ... import store_schema
from ...cli._service_storage import _migrate_name_map
from ...config import EnvVar, reset_config
from ...qdrant_runtime import (
    QdrantProvisionAction,
    QdrantSupervisor,
    provision,
    resolve_binary,
)
from ...server._routes_storage import _shape_survey_payload
from ...storage_manifest import record_root
from ...storage_ops import (
    debris_surveys,
    gather_survey,
    migrate_collections,
    prune_orphaned,
)
from ...store import root_collection_prefix

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory
    from qdrant_client import QdrantClient

pytestmark = [pytest.mark.integration]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def migration_qdrant_binary() -> Path:
    """Provision the pinned real Qdrant binary."""
    reset_config()
    report = provision()
    assert report.action in {
        QdrantProvisionAction.CREATED,
        QdrantProvisionAction.UNCHANGED,
        QdrantProvisionAction.UPDATED,
    }
    resolved = resolve_binary()
    assert resolved is not None
    return resolved.path


@pytest.fixture(scope="module")
def migration_qdrant_server(
    migration_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """Run one isolated real server for migration and maintenance."""
    root = tmp_path_factory.mktemp("document-migration-qdrant")
    supervisor = QdrantSupervisor(
        migration_qdrant_binary,
        http_port=_free_port(),
        grpc_port=_free_port(),
        storage_dir=root / "storage",
        log_path=root / "qdrant.log",
    )
    supervisor.start(timeout=60.0)
    yield supervisor
    supervisor.stop()


@pytest.fixture
def isolated_storage_status(tmp_path: Path) -> Iterator[Path]:
    """Keep the real manifest inside the test's managed directory."""
    status_key = EnvVar.STATUS_DIR.value
    previous = os.environ.get(status_key)
    status_dir = tmp_path / "managed"
    os.environ[status_key] = str(status_dir)
    reset_config()
    try:
        yield status_dir
    finally:
        if previous is None:
            os.environ.pop(status_key, None)
        else:
            os.environ[status_key] = previous
        reset_config()


def _make_document_collection(client: QdrantClient, name: str) -> None:
    from qdrant_client import models

    client.create_collection(
        collection_name=name,
        vectors_config=models.VectorParams(size=4, distance=models.Distance.COSINE),
    )
    client.upsert(
        collection_name=name,
        points=[
            models.PointStruct(
                id=1,
                vector=[0.1, 0.2, 0.3, 0.4],
                payload={"source_path": "inputs/reference.bin"},
            )
        ],
        wait=True,
    )


def test_real_local_to_service_document_migration_is_idempotent(
    migration_qdrant_server: QdrantSupervisor,
    isolated_storage_status: Path,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Copy a real local document collection once and safely skip its replay."""
    from qdrant_client import QdrantClient

    local = QdrantClient(path=str(tmp_path / "local-qdrant"))
    server = QdrantClient(url=migration_qdrant_server.url)
    try:
        _make_document_collection(local, store_schema.DOCUMENT_COLLECTION)
        name_map = _migrate_name_map(str(tmp_path), to_server=True)
        target = name_map[store_schema.DOCUMENT_COLLECTION]

        first = migrate_collections(local, server, name_map, dry_run=False)
        document_first = next(
            result
            for result in first
            if result.source == store_schema.DOCUMENT_COLLECTION
        )
        assert document_first.status == "migrated"
        assert document_first.points == 1
        assert server.count(collection_name=target, exact=True).count == 1

        second = migrate_collections(local, server, name_map, dry_run=False)
        document_second = next(
            result
            for result in second
            if result.source == store_schema.DOCUMENT_COLLECTION
        )
        assert document_second.status == "skipped"
        assert document_second.reason == "target_exists"
        assert server.count(collection_name=target, exact=True).count == 1
    finally:
        local.close()
        server.close()


def test_real_document_pruning_debris_and_maintenance_route(
    migration_qdrant_server: QdrantSupervisor,
    isolated_storage_status: Path,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Cover document prefix pruning, debris classification, and route counts."""
    from qdrant_client import QdrantClient

    client = QdrantClient(url=migration_qdrant_server.url)
    try:
        orphan_root = tmp_path / "orphan"
        orphan_root.mkdir()
        orphan_prefix = root_collection_prefix(orphan_root)
        record_root(orphan_root, backend="server")
        orphan_collection = orphan_prefix + store_schema.DOCUMENT_COLLECTION
        _make_document_collection(client, orphan_collection)
        orphan_root.rmdir()

        result = prune_orphaned(client, dry_run=False)
        removed = next(item for item in result.results if item.prefix == orphan_prefix)
        assert removed.status == "removed"
        assert removed.collections == [orphan_collection]
        assert not client.collection_exists(orphan_collection)

        live_root = tmp_path / "live"
        live_root.mkdir()
        live_prefix = root_collection_prefix(live_root)
        record_root(live_root, backend="server")
        live_collection = live_prefix + store_schema.DOCUMENT_COLLECTION
        _make_document_collection(client, live_collection)
        surveys = gather_survey(
            client,
            storage_dir=migration_qdrant_server.storage_dir / "collections",
        )
        payload = _shape_survey_payload(
            surveys,
            None,
            20,
            str(live_root),
            computed_at="2026-07-22T00:00:00+00:00",
            source="fresh",
        )
        namespace = payload["namespaces"][0]
        assert namespace["collections"] == [live_collection]
        assert namespace["document_points"] == 1

        debris_name = "rbbbbbbbbbbbb_" + store_schema.DOCUMENT_COLLECTION
        debris_path = migration_qdrant_server.storage_dir / "collections" / debris_name
        debris_path.mkdir()
        (debris_path / "partial-segment").write_bytes(b"incomplete")
        live_names = [item.name for item in client.get_collections().collections]
        debris = debris_surveys(
            live_names,
            migration_qdrant_server.storage_dir / "collections",
        )
        classified = next(
            item for item in debris if debris_name in item.collections
        )
        assert classified.status == "debris"
        assert classified.footprint_bytes == len(b"incomplete")
    finally:
        client.close()
