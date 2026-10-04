"""Clean resumed rebuilds reconcile their own storage-confirmed manifest."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING

import pytest

from .._publication_state import (
    acquire_publication_snapshot,
    read_all_publication_evidence,
)
from .._source_types import PublicSourceType
from ..config._settings import get_config
from ..indexer import CodebaseIndexer
from ..indexer._chunk_worker import chunk_and_hash_file
from ..indexer._codebase_indexer import _FullStaleReconciliation
from ..indexer._consumer_pipeline import CodePipelineRun
from ..indexer._content_policy import RootContentPolicy, SourceProfileVersion
from ..indexer._generation_lifecycle import CodeGenerationOpenRequest
from ..indexer._publication_proof import ProofIncompatibleError, ProofProvenance
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    resolve_index_policy,
)
from ..indexer._run_checkpoint import CodeRunCheckpoint
from ..indexer._run_ledger_models import RunAuthority, RunOperation, RunTerminalState
from ..indexer._run_ledger_publication_identity import compatibility_for_signature
from ..job_control import NO_RUN_CONTROL
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from .test_code_pipeline_retained_ids import _limits, _pipeline, _segments
from .test_live_checkpoint_resilience import unloaded_model

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._consumer_pipeline import ChunkEmbedResult

__all__ = ["unloaded_model"]
pytestmark = pytest.mark.unit


@dataclass(frozen=True)
class _ShadowResume:
    indexer: CodebaseIndexer
    checkpoint: CodeRunCheckpoint
    prior_checkpoint: CodeRunCheckpoint
    previous_metadata: dict[str, str]
    old_ids: set[str]
    old_collection: str
    target: str
    existing_ids: set[str]
    result: ChunkEmbedResult

    def reconcile(self) -> list[str]:
        return self.indexer._reconcile_full_stale_ids(
            _FullStaleReconciliation(
                self.checkpoint,
                self.previous_metadata,
                self.result.metadata,
                self.existing_ids,
                self.result.new_ids,
                self.target,
                NullProgressReporter(),
            )
        )


def _request(root: Path) -> CodeGenerationOpenRequest:
    return CodeGenerationOpenRequest(
        policy=resolve_index_policy(
            root,
            IndexPolicyResolutionOptions(
                content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
            ),
        ),
        operation=RunOperation.FULL,
        clean=True,
        configuration=_limits().run_configuration,
        dense_dimensions=2,
        sparse_enabled=False,
        run_control=NO_RUN_CONTROL,
        authority=RunAuthority.REBUILD,
    )


def _run(
    indexer: CodebaseIndexer, checkpoint: CodeRunCheckpoint, paths: list[Path]
) -> ChunkEmbedResult:
    return _pipeline(indexer.root_dir, indexer.store, indexer._lifecycle).run(
        paths,
        CodePipelineRun(
            reporter=NullProgressReporter(),
            checkpoint=checkpoint,
            limits=_limits(),
            content_epoch=None,
            code_build_target=indexer._lifecycle.active_build_target,
        ),
    )


def _configure(model: str) -> None:
    get_config(
        {
            "embedding_model": model,
            "embedding_dimension": 2,
            "sparse_enabled": False,
            "qdrant_url": None,
            "index_chunk_workers": 1,
            "index_segment_max_chunks": 8,
            "index_segment_max_bytes": 65536,
            "index_queue_max_chunks": 32,
            "index_queue_max_bytes": 1048576,
            "embedding_code_encode_batch_size": 8,
            "index_cache_flush_slices": 64,
        }
    )


@pytest.fixture
def shadow_resume(
    tmp_path: Path, unloaded_model: EmbeddingModel
) -> Generator[_ShadowResume]:
    """Use real producers, ledgers and isolated local storage for both models."""
    _configure("old/dense")
    removed = tmp_path / "served_removed.py"
    survivor = tmp_path / "survivor.py"
    shadow_only = tmp_path / "shadow_only.py"
    for path in (removed, survivor):
        path.write_text(f"def {path.stem}():\n    return 1\n", encoding="utf-8")
    with VaultStore(tmp_path, embedding_dim=2) as store:
        indexer = CodebaseIndexer(tmp_path, unloaded_model, store)
        lifecycle = indexer._lifecycle
        request = _request(tmp_path)
        old_checkpoint = lifecycle.open_checkpoint(request)
        old_result = _run(indexer, old_checkpoint, [removed, survivor])
        lifecycle.publish(
            old_checkpoint,
            build_target=lifecycle.active_build_target,
            reporter=NullProgressReporter(),
            phase_label="publish old model",
        )
        old_collection = store.CODE_TABLE_NAME
        snapshot = acquire_publication_snapshot(tmp_path, PublicSourceType.CODE)
        previous_metadata = {
            path: evidence.content_identity
            for path, evidence in read_all_publication_evidence(snapshot).items()
        }
        snapshot.validate()
        prior = lifecycle.open_checkpoint(
            replace(
                request,
                operation=RunOperation.SCOPED_INCREMENTAL,
                clean=False,
                authority=RunAuthority.PUBLICATION,
            )
        )
        assert prior.receipt is not None
        # The genuine empty incremental reservation is settled before the
        # replacement; its retained object later exercises stale-key refusal.
        prior.ledger.begin_publication_rollback(prior.receipt.receipt_id)
        prior.ledger.roll_back_publication_receipt(
            prior.receipt.receipt_id, compensated_units=()
        )
        prior.ledger.finish_generation(
            prior.generation_id, RunTerminalState.INVALIDATED
        )

        _configure("new/dense")
        shadow_only.write_text("def shadow_only():\n    return 2\n", encoding="utf-8")
        checkpoint = lifecycle.open_checkpoint(request)
        _run(indexer, checkpoint, [removed, survivor, shadow_only])
        generation_id = checkpoint.generation_id
        target = lifecycle.active_build_target
        assert target is not None and target != old_collection
        checkpoint.ledger.finish_generation(generation_id, RunTerminalState.FAILED)
        removed.unlink()
        shadow_only.unlink()
        lifecycle.forget_open_generation()
        checkpoint = lifecycle.open_checkpoint(request)
        assert checkpoint.generation_id == generation_id
        existing_ids = set(store.get_all_code_ids(collection=target))
        result = _run(indexer, checkpoint, [survivor])
        # These are the actual consumer-seeded identities, including paths
        # absent from the resumed producer stream; the fixture does not filter.
        assert result.new_ids == existing_ids and len(existing_ids) == 3
        store.apply_ingest_barrier(
            target,
            expected_points=len(existing_ids | result.new_ids),
            write_policy=checkpoint.run_policy.store_write_policy,
        )
        yield _ShadowResume(
            indexer,
            checkpoint,
            prior,
            previous_metadata,
            old_result.new_ids,
            old_collection,
            target,
            existing_ids,
            result,
        )


def test_clean_rebuild_reconciles_own_manifest_across_model_change(
    shadow_resume: _ShadowResume,
) -> None:
    case = shadow_resume
    incompatible: ProofIncompatibleError | None = None
    try:
        stale = case.reconcile()
    except ProofIncompatibleError as exc:
        incompatible = exc
        stale = []
    # Restoring the served-proof lookup fails this assertion before cleanup.
    assert incompatible is None, (
        "clean shadow cleanup consulted incompatible served proof"
    )
    # Served-path membership omits shadow-only sources; retaining seeded
    # removed identities loses their actual cleanup count.
    assert len(stale) == 2, (
        "consumer-seeded removed shadow identities remained retained"
    )
    assert {
        state.rel_path
        for state in case.checkpoint.ledger.iter_file_states(
            case.checkpoint.generation_id
        )
    } == {"survivor.py"}, "shadow-only removed file state was not retired"
    store = case.indexer.store
    retained = set(
        case.checkpoint.ledger.iter_retained_point_ids(case.checkpoint.generation_id)
    )
    assert len(retained) == 1 and retained == set(
        store.get_all_code_ids(collection=case.target)
    )
    assert case.old_collection == store.CODE_TABLE_NAME
    assert set(store.get_all_code_ids(collection=case.old_collection)) == case.old_ids
    case.indexer._lifecycle.publish(
        case.checkpoint,
        build_target=case.target,
        reporter=NullProgressReporter(),
        phase_label="publish resumed replacement",
    )
    snapshot = acquire_publication_snapshot(
        case.indexer.root_dir, PublicSourceType.CODE
    )
    assert snapshot.proof.provenance is ProofProvenance.VERIFIED
    assert snapshot.proof.generation_id == case.checkpoint.generation_id
    assert snapshot.proof.compatibility_key == compatibility_for_signature(
        case.checkpoint.generation.signature
    )
    assert (
        json.loads(case.checkpoint.generation.signature.model_identity)["dense"]
        == "new/dense"
    )
    evidence = read_all_publication_evidence(snapshot)
    assert set(evidence) == {"survivor.py"}
    assert {point for item in evidence.values() for point in item.point_ids} == retained
    snapshot.validate()
    assert set(store.get_all_code_ids(collection=case.old_collection)) == case.old_ids


def test_unconfirmed_cleanup_cannot_retire_shadow_manifest(
    shadow_resume: _ShadowResume, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = shadow_resume
    confirmed = case.checkpoint.ledger.committed_unit_count(
        case.checkpoint.generation_id
    )

    def fail_delete(*_args: object, **_kwargs: object) -> None:
        raise OSError("injected deletion transport failure")

    with monkeypatch.context() as patch:
        patch.setattr(case.indexer.store, "delete_code_chunks", fail_delete)
        with pytest.raises(OSError, match="injected deletion transport failure"):
            case.reconcile()
    # Moving retirement before the actual store acknowledgement fails here.
    assert (
        case.checkpoint.ledger.committed_unit_count(case.checkpoint.generation_id)
        == confirmed
    ), "unconfirmed cleanup changed durable own-generation evidence"
    assert (
        set(
            case.checkpoint.ledger.iter_retained_point_ids(
                case.checkpoint.generation_id
            )
        )
        == case.existing_ids
    )
    assert (
        set(case.indexer.store.get_all_code_ids(collection=case.target))
        == case.existing_ids
    )
    assert (
        set(case.indexer.store.get_all_code_ids(collection=case.old_collection))
        == case.old_ids
    )


def test_clean_retained_lookup_excludes_confirmed_deletion_units(
    shadow_resume: _ShadowResume,
) -> None:
    case = shadow_resume
    case.reconcile()
    removed_paths = {"served_removed.py", "shadow_only.py"}
    # Reading every unit kind resurrects deletion-only identities.
    assert case.indexer._lifecycle.checkpoint_ids_by_path(
        case.checkpoint, removed_paths, retained=True
    ) == {path: set() for path in removed_paths}, (
        "deletion evidence was treated as retained upserts"
    )


def test_incremental_receipt_keeps_strict_parent_model_key(
    shadow_resume: _ShadowResume,
) -> None:
    case = shadow_resume
    case.reconcile()
    case.indexer._lifecycle.publish(
        case.checkpoint,
        build_target=case.target,
        reporter=NullProgressReporter(),
        phase_label="publish replacement before stale reader",
    )
    refused = False
    try:
        case.indexer._lifecycle.checkpoint_ids_by_path(
            case.prior_checkpoint, {"served_removed.py"}, retained=True
        )
    except ProofIncompatibleError:
        refused = True
    # Broadening the shadow exception to receipts loses exact-key refusal.
    assert refused, "incremental receipt bypassed strict published model identity"


@pytest.mark.parametrize("partial", [False, True])
@pytest.mark.parametrize("interrupted_deletion", [False, True])
def test_full_owner_resumes_removed_own_sources_before_seeding(
    shadow_resume: _ShadowResume,
    monkeypatch: pytest.MonkeyPatch,
    partial: bool,
    interrupted_deletion: bool,
) -> None:
    case = shadow_resume
    if partial:
        source = case.indexer.root_dir / "partial.py"
        source.write_text(
            'def first():\n    return "'
            + "x" * 1000
            + '"\n\ndef last():\n    return 2\n',
            encoding="utf-8",
        )
        result = chunk_and_hash_file(source, case.indexer.root_dir)
        segments = _segments(result)
        assert len(segments) == 2 and not segments[0].is_file_end
        chunk = segments[0].chunks[0]
        chunk.vector = [0.0, 1.0]
        case.indexer.store.upsert_code_chunks(
            [chunk],
            collection=case.target,
            write_policy=case.checkpoint.run_policy.store_write_policy,
        )
        case.checkpoint.record_confirmed_segments(
            segments[:1], {source.name: result.content_hash}
        )
        assert source.name not in {
            state.rel_path
            for state in case.checkpoint.ledger.iter_file_states(
                case.checkpoint.generation_id
            )
        }
        source.unlink()

    def fail_retirement(
        _checkpoint: CodeRunCheckpoint,
        _path: str,
        _ids: tuple[str, ...],
        *,
        remove_path: bool,
    ) -> bool:
        del remove_path
        raise OSError("injected retirement commit failure")

    if interrupted_deletion:
        with monkeypatch.context() as patch:
            patch.setattr(CodeRunCheckpoint, "retire_retained_upserts", fail_retirement)
            with pytest.raises(OSError, match="injected retirement commit failure"):
                case.reconcile()
        assert (
            len(case.indexer.store.get_all_code_ids(collection=case.target))
            == 2 + partial
        )
        assert (
            len(
                list(
                    case.checkpoint.ledger.iter_retained_point_ids(
                        case.checkpoint.generation_id
                    )
                )
            )
            == 3
        )
    case.checkpoint.ledger.finish_generation(
        case.checkpoint.generation_id, RunTerminalState.FAILED
    )
    # The full invocation consumes the same real pipeline and deterministic
    # external encoder used above; it owns discovery, recovery and publication.
    case.indexer._consumer_pipeline = _pipeline(
        case.indexer.root_dir, case.indexer.store, case.indexer._lifecycle
    )
    failure: Exception | None = None
    result = None
    with monkeypatch.context() as patch:
        patch.setattr(case.indexer.store, "_server_mode", True)
        try:
            result = case.indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=case.indexer.preflight_content(),
            )
        except Exception as exc:
            failure = exc
    # Omitting full-entry recovery fails the barrier after a storage-first
    # interruption; INDEXED-only recovery cannot finalize partial prefixes.
    assert failure is None, "full owner could not recover absent own-source evidence"
    assert result is not None and result.total == 1
    assert result.removed == 2 + partial - interrupted_deletion
    snapshot = acquire_publication_snapshot(
        case.indexer.root_dir, PublicSourceType.CODE
    )
    assert snapshot.proof.generation_id == case.checkpoint.generation_id
    assert set(read_all_publication_evidence(snapshot)) == {"survivor.py"}
    assert snapshot.proof.provenance is ProofProvenance.VERIFIED
    snapshot.validate()
    assert (
        set(case.indexer.store.get_all_code_ids(collection=case.old_collection))
        == case.old_ids
    )


def test_full_owner_keeps_present_source_missing_points_fail_closed(
    shadow_resume: _ShadowResume, monkeypatch: pytest.MonkeyPatch
) -> None:
    case = shadow_resume
    current = {"survivor.py"}
    ids = case.indexer._lifecycle.checkpoint_ids_by_path(
        case.checkpoint, current, retained=True
    )["survivor.py"]
    case.indexer.store.delete_code_chunks(list(ids), collection=case.target)
    before = acquire_publication_snapshot(case.indexer.root_dir, PublicSourceType.CODE)
    case.checkpoint.ledger.finish_generation(
        case.checkpoint.generation_id, RunTerminalState.FAILED
    )
    case.indexer._consumer_pipeline = _pipeline(
        case.indexer.root_dir, case.indexer.store, case.indexer._lifecycle
    )
    from ..store_runtime import IngestVerificationError

    failure: Exception | None = None
    with monkeypatch.context() as patch:
        patch.setattr(case.indexer.store, "_server_mode", True)
        try:
            case.indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=case.indexer.preflight_content(),
            )
        except Exception as exc:
            failure = exc
    # Removing current-path exclusion silently re-encodes missing evidence.
    assert isinstance(failure, IngestVerificationError), (
        "present-source missing acknowledged points bypassed the exact barrier"
    )
    after = acquire_publication_snapshot(case.indexer.root_dir, PublicSourceType.CODE)
    assert after.proof == before.proof
    after.validate()
    assert case.old_collection == case.indexer.store.CODE_TABLE_NAME
    assert (
        set(case.indexer.store.get_all_code_ids(collection=case.old_collection))
        == case.old_ids
    )
