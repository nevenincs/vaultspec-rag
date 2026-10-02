"""Real-store document migration and maintenance contracts."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ... import store_schema
from ..._store_models import root_collection_prefix
from ...cli._service_storage import _migrate_name_map
from ...server._routes_storage import _shape_survey_payload, _SurveyPayloadRequest
from ...storage_manifest import record_root
from ...storage_migration import migrate_collections
from ...storage_survey_ops import debris_surveys, gather_survey, prune_orphaned
from .._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS
from ._helpers import provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory
    from qdrant_client import QdrantClient

    from ...qdrant_runtime._supervise import QdrantSupervisor

pytestmark = [pytest.mark.integration]


@pytest.fixture(scope="module")
def migration_qdrant_binary() -> Path:
    """Provision (or reuse) the pinned real Qdrant binary."""
    return provisioned_qdrant_binary()


@pytest.fixture(scope="module")
def migration_qdrant_server(
    migration_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """One real qdrant server on ephemeral ports with temp storage."""
    yield from serve_qdrant(
        migration_qdrant_binary, tmp_path_factory.mktemp("document-migration-qdrant")
    )


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
    isolated_status_dir: Path,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Copy a real local document collection once and safely skip its replay."""
    from qdrant_client import QdrantClient

    local = QdrantClient(
        path=str(tmp_path / "local-qdrant"),
        force_disable_check_same_thread=sqlite3.threadsafety == 3,
    )
    server = QdrantClient(
        url=migration_qdrant_server.url,
        timeout=int(CHILD_PROCESS_TIMEOUT_SECONDS),
    )
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


def test_canonical_local_migration_closes_sqlite_resources_in_fresh_process(
    migration_qdrant_server: QdrantSupervisor,
    isolated_status_dir: Path,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Real CLI migration must not strand the SDK's SQLite thread-mode probe."""
    from qdrant_client import QdrantClient

    source = root_collection_prefix(tmp_path) + store_schema.DOCUMENT_COLLECTION
    server = QdrantClient(
        url=migration_qdrant_server.url,
        timeout=int(CHILD_PROCESS_TIMEOUT_SECONDS),
    )
    try:
        _make_document_collection(server, source)
    finally:
        server.close()
    script = """
import gc
import sqlite3
import sys
from qdrant_client import QdrantClient
from qdrant_client.local.persistence import CollectionPersistence
from vaultspec_rag import store_schema
from vaultspec_rag.cli._service_storage import _local_store_path, storage_migrate

assert CollectionPersistence.CHECK_SAME_THREAD is None
storage_migrate(
    sys.argv[1], to_backend="local", yes=True, dry_run=False, json_mode=True
)
client = QdrantClient(
    path=str(_local_store_path(sys.argv[1])),
    force_disable_check_same_thread=sqlite3.threadsafety == 3,
)
try:
    points, _ = client.scroll(collection_name=store_schema.DOCUMENT_COLLECTION)
    assert len(points) == 1
    assert points[0].id == 1
    assert points[0].payload == {"source_path": "inputs/reference.bin"}
finally:
    client.close()
gc.collect()
"""
    child = subprocess.run(
        [sys.executable, "-W", "error", "-c", script, str(tmp_path)],
        env={
            **os.environ,
            "PYTHONWARNINGS": "error",
            "VAULTSPEC_RAG_QDRANT_URL": migration_qdrant_server.url,
        },
        capture_output=True,
        text=True,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert child.returncode == 0, child.stderr
    assert child.stderr == "", child.stderr
    envelope = json.loads(child.stdout)
    assert envelope["ok"] is True
    document = next(
        item for item in envelope["data"]["results"] if item["source"] == source
    )
    assert document["status"] == "migrated"
    assert document["points"] == 1


def test_real_document_pruning_debris_and_maintenance_route(
    migration_qdrant_server: QdrantSupervisor,
    isolated_status_dir: Path,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Cover document prefix pruning, debris classification, and route counts."""
    from qdrant_client import QdrantClient

    client = QdrantClient(
        url=migration_qdrant_server.url,
        timeout=int(CHILD_PROCESS_TIMEOUT_SECONDS),
    )
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
            _SurveyPayloadRequest(
                surveys=surveys,
                status_filter=None,
                limit=20,
                root=str(live_root),
                computed_at="2026-07-22T00:00:00+00:00",
                source="fresh",
            )
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
        classified = next(item for item in debris if debris_name in item.collections)
        assert classified.status == "debris"
        assert classified.footprint_bytes == len(b"incomplete")
    finally:
        client.close()
