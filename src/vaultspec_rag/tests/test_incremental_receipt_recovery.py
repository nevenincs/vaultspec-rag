"""Publication recovery uses real receipt state and acknowledged temp storage.

Guard evidence: removing the production proof fence or accepting a vanished
receipt failed with DID NOT RAISE. Every mutation was immediately restored
and its selected test then passed.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import pytest
from qdrant_client import QdrantClient, models

from .._qdrant_local_client import open_local_client
from .._source_types import PublicSourceType
from ..indexer._document_checkpoint import DocumentRunCheckpoint
from ..indexer._publication_proof import (
    ProofReceiptState,
)
from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunAuthority,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
)
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
from ..indexer._run_ledger_runtime import RunLedger
from ..indexer._run_policy import RunPolicy
from ._run_ledger_test_support import ledger_test_digest, ledger_test_signature

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def receipt_store(tmp_path: Path) -> Generator[QdrantClient]:
    client = open_local_client(tmp_path / "qdrant")
    client.create_collection(
        "served",
        vectors_config=models.VectorParams(size=8, distance=models.Distance.COSINE),
    )
    try:
        yield client
    finally:
        client.close()


def _signature(root: Path) -> RunSignature:
    return replace(
        ledger_test_signature(root),
        source_type=PublicSourceType.DOCUMENT,
        collection_identity="document-v1",
        clean=True,
    )


def _checkpoint(
    ledger: RunLedger,
    signature: RunSignature,
    authority: RunAuthority,
) -> DocumentRunCheckpoint:
    run_policy = RunPolicy(no_progress_timeout_seconds=30)
    generation = DocumentRunCheckpoint.start_compatible_generation(
        ledger, signature, authority
    )
    receipt = DocumentRunCheckpoint.open_publication_receipt(
        ledger, generation, authority
    )
    return DocumentRunCheckpoint(
        ledger, generation, None, run_policy, authority, receipt
    )


def _write(
    checkpoint: DocumentRunCheckpoint, client: QdrantClient, path: str
) -> CommitUnit:
    unit = CommitUnit(
        rel_path=path,
        kind=CommitUnitKind.UPSERT,
        source_digest=ledger_test_digest(path),
        segment_ordinal=0,
        is_file_end=True,
        point_ids=(str(uuid5(NAMESPACE_URL, path)),),
    )
    lifecycle = checkpoint.mutation_lifecycle(unit)
    if lifecycle is not None:
        assert lifecycle.prepare()
    client.upsert(
        "served",
        points=[
            models.PointStruct(
                id=unit.point_ids[0], vector=[0.5] * 8, payload={"path": path}
            )
        ],
        wait=True,
    )
    if lifecycle is not None:
        lifecycle.mark_applied()
        lifecycle.confirm()
    checkpoint.record_confirmed_slice(unit)
    return unit


def _published(
    root: Path, client: QdrantClient, *, populated: bool
) -> tuple[RunLedger, DocumentRunCheckpoint]:
    ledger = RunLedger(root / "runs.sqlite3")
    checkpoint = _checkpoint(ledger, _signature(root), RunAuthority.REBUILD)
    if populated:
        _write(checkpoint, client, "guide.md")
    checkpoint.publish_proof_transition()
    checkpoint.publish_generation()
    return ledger, checkpoint


@pytest.mark.parametrize("populated", [False, True])
@pytest.mark.parametrize(
    "operation",
    [RunOperation.FULL, RunOperation.INCREMENTAL, RunOperation.SCOPED_INCREMENTAL],
    ids=["full", "incremental", "scoped"],
)
def test_repeated_noop_finalization_preserves_parent_proof_and_storage(
    tmp_path: Path,
    receipt_store: QdrantClient,
    populated: bool,
    operation: RunOperation,
) -> None:
    ledger, rebuilt = _published(tmp_path, receipt_store, populated=populated)
    key = compatibility_for_signature(rebuilt.generation.signature)
    original = ledger.publication_proof(key)
    for _attempt in range(3):
        checkpoint = _checkpoint(
            ledger,
            replace(
                rebuilt.generation.signature,
                operation=operation,
                clean=False,
            ),
            RunAuthority.PUBLICATION,
        )
        assert checkpoint.seal_incremental_proof() == 0
        assert checkpoint.seal_incremental_proof() == 0
        assert checkpoint.publish_proof_transition() == 0
        assert checkpoint.publish_proof_transition() == 0
        checkpoint.publish_generation()
        current = ledger.publication_proof(key)
        assert current.revision == original.revision
        assert current.generation_id == original.generation_id
        assert current.aggregate == original.aggregate
        assert ledger.active_publication_receipt(key) is None
        assert receipt_store.count("served", exact=True).count == int(populated)
        receipt = ledger.publication_receipt_for_generation(checkpoint.generation_id)
        assert receipt is not None and receipt.state is ProofReceiptState.ROLLED_BACK


def test_noop_receipt_survives_interruption_between_sealing_and_finalization(
    tmp_path: Path, receipt_store: QdrantClient
) -> None:
    ledger, rebuilt = _published(tmp_path, receipt_store, populated=True)
    signature = replace(
        rebuilt.generation.signature, operation=RunOperation.INCREMENTAL, clean=False
    )
    interrupted = _checkpoint(ledger, signature, RunAuthority.PUBLICATION)
    assert interrupted.seal_incremental_proof() == 0
    interrupted.mark_failed("interrupted after no-op closure")

    resumed = _checkpoint(RunLedger(ledger.path), signature, RunAuthority.PUBLICATION)
    assert resumed.generation_id == interrupted.generation_id
    assert resumed.receipt == ledger.publication_receipt_for_generation(
        interrupted.generation_id
    )
    assert resumed.publish_proof_transition() == 0
    assert resumed.publish_generation().terminal_state is RunTerminalState.SUCCEEDED


@pytest.mark.parametrize("metadata_published", [False, True])
def test_resume_after_receipt_commit_does_not_reconcile_or_advance_proof_again(
    tmp_path: Path, receipt_store: QdrantClient, metadata_published: bool
) -> None:
    ledger, rebuilt = _published(tmp_path, receipt_store, populated=True)
    signature = replace(
        rebuilt.generation.signature, operation=RunOperation.INCREMENTAL, clean=False
    )
    interrupted = _checkpoint(ledger, signature, RunAuthority.PUBLICATION)
    _write(interrupted, receipt_store, "new-guide.md")
    interrupted.seal_incremental_proof()
    interrupted.generation = ledger.advance_finalization(
        interrupted.generation_id, FinalizationPhase.STALE_RECONCILED
    )
    assert interrupted.receipt is not None
    proof = ledger.commit_publication_receipt(interrupted.receipt.receipt_id)
    if metadata_published:
        interrupted.generation = ledger.advance_finalization(
            interrupted.generation_id, FinalizationPhase.METADATA_PUBLISHED
        )
    interrupted.mark_failed("interrupted after exact proof commit")

    resumed = _checkpoint(RunLedger(ledger.path), signature, RunAuthority.PUBLICATION)

    assert resumed.receipt is None
    assert resumed.ledger.publication_already_committed(resumed.generation_id)
    assert resumed.publish_proof_transition() == 0
    resumed.publish_generation()
    assert resumed.ledger.publication_proof(proof.compatibility_key) == proof
    assert receipt_store.count("served", exact=True).count == 2


def test_resume_refuses_a_committed_receipt_with_changed_current_proof(
    tmp_path: Path, receipt_store: QdrantClient
) -> None:
    """Mutation: skipping the canonical proof fence certifies changed evidence."""
    ledger, rebuilt = _published(tmp_path, receipt_store, populated=True)
    incremental = _checkpoint(
        ledger,
        replace(
            rebuilt.generation.signature,
            operation=RunOperation.INCREMENTAL,
            clean=False,
        ),
        RunAuthority.PUBLICATION,
    )
    _write(incremental, receipt_store, "new-guide.md")
    incremental.seal_incremental_proof()
    incremental.generation = ledger.advance_finalization(
        incremental.generation_id, FinalizationPhase.STALE_RECONCILED
    )
    assert incremental.receipt is not None
    ledger.commit_publication_receipt(incremental.receipt.receipt_id)
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute("UPDATE publication_proofs SET revision = revision + 1")

    with pytest.raises(
        RunLedgerStateError, match="receipt must commit the current proof"
    ):
        ledger.publication_already_committed(incremental.generation_id)


def test_generation_publication_requires_proof_in_the_production_checkpoint(
    tmp_path: Path,
) -> None:
    """Mutation: removing the GENERATION_PUBLISHED proof gate makes this red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    checkpoint = _checkpoint(ledger, _signature(tmp_path), RunAuthority.REBUILD)
    for phase in (
        FinalizationPhase.STALE_RECONCILED,
        FinalizationPhase.METADATA_PUBLISHED,
    ):
        checkpoint.generation = ledger.advance_finalization(
            checkpoint.generation_id, phase
        )
    with pytest.raises(RunLedgerStateError, match="proof must commit"):
        checkpoint.publish_generation()
    assert (
        ledger.generation(checkpoint.generation_id).finalization_phase
        is FinalizationPhase.METADATA_PUBLISHED
    )


