"""Real-store contract tests for independent document storage."""

from __future__ import annotations

import contextlib
import copy
import json
import os
import socket
from typing import TYPE_CHECKING

import pytest

from ... import store_schema
from ..._store_models import (
    DocumentChunk,
    DocumentLocator,
    DocumentMetadata,
    DocumentPayload,
)
from ...config import EnvVar, reset_config
from ...indexer._document_identity import document_point_id
from ...indexer._document_meta import (
    DocumentFileMetadata,
    DocumentIndexMetadata,
    document_metadata_path,
    write_document_meta,
)
from ...qdrant_runtime import (
    QdrantProvisionAction,
    QdrantSupervisor,
    provision,
    resolve_binary,
)
from ...store import VaultStore
from ...storage_ops import archive_prefix, gather_survey
from ...server._routes_storage import _shape_survey_payload

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory

pytestmark = [pytest.mark.integration]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture(scope="module")
def document_qdrant_binary() -> Path:
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
def document_qdrant_server(
    document_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Iterator[QdrantSupervisor]:
    """Run one isolated real server for the document-store tests."""
    root = tmp_path_factory.mktemp("document-qdrant")
    supervisor = QdrantSupervisor(
        document_qdrant_binary,
        http_port=_free_port(),
        grpc_port=_free_port(),
        storage_dir=root / "storage",
        log_path=root / "qdrant.log",
    )
    supervisor.start(timeout=60.0)
    yield supervisor
    supervisor.stop()


@pytest.fixture
def document_server_mode(
    document_qdrant_server: QdrantSupervisor,
    tmp_path: Path,
) -> Iterator[QdrantSupervisor]:
    """Point store construction at the isolated real server."""
    url_key = EnvVar.QDRANT_URL.value
    status_key = EnvVar.STATUS_DIR.value
    previous_url = os.environ.get(url_key)
    previous_status = os.environ.get(status_key)
    os.environ[url_key] = document_qdrant_server.url
    os.environ[status_key] = str(tmp_path / "managed")
    reset_config()
    try:
        yield document_qdrant_server
    finally:
        if previous_url is None:
            os.environ.pop(url_key, None)
        else:
            os.environ[url_key] = previous_url
        if previous_status is None:
            os.environ.pop(status_key, None)
        else:
            os.environ[status_key] = previous_status
        reset_config()


@pytest.fixture
def document_local_mode(tmp_path: Path) -> Iterator[None]:
    """Force real local storage without leaking process configuration."""
    url_key = EnvVar.QDRANT_URL.value
    status_key = EnvVar.STATUS_DIR.value
    previous_url = os.environ.pop(url_key, None)
    previous_status = os.environ.get(status_key)
    os.environ[status_key] = str(tmp_path / "managed")
    reset_config()
    try:
        yield
    finally:
        if previous_url is not None:
            os.environ[url_key] = previous_url
        if previous_status is None:
            os.environ.pop(status_key, None)
        else:
            os.environ[status_key] = previous_status
        reset_config()


def _chunk(source_path: str = "inputs/manual.bin") -> DocumentChunk:
    locator = DocumentLocator("page", 7)
    content_fingerprint = "content-v1"
    point_id = document_point_id(
        source_path=source_path,
        unit_ordinal=2,
        content_fingerprint=content_fingerprint,
        locator=locator,
    )
    return DocumentChunk(
        point_id,
        DocumentPayload(
            source_path,
            2,
            content_fingerprint,
            "Document storage sentinel text.",
            title="Storage sentinel",
            section="Lifecycle",
            anchor="#lifecycle",
            locator=locator,
            document_metadata=DocumentMetadata.from_mapping({"category": "reference"}),
            unit_metadata=DocumentMetadata.from_mapping({"confidence": 1.0}),
            extractor_id="real-test-extractor",
            extractor_version="1",
        ),
        vector=[0.1, 0.2, 0.3, 0.4],
    )


def _assert_document_round_trip(store: VaultStore) -> None:
    """Exercise production upsert, count, scroll, ID, and delete behavior."""
    chunk = _chunk()
    store.upsert_document_content_chunks([chunk], write_policy=None)
    assert store.count_document() == 1
    assert store.get_all_document_content_ids() == {chunk.id}
    rows, offset = store.scroll_document_content(limit=10)
    assert offset is None
    assert len(rows) == 1
    payload = rows[0]["payload"]
    assert payload["document_id"] == chunk.id
    assert payload["source_path"] == chunk.payload.source_path
    assert payload["locator_kind"] == "page"
    assert payload["locator_value_int"] == 7
    assert payload["document_metadata"] == {"category": "reference"}

    store.delete_document_sources({chunk.payload.source_path})
    assert store.count_document() == 0
    store.upsert_document_content_chunks([chunk], write_policy=None)
    store.delete_document_content_chunks([chunk.id])
    assert store.count_document() == 0


def test_document_store_round_trip_local(
    document_local_mode: None,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Exercise the document lifecycle through real QdrantLocal storage."""
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        assert store._server_mode is False
        assert (
            store._collection_locks[store.DOCUMENT_TABLE_NAME]
            is not (store._collection_locks[store.CODE_TABLE_NAME])
        )
        _assert_document_round_trip(store)
        store.drop_document_table()
        assert not store.client.collection_exists(store.DOCUMENT_TABLE_NAME)
        store.ensure_document_table()
        assert store.client.collection_exists(store.DOCUMENT_TABLE_NAME)
    finally:
        store.close()


def test_document_store_round_trip_server(
    document_server_mode: QdrantSupervisor,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Exercise namespaced document storage through the real Qdrant server."""
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        assert store._server_mode is True
        assert isinstance(
            store._point_lock(store.DOCUMENT_TABLE_NAME),
            contextlib.nullcontext,
        )
        _assert_document_round_trip(store)
        info = store.client.get_collection(store.DOCUMENT_TABLE_NAME)
        payload_schema = set(info.payload_schema or {})
        assert set(store_schema.DOCUMENT_KEYWORD_INDEXES) <= payload_schema
        assert set(store_schema.DOCUMENT_INTEGER_INDEXES) <= payload_schema
    finally:
        store.close()


def test_document_schema_and_identity_contract() -> None:
    """Keep the descriptor and normalized identity aligned with live storage."""
    descriptor = store_schema.describe_storage_schema()
    document = descriptor["document"]
    assert document["collection"] == store_schema.DOCUMENT_COLLECTION
    assert document["id_scheme"]["chunk"].endswith("@v1")
    first = document_point_id(
        source_path="inputs\\manual.bin",
        unit_ordinal=9,
        content_fingerprint="same",
        locator=DocumentLocator("page", 2),
    )
    second = document_point_id(
        source_path="inputs/manual.bin",
        unit_ordinal=1,
        content_fingerprint="same",
        locator=DocumentLocator("page", 2),
    )
    assert first == second


def test_document_descriptor_version_compatibility_contract() -> None:
    """Direct consumers refuse missing document and unknown newer shapes."""
    descriptor = store_schema.describe_storage_schema()
    compatible = store_schema.assert_compatible(
        descriptor,
        known_version=store_schema.STORAGE_SCHEMA_VERSION,
        expected_dense_dim=store_schema.effective_dense_dim(),
        required_domains=("document",),
    )
    assert compatible == {"compatible": True, "reason": ""}

    older = copy.deepcopy(descriptor)
    older["version"] = store_schema.STORAGE_SCHEMA_VERSION - 1
    del older["document"]
    older_verdict = store_schema.assert_compatible(
        older,
        known_version=store_schema.STORAGE_SCHEMA_VERSION,
        expected_dense_dim=store_schema.effective_dense_dim(),
        required_domains=("document",),
    )
    assert older_verdict["compatible"] is False
    assert "document" in older_verdict["reason"]

    newer = copy.deepcopy(descriptor)
    newer["version"] = store_schema.STORAGE_SCHEMA_VERSION + 1
    newer_verdict = store_schema.assert_compatible(
        newer,
        known_version=store_schema.STORAGE_SCHEMA_VERSION,
        expected_dense_dim=store_schema.effective_dense_dim(),
        required_domains=("document",),
    )
    assert newer_verdict["compatible"] is False
    assert "newer" in newer_verdict["reason"]


def test_document_count_appears_in_real_storage_survey(
    document_server_mode: QdrantSupervisor,  # noqa: ARG001
    tmp_path: Path,
) -> None:
    """Expose an independently counted real document collection."""
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        store.upsert_document_content_chunks([_chunk()], write_policy=None)
        surveys = gather_survey(store.client, storage_dir=None)
        survey = next(item for item in surveys if item.root == str(tmp_path.resolve()))
        assert survey.points == 1
        assert survey.vault_points == 0
        assert survey.code_points == 0
        assert survey.document_points == 1

        payload = _shape_survey_payload(
            surveys,
            None,
            10,
            None,
            computed_at="2026-07-22T00:00:00+00:00",
            source="fresh",
        )
        namespace = next(
            item
            for item in payload["namespaces"]
            if item["root"] == str(tmp_path.resolve())
        )
        assert namespace["document_points"] == 1
        assert payload["totals"]["document_points"] >= 1
    finally:
        store.close()


def test_document_collection_and_metadata_appear_in_real_snapshot_manifest(
    document_server_mode: QdrantSupervisor,
    tmp_path: Path,
) -> None:
    """Archive real document points with their independent metadata evidence."""
    store = VaultStore(tmp_path, embedding_dim=4)
    chunk = _chunk()
    try:
        store.upsert_document_content_chunks([chunk], write_policy=None)
        metadata = DocumentIndexMetadata(
            membership_fingerprint="membership-v1",
            content_fingerprint="content-v1",
            policy_snapshot="policy-v1",
            files=(
                DocumentFileMetadata(
                    source_path=chunk.payload.source_path,
                    content_fingerprint=chunk.payload.content_fingerprint,
                    point_ids=(chunk.id,),
                ),
            ),
        )
        write_document_meta(document_metadata_path(tmp_path), metadata)
        archive_dir = tmp_path / "archive"
        artifacts = archive_prefix(
            store.client,
            store.TABLE_NAME[: -len(store_schema.VAULT_COLLECTION)],
            snapshots_dir=document_server_mode.storage_dir.parent / "snapshots",
            archive_dir=archive_dir,
        )
        manifest_path = next(path for path in artifacts if path.name == "snapshot-manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        collections = {item["name"]: item for item in manifest["collections"]}
        assert store.DOCUMENT_TABLE_NAME in collections
        assert collections[store.DOCUMENT_TABLE_NAME]["points"] == 1
        assert manifest["metadata_files"] == ["document_index_meta.json"]
        assert (manifest_path.parent / "document_index_meta.json").is_file()
    finally:
        store.close()
