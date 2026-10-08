"""Publication recovery uses real receipt state and acknowledged temp storage.

Guard evidence: removing the production proof fence or accepting a vanished
receipt failed with DID NOT RAISE. Bypassing the unsealed recovery boundary
failed its exact refusal matcher while the canonical commit still refused.
Removing each source, root, backend or collection restriction independently
failed the foreign-identity assertion; removing each typed recovery projection
field, readiness or committed-proof fence failed with DID NOT RAISE. Removing
typed authority/signature admission reached KeyError instead of its refusal.
Every mutation was immediately restored and its selected test then passed.
"""

from __future__ import annotations

import sqlite3
from contextlib import closing
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import pytest
from qdrant_client import QdrantClient, models

from .._source_types import PublicSourceType
from ..indexer._document_checkpoint import DocumentRunCheckpoint
from ..indexer._publication_proof import (
    ProofReadConflictError,
    ProofReceiptState,
)
from ..indexer._run_ledger_models import (
    MAX_RESUME_FAILURES,
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
from ..indexer._run_policy import DurableProgressKind, RunPolicy
from ._run_ledger_test_support import ledger_test_digest, ledger_test_signature

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture
def receipt_store(tmp_path: Path) -> Generator[QdrantClient]:
    client = QdrantClient(path=str(tmp_path / "qdrant"))
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
        ledger, signature, authority, run_policy
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


def test_explicit_rebuild_closes_abandoned_mutation_free_reservation(
    tmp_path: Path, receipt_store: QdrantClient
) -> None:
    ledger, rebuilt = _published(tmp_path, receipt_store, populated=True)
    key = compatibility_for_signature(rebuilt.generation.signature)
    original = ledger.publication_proof(key)
    incremental = _checkpoint(
        ledger,
        replace(
            rebuilt.generation.signature,
            operation=RunOperation.INCREMENTAL,
            clean=False,
        ),
        RunAuthority.PUBLICATION,
    )
    incremental.mark_failed("interrupted before any mutation")

    replacement = _checkpoint(
        ledger, rebuilt.generation.signature, RunAuthority.REBUILD
    )

    assert replacement.generation_id != incremental.generation_id
    assert ledger.active_publication_receipt(key) is None
    receipt = ledger.publication_receipt_for_generation(incremental.generation_id)
    assert receipt is not None and receipt.state is ProofReceiptState.ROLLED_BACK
    assert ledger.publication_proof(key).revision == original.revision
    assert ledger.publication_proof(key).generation_id == original.generation_id
    assert receipt_store.count("served", exact=True).count == 1


def test_explicit_rebuild_finishes_confirmed_sealed_receipt_without_erasing_evidence(
    tmp_path: Path, receipt_store: QdrantClient
) -> None:
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
    assert incremental.seal_incremental_proof() == 1
    assert incremental.receipt is not None
    incremental.mark_failed("no progress while reconciling routes")
    key = compatibility_for_signature(rebuilt.generation.signature)
    with pytest.raises(ProofReadConflictError, match="open receipt"):
        ledger.acquire_current_publication_snapshot(
            source_type=key.source_type,
            root_identity=key.root_identity,
            backend_identity=key.backend_identity,
        )

    replacement = _checkpoint(
        ledger, rebuilt.generation.signature, RunAuthority.REBUILD
    )

    assert replacement.generation_id != incremental.generation_id
    assert (
        ledger.generation(incremental.generation_id).terminal_state
        is RunTerminalState.INVALIDATED
    )
    assert ledger.publication_proof(key).generation_id == incremental.generation_id
    assert ledger.publication_proof(key).revision == 1
    assert ledger.active_publication_receipt(key) is None
    recovered = ledger.publication_receipt_for_generation(incremental.generation_id)
    assert recovered is not None and recovered.state is ProofReceiptState.COMMITTED
    assert recovered.mutations and recovered.deltas
    assert receipt_store.count("served", exact=True).count == 2
    assert replacement.generation.finalization_phase is FinalizationPhase.INGESTING

    _write(replacement, receipt_store, "guide.md")
    _write(replacement, receipt_store, "new-guide.md")
    replacement.publish_proof_transition()
    replacement.publish_generation()
    assert ledger.publication_proof(key).generation_id == replacement.generation_id
    assert receipt_store.count("served", exact=True).count == 2


@pytest.mark.parametrize("recovery", ["empty", "sealed"])
def test_rebuild_recovery_records_progress_only_after_durable_completion(
    tmp_path: Path, receipt_store: QdrantClient, recovery: str
) -> None:
    """Removing either progress record failed the count assertion; restoring passed."""
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
    if recovery == "sealed":
        _write(incremental, receipt_store, "new-guide.md")
        incremental.seal_incremental_proof()
    incremental.mark_failed("interrupted before receipt completion")
    run_policy = RunPolicy(no_progress_timeout_seconds=30)
    before = run_policy.snapshot()

    DocumentRunCheckpoint.start_compatible_generation(
        ledger, rebuilt.generation.signature, RunAuthority.REBUILD, run_policy
    )

    after = run_policy.snapshot()
    receipt = ledger.publication_receipt_for_generation(incremental.generation_id)
    assert receipt is not None
    assert receipt.state is (
        ProofReceiptState.COMMITTED
        if recovery == "sealed"
        else ProofReceiptState.ROLLED_BACK
    )
    assert after.durable_progress_count == before.durable_progress_count + 1
    assert after.last_durable_progress_at > before.last_durable_progress_at
    assert after.last_progress_kind is DurableProgressKind.FINALIZATION_PHASE_COMMITTED
    assert after.last_progress_label == (
        "publication proof recovery"
        if recovery == "sealed"
        else "publication receipt rollback recovery"
    )


@pytest.mark.parametrize(
    "recovery", ["absent", "unsealed", "not-ready", "rollback-refused"]
)
def test_rebuild_recovery_without_a_durable_commit_does_not_advance_progress(
    tmp_path: Path, receipt_store: QdrantClient, recovery: str
) -> None:
    """Early read or failed-commit pulses failed the count fence; restoring passed."""
    ledger, rebuilt = _published(tmp_path, receipt_store, populated=True)
    if recovery != "absent":
        incremental = _checkpoint(
            ledger,
            replace(
                rebuilt.generation.signature,
                operation=RunOperation.INCREMENTAL,
                clean=False,
            ),
            RunAuthority.PUBLICATION,
        )
        if recovery != "rollback-refused":
            _write(incremental, receipt_store, "new-guide.md")
        if recovery == "not-ready":
            incremental.seal_incremental_proof()
            with closing(sqlite3.connect(ledger.path)) as connection, connection:
                connection.execute(
                    "DELETE FROM file_states WHERE generation_id = ?",
                    (incremental.generation_id,),
                )
        elif recovery == "rollback-refused":
            with closing(sqlite3.connect(ledger.path)) as connection, connection:
                connection.execute(
                    """
                    CREATE TRIGGER refuse_receipt_rollback
                    BEFORE UPDATE OF state ON publication_receipts
                    WHEN NEW.state = 'rolled_back'
                    BEGIN
                        SELECT RAISE(ABORT, 'injected receipt rollback refusal');
                    END
                    """
                )
        incremental.mark_failed("unfinished receipt")
    run_policy = RunPolicy(no_progress_timeout_seconds=30)
    before = run_policy.snapshot()
    if recovery == "absent":
        DocumentRunCheckpoint.start_compatible_generation(
            ledger, rebuilt.generation.signature, RunAuthority.REBUILD, run_policy
        )
    else:
        refusal_type = (
            sqlite3.IntegrityError
            if recovery == "rollback-refused"
            else RunLedgerStateError
        )
        refusal = {
            "not-ready": "without matching indexed state",
            "unsealed": "exact recorded-unit recovery",
            "rollback-refused": "injected receipt rollback refusal",
        }[recovery]
        with pytest.raises(refusal_type, match=refusal):
            DocumentRunCheckpoint.start_compatible_generation(
                ledger, rebuilt.generation.signature, RunAuthority.REBUILD, run_policy
            )

    after = run_policy.snapshot()
    assert after.durable_progress_count == before.durable_progress_count
    assert after.last_durable_progress_at == before.last_durable_progress_at
    assert after.last_progress_kind is before.last_progress_kind
    assert after.last_progress_label == before.last_progress_label


@pytest.mark.parametrize("owner_state", ["invalidated", "exhausted"])
def test_explicit_recovery_commits_retired_receipt_without_reactivating_owner(
    tmp_path: Path, receipt_store: QdrantClient, owner_state: str
) -> None:
    ledger, rebuilt = _published(tmp_path, receipt_store, populated=True)
    signature = replace(
        rebuilt.generation.signature, operation=RunOperation.INCREMENTAL, clean=False
    )
    incremental = _checkpoint(ledger, signature, RunAuthority.PUBLICATION)
    _write(incremental, receipt_store, "new-guide.md")
    incremental.seal_incremental_proof()
    assert incremental.receipt is not None
    receipt_id = incremental.receipt.receipt_id
    if owner_state == "invalidated":
        incremental.mark_failed("failed incremental cleanup")
        attempted_full = ledger.start_generation(
            replace(
                rebuilt.generation.signature,
                configuration_fingerprint="previous-full-attempt",
            )
        )
        ledger.finish_generation(
            attempted_full.generation_id, RunTerminalState.REBUILD_INCOMPLETE
        )
    else:
        for attempt in range(MAX_RESUME_FAILURES):
            incremental.mark_failed("repeated failed cleanup")
            if attempt + 1 < MAX_RESUME_FAILURES:
                incremental = _checkpoint(ledger, signature, RunAuthority.PUBLICATION)
    before = ledger.generation(incremental.generation_id)

    proof = ledger.commit_publication_receipt(
        receipt_id,
        authority=RunAuthority.REBUILD,
        rebuild_signature=rebuilt.generation.signature,
    )

    assert ledger.generation(incremental.generation_id) == before
    assert proof.generation_id == incremental.generation_id
    assert proof.revision == 1
    replacement = _checkpoint(
        ledger, rebuilt.generation.signature, RunAuthority.REBUILD
    )
    assert replacement.generation_id != incremental.generation_id
    assert ledger.active_publication_receipt(proof.compatibility_key) is None
    if owner_state == "invalidated":
        assert ledger.generation(incremental.generation_id) == before
    assert receipt_store.count("served", exact=True).count == 2


@pytest.mark.parametrize(
    ("authority", "operation"),
    [
        (RunAuthority.PUBLICATION, RunOperation.FULL),
        (RunAuthority.AUDIT_VERIFICATION, RunOperation.FULL),
        (RunAuthority.REBUILD, RunOperation.INCREMENTAL),
        (RunAuthority.REBUILD, None),
    ],
)
def test_recovery_commit_requires_both_rebuild_authority_and_full_signature(
    tmp_path: Path, authority: RunAuthority, operation: RunOperation | None
) -> None:
    """Mutation: removing authority/signature admission changes this exact refusal."""
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    signature = (
        None
        if operation is None
        else replace(_signature(tmp_path), operation=operation)
    )
    with pytest.raises(PermissionError, match="receipt recovery requires"):
        ledger.commit_publication_receipt(
            "unknown-receipt", authority=authority, rebuild_signature=signature
        )


@pytest.mark.parametrize("foreign", ["source", "root", "backend", "collection"])
def test_recovery_commit_refuses_a_foreign_full_rebuild_projection(
    tmp_path: Path, receipt_store: QdrantClient, foreign: str
) -> None:
    """Mutation: replacing one request field with the receipt identity admits it."""
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
    incremental.mark_failed("interrupted after sealing")
    signatures = {
        "source": replace(
            rebuilt.generation.signature, source_type=PublicSourceType.CODE
        ),
        "root": replace(
            rebuilt.generation.signature, root_identity=str(tmp_path / "foreign")
        ),
        "backend": replace(
            rebuilt.generation.signature, backend_identity="foreign-backend"
        ),
        "collection": replace(
            rebuilt.generation.signature, collection_identity="foreign-collection"
        ),
    }
    assert incremental.receipt is not None
    owner = ledger.generation(incremental.generation_id)
    before = ledger.active_publication_receipt(incremental.receipt.compatibility_key)

    with pytest.raises(PermissionError, match="exact full rebuild projection"):
        ledger.commit_publication_receipt(
            incremental.receipt.receipt_id,
            authority=RunAuthority.REBUILD,
            rebuild_signature=signatures[foreign],
        )

    assert ledger.generation(incremental.generation_id) == owner
    assert (
        ledger.active_publication_receipt(incremental.receipt.compatibility_key)
        == before
    )
    assert receipt_store.count("served", exact=True).count == 2


def test_recovery_commit_refuses_confirmed_units_without_matching_file_state(
    tmp_path: Path, receipt_store: QdrantClient
) -> None:
    """Mutation: dropping recovery readiness admits an incomplete manifest."""
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
    incremental.mark_failed("interrupted after sealing")
    assert incremental.receipt is not None
    with closing(sqlite3.connect(ledger.path)) as connection, connection:
        connection.execute(
            "DELETE FROM file_states WHERE generation_id = ?",
            (incremental.generation_id,),
        )

    with pytest.raises(RunLedgerStateError, match="without matching indexed state"):
        ledger.commit_publication_receipt(
            incremental.receipt.receipt_id,
            authority=RunAuthority.REBUILD,
            rebuild_signature=rebuilt.generation.signature,
        )

    receipt = ledger.active_publication_receipt(incremental.receipt.compatibility_key)
    assert receipt is not None and receipt.state is ProofReceiptState.SEALED
    assert ledger.publication_proof(receipt.compatibility_key).revision == 0


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


@pytest.mark.parametrize("mutation_state", ["prepared", "confirmed"])
def test_rebuild_refuses_unsealed_mutations_and_preserves_served_state(
    tmp_path: Path, receipt_store: QdrantClient, mutation_state: str
) -> None:
    """Mutation: allowing a nonempty RESERVED receipt to recover loses this fence."""
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
    assert incremental.receipt is not None
    unit = CommitUnit(
        rel_path="pending.md",
        kind=CommitUnitKind.UPSERT,
        source_digest=ledger_test_digest("pending"),
        segment_ordinal=0,
        is_file_end=True,
        point_ids=("pending-point",),
    )
    if mutation_state == "confirmed":
        _write(incremental, receipt_store, unit.rel_path)
    else:
        ledger.prepare_publication_mutation(incremental.receipt.receipt_id, unit)
    incremental.mark_failed("interrupted before sealing")
    key = compatibility_for_signature(incremental.generation.signature)
    before = ledger.active_publication_receipt(key)
    proof = ledger.publication_proof(key)

    with pytest.raises(RunLedgerStateError, match="exact recorded-unit recovery"):
        _checkpoint(ledger, rebuilt.generation.signature, RunAuthority.REBUILD)

    assert ledger.active_publication_receipt(key) == before
    assert ledger.publication_proof(key) == proof
    assert (
        ledger.generation(incremental.generation_id).terminal_state
        is RunTerminalState.FAILED
    )
    assert receipt_store.count("served", exact=True).count == (
        2 if mutation_state == "confirmed" else 1
    )


def test_rebuild_recovery_does_not_touch_foreign_source_root_or_backend(
    tmp_path: Path, receipt_store: QdrantClient
) -> None:
    """Mutation: dropping any stable identity predicate makes a foreign case red."""
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
    assert incremental.receipt is not None
    key = compatibility_for_signature(incremental.generation.signature)
    original = ledger.active_publication_receipt(key)
    signatures = (
        replace(rebuilt.generation.signature, source_type=PublicSourceType.CODE),
        replace(
            rebuilt.generation.signature, root_identity=str(tmp_path / "foreign-root")
        ),
        replace(rebuilt.generation.signature, backend_identity="foreign-backend"),
        replace(rebuilt.generation.signature, collection_identity="foreign-collection"),
    )
    for signature in signatures:
        assert ledger.rebuild_recovery_receipt(signature, RunAuthority.REBUILD) is None
        assert ledger.active_publication_receipt(key) == original


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


def test_rebuild_refuses_empty_receipt_with_unjournaled_committed_units(
    tmp_path: Path,
) -> None:
    """Rebuild cannot abandon units absent from an unfinished receipt's journal.

    Guard evidence: without the committed-unit fence this failed with DID NOT
    RAISE; adding the fence passed the same test.
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
    key = incremental.receipt.compatibility_key
    proof = ledger.publication_proof(key)
    receipt = ledger.active_publication_receipt(key)

    with pytest.raises(RunLedgerStateError, match="exact recorded-unit recovery"):
        _checkpoint(ledger, rebuilt.generation.signature, RunAuthority.REBUILD)

    assert ledger.active_publication_receipt(key) == receipt
    assert ledger.publication_proof(key) == proof
