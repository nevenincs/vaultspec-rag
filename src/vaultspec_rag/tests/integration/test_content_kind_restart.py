"""Real-store restart evidence for independent content-kind generations."""

from __future__ import annotations

import sqlite3
import threading
import time
from typing import TYPE_CHECKING, NamedTuple

import pytest

from ...progress import NullProgressReporter
from ._helpers import _document_policy

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel
    from ...indexer._content_policy import RootContentPolicy
    from ...store_runtime import VaultStore

pytestmark = [pytest.mark.integration, pytest.mark.timeout(600)]

_WAIT_SECONDS = 30.0


class _InterruptedDocumentRun(NamedTuple):
    """The durable progress recorded before the real indexing run was cancelled."""

    ledger_path: Path
    committed: int
    generation_id: str


def _interrupt_document_indexing(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    store: VaultStore,
    policy: RootContentPolicy,
) -> _InterruptedDocumentRun:
    """Cancel a real document index only after its first committed unit appears."""
    from ... import store_schema
    from ...config._settings import get_config
    from ...indexer import DocumentIndexer
    from ...indexer._content_policy import ContentKind
    from ...indexer._run_ledger_models import index_run_ledger_path
    from ...indexer._run_ledger_runtime import RunLedger
    from ...job_control import CancelRequested, RunControlToken

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
    ledger_path = index_run_ledger_path(tmp_path / get_config().data_dir)
    deadline = time.monotonic() + _WAIT_SECONDS
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
    return _InterruptedDocumentRun(ledger_path, committed, generation_id)


def test_document_restart_reuses_confirmed_slices_and_publishes_once(
    clean_config: None,
    embedding_model: EmbeddingModel,
    tmp_path: Path,
) -> None:
    del clean_config
    from ... import store_schema
    from ...config._settings import get_config
    from ...indexer import DocumentIndexer
    from ...indexer._content_policy import ContentKind
    from ...indexer._run_ledger_runtime import RunLedger
    from ...store_runtime import VaultStore

    get_config({"embedding_batch_size": 1})
    source = tmp_path / "restart.txt"
    source.write_text(
        ("restart-safe document content " * 8000).strip(), encoding="utf-8"
    )
    policy = _document_policy("restart.txt")
    store = VaultStore(tmp_path)
    interrupted = _interrupt_document_indexing(tmp_path, embedding_model, store, policy)

    with sqlite3.connect(interrupted.ledger_path) as connection:
        before = dict(
            connection.execute(
                "SELECT unit_id, committed_at FROM commit_units "
                "WHERE generation_id = ?",
                (interrupted.generation_id,),
            ).fetchall()
        )
    indexer = DocumentIndexer(tmp_path, embedding_model, store, content_policy=policy)
    result = indexer.full_index(
        reporter=NullProgressReporter(),
        preflight=indexer.preflight_content(),
    )
    ledger = RunLedger(interrupted.ledger_path)
    published = ledger.latest_generation(
        ContentKind.DOCUMENT,
        collection_identity=store_schema.DOCUMENT_COLLECTION,
    )
    assert (
        published is not None and published.generation_id == interrupted.generation_id
    )
    with sqlite3.connect(interrupted.ledger_path) as connection:
        after = dict(
            connection.execute(
                "SELECT unit_id, committed_at FROM commit_units "
                "WHERE generation_id = ?",
                (interrupted.generation_id,),
            ).fetchall()
        )
    assert before.items() <= after.items()
    assert len(after) > interrupted.committed
    assert result.preprocess_skipped == 0
    assert store.count_document() == result.total
    store.close()


