"""Real-store evidence for bounded destination-first route migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING

import pytest

from ..._store_models import (
    CodeChunk,
    DocumentChunk,
    DocumentLocator,
    DocumentPayload,
)
from ...config import get_config
from ...indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ...indexer._document_checkpoint import (
    DocumentRunCheckpoint,
    DocumentRunConfiguration,
)
from ...indexer._document_identity import document_point_id
from ...indexer._resolved_policy import resolve_index_policy
from ...indexer._route_migration import (
    RouteMigrationJournal,
    iter_stored_route_pages,
    purge_unpublished_rows,
    reconcile_checkpoint_routes,
    reconcile_origin_after_destination,
    resume_pending_migrations,
)
from ...indexer._run_ledger import RunOperation
from ...indexer._run_policy import RunPolicy
from ...store import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]


def _resolved_policy(root: Path):
    policy = RootContentPolicy(
        SourceProfileVersion.EXPLICIT_ONLY_V1,
        (
            ContentRoute("module.py", ContentKind.CODE),
            ContentRoute("guide.txt", ContentKind.DOCUMENT),
        ),
    )
    return resolve_index_policy(root, content_policy=policy)


def _document_chunk(source_path: str, text: str) -> DocumentChunk:
    locator = DocumentLocator("line", 1)
    fingerprint = hashlib.blake2b(text.encode("utf-8")).hexdigest()
    point_id = document_point_id(
        source_path=source_path,
        unit_ordinal=0,
        content_fingerprint=fingerprint,
        locator=locator,
    )
    return DocumentChunk(
        point_id,
        DocumentPayload(
            source_path,
            0,
            fingerprint,
            text,
            locator=locator,
            extractor_id="route-migration-test",
            extractor_version="1",
        ),
        vector=[0.1, 0.2, 0.3, 0.4],
    )


def _code_chunk(point_id: str, path: str) -> CodeChunk:
    return CodeChunk(
        id=point_id,
        path=path,
        language="python",
        content="value = 1",
        line_start=1,
        line_end=1,
        vector=[0.1, 0.2, 0.3, 0.4],
    )


def _document_checkpoint(root: Path, rel_path: str, point_id: str):
    policy = _resolved_policy(root)
    checkpoint = DocumentRunCheckpoint.open(
        data_root=root / get_config().data_dir,
        root_dir=root,
        policy=policy,
        run_policy=RunPolicy(no_progress_timeout_seconds=60.0),
        operation=RunOperation.FULL,
        clean=False,
        model_identity="route-migration-test",
        dense_dimensions=4,
        configuration=DocumentRunConfiguration(
            slice_max_chunks=1,
            source_bytes=1,
            generated_chunks=1,
            weighted_bytes=1,
            sparse_enabled=False,
            sparse_dimension=1,
            encode_batch_size=1,
        ),
    )
    source_digest = hashlib.blake2b(rel_path.encode("utf-8")).hexdigest()
    unit = checkpoint.unit_for(
        rel_path,
        source_digest,
        0,
        is_file_end=True,
        point_ids=(point_id,),
    )
    checkpoint.record_confirmed_slice(unit)
    return checkpoint


def test_store_survey_is_bounded_and_freshly_classified(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        store.upsert_code_chunks(
            [
                _code_chunk("code-current", "module.py"),
                _code_chunk("code-moved", "guide.txt"),
            ],
            write_policy=None,
        )
        store.upsert_document_content_chunks(
            [
                _document_chunk("guide.txt", "current document"),
                _document_chunk("module.py", "moved document"),
            ],
            write_policy=None,
        )

        code_pages = list(
            iter_stored_route_pages(
                store,
                _resolved_policy(tmp_path),
                ContentKind.CODE,
                page_size=1,
            )
        )
        document_pages = list(
            iter_stored_route_pages(
                store,
                _resolved_policy(tmp_path),
                ContentKind.DOCUMENT,
                page_size=1,
            )
        )

        assert all(len(page) == 1 for page in (*code_pages, *document_pages))
        assert {
            (row.source_path, row.stored_kind, row.current_kind)
            for page in (*code_pages, *document_pages)
            for row in page
        } == {
            ("module.py", ContentKind.CODE, ContentKind.CODE),
            ("guide.txt", ContentKind.CODE, ContentKind.DOCUMENT),
            ("guide.txt", ContentKind.DOCUMENT, ContentKind.DOCUMENT),
            ("module.py", ContentKind.DOCUMENT, ContentKind.CODE),
        }
    finally:
        store.close()


def test_interrupted_destination_first_flip_resumes_idempotently(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    rel_path = "guide.txt"
    origin = _code_chunk("legacy-before-delete", rel_path)
    deleted_origin = _code_chunk("legacy-after-delete", rel_path)
    destination = _document_chunk(rel_path, "destination content")
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        store.upsert_code_chunks([origin, deleted_origin], write_policy=None)
        store.upsert_document_content_chunks([destination], write_policy=None)
        checkpoint = _document_checkpoint(tmp_path, rel_path, destination.id)
        journal = RouteMigrationJournal(
            tmp_path / get_config().data_dir / "route_migrations.sqlite3"
        )
        first = journal.begin(
            rel_path=rel_path,
            origin_kind=ContentKind.CODE,
            destination_kind=ContentKind.DOCUMENT,
            destination_generation_id=checkpoint.generation_id,
            point_ids=(origin.id,),
        )
        second = journal.begin(
            rel_path=rel_path,
            origin_kind=ContentKind.CODE,
            destination_kind=ContentKind.DOCUMENT,
            destination_generation_id=checkpoint.generation_id,
            point_ids=(origin.id,),
        )
        journal.begin(
            rel_path=rel_path,
            origin_kind=ContentKind.CODE,
            destination_kind=ContentKind.DOCUMENT,
            destination_generation_id=checkpoint.generation_id,
            point_ids=(deleted_origin.id,),
        )
        store.delete_code_chunks([deleted_origin.id])
        assert first == second
        assert store.count_code() == 1
        assert store.count_document() == 1

        assert resume_pending_migrations(store, tmp_path / get_config().data_dir) == 2
        assert resume_pending_migrations(store, tmp_path / get_config().data_dir) == 0
        assert store.count_code() == 0
        assert store.get_all_document_content_ids() == {destination.id}
        assert list(journal.pending()) == []
    finally:
        store.close()


def test_missing_sidecar_recovery_retains_ledger_confirmed_points(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    retained = _document_chunk("guide.txt", "confirmed")
    stale_same_path = _document_chunk("guide.txt", "obsolete generation")
    rejected = _document_chunk("unrouted.bin", "stale")
    opposite = _document_chunk("module.py", "awaiting destination publication")
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        store.upsert_document_content_chunks(
            [retained, stale_same_path, rejected, opposite],
            write_policy=None,
        )
        checkpoint = _document_checkpoint(tmp_path, "guide.txt", retained.id)

        removed = purge_unpublished_rows(
            store,
            checkpoint,
            _resolved_policy(tmp_path),
            ContentKind.DOCUMENT,
            page_size=1,
        )

        assert removed == 2
        assert store.get_all_document_content_ids() == {retained.id, opposite.id}
    finally:
        store.close()


def test_origin_cleanup_journals_bounded_batches(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    rel_path = "guide.txt"
    destination = _document_chunk(rel_path, "bounded destination")
    origins = [_code_chunk(f"legacy-{ordinal:04d}", rel_path) for ordinal in range(257)]
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        store.upsert_code_chunks(origins, write_policy=None)
        store.upsert_document_content_chunks([destination], write_policy=None)
        checkpoint = _document_checkpoint(tmp_path, rel_path, destination.id)

        assert (
            reconcile_origin_after_destination(
                store,
                checkpoint,
                ContentKind.DOCUMENT,
                rel_path,
            )
            == 257
        )
        assert store.count_code() == 0
        journal_path = tmp_path / get_config().data_dir / "route_migrations.sqlite3"
        with sqlite3.connect(journal_path) as connection:
            batches = [
                json.loads(raw)
                for (raw,) in connection.execute(
                    "SELECT point_ids_json FROM route_migrations ORDER BY created_at"
                )
            ]
        assert [len(batch) for batch in batches] == [256, 1]
    finally:
        store.close()


def test_generation_route_cleanup_uses_bounded_store_and_ledger_pages(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    destinations = [
        _document_chunk("guide.txt", "first destination"),
        _document_chunk("appendix.txt", "second destination"),
    ]
    origins = [
        _code_chunk("legacy-guide", "guide.txt"),
        _code_chunk("legacy-appendix", "appendix.txt"),
        _code_chunk("retained-code", "module.py"),
    ]
    policy = resolve_index_policy(
        tmp_path,
        content_policy=RootContentPolicy(
            SourceProfileVersion.EXPLICIT_ONLY_V1,
            (
                ContentRoute("guide.txt", ContentKind.DOCUMENT),
                ContentRoute("appendix.txt", ContentKind.DOCUMENT),
                ContentRoute("module.py", ContentKind.CODE),
            ),
        ),
    )
    checkpoint = DocumentRunCheckpoint.open(
        data_root=tmp_path / get_config().data_dir,
        root_dir=tmp_path,
        policy=policy,
        run_policy=RunPolicy(no_progress_timeout_seconds=60.0),
        operation=RunOperation.FULL,
        clean=False,
        model_identity="route-migration-page-test",
        dense_dimensions=4,
        configuration=DocumentRunConfiguration(
            slice_max_chunks=1,
            source_bytes=2,
            generated_chunks=2,
            weighted_bytes=2,
            sparse_enabled=False,
            sparse_dimension=1,
            encode_batch_size=1,
        ),
    )
    for destination in destinations:
        rel_path = destination.payload.source_path
        digest = hashlib.blake2b(rel_path.encode("utf-8")).hexdigest()
        checkpoint.record_confirmed_slice(
            checkpoint.unit_for(
                rel_path,
                digest,
                0,
                is_file_end=True,
                point_ids=(destination.id,),
            )
        )

    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        store.upsert_code_chunks(origins, write_policy=None)
        store.upsert_document_content_chunks(destinations, write_policy=None)

        removed = reconcile_checkpoint_routes(
            store,
            checkpoint,
            policy,
            ContentKind.DOCUMENT,
            page_size=1,
        )

        assert removed == 2
        assert store.get_all_code_ids() == {"retained-code"}
        assert store.get_all_document_content_ids() == {
            destination.id for destination in destinations
        }
        assert checkpoint.run_policy.snapshot().expired is False
    finally:
        store.close()


def test_real_indexers_flip_ownership_destination_first(
    clean_config: None,
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    del clean_config
    from ...indexer import CodebaseIndexer, DocumentIndexer
    from ...progress import NullProgressReporter

    source = tmp_path / "shared.py"
    source.write_text("def routed_value() -> int:\n    return 17\n", encoding="utf-8")
    code_policy = RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
    document_policy = RootContentPolicy(
        SourceProfileVersion.EXPLICIT_ONLY_V1,
        (ContentRoute("shared.py", ContentKind.DOCUMENT),),
    )
    store = VaultStore(tmp_path)
    try:
        code = CodebaseIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=code_policy,
        )
        code.full_index(
            reporter=NullProgressReporter(),
            preflight=code.preflight_content(),
        )
        assert store.count_code() > 0
        assert store.count_document() == 0

        document = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=document_policy,
        )
        document.full_index(
            reporter=NullProgressReporter(),
            preflight=document.preflight_content(),
        )
        assert store.count_code() == 0
        assert store.count_document() > 0

        code = CodebaseIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=code_policy,
        )
        code.full_index(
            reporter=NullProgressReporter(),
            preflight=code.preflight_content(),
        )
        assert store.count_code() > 0
        assert store.count_document() == 0
    finally:
        store.close()
