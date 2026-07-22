"""Real-store restart evidence for independent content-kind generations."""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import TYPE_CHECKING

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration, pytest.mark.timeout(600)]

_WAIT_SECONDS = 30.0


def _document_policy(pattern: str):
    from ...indexer._content_policy import (
        ContentKind,
        ContentRoute,
        RootContentPolicy,
        SourceProfileVersion,
    )

    return RootContentPolicy(
        SourceProfileVersion.CONVENTIONAL_V1,
        (ContentRoute(pattern, ContentKind.DOCUMENT),),
    )


def test_completed_source_generation_exposes_route_migration_evidence(
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    from ... import store_schema
    from ...config import get_config
    from ...indexer import CodebaseIndexer
    from ...indexer._code_meta import GENERATION_ID_KEY, read_meta_raw
    from ...indexer._content_policy import ContentKind
    from ...indexer._file_state import FileStateKind
    from ...indexer._run_ledger import (
        FinalizationPhase,
        RunLedger,
        RunTerminalState,
        index_run_ledger_path,
    )
    from ...store import VaultStore

    source = tmp_path / "module.py"
    source.write_text("def indexed_source() -> int:\n    return 23\n", encoding="utf-8")
    store = VaultStore(tmp_path)
    try:
        indexer = CodebaseIndexer(tmp_path, embedding_model, store)
        preflight = indexer.preflight_content()
        indexer.full_index(reporter=NullProgressReporter(), preflight=preflight)

        ledger = RunLedger(index_run_ledger_path(tmp_path / get_config().data_dir))
        generation = ledger.latest_generation(
            ContentKind.CODE,
            collection_identity=store_schema.CODE_COLLECTION,
        )
        assert generation is not None
        kind_fingerprints = preflight.policy.fingerprints_for(ContentKind.CODE)
        assert (
            generation.signature.policy_fingerprint
            == preflight.policy.fingerprints.snapshot
        )
        assert generation.signature.membership_epoch == kind_fingerprints.membership
        assert generation.signature.content_epoch == kind_fingerprints.content
        assert generation.terminal_state is RunTerminalState.SUCCEEDED
        assert generation.finalization_phase is FinalizationPhase.COMPACTED
        states = list(ledger.iter_file_states(generation.generation_id))
        assert [(state.rel_path, state.state, state.kind) for state in states] == [
            ("module.py", FileStateKind.INDEXED, ContentKind.CODE)
        ]
        raw = read_meta_raw(indexer._meta_path)
        assert raw[GENERATION_ID_KEY] == generation.generation_id
        assert raw["module.py"] == states[0].content_hash
    finally:
        store.close()


def test_code_and_document_publish_independent_generation_signatures(
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    from ... import store_schema
    from ...config import get_config
    from ...indexer import CodebaseIndexer, DocumentIndexer
    from ...indexer._content_policy import ContentKind
    from ...indexer._document_meta import read_document_meta
    from ...indexer._run_ledger import RunLedger, index_run_ledger_path
    from ...store import VaultStore

    (tmp_path / "module.py").write_text(
        "def source() -> int:\n    return 7\n", encoding="utf-8"
    )
    document = tmp_path / "guide.txt"
    document.write_text("Document-owned generation material.", encoding="utf-8")
    policy = _document_policy("guide.txt")
    store = VaultStore(tmp_path)
    try:
        code_indexer = CodebaseIndexer(
            tmp_path, embedding_model, store, content_policy=policy
        )
        document_indexer = DocumentIndexer(
            tmp_path,
            embedding_model,
            store,
            content_policy=policy,
        )
        code_indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=code_indexer.preflight_content(),
        )
        document_indexer.full_index(
            reporter=NullProgressReporter(),
            preflight=document_indexer.preflight_content(),
        )

        ledger = RunLedger(index_run_ledger_path(tmp_path / get_config().data_dir))
        code_generation = ledger.latest_generation(
            ContentKind.CODE,
            collection_identity=store_schema.CODE_COLLECTION,
        )
        document_generation = ledger.latest_generation(
            ContentKind.DOCUMENT,
            collection_identity=store_schema.DOCUMENT_COLLECTION,
        )
        assert code_generation is not None and document_generation is not None
        assert code_generation.generation_id != document_generation.generation_id
        assert (
            code_generation.signature.fingerprint
            != document_generation.signature.fingerprint
        )
        metadata = read_document_meta(document_indexer._meta_path)
        assert metadata is not None
        assert metadata.complete
        assert metadata.generation_id == document_generation.generation_id
        assert [item.source_path for item in metadata.files] == ["guide.txt"]
    finally:
        store.close()


def test_document_restart_reuses_confirmed_slices_and_publishes_once(
    clean_config: None,
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    del clean_config
    from ... import store_schema
    from ...config import get_config
    from ...indexer import DocumentIndexer
    from ...indexer._content_policy import ContentKind
    from ...indexer._run_ledger import RunLedger, index_run_ledger_path
    from ...job_control import CancelRequested, RunControlToken
    from ...store import VaultStore

    get_config({"embedding_batch_size": 1})
    source = tmp_path / "restart.txt"
    source.write_text(
        ("restart-safe document content " * 8000).strip(), encoding="utf-8"
    )
    policy = _document_policy("restart.txt")
    store = VaultStore(tmp_path)
    token = RunControlToken()
    caught: list[BaseException] = []

    def _run_interrupted() -> None:
        try:
            indexer = DocumentIndexer(
                tmp_path,
                embedding_model,
                store,
                content_policy=policy,
            )
            indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=indexer.preflight_content(),
                run_control=token,
            )
        except BaseException as exc:
            caught.append(exc)

    worker = threading.Thread(target=_run_interrupted, name="document-restart-test")
    worker.start()
    deadline = time.monotonic() + _WAIT_SECONDS
    ledger_path = index_run_ledger_path(tmp_path / get_config().data_dir)
    committed = 0
    generation_id = ""
    while time.monotonic() < deadline:
        if ledger_path.exists():
            ledger = RunLedger(ledger_path)
            generation = ledger.latest_generation(
                ContentKind.DOCUMENT,
                collection_identity=store_schema.DOCUMENT_COLLECTION,
            )
            if generation is not None:
                units = list(ledger.iter_units(generation.generation_id))
                if units:
                    committed = len(units)
                    generation_id = generation.generation_id
                    token.request_cancel()
                    break
        time.sleep(0.01)
    worker.join(timeout=_WAIT_SECONDS)
    assert not worker.is_alive()
    assert committed > 0
    assert len(caught) == 1 and isinstance(caught[0], CancelRequested)

    with sqlite3.connect(ledger_path) as connection:
        before = dict(
            connection.execute(
                "SELECT unit_id, committed_at FROM commit_units "
                "WHERE generation_id = ?",
                (generation_id,),
            ).fetchall()
        )
    indexer = DocumentIndexer(tmp_path, embedding_model, store, content_policy=policy)
    result = indexer.full_index(
        reporter=NullProgressReporter(),
        preflight=indexer.preflight_content(),
    )
    ledger = RunLedger(ledger_path)
    published = ledger.latest_generation(
        ContentKind.DOCUMENT,
        collection_identity=store_schema.DOCUMENT_COLLECTION,
    )
    assert published is not None and published.generation_id == generation_id
    with sqlite3.connect(ledger_path) as connection:
        after = dict(
            connection.execute(
                "SELECT unit_id, committed_at FROM commit_units "
                "WHERE generation_id = ?",
                (generation_id,),
            ).fetchall()
        )
    assert before.items() <= after.items()
    assert len(after) > committed
    assert result.preprocess_skipped == 0
    assert store.count_document() == result.total
    store.close()
