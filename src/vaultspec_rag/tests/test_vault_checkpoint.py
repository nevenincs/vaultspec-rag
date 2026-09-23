"""Vault publication uses the same durable receipt/proof protocol as other sources."""

import hashlib
from pathlib import Path

import pytest

from .._job_errors import JobError, JobErrorKind
from .._store_models import VaultChunk
from ..indexer import _vault_checkpoint
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..indexer._run_ledger_publication import compatibility_for_signature
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..job_control import NO_RUN_CONTROL

pytestmark = pytest.mark.unit


def _chunk(doc_id: str, ordinal: int, count: int) -> VaultChunk:
    return VaultChunk(
        doc_id=doc_id,
        ordinal=ordinal,
        chunk_count=count,
        text=f"chunk {ordinal}",
        path=f"{doc_id}.md",
        doc_type="feature",
        feature="",
        date="",
        tags=[],
        related=[],
        title=doc_id,
    )


def test_vault_rebuild_establishes_proof_from_confirmed_chunk_units(
    tmp_path: Path,
) -> None:
    checkpoint = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    chunks = [_chunk("docs/a", 0, 2), _chunk("docs/a", 1, 2)]
    digest = hashlib.blake2b(b"docs/a").hexdigest()
    checkpoint.record_confirmed_chunks(chunks, {"docs/a": digest})

    assert checkpoint.publish_proof_transition() == 1
    proof = checkpoint.ledger.publication_proof(
        compatibility_for_signature(checkpoint.generation.signature)
    )
    assert proof.aggregate.indexed_identities == 1
    assert proof.aggregate.retained_points == 2
    checkpoint.publish_generation()


def test_an_incremental_run_without_a_compatible_proof_asks_for_a_rebuild(
    tmp_path: Path,
) -> None:
    with pytest.raises(JobError) as refused:
        VaultRunCheckpoint.open(
            tmp_path,
            backend_identity="backend-v1",
            authority=RunAuthority.PUBLICATION,
            operation=RunOperation.INCREMENTAL,
            run_control=NO_RUN_CONTROL,
        )
    assert refused.value.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED
    assert "vaultspec-rag index --rebuild --type vault" in str(refused.value)


def test_a_proof_from_an_older_point_schema_asks_for_a_rebuild(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An index built before the current chunk payload shape is not carried on."""
    monkeypatch.setattr(
        _vault_checkpoint,
        "VAULT_POINT_SCHEMA",
        _vault_checkpoint.VAULT_POINT_SCHEMA - 1,
    )
    older = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    older.record_confirmed_chunks(
        [_chunk("docs/a", 0, 1)], {"docs/a": hashlib.blake2b(b"docs/a").hexdigest()}
    )
    assert older.publish_proof_transition() == 1
    older.publish_generation()
    monkeypatch.undo()

    with pytest.raises(JobError) as refused:
        VaultRunCheckpoint.open(
            tmp_path,
            backend_identity="backend-v1",
            authority=RunAuthority.PUBLICATION,
            operation=RunOperation.INCREMENTAL,
            run_control=NO_RUN_CONTROL,
        )
    assert refused.value.error_kind is JobErrorKind.FULL_REINDEX_REQUIRED


def test_vault_rebuild_accepts_length_sorted_chunk_batches(tmp_path: Path) -> None:
    """Confirm storage order while publishing canonical lexical point order.

    Mutation proof: removing ``sorted`` from ``_verified_evidence`` makes
    ``publish_proof_transition`` fail with the canonical-ordering assertion.
    """
    checkpoint = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    digest = hashlib.blake2b(b"docs/a").hexdigest()
    chunks = [_chunk("docs/a", ordinal, 12) for ordinal in range(12)]

    checkpoint.record_confirmed_chunks(chunks[10:], {"docs/a": digest})
    checkpoint.record_confirmed_chunks(chunks[:10], {"docs/a": digest})

    assert checkpoint.publish_proof_transition() == 1
    key = compatibility_for_signature(checkpoint.generation.signature)
    proof = checkpoint.ledger.publication_proof(key)
    assert proof.aggregate.indexed_identities == 1
    assert proof.aggregate.retained_points == 12
    evidence = checkpoint.ledger.publication_evidence_for_paths(key, ("docs/a",))
    assert evidence["docs/a"].point_ids == tuple(
        sorted(chunk.point_key for chunk in chunks)
    )
