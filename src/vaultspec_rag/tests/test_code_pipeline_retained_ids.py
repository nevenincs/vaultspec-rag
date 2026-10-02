"""Resumed pipeline identities follow real durable drift retirement."""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, cast

import pytest

from ..indexer._chunk_producer import CodeChunkProducer
from ..indexer._chunk_worker import ChunkExecutionPolicy, chunk_and_hash_file
from ..indexer._consumer_pipeline import (
    CodeConsumerPipeline,
    CodePipelineBindings,
    CodePipelineLimits,
    CodePipelineRun,
)
from ..indexer._content_policy import RootContentPolicy, SourceProfileVersion
from ..indexer._generation_lifecycle import (
    CodeGenerationBindings,
    CodeGenerationLifecycle,
    CodeGenerationOpenRequest,
)
from ..indexer._resolved_policy import (
    IndexPolicyResolutionOptions,
    resolve_index_policy,
)
from ..indexer._run_ledger_models import RunAuthority, RunOperation
from ..indexer._streaming_types import CodeFileSegment
from ..job_control import NO_RUN_CONTROL
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._chunk_worker import FileChunkResult
    from ..memory_probe import MemoryBudgetSnapshot

pytestmark = pytest.mark.unit


class _CPUEncoder:
    """Only the external model boundary is deterministic; storage is real."""

    def encode_documents_on_device(
        self, texts: list[str], **_options: object
    ) -> list[list[float]]:
        return [[0.0, 1.0] for _ in texts]

    def encode_documents_sparse(
        self, texts: list[str], **_options: object
    ) -> list[None]:
        return [None for _ in texts]


def _sample(_label: str) -> MemoryBudgetSnapshot:
    return cast("MemoryBudgetSnapshot", None)


def _round_trip_source(
    path: Path,
    store: VaultStore,
    lifecycle: CodeGenerationLifecycle,
    initial: FileChunkResult,
) -> None:
    replacement = chunk_and_hash_file(path, path.parent)
    assert len(replacement.chunks) == 1
    fresh = replacement.chunks[0]
    fresh.vector = [0.0, 1.0]
    store.upsert_code_chunks([fresh], write_policy=None)
    fresh_segment = CodeFileSegment(
        path="sample.py",
        ordinal=0,
        chunks=(fresh,),
        estimated_bytes=len(fresh.content),
        is_file_end=True,
    )
    lifecycle.drift_owner.record_segments(
        (fresh_segment,), {"sample.py": replacement.content_hash}
    )
    old = initial.chunks[0]
    path.write_text("def old():\n    return 1\n", encoding="utf-8")
    store.upsert_code_chunks([old], write_policy=None)
    old_segment = CodeFileSegment(
        path="sample.py",
        ordinal=0,
        chunks=(old,),
        estimated_bytes=len(old.content),
        is_file_end=True,
    )
    lifecycle.drift_owner.record_segments(
        (old_segment,), {"sample.py": initial.content_hash}
    )


@pytest.mark.parametrize("outcome", ["unchanged", "changed", "round_trip", "removed"])
def test_resumed_pipeline_retains_only_live_committed_ids(
    tmp_path: Path, clean_config: None, outcome: str
) -> None:
    del clean_config
    path = tmp_path / "sample.py"
    source = "def old():\n    return 1\n"
    path.write_text(source, encoding="utf-8")
    initial = chunk_and_hash_file(path, tmp_path)
    assert len(initial.chunks) == 1
    old = initial.chunks[0]
    old.vector = [0.0, 1.0]
    digest = initial.content_hash
    limits = CodePipelineLimits(
        segment_max_chunks=8,
        segment_max_bytes=65536,
        queue_max_chunks=32,
        queue_max_bytes=1048576,
        slice_max_chunks=32,
        slice_max_bytes=1048576,
        dense_dimension=2,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=8,
        flush_slices=64,
    )
    with VaultStore(tmp_path, embedding_dim=2) as store:
        store.upsert_code_chunks([old], write_policy=None)
        lifecycle = CodeGenerationLifecycle(
            CodeGenerationBindings(
                root_dir=tmp_path, data_root=tmp_path / ".state", store=store
            )
        )
        checkpoint = lifecycle.open_checkpoint(
            CodeGenerationOpenRequest(
                policy=resolve_index_policy(
                    tmp_path,
                    IndexPolicyResolutionOptions(
                        content_policy=RootContentPolicy(
                            SourceProfileVersion.CONVENTIONAL_V1
                        )
                    ),
                ),
                operation=RunOperation.FULL,
                clean=False,
                configuration=limits.run_configuration,
                dense_dimensions=2,
                sparse_enabled=False,
                run_control=NO_RUN_CONTROL,
                authority=RunAuthority.REBUILD,
            )
        )
        segment = CodeFileSegment(
            path="sample.py",
            ordinal=0,
            chunks=(old,),
            estimated_bytes=len(source),
            is_file_end=True,
        )
        checkpoint.record_confirmed_segments((segment,), {"sample.py": digest})
        before = set(store.get_all_code_ids())
        assert before == {old.id}
        if outcome in {"changed", "round_trip"}:
            path.write_text("def replacement():\n    return 2\n", encoding="utf-8")
        if outcome == "round_trip":
            _round_trip_source(path, store, lifecycle, initial)
        if outcome == "removed":
            path.unlink()
        producer = CodeChunkProducer(
            tmp_path,
            chunk_execution_policy=ChunkExecutionPolicy(),
            prep_ctx=lambda: None,
        )
        pipeline = CodeConsumerPipeline(
            CodePipelineBindings(
                root_dir=tmp_path,
                model=cast("EmbeddingModel", _CPUEncoder()),
                store=store,
                producer=producer,
                lifecycle=lifecycle,
                gpu_lock=None,
                begin_memory_budget=lambda: None,
                sample_memory_budget=_sample,
                forward_peak_recording=nullcontext,
                fail_cuda_oom=lambda _label, _error: None,
                begin_support_measurement=lambda _paths: None,
                measure_code_segments=iter,
                record_extracted_bytes=lambda _size: None,
                record_preprocess_result=lambda _result: None,
            )
        )
        result = pipeline.run(
            [path],
            CodePipelineRun(
                reporter=NullProgressReporter(),
                checkpoint=checkpoint,
                limits=limits,
                content_epoch=None,
                code_build_target=None,
            ),
        )
        live = set(store.get_all_code_ids())
        retired = lifecycle.drift_owner.superseded_point_ids
        if outcome in {"changed", "removed"}:
            assert retired == {old.id}
            assert old.id not in live
            # Removing retirement, or treating DELETE units as retained
            # upserts, fails this assertion; restoring reconciliation passes.
            assert old.id not in result.new_ids
        elif outcome == "round_trip":
            assert old.id in retired
            # Blind retirement fails this equality; manifest retention passes.
            assert result.new_ids == {old.id}
        else:
            assert not retired
            assert result.new_ids == {old.id}
        assert result.new_ids == live
        expected = len((result.new_ids | before) - (retired - result.new_ids))
        store.apply_ingest_barrier(
            store.CODE_TABLE_NAME,
            expected_points=expected,
            write_policy=checkpoint.run_policy.store_write_policy,
        )
