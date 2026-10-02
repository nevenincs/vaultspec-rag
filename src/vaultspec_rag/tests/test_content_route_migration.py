"""CPU real-store and ledger evidence for destination-first route migration."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from contextlib import closing
from dataclasses import dataclass
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from .._store_models import (
    CodeChunk,
    DocumentChunk,
    DocumentLocator,
    DocumentPayload,
)
from ..config._settings import get_config
from ..indexer._content_policy import (
    ContentKind,
    ContentRoute,
    RootContentPolicy,
    SourceProfileVersion,
)
from ..indexer._document_checkpoint import (
    DocumentRunCheckpoint,
    DocumentRunConfiguration,
    DocumentRunOpenRequest,
)
from ..indexer._document_identity import document_point_id
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    resolve_index_policy,
)
from ..indexer._route_migration import (
    DestinationCheckpoint,
    RouteMigrationJournal,
    RouteScanOptions,
    iter_stored_route_pages,
    purge_unpublished_rows,
    reconcile_checkpoint_routes,
    reconcile_generation_storage,
    reconcile_origin_after_destination,
    resume_pending_migrations,
)
from ..indexer._run_checkpoint import (
    CodeRunCheckpoint,
    CodeRunConfiguration,
    CodeRunOpenRequest,
)
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..indexer._run_policy import RunPolicy
from ..indexer._streaming_types import CodeFileSegment
from ..job_control import CancelRequested, RunControlToken
from ..storage_identity import sidecar_path
from ..store_runtime import StorageModelError, VaultStore

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path


pytestmark = [pytest.mark.unit]


def _resolved_policy(root: Path):
    policy = RootContentPolicy(
        SourceProfileVersion.EXPLICIT_ONLY_V1,
        (
            ContentRoute("module.py", ContentKind.CODE),
            ContentRoute("guide.txt", ContentKind.DOCUMENT),
        ),
    )
    return resolve_index_policy(
        root, IndexPolicyResolutionOptions(content_policy=policy)
    )


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


def _document_checkpoint(
    root: Path,
    rel_path: str,
    point_id: str,
    *,
    run_policy: RunPolicy | None = None,
) -> DocumentRunCheckpoint:
    policy = _resolved_policy(root)
    checkpoint = DocumentRunCheckpoint.open_generation(
        DocumentRunOpenRequest(
            data_root=root / get_config().data_dir,
            root_dir=root,
            policy=policy,
            run_policy=run_policy or RunPolicy(no_progress_timeout_seconds=60.0),
            operation=RunOperation.FULL,
            authority=RunAuthority.REBUILD,
            clean=False,
            model_identity="route-migration-test",
            backend_identity="test-backend:content-route-migration",
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


def _code_checkpoint(root: Path, chunk: CodeChunk) -> CodeRunCheckpoint:
    checkpoint = CodeRunCheckpoint.open_generation(
        CodeRunOpenRequest(
            data_root=root / get_config().data_dir,
            root_dir=root,
            policy=_resolved_policy(root),
            run_policy=RunPolicy(no_progress_timeout_seconds=60.0),
            operation=RunOperation.FULL,
            authority=RunAuthority.REBUILD,
            clean=False,
            model_identity="route-migration-test",
            backend_identity="test-backend:content-route-migration",
            dense_dimensions=4,
            configuration=CodeRunConfiguration(
                segment_max_chunks=1,
                segment_max_bytes=1024,
                queue_max_chunks=1,
                queue_max_bytes=1024,
                slice_max_chunks=1,
                slice_max_bytes=1024,
                sparse_enabled=False,
                sparse_dimension=1,
                encode_batch_size=1,
                flush_slices=1,
            ),
        )
    )
    checkpoint.record_confirmed_segments(
        (CodeFileSegment(chunk.path, 0, (chunk,), 1024, is_file_end=True),),
        {chunk.path: hashlib.blake2b(chunk.path.encode("utf-8")).hexdigest()},
    )
    return checkpoint


def _stamp_old_sparse_identity(store: VaultStore, collection: str) -> VaultStore:
    """Leave real persisted old provenance, then reopen without ensure caches."""
    root, local_dir = store.root_dir, store.db_path
    store.close()
    path = sidecar_path(local_dir)
    raw = json.loads(path.read_text(encoding="utf-8"))
    raw["collections"][collection]["sparse_model"] = "superseded/sparse"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return VaultStore(root, embedding_dim=4)


@dataclass(slots=True)
class _MigrationCase:
    store: VaultStore
    checkpoint: DestinationCheckpoint
    destination_kind: ContentKind
    origin_id: str
    unrelated_id: str
    destination_id: str

    @property
    def origin_collection(self) -> str:
        return (
            self.store.DOCUMENT_TABLE_NAME
            if self.destination_kind is ContentKind.CODE
            else self.store.CODE_TABLE_NAME
        )

    @property
    def destination_collection(self) -> str:
        return (
            self.store.CODE_TABLE_NAME
            if self.destination_kind is ContentKind.CODE
            else self.store.DOCUMENT_TABLE_NAME
        )

    @property
    def rel_path(self) -> str:
        return "module.py" if self.destination_kind is ContentKind.CODE else "guide.txt"


@pytest.fixture(params=(ContentKind.CODE, ContentKind.DOCUMENT))
def migration_case(
    request: pytest.FixtureRequest,
    clean_config: None,
    tmp_path: Path,
) -> Iterator[_MigrationCase]:
    del clean_config
    kind = request.param
    assert isinstance(kind, ContentKind)
    store = VaultStore(tmp_path, embedding_dim=4)
    code = _code_chunk(
        "migration-code", "module.py" if kind is ContentKind.CODE else "guide.txt"
    )
    document = _document_chunk(
        "module.py" if kind is ContentKind.CODE else "guide.txt", "migration-document"
    )
    if kind is ContentKind.CODE:
        unrelated = _document_chunk("guide.txt", "unrelated-document")
        store.upsert_code_chunks([code], write_policy=None)
        store.upsert_document_content_chunks([document, unrelated], write_policy=None)
        case = _MigrationCase(
            store,
            _code_checkpoint(tmp_path, code),
            kind,
            document.id,
            unrelated.id,
            code.id,
        )
    else:
        unrelated = _code_chunk("unrelated-code", "module.py")
        store.upsert_code_chunks([code, unrelated], write_policy=None)
        store.upsert_document_content_chunks([document], write_policy=None)
        case = _MigrationCase(
            store,
            _document_checkpoint(tmp_path, "guide.txt", document.id),
            kind,
            code.id,
            unrelated.id,
            document.id,
        )
    case.store = _stamp_old_sparse_identity(store, case.origin_collection)
    try:
        yield case
    finally:
        case.store.close()


@pytest.mark.parametrize("entry", ("generation", "scoped", "replay"))
def test_old_sparse_origin_cleanup_is_payload_only_and_destination_first(
    migration_case: _MigrationCase,
    entry: str,
) -> None:
    """Guard: restoring origin ensure in scans/deletes blocks real migration."""
    case = migration_case
    store, checkpoint = case.store, case.checkpoint
    identity_before = sidecar_path(store.db_path).read_bytes()
    journal = RouteMigrationJournal(
        checkpoint.ledger.path.parent / "route_migrations.sqlite3"
    )
    if entry == "replay":
        journal.begin(
            rel_path=case.rel_path,
            origin_kind=ContentKind.DOCUMENT
            if case.destination_kind is ContentKind.CODE
            else ContentKind.CODE,
            destination_kind=case.destination_kind,
            destination_generation_id=checkpoint.generation_id,
            point_ids=(case.origin_id,),
        )
        assert resume_pending_migrations(store, checkpoint.ledger.path.parent) == 1
    elif entry == "scoped":
        assert (
            reconcile_origin_after_destination(
                store, checkpoint, case.destination_kind, case.rel_path
            )
            == 1
        )
    else:
        assert reconcile_generation_storage(
            store,
            checkpoint,
            _resolved_policy(store.root_dir),
            case.destination_kind,
            include_same_kind=False,
        ) == (0, 0, 1)
    rows, _offset = store.scroll_index_audit_content(
        case.origin_collection, limit=10, offset=None
    )
    assert {
        row["payload"].get("chunk_id") or row["payload"].get("document_id")
        for row in rows
    } == {case.unrelated_id}
    assert all(row["vector"] is None for row in rows)
    assert sidecar_path(store.db_path).read_bytes() == identity_before
    assert not store._ensured.get(case.origin_collection, False)
    assert list(journal.pending()) == []
    # Normal payload/vector reads, writes, and same-kind purge remain strict.
    with pytest.raises(StorageModelError):
        if case.destination_kind is ContentKind.CODE:
            store.scroll_document_content(with_vectors=True)
        else:
            store.scroll_code_content(with_vectors=True)
    with pytest.raises(StorageModelError):
        if case.destination_kind is ContentKind.CODE:
            store.delete_document_content_chunks([case.unrelated_id])
        else:
            store.delete_code_chunks([case.unrelated_id])
    with pytest.raises(StorageModelError):
        purge_unpublished_rows(
            store,
            checkpoint,
            _resolved_policy(store.root_dir),
            ContentKind.DOCUMENT
            if case.destination_kind is ContentKind.CODE
            else ContentKind.CODE,
        )


@pytest.mark.parametrize("entry", ("generation", "scoped", "replay"))
def test_incompatible_selected_destination_retains_old_origin(
    migration_case: _MigrationCase,
    entry: str,
) -> None:
    """Guard: removing selected-destination ensure deletes the last valid owner."""
    case = migration_case
    case.store = _stamp_old_sparse_identity(case.store, case.destination_collection)
    store, checkpoint = case.store, case.checkpoint
    before = sidecar_path(store.db_path).read_bytes()
    journal = RouteMigrationJournal(
        checkpoint.ledger.path.parent / "route_migrations.sqlite3"
    )
    if entry == "replay":
        journal.begin(
            rel_path=case.rel_path,
            origin_kind=ContentKind.DOCUMENT
            if case.destination_kind is ContentKind.CODE
            else ContentKind.CODE,
            destination_kind=case.destination_kind,
            destination_generation_id=checkpoint.generation_id,
            point_ids=(case.origin_id,),
        )
        assert resume_pending_migrations(store, checkpoint.ledger.path.parent) == 0
        assert len(list(journal.pending())) == 1
    elif entry == "scoped":
        assert (
            reconcile_origin_after_destination(
                store, checkpoint, case.destination_kind, case.rel_path
            )
            == 0
        )
    else:
        assert reconcile_generation_storage(
            store,
            checkpoint,
            _resolved_policy(store.root_dir),
            case.destination_kind,
            include_same_kind=False,
        ) == (0, 0, 0)
    rows, _offset = store.scroll_index_audit_content(
        case.origin_collection, limit=10, offset=None
    )
    assert len(rows) == 2
    assert sidecar_path(store.db_path).read_bytes() == before
    assert not store._ensured.get(case.destination_collection, False)


def test_metadata_administration_is_noncreating_and_projection_restricted(
    clean_config: None,
    tmp_path: Path,
) -> None:
    """Guards: administration must neither create nor address foreign sources."""
    del clean_config
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        for collection in (store.CODE_TABLE_NAME, store.DOCUMENT_TABLE_NAME):
            assert store.scroll_index_audit_content(
                collection, limit=1, offset=None, source_paths={"missing.py"}
            ) == ([], None)
            store.delete_migration_origin_points(collection, ("missing",))
            assert not store._collection_exists(collection)
        with pytest.raises(ValueError, match="active content"):
            store.delete_migration_origin_points(store.TABLE_NAME, ("not-content",))
        with pytest.raises(ValueError, match="active content"):
            store.delete_migration_origin_points(
                "another-root_codebase_docs", ("foreign",)
            )
        with pytest.raises(ValueError, match="active source"):
            store.scroll_index_audit_content(
                "another-root_codebase_docs", limit=1, offset=None
            )
        with pytest.raises(ValueError, match="code or document"):
            store.scroll_index_audit_content(
                store.TABLE_NAME, limit=1, offset=None, source_paths={"missing"}
            )
    finally:
        store.close()


def test_origin_payload_scan_never_requests_vectors(
    migration_case: _MigrationCase,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Guard: with_vectors=True must fail at the actual local-store boundary."""
    store = migration_case.store
    observed_scroll = Mock(wraps=store._scroll)
    monkeypatch.setattr(store, "_scroll", observed_scroll)
    assert (
        reconcile_origin_after_destination(
            store,
            migration_case.checkpoint,
            migration_case.destination_kind,
            migration_case.rel_path,
        )
        == 1
    )
    assert observed_scroll.call_count == 2
    assert all(
        call.kwargs["with_vectors"] is False
        and call.kwargs["with_payload"] is True
        and call.kwargs["collection_name"] == migration_case.origin_collection
        for call in observed_scroll.call_args_list
    )