def test_each_kind_replays_only_its_final_unconfirmed_unit(tmp_path: Path) -> None:
    """Independent production checkpoints retain every confirmed kind-local unit."""
    import hashlib

    from ..._store_models import CodeChunk
    from ...indexer._document_checkpoint import (
        DocumentRunCheckpoint,
        DocumentRunConfiguration,
        DocumentRunOpenRequest,
    )
    from ...indexer._resolved_policy import (
        IndexPolicyResolutionOptions,
        resolve_index_policy,
    )
    from ...indexer._run_checkpoint import (
        CodeRunCheckpoint,
        CodeRunConfiguration,
        CodeRunOpenRequest,
    )
    from ...indexer._run_ledger_models import (
        RunAuthority,
        RunOperation,
        RunTerminalState,
    )
    from ...indexer._run_policy import RunPolicy
    from ...indexer._streaming_types import CodeFileSegment

    policy = resolve_index_policy(
        tmp_path,
        IndexPolicyResolutionOptions(content_policy=_document_policy("guide.txt")),
    )
    run_policy = RunPolicy(no_progress_timeout_seconds=30.0)
    data_root = tmp_path / ".state"
    code_configuration = CodeRunConfiguration(
        segment_max_chunks=1,
        segment_max_bytes=4096,
        queue_max_chunks=2,
        queue_max_bytes=8192,
        slice_max_chunks=2,
        slice_max_bytes=8192,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=2,
        flush_slices=2,
    )
    document_configuration = DocumentRunConfiguration(
        slice_max_chunks=1,
        source_bytes=4096,
        generated_chunks=3,
        weighted_bytes=8192,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=2,
    )

    def _open_code() -> CodeRunCheckpoint:
        return CodeRunCheckpoint.open_generation(
            CodeRunOpenRequest(
                data_root=data_root,
                root_dir=tmp_path,
                policy=policy,
                run_policy=run_policy,
                operation=RunOperation.FULL,
                authority=RunAuthority.REBUILD,
                clean=False,
                model_identity="restart-model-v1",
                backend_identity="test-backend:content-kind-restart",
                dense_dimensions=4,
                configuration=code_configuration,
            )
        )

    def _open_document() -> DocumentRunCheckpoint:
        return DocumentRunCheckpoint.open_generation(
            DocumentRunOpenRequest(
                data_root=data_root,
                root_dir=tmp_path,
                policy=policy,
                run_policy=run_policy,
                operation=RunOperation.FULL,
                authority=RunAuthority.REBUILD,
                clean=False,
                model_identity="restart-model-v1",
                backend_identity="test-backend:content-kind-restart",
                dense_dimensions=4,
                configuration=document_configuration,
            )
        )

    code_digest = hashlib.blake2b(b"code restart input").hexdigest()
    code_segments = tuple(
        CodeFileSegment(
            "module.py",
            ordinal,
            (
                CodeChunk(
                    id=f"code-{ordinal}",
                    path="module.py",
                    language="python",
                    content=f"def unit_{ordinal}():\n    return {ordinal}\n",
                    line_start=ordinal * 2 + 1,
                    line_end=ordinal * 2 + 2,
                ),
            ),
            256,
            ordinal == 2,
        )
        for ordinal in range(3)
    )
    document_digest = hashlib.blake2b(b"document restart input").hexdigest()

    code = _open_code()
    document = _open_document()
    for segment in code_segments[:2]:
        assert code.record_confirmed_segment(segment, code_digest)
    document_units = tuple(
        document.unit_for(
            "guide.txt",
            document_digest,
            ordinal,
            is_file_end=ordinal == 2,
            point_ids=(f"document-{ordinal}",),
        )
        for ordinal in range(3)
    )
    for unit in document_units[:2]:
        assert document.record_confirmed_slice(unit)
    code.ledger.finish_generation(
        code.generation_id,
        RunTerminalState.CANCELLED,
        detail="interrupted before final code segment",
    )
    document.ledger.finish_generation(
        document.generation_id,
        RunTerminalState.CANCELLED,
        detail="interrupted before final document slice",
    )

    resumed_code = _open_code()
    resumed_document = _open_document()
    assert resumed_code.generation_id == code.generation_id
    assert resumed_document.generation_id == document.generation_id
    assert tuple(resumed_code.pending_segments(code_segments, code_digest)) == (
        code_segments[-1],
    )
    assert [resumed_document.slice_committed(unit) for unit in document_units] == [
        True,
        True,
        False,
    ]
    assert resumed_code.record_confirmed_segment(code_segments[-1], code_digest)
    assert resumed_document.record_confirmed_slice(document_units[-1])
    assert tuple(resumed_code.pending_segments(code_segments, code_digest)) == ()
    assert all(resumed_document.slice_committed(unit) for unit in document_units)
