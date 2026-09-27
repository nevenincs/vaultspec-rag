"""Run-ledger publication models behavior."""

from __future__ import annotations

import json
from dataclasses import MISSING, replace
from pathlib import Path

import pytest

from .._source_types import PublicSourceType
from ..indexer._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofAggregate,
    ProofEvidence,
    ProofMissingError,
    ProofMutationState,
    ProofProvenance,
    ProofReceiptState,
)
from ..indexer._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    PublicationMutationUnit,
    PublicationProof,
    PublicationReceipt,
    RunAuthority,
    RunOperation,
    RunSignature,
    RunTerminalState,
)
from ..indexer._run_ledger_runtime import RunLedger, _signature_from_payload
from ._run_ledger_test_support import (
    ledger_test_digest,
    ledger_test_proof_compatibility,
    ledger_test_signature,
    ledger_test_unit,
)

pytestmark = [pytest.mark.unit]


def test_verified_proof_parents_incremental_without_copying_manifest_rows(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    full = ledger.start_generation(replace(ledger_test_signature(tmp_path), clean=True))
    evidence = (
        ProofEvidence("src/a.py", ledger_test_digest("a"), ("a:0",)),
        ProofEvidence("src/b.py", ledger_test_digest("b"), ("b:0", "b:1")),
    )

    proof = ledger.establish_verified_publication(
        full.generation_id,
        RunAuthority.REBUILD,
        evidence,
    )
    assert proof.aggregate == ProofAggregate(indexed_identities=2, retained_points=3)
    assert ledger.publication_evidence_page(proof.compatibility_key, limit=1) == {
        "src/a.py": evidence[0]
    }

    incremental = ledger.start_generation(
        replace(
            full.signature,
            operation=RunOperation.INCREMENTAL,
            clean=False,
            configuration_fingerprint="configuration-v2",
        )
    )
    assert incremental.parent_generation_id == full.generation_id
    assert list(ledger.iter_file_states(incremental.generation_id)) == []
    assert list(ledger.iter_units(incremental.generation_id)) == []


def test_clearing_publication_invalidates_proof_before_storage_removal(
    tmp_path: Path,
) -> None:
    ledger = RunLedger(tmp_path / "runs.sqlite3")
    generation = ledger.start_generation(
        replace(ledger_test_signature(tmp_path), clean=True)
    )
    proof = ledger.establish_verified_publication(
        generation.generation_id,
        RunAuthority.REBUILD,
        (ProofEvidence("src/a.py", ledger_test_digest("a"), ("a:0",)),),
    )

    ledger.clear_publication_source(
        PublicSourceType.CODE,
        str(tmp_path.resolve()),
        "backend-v1",
    )

    with pytest.raises(ProofMissingError):
        ledger.publication_proof(proof.compatibility_key)
    assert ledger.generation(generation.generation_id).terminal_state is (
        RunTerminalState.REBUILD_INCOMPLETE
    )


def test_run_authority_has_exact_persisted_vocabulary() -> None:
    """Guard: authority cannot be inferred from run mode or widened for migration."""
    assert [
        (name, member.value) for name, member in RunAuthority.__members__.items()
    ] == [
        ("PUBLICATION", "publication"),
        ("REBUILD", "rebuild"),
        ("AUDIT_VERIFICATION", "audit_verification"),
    ]
    assert {authority.value for authority in RunAuthority}.isdisjoint(
        operation.value for operation in RunOperation
    )

    for authority in RunAuthority:
        encoded = json.dumps({"authority": authority}, sort_keys=True)
        assert json.loads(encoded) == {"authority": authority.value}

    for forbidden in ("migration", "recovery", "full", "exact_verification"):
        with pytest.raises(ValueError):
            RunAuthority(forbidden)


def test_run_signature_and_decoder_require_backend_identity() -> None:
    """Mutation: a default or missing-field fallback reopens old signatures."""
    backend_field = RunSignature.__dataclass_fields__["backend_identity"]
    assert backend_field.default is MISSING

    payload = json.loads(ledger_test_signature(Path(".")).canonical_json)
    del payload["backend_identity"]
    with pytest.raises(TypeError, match="backend_identity"):
        _signature_from_payload(payload)


def test_publication_generation_is_provenance_not_compatibility() -> None:
    key = ledger_test_proof_compatibility()
    first = PublicationProof(
        revision=3,
        reservation_sequence=7,
        compatibility_key=key,
        generation_id="generation-a",
        aggregate=ProofAggregate(indexed_identities=1, retained_points=2),
        provenance=ProofProvenance.DELTA_DERIVED,
        committed_at=2.0,
    )
    second = replace(first, generation_id="generation-b", committed_at=3.0)

    assert first.compatibility_key == second.compatibility_key
    assert first.generation_id != second.generation_id
    assert not hasattr(key, "generation_id")


def test_streaming_mutations_advance_independently_before_receipt_sealing() -> None:
    prepared = PublicationMutationUnit(
        ordinal=0,
        unit=ledger_test_unit("src/item.py", 0, 1),
        state=ProofMutationState.PREPARED,
        prepared_at=1.0,
    )
    applied = replace(
        prepared,
        state=ProofMutationState.APPLIED,
        applied_at=2.0,
    )
    confirmed = replace(
        applied,
        state=ProofMutationState.CONFIRMED,
        confirmed_at=3.0,
    )

    assert prepared.identity == applied.identity == confirmed.identity
    with pytest.raises(ValueError, match="timestamps must match"):
        replace(prepared, state=ProofMutationState.CONFIRMED, confirmed_at=3.0)
    with pytest.raises(ValueError, match="monotonic"):
        replace(applied, applied_at=0.5)


def test_receipt_rejects_ambiguous_point_ownership_across_paths() -> None:
    """Mutation proving this can fail: omit receipt-wide point ownership checks."""
    shared_a = ProofEvidence(
        rel_path="src/a.py",
        content_identity=ledger_test_digest("content-a"),
        point_ids=("shared-point",),
    )
    shared_b = ProofEvidence(
        rel_path="src/b.py",
        content_identity=ledger_test_digest("content-b"),
        point_ids=("shared-point",),
    )

    def ledger_test_unit(kind: CommitUnitKind, evidence: ProofEvidence) -> CommitUnit:
        return CommitUnit(
            rel_path=evidence.rel_path,
            kind=kind,
            source_digest=(
                evidence.content_identity if kind is CommitUnitKind.UPSERT else None
            ),
            segment_ordinal=0,
            is_file_end=True,
            point_ids=evidence.point_ids,
        )

    def seal(
        deltas: tuple[PathDelta, ...], units: tuple[CommitUnit, ...]
    ) -> PublicationReceipt:
        prepared = tuple(
            PublicationMutationUnit(
                ordinal=ordinal,
                unit=value,
                state=ProofMutationState.PREPARED,
                prepared_at=1.5,
            )
            for ordinal, value in enumerate(units)
        )
        sealed_order = {
            mutation.identity: ordinal
            for ordinal, mutation in enumerate(
                sorted(prepared, key=lambda mutation: mutation.identity)
            )
        }
        mutations = tuple(
            replace(
                mutation,
                sealed_ordinal=sealed_order[mutation.identity],
            )
            for mutation in prepared
        )
        return PublicationReceipt(
            receipt_id="receipt-overlap",
            reservation_sequence=9,
            compatibility_key=ledger_test_proof_compatibility(),
            generation_id="generation-v2",
            parent_revision=3,
            target_revision=4,
            state=ProofReceiptState.SEALED,
            reserved_at=1.0,
            mutations=mutations,
            deltas=deltas,
            sealed_at=2.0,
        )

    add_a = PathDelta(
        outcome=PathOutcome.ADD,
        expected_parent_revision=3,
        rel_path=shared_a.rel_path,
        new=shared_a,
    )
    add_b = PathDelta(
        outcome=PathOutcome.ADD,
        expected_parent_revision=3,
        rel_path=shared_b.rel_path,
        new=shared_b,
    )
    delete_a = PathDelta(
        outcome=PathOutcome.DELETE,
        expected_parent_revision=3,
        rel_path=shared_a.rel_path,
        old=shared_a,
    )
    delete_b = PathDelta(
        outcome=PathOutcome.DELETE,
        expected_parent_revision=3,
        rel_path=shared_b.rel_path,
        old=shared_b,
    )
    with pytest.raises(ValueError, match="multiple proof paths"):
        seal(
            (add_a, add_b),
            (
                ledger_test_unit(CommitUnitKind.UPSERT, shared_a),
                ledger_test_unit(CommitUnitKind.UPSERT, shared_b),
            ),
        )
    with pytest.raises(ValueError, match="multiple proof paths"):
        seal(
            (delete_a, delete_b),
            (
                ledger_test_unit(CommitUnitKind.DELETE_PATH, shared_a),
                ledger_test_unit(CommitUnitKind.DELETE_PATH, shared_b),
            ),
        )
    with pytest.raises(ValueError, match="transfer point identity"):
        seal(
            (delete_a, add_b),
            (
                ledger_test_unit(CommitUnitKind.DELETE_PATH, shared_a),
                ledger_test_unit(CommitUnitKind.UPSERT, shared_b),
            ),
        )