def test_absent_selected_destination_stays_absent_and_retains_origin(
    migration_case: _MigrationCase,
) -> None:
    """Guard: ensure before presence evidence creates a nonexistent replacement."""
    case = migration_case
    if case.destination_kind is ContentKind.CODE:
        case.store.drop_code_table()
    else:
        case.store.drop_document_table()
    assert (
        reconcile_origin_after_destination(
            case.store, case.checkpoint, case.destination_kind, case.rel_path
        )
        == 0
    )
    assert not case.store._collection_exists(case.destination_collection)
    rows, _offset = case.store.scroll_index_audit_content(
        case.origin_collection, limit=10, offset=None
    )
    assert len(rows) == 2


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
        assert store.code_content_ids_exist(("code-current", "code-moved"))
        assert not store.code_content_ids_exist(("code-current", "code-missing"))

        code_pages = list(
            iter_stored_route_pages(
                store,
                _resolved_policy(tmp_path),
                ContentKind.CODE,
                options=RouteScanOptions(page_size=1),
            )
        )
        document_pages = list(
            iter_stored_route_pages(
                store,
                _resolved_policy(tmp_path),
                ContentKind.DOCUMENT,
                options=RouteScanOptions(page_size=1),
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


def test_stale_destination_confirmation_retains_the_last_origin(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    rel_path = "guide.txt"
    origin = _code_chunk("last-confirmed-origin", rel_path)
    destination = _document_chunk(rel_path, "replacement destination")
    store = VaultStore(tmp_path, embedding_dim=4)
    try:
        store.upsert_code_chunks([origin], write_policy=None)
        store.upsert_document_content_chunks([destination], write_policy=None)
        checkpoint = _document_checkpoint(tmp_path, rel_path, destination.id)
        journal = RouteMigrationJournal(
            tmp_path / get_config().data_dir / "route_migrations.sqlite3"
        )
        journal.begin(
            rel_path=rel_path,
            origin_kind=ContentKind.CODE,
            destination_kind=ContentKind.DOCUMENT,
            destination_generation_id=checkpoint.generation_id,
            point_ids=(origin.id,),
        )

        store.drop_document_table()
        store.ensure_document_table()

        assert (
            resume_pending_migrations(
                store,
                tmp_path / get_config().data_dir,
            )
            == 0
        )
        assert store.get_all_code_ids() == {origin.id}
        assert store.count_document() == 0
        assert len(list(journal.pending())) == 1
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
            options=RouteScanOptions(page_size=1),
        )

        assert removed == 2
        assert store.get_all_document_content_ids() == {retained.id, opposite.id}
    finally:
        store.close()


def test_same_kind_cleanup_resumes_after_a_real_page_boundary_interruption(
    clean_config: None,
    tmp_path: Path,
) -> None:
    del clean_config
    retained = _document_chunk("guide.txt", "confirmed destination")
    stale = [
        _document_chunk(f"unrouted-{ordinal:03d}.bin", f"stale {ordinal}")
        for ordinal in range(32)
    ]
    token = RunControlToken()
    interrupted = _document_checkpoint(
        tmp_path,
        "guide.txt",
        retained.id,
        run_policy=RunPolicy(
            no_progress_timeout_seconds=60.0,
            run_control=token,
        ),
    )
    store = VaultStore(tmp_path, embedding_dim=4)
    caught: list[BaseException] = []

    def _purge_until_cancelled() -> None:
        try:
            purge_unpublished_rows(
                store,
                interrupted,
                _resolved_policy(tmp_path),
                ContentKind.DOCUMENT,
                options=RouteScanOptions(page_size=1),
            )
        except BaseException as exc:
            caught.append(exc)

    try:
        store.upsert_document_content_chunks(
            [retained, *stale],
            write_policy=None,
        )
        worker = threading.Thread(
            target=_purge_until_cancelled,
            name="same-kind-cleanup-interruption",
        )
        worker.start()
        deadline = time.monotonic() + 10.0
        initial_count = len(stale) + 1
        while worker.is_alive() and time.monotonic() < deadline:
            current_count = store.count_document()
            if 1 < current_count < initial_count:
                assert token.request_cancel()
                break
            time.sleep(0.01)
        worker.join(timeout=10.0)

        assert not worker.is_alive()
        assert len(caught) == 1 and isinstance(caught[0], CancelRequested)
        assert 1 < store.count_document() < initial_count

        resumed = _document_checkpoint(tmp_path, "guide.txt", retained.id)
        assert resumed.generation_id == interrupted.generation_id
        assert (
            purge_unpublished_rows(
                store,
                resumed,
                _resolved_policy(tmp_path),
                ContentKind.DOCUMENT,
                options=RouteScanOptions(page_size=1),
            )
            > 0
        )
        assert store.get_all_document_content_ids() == {retained.id}
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
        with closing(sqlite3.connect(journal_path)) as connection:
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
        IndexPolicyResolutionOptions(
            content_policy=RootContentPolicy(
                SourceProfileVersion.EXPLICIT_ONLY_V1,
                (
                    ContentRoute("guide.txt", ContentKind.DOCUMENT),
                    ContentRoute("appendix.txt", ContentKind.DOCUMENT),
                    ContentRoute("module.py", ContentKind.CODE),
                ),
            ),
        ),
    )
    checkpoint = DocumentRunCheckpoint.open_generation(
        DocumentRunOpenRequest(
            data_root=tmp_path / get_config().data_dir,
            root_dir=tmp_path,
            policy=policy,
            run_policy=RunPolicy(no_progress_timeout_seconds=60.0),
            operation=RunOperation.FULL,
            authority=RunAuthority.REBUILD,
            clean=False,
            model_identity="route-migration-page-test",
            backend_identity="test-backend:content-route-migration",
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
