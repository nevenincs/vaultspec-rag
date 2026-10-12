"""Vault publication uses the same durable receipt/proof protocol as other sources."""

import hashlib
from pathlib import Path

import pytest

from .._job_errors import JobError, JobErrorKind
from .._store_models import VaultChunk
from ..indexer import _vault_checkpoint
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
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


@pytest.mark.parametrize("source_changed", [False, True])
def test_vault_pending_chunks_reuses_only_exact_confirmed_evidence(
    tmp_path: Path, source_changed: bool
) -> None:
    """Exact evidence skips confirmed chunks; changed bytes retain new units.

    Returning every chunk failed the pending-list assertion; restoring passed.
    """
    checkpoint = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity="backend-v1",
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    chunks = [_chunk("docs/a", 0, 2), _chunk("docs/a", 1, 2)]
    digest = hashlib.blake2b(b"original").hexdigest()
    checkpoint.record_confirmed_chunks(chunks[:1], {"docs/a": digest})
    current_digest = (
        hashlib.blake2b(b"changed").hexdigest() if source_changed else digest
    )
    pending = checkpoint.pending_chunks(chunks, {"docs/a": current_digest})
    assert pending == (chunks if source_changed else chunks[1:])


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
    # Only an older build writes an older-schema proof; lowering the constant
    # for this one rebuild lets the real ledger record it and then refuse it.
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


@pytest.mark.parametrize(
    "boundary", ["before_delete", "after_delete", "after_retirement"]
)
def test_resumed_vault_reset_survives_source_revert_and_provisional_points(
    tmp_path: Path, clean_config: None, boundary: str
) -> None:
    """Durable intent prevents old-digest skips after any interrupted reset.

    Removing marker insertion failed the replay-count assertion; restoring passed.
    """
    from ..config._settings import get_config
    from ..store_runtime import VaultStore

    del clean_config
    get_config({"embedding_dimension": 2, "qdrant_url": None, "sparse_enabled": False})
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = VaultRunCheckpoint.open(
            tmp_path,
            backend_identity=store.backend_identity,
            authority=RunAuthority.REBUILD,
            operation=RunOperation.FULL,
            run_control=NO_RUN_CONTROL,
        )
        original = hashlib.blake2b(b"original").hexdigest()
        sibling = _chunk("docs/sibling", 0, 1)
        old = _chunk("docs/changed", 0, 2)
        provisional = _chunk("docs/changed", 5, 6)
        for chunk in (old, sibling, provisional):
            chunk.vector = [1.0, 0.0]
        store.upsert_document_chunks([old, sibling, provisional], write_policy=None)
        identities = {"docs/changed": original, "docs/sibling": original}
        checkpoint.record_confirmed_chunks([old, sibling], identities)
        checkpoint.ledger.begin_generation_storage_reset(
            checkpoint.generation_id, (old.doc_id,)
        )
        if boundary != "before_delete":
            store.delete_documents([old.doc_id])
        if boundary == "after_retirement":
            checkpoint.ledger.reopen_drifted_path(
                checkpoint.generation_id, old.doc_id, superseded_digest=original
            )
        assert checkpoint.reconcile_resumed_paths(store, identities) == 1
        assert store.get_chunk_counts() == {sibling.doc_id: 1}
        assert list(checkpoint.ledger.iter_units(checkpoint.generation_id)) == list(
            checkpoint.units_for_chunks([sibling], identities)
        )
        assert (
            checkpoint.ledger.generation_storage_reset_paths(checkpoint.generation_id)
            == ()
        )
        assert checkpoint.pending_chunks([old, sibling], identities) == [old]


@pytest.mark.parametrize("removed", [False, True])
def test_resumed_vault_retires_changed_or_removed_partial_file(
    tmp_path: Path, clean_config: None, removed: bool
) -> None:
    """Ignoring changed digests failed the retirement assertion; restoring passed."""
    from ..config._settings import get_config
    from ..store_runtime import VaultStore

    del clean_config
    get_config({"embedding_dimension": 2, "qdrant_url": None, "sparse_enabled": False})
    with VaultStore(tmp_path, embedding_dim=2) as store:
        checkpoint = VaultRunCheckpoint.open(
            tmp_path,
            backend_identity=store.backend_identity,
            authority=RunAuthority.REBUILD,
            operation=RunOperation.FULL,
            run_control=NO_RUN_CONTROL,
        )
        old = _chunk("docs/changed", 0, 2)
        old.vector = [1.0, 0.0]
        store.upsert_document_chunks([old], write_policy=None)
        checkpoint.record_confirmed_chunks(
            [old], {old.doc_id: hashlib.blake2b(b"old").hexdigest()}
        )
        current = {} if removed else {old.doc_id: hashlib.blake2b(b"new").hexdigest()}
        assert checkpoint.reconcile_resumed_paths(store, current) == 1
        assert store.count() == 0
        assert not list(checkpoint.ledger.iter_units(checkpoint.generation_id))
