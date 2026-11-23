"""Real model-free code publication resumes exact committed storage work."""

from __future__ import annotations

import os
from dataclasses import replace
from typing import TYPE_CHECKING
from uuid import NAMESPACE_URL, uuid5

import pytest

from .. import store_schema
from .._store_models import (
    CodeChunk,
    resolve_served_code_collection,
)
from ..config._types import EnvVar
from ..indexer._checkpoint_common import classify_interrupted_generation
from ..indexer._content_policy import RootContentPolicy, SourceProfileVersion
from ..indexer._generation_lifecycle import (
    CodeGenerationBindings,
    CodeGenerationLifecycle,
)
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    resolve_index_policy,
)
from ..indexer._run_checkpoint import CodeRunCheckpoint
from ..indexer._run_ledger_models import FinalizationPhase, RunAuthority, RunOperation
from ..indexer._run_ledger_runtime import RunLedger
from ..indexer._run_policy import RunPolicy
from ..indexer._streaming_types import CodeFileSegment
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from ._config_fixtures import reset_config
from ._ledger_fixtures import continue_rebuild
from ._run_ledger_test_support import ledger_test_digest, ledger_test_signature

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..indexer._run_ledger_models import RunSignature

pytestmark = pytest.mark.unit


@pytest.fixture
def recovery_code_store(tmp_path: Path) -> Generator[VaultStore]:
    prior_url = os.environ.get(EnvVar.QDRANT_URL.value)
    prior_storage = os.environ.get(EnvVar.QDRANT_STORAGE_DIR.value)
    os.environ[EnvVar.QDRANT_URL.value] = ""
    os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(tmp_path / "managed-storage")
    reset_config()
    try:
        store = VaultStore(tmp_path, embedding_dim=8)
        try:
            yield store
        finally:
            store.close()
    finally:
        if prior_url is None:
            os.environ.pop(EnvVar.QDRANT_URL.value, None)
        else:
            os.environ[EnvVar.QDRANT_URL.value] = prior_url
        if prior_storage is None:
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR.value, None)
        else:
            os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = prior_storage
        reset_config()


def _checkpoint(
    ledger: RunLedger, signature: RunSignature, authority: RunAuthority
) -> CodeRunCheckpoint:
    run_policy = RunPolicy(no_progress_timeout_seconds=60)
    generation = CodeRunCheckpoint.start_compatible_generation(
        ledger, signature, authority
    )
    receipt = CodeRunCheckpoint.open_publication_receipt(ledger, generation, authority)
    return CodeRunCheckpoint(
        ledger,
        generation,
        resolve_index_policy(
            ledger.path.parent,
            IndexPolicyResolutionOptions(
                content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
            ),
        ),
        run_policy,
        authority,
        receipt,
    )


def _write(
    checkpoint: CodeRunCheckpoint,
    store: VaultStore,
    path: str,
) -> None:
    content = "value = 1\n"
    (store.root_dir / path).write_text(content, encoding="utf-8")
    chunk = CodeChunk(
        id=str(uuid5(NAMESPACE_URL, path)),
        path=path,
        language="python",
        content=content,
        line_start=1,
        line_end=1,
        vector=[0.5] * 8,
    )
    segment = CodeFileSegment(path, 0, (chunk,), 8, True)
    digest = ledger_test_digest(content)
    lifecycle = checkpoint.mutation_lifecycle(checkpoint.unit_for(segment, digest))
    if lifecycle is not None:
        assert lifecycle.prepare()
    store.upsert_code_chunks([chunk], write_policy=None)
    if lifecycle is not None:
        lifecycle.mark_applied()
        lifecycle.confirm()
    checkpoint.record_confirmed_segments((segment,), {path: digest})


def _published(root: Path, store: VaultStore) -> tuple[RunLedger, CodeRunCheckpoint]:
    ledger = RunLedger(root / "runs.sqlite3")
    signature = replace(
        ledger_test_signature(root),
        collection_identity=store_schema.CODE_COLLECTION,
        backend_identity=store.backend_identity,
    )
    checkpoint = _checkpoint(ledger, signature, RunAuthority.REBUILD)
    _write(checkpoint, store, "original.py")
    checkpoint.publish_proof_transition()
    checkpoint.publish_generation()
    return ledger, checkpoint


