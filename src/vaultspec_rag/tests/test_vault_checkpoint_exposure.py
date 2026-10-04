"""Real vault runs report their actual attempt checkpoint without loading a model.

Mutation evidence: removing the initial attempt observation failed the exact
checkpoint-count assertion; restoring it passed the same test.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import pytest

from ..config._settings import get_config
from ..config._types import EnvVar
from ..indexer._checkpoint_common import RunCheckpointBase, observe_checkpoint_progress
from ..indexer._run_ledger_models import RunAuthority, RunOperation, RunTerminalState
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
from ..indexer._vault_checkpoint import VaultRunCheckpoint
from ..indexer._vault_fingerprint import fingerprint_path
from ..indexer._vault_indexer import VaultIndexer
from ..indexer._vault_prep import prepare_document, split_document
from ..job_control import NO_RUN_CONTROL
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from ._config_fixtures import reset_config

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._run_policy import RunPolicySnapshot

pytestmark = pytest.mark.unit


class _UnusedEmbeddingModel:
    """Only the result's device label is needed; every tested run avoids encoding."""

    device = "cpu"


@pytest.fixture
def vault_checkpoint_store(tmp_path: Path) -> Generator[VaultStore]:
    overrides = {
        EnvVar.QDRANT_URL.value: "",
        EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "managed-storage"),
        EnvVar.EMBEDDING_DIMENSION.value: "8",
        EnvVar.SPARSE_ENABLED.value: "false",
    }
    prior = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    reset_config()
    try:
        store = VaultStore(tmp_path, embedding_dim=8)
        try:
            yield store
        finally:
            store.close()
    finally:
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


def _indexer(root: Path, store: VaultStore) -> VaultIndexer:
    return VaultIndexer(root, cast("EmbeddingModel", _UnusedEmbeddingModel()), store)


@pytest.fixture
def observed_vault_checkpoints() -> Generator[list[VaultRunCheckpoint]]:
    checkpoints: list[VaultRunCheckpoint] = []

    def observe(
        checkpoint: RunCheckpointBase, snapshot: RunPolicySnapshot | None
    ) -> None:
        assert isinstance(checkpoint, VaultRunCheckpoint)
        if snapshot is None:
            checkpoints.append(checkpoint)

    with observe_checkpoint_progress(observe):
        yield checkpoints


def test_empty_full_vault_run_exposes_its_real_published_checkpoint(
    tmp_path: Path,
    vault_checkpoint_store: VaultStore,
    observed_vault_checkpoints: list[VaultRunCheckpoint],
) -> None:
    indexer = _indexer(tmp_path, vault_checkpoint_store)
    assert observed_vault_checkpoints == []

    result = indexer.full_index(reporter=NullProgressReporter())

    assert len(observed_vault_checkpoints) == 1
    checkpoint = observed_vault_checkpoints[-1]
    assert isinstance(checkpoint, VaultRunCheckpoint)
    assert checkpoint.generation.signature.operation is RunOperation.FULL
    assert checkpoint.generation.terminal_state is RunTerminalState.SUCCEEDED
    assert (
        checkpoint.ledger.generation(checkpoint.generation_id) == checkpoint.generation
    )
    proof = checkpoint.ledger.publication_proof(
        compatibility_for_signature(checkpoint.generation.signature)
    )
    assert proof.generation_id == checkpoint.generation_id
    assert proof.aggregate.indexed_identities == result.total == 0


@pytest.mark.parametrize("scoped", [False, True])
def test_empty_incremental_vault_run_exposes_the_new_receipt_owner(
    tmp_path: Path,
    vault_checkpoint_store: VaultStore,
    observed_vault_checkpoints: list[VaultRunCheckpoint],
    scoped: bool,
) -> None:
    indexer = _indexer(tmp_path, vault_checkpoint_store)
    indexer.full_index(reporter=NullProgressReporter())
    assert len(observed_vault_checkpoints) == 1
    parent = observed_vault_checkpoints[-1]

    indexer.incremental_index(
        reporter=NullProgressReporter(), changed_paths=[] if scoped else None
    )

    assert len(observed_vault_checkpoints) == 2
    checkpoint = observed_vault_checkpoints[-1]
    assert isinstance(checkpoint, VaultRunCheckpoint)
    assert checkpoint.generation_id != parent.generation_id
    assert checkpoint.generation.signature.operation is (
        RunOperation.SCOPED_INCREMENTAL if scoped else RunOperation.INCREMENTAL
    )
    assert checkpoint.generation.terminal_state is RunTerminalState.SUCCEEDED
    assert (
        checkpoint.ledger.generation(checkpoint.generation_id) == checkpoint.generation
    )
    assert checkpoint.receipt is not None
    assert checkpoint.receipt.generation_id == checkpoint.generation_id


def test_payload_only_vault_run_exposes_the_committed_receipt_generation(
    tmp_path: Path,
    vault_checkpoint_store: VaultStore,
    observed_vault_checkpoints: list[VaultRunCheckpoint],
) -> None:
    path = tmp_path / ".vault" / "adr" / "2026-01-01-checkpoint-adr.md"
    path.parent.mkdir(parents=True)
    text = (
        "---\ntags:\n  - '#adr'\n  - '#checkpoint'\n"
        "date: '2026-01-01'\n---\n# Checkpoint\n\nBody.\n"
    )
    path.write_text(text, encoding="utf-8", newline="")
    doc = prepare_document(path, tmp_path)
    assert doc is not None
    chunks = split_document(doc, int(get_config().vault_chunk_chars))
    for chunk in chunks:
        chunk.vector = [0.5] * 8
    vault_checkpoint_store.upsert_document_chunks(chunks, write_policy=None)
    parent = VaultRunCheckpoint.open(
        tmp_path,
        backend_identity=vault_checkpoint_store.backend_identity,
        authority=RunAuthority.REBUILD,
        operation=RunOperation.FULL,
        run_control=NO_RUN_CONTROL,
    )
    parent.record_confirmed_chunks(chunks, {doc.id: fingerprint_path(path, tmp_path)})
    parent.publish_proof_transition()
    parent.publish_generation()
    path.write_text(
        text.replace("  - '#checkpoint'", "  - '#checkpoint'\n  - '#updated'"),
        encoding="utf-8",
        newline="",
    )
    indexer = _indexer(tmp_path, vault_checkpoint_store)

    result = indexer.incremental_index(reporter=NullProgressReporter())

    assert result.payload_updated == 1
    assert len(observed_vault_checkpoints) == 2
    checkpoint = observed_vault_checkpoints[-1]
    assert isinstance(checkpoint, VaultRunCheckpoint)
    assert checkpoint.generation_id != parent.generation_id
    assert checkpoint.generation.terminal_state is RunTerminalState.SUCCEEDED
    assert (
        checkpoint.ledger.generation(checkpoint.generation_id) == checkpoint.generation
    )
    proof = checkpoint.ledger.publication_proof(
        compatibility_for_signature(checkpoint.generation.signature)
    )
    assert proof.generation_id == checkpoint.generation_id
    assert proof.revision == 1
    assert vault_checkpoint_store.count() == 1
