"""Public CODE incremental failures retain confirmed work and classify the run."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pytest

from .._job_errors import JobError, JobErrorKind
from .._source_types import PublicSourceType
from ..config._settings import get_config
from ..embeddings import EmbeddingModel
from ..indexer import CodebaseIndexer
from ..indexer._publication_proof import ProofReadConflictError, ProofReceiptState
from ..indexer._run_ledger_models import (
    FinalizationPhase,
    RunOperation,
    RunTerminalState,
)
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..indexer._run_checkpoint import CodeRunCheckpoint
    from ..indexer._vault_prep import IndexResult
    from ..progress import ProgressReporter

pytestmark = [pytest.mark.unit]


@dataclass
class _Case:
    indexer: CodebaseIndexer
    path: Path
    scoped: bool

    def run(self, reporter: ProgressReporter | None = None) -> IndexResult:
        changed = [self.path] if self.scoped else None
        preflight = (
            self.indexer.preflight_changed_paths(changed)
            if changed is not None
            else self.indexer.preflight_content()
        )
        return self.indexer.incremental_index(
            reporter=reporter or NullProgressReporter(),
            changed_paths=changed,
            preflight=preflight,
        )

    @property
    def checkpoint(self) -> CodeRunCheckpoint:
        checkpoint = self.indexer.last_checkpoint
        assert checkpoint is not None
        return checkpoint


@pytest.fixture(params=[False, True], ids=["unscoped", "scoped"])
def case(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    clean_config: None,
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[_Case]:
    del clean_config
    config = get_config(
        {
            "embedding_dimension": 2,
            "qdrant_url": None,
            "sparse_enabled": False,
            "index_chunk_workers": 1,
            "index_reuse_enabled": False,
        }
    )
    model = EmbeddingModel.__new__(EmbeddingModel)
    # No weights are loaded here, so there is no device to name.
    model._device = "unloaded"
    model._init_encode_state(config)

    def encode(texts: list[str], **options: object) -> list[list[float]]:
        del options
        return [[1.0, 0.0] for _ in texts]

    monkeypatch.setattr(model, "encode_documents_on_device", encode)
    (tmp_path / ".vault").mkdir()
    with VaultStore(tmp_path, embedding_dim=2) as store:
        indexer = CodebaseIndexer(tmp_path, model, store)
        indexer.full_index(
            reporter=NullProgressReporter(), preflight=indexer.preflight_content()
        )
        path = tmp_path / "module.py"
        path.write_text("def alpha():\n    return 1\n", encoding="utf-8")
        yield _Case(indexer, path, bool(request.param))


class _FailAfterAcknowledgement(NullProgressReporter):
    def __init__(self, case: _Case, error: JobError) -> None:
        self.case = case
        self.error = error
        self.confirmed_units = 0

    def confirmed_chunks(self, n: int) -> None:
        assert n > 0
        checkpoint = self.case.checkpoint
        self.confirmed_units = checkpoint.ledger.committed_unit_count(
            checkpoint.generation_id
        )
        assert self.confirmed_units > 0, "failure injection preceded confirmed unit"
        raise self.error


def _failure_count(checkpoint: CodeRunCheckpoint) -> int:
    with sqlite3.connect(checkpoint.ledger.path) as connection:
        row = connection.execute(
            "SELECT consecutive_failures FROM generations WHERE generation_id = ?",
            (checkpoint.generation_id,),
        ).fetchone()
    assert row is not None
    return int(row[0])


def _current_proof(case: _Case) -> str:
    proof, token = case.checkpoint.ledger.acquire_current_publication_snapshot(
        source_type=PublicSourceType.CODE,
        root_identity=str(case.indexer.root_dir.resolve()),
        backend_identity=case.indexer.store.backend_identity,
    )
    case.checkpoint.ledger.validate_publication_read_token(token)
    return proof.generation_id


def test_confirmed_incremental_failure_is_classified_and_fenced(case: _Case) -> None:
    """Removing either incremental context leaves its generation RUNNING."""
    error = JobError(JobErrorKind.CHUNK_FAILED, "injected after confirmed CODE unit")
    reporter = _FailAfterAcknowledgement(case, error)
    with pytest.raises(JobError) as caught:
        case.run(reporter)
    assert caught.value is error, "classification replaced the original exception"
    checkpoint = case.checkpoint
    generation = checkpoint.ledger.generation(checkpoint.generation_id)
    assert generation.terminal_state is RunTerminalState.FAILED, (
        "confirmed incremental failure must classify generation FAILED"
    )
    assert checkpoint.generation == generation
    assert generation.terminal_detail == f"JobError: {error}"
    assert generation.finalization_phase is FinalizationPhase.INGESTING
    assert generation.signature.operation is (
        RunOperation.SCOPED_INCREMENTAL if case.scoped else RunOperation.INCREMENTAL
    )
    assert _failure_count(checkpoint) == 1, "one failure must be recorded exactly once"
    assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == (
        reporter.confirmed_units
    )
    confirmed_ids = set(checkpoint.ledger.iter_point_ids(checkpoint.generation_id))
    assert confirmed_ids
    assert confirmed_ids <= case.indexer.store.get_all_code_ids()
    assert checkpoint.receipt is not None
    receipt = checkpoint.ledger.active_publication_receipt(
        checkpoint.receipt.compatibility_key
    )
    assert receipt is not None and receipt.state is ProofReceiptState.RESERVED
    assert receipt.generation_id == checkpoint.generation_id
    # Classification must preserve the canonical open-receipt reader refusal.
    with pytest.raises(
        ProofReadConflictError, match=r"^an open receipt prevents proof certification$"
    ):
        _current_proof(case)
    # The unchanged recovery owner must refuse a nonempty, unsealed delta.
    with pytest.raises(
        JobError,
        match=(
            r"^full_reindex_required: interrupted publication has no "
            r"complete storage-confirmed delta; "
            r"run vaultspec-rag index --rebuild --type code$"
        ),
    ) as retry:
        case.run()
    assert retry.value.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert checkpoint.ledger.generation(checkpoint.generation_id) == generation
    assert _failure_count(checkpoint) == 1
    assert checkpoint.ledger.active_publication_receipt(receipt.compatibility_key) == (
        receipt
    )


def test_incremental_success_and_noop_keep_published_generation(case: _Case) -> None:
    result = case.run()
    checkpoint = case.checkpoint
    generation = checkpoint.ledger.generation(checkpoint.generation_id)
    assert result.added == 1 and result.total > 0
    assert generation.terminal_state is RunTerminalState.SUCCEEDED
    assert _failure_count(checkpoint) == 0
    assert _current_proof(case) == checkpoint.generation_id
    noop = case.run()
    assert noop.added == noop.updated == noop.removed == 0
    assert case.checkpoint is checkpoint, "no-op must not open another checkpoint"
    assert checkpoint.ledger.generation(checkpoint.generation_id) == generation
    assert _failure_count(checkpoint) == 0
    assert _current_proof(case) == checkpoint.generation_id


def test_exception_after_publication_preserves_success(
    case: _Case, monkeypatch: pytest.MonkeyPatch
) -> None:
    error = JobError(JobErrorKind.OTHER, "injected after CODE publication")
    original_count = case.indexer.store.count_code
    parent_id = case.checkpoint.generation_id

    def count_after_publication(collection: str | None = None) -> int:
        checkpoint = case.checkpoint
        if (
            checkpoint.generation_id != parent_id
            and checkpoint.generation.terminal_state is RunTerminalState.SUCCEEDED
        ):
            raise error
        return original_count(collection=collection)

    monkeypatch.setattr(case.indexer.store, "count_code", count_after_publication)
    with pytest.raises(JobError) as caught:
        case.run()
    assert caught.value is error
    checkpoint = case.checkpoint
    assert checkpoint.generation_id != parent_id
    assert checkpoint.ledger.generation(checkpoint.generation_id).terminal_state is (
        RunTerminalState.SUCCEEDED
    ), "a published generation must retain immutable success"
    assert _failure_count(checkpoint) == 0
    assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) > 0
    assert _current_proof(case) == checkpoint.generation_id