@pytest.mark.parametrize("metadata_published", [False, True])
def test_code_lifecycle_resumes_after_exact_receipt_commit(
    tmp_path: Path, recovery_code_store: VaultStore, metadata_published: bool
) -> None:
    ledger, parent = _published(tmp_path, recovery_code_store)
    signature = replace(parent.generation.signature, operation=RunOperation.INCREMENTAL)
    checkpoint = _checkpoint(ledger, signature, RunAuthority.PUBLICATION)
    _write(checkpoint, recovery_code_store, "added.py")
    checkpoint.seal_incremental_proof()
    checkpoint.generation = ledger.advance_finalization(
        checkpoint.generation_id, FinalizationPhase.STALE_RECONCILED
    )
    assert checkpoint.receipt is not None
    proof = ledger.commit_publication_receipt(checkpoint.receipt.receipt_id)
    if metadata_published:
        checkpoint.generation = ledger.advance_finalization(
            checkpoint.generation_id, FinalizationPhase.METADATA_PUBLISHED
        )
    classify_interrupted_generation(
        ledger, checkpoint.generation, RuntimeError("interrupted after commit")
    )
    resumed = _checkpoint(ledger, signature, RunAuthority.PUBLICATION)
    lifecycle = CodeGenerationLifecycle(
        CodeGenerationBindings(tmp_path, ledger.path.parent, recovery_code_store)
    )

    assert lifecycle.publish_pending_finalization(
        resumed, reporter=NullProgressReporter()
    )

    assert ledger.publication_proof(proof.compatibility_key) == proof
    assert recovery_code_store.count_code() == 2


def test_code_rebuild_resumes_publication_after_proof_commit(
    tmp_path: Path, recovery_code_store: VaultStore
) -> None:
    """A rebuild interrupted after its proof commit finishes in place.

    The rebuild reset its source under its own generation before writing, so
    the resumed attempt keeps that work and certifies the same collection.
    """
    from .._source_types import PublicSourceType
    from ..indexer._run_ledger_models import SourceResetPhase

    ledger, parent = _published(tmp_path, recovery_code_store)
    signature = replace(parent.generation.signature, clean=True)
    checkpoint = _checkpoint(ledger, signature, RunAuthority.REBUILD)
    reset = ledger.begin_source_reset(
        PublicSourceType.CODE,
        signature.root_identity,
        signature.backend_identity,
        checkpoint.generation_id,
    )
    recovery_code_store.discard_source_storage(PublicSourceType.CODE)
    reset = ledger.advance_source_reset(reset, SourceResetPhase.DISCARDED)
    recovery_code_store.recreate_empty_source(PublicSourceType.CODE)
    ledger.advance_source_reset(reset, SourceResetPhase.COMPLETE)
    _write(checkpoint, recovery_code_store, "replacement.py")
    checkpoint.publish_proof_transition()
    classify_interrupted_generation(
        ledger, checkpoint.generation, RuntimeError("interrupted after proof")
    )
    with continue_rebuild(checkpoint.generation_id):
        resumed = _checkpoint(ledger, signature, RunAuthority.REBUILD)
    lifecycle = CodeGenerationLifecycle(
        CodeGenerationBindings(tmp_path, ledger.path.parent, recovery_code_store)
    )

    assert resumed.generation_id == checkpoint.generation_id
    assert recovery_code_store.count_code() == 1
    assert lifecycle.publish_pending_finalization(
        resumed, reporter=NullProgressReporter()
    )

    canonical = recovery_code_store.DERIVED_CODE_TABLE_NAME
    assert resolve_served_code_collection(tmp_path, canonical) == canonical
    assert canonical == recovery_code_store.CODE_TABLE_NAME
    assert recovery_code_store.count_code() == 1
    published = ledger.generation(checkpoint.generation_id)
    assert published.complete
