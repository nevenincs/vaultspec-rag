"""Vault publication uses the same durable receipt/proof protocol as other sources."""

import hashlib
from pathlib import Path

import pytest

from .._store_models import VaultChunk
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
