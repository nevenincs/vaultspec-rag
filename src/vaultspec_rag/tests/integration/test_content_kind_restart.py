"""Real-store restart evidence for independent content-kind generations."""

from __future__ import annotations

import sqlite3
import threading
import time
from contextlib import closing
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
    with VaultStore(tmp_path) as store:
        interrupted = _interrupt_document_indexing(
            tmp_path, embedding_model, store, policy
        )

        with closing(sqlite3.connect(interrupted.ledger_path)) as connection:
            before = dict(
                connection.execute(
                    "SELECT unit_id, committed_at FROM commit_units "
                    "WHERE generation_id = ?",
                    (interrupted.generation_id,),
                ).fetchall()
            )
        indexer = DocumentIndexer(
            tmp_path, embedding_model, store, content_policy=policy
        )
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
            published is not None
            and published.generation_id == interrupted.generation_id
        )
        with closing(sqlite3.connect(interrupted.ledger_path)) as connection:
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