def test_missing_receipt_is_not_treated_as_completed_noop(tmp_path: Path) -> None:
    """Mutation: accepting any missing active receipt as a no-op makes this red."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    rebuilt = _checkpoint(ledger, _signature(tmp_path), RunAuthority.REBUILD)
    rebuilt.publish_proof_transition()
    rebuilt.publish_generation()
    incremental = _checkpoint(
        ledger,
        replace(
            rebuilt.generation.signature,
            operation=RunOperation.INCREMENTAL,
            clean=False,
        ),
        RunAuthority.PUBLICATION,
    )
    assert incremental.receipt is not None
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            "DELETE FROM publication_receipts WHERE receipt_id = ?",
            (incremental.receipt.receipt_id,),
        )
    with pytest.raises(RunLedgerStateError, match="receipt disappeared"):
        incremental.seal_incremental_proof()


def test_rolled_back_noop_refuses_unjournaled_committed_units(tmp_path: Path) -> None:
    """An empty receipt cannot certify storage units absent from its journal.

    Mutation evidence: removing the committed-unit fence failed the no-op
    refusal assertion; restoring it passed the same test.
    """
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    rebuilt = _checkpoint(ledger, _signature(tmp_path), RunAuthority.REBUILD)
    rebuilt.publish_proof_transition()
    rebuilt.publish_generation()
    incremental = _checkpoint(
        ledger,
        replace(
            rebuilt.generation.signature,
            operation=RunOperation.INCREMENTAL,
            clean=False,
        ),
        RunAuthority.PUBLICATION,
    )
    assert incremental.receipt is not None
    assert incremental.seal_incremental_proof() == 0
    ledger.record_storage_confirmed_unit(
        incremental.generation_id,
        CommitUnit(
            rel_path="unexpected.md",
            kind=CommitUnitKind.UPSERT,
            source_digest=ledger_test_digest("unexpected"),
            segment_ordinal=0,
            is_file_end=True,
            point_ids=("unexpected-point",),
        ),
    )

    assert not ledger.publication_noop_completed(
        incremental.generation_id, incremental.receipt.receipt_id
    )
    with pytest.raises(RunLedgerStateError, match="receipt disappeared"):
        incremental.seal_incremental_proof()
