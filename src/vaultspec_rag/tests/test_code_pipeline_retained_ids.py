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
from ..indexer._run_ledger_models import (
    CommitUnitKind,
    RunAuthority,
    RunOperation,
    RunTerminalState,
)
from ..indexer._slicing import iter_code_file_segments
from ..indexer._streaming_types import CodeFileSegment, CodeFileSegmentRequest
from ..job_control import NO_RUN_CONTROL
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore

if TYPE_CHECKING:
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._chunk_worker import FileChunkResult
    from ..indexer._run_checkpoint import CodeRunCheckpoint
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


def _limits() -> CodePipelineLimits:
    return CodePipelineLimits(8, 65536, 32, 1048576, 32, 1048576, 2, False, 1, 8, 64)


def _open_generation(
    root: Path, store: VaultStore, limits: CodePipelineLimits
) -> tuple[CodeGenerationLifecycle, CodeRunCheckpoint, CodeGenerationOpenRequest]:
    lifecycle = CodeGenerationLifecycle(
        CodeGenerationBindings(root_dir=root, data_root=root / ".state", store=store)
    )
    request = CodeGenerationOpenRequest(
        policy=resolve_index_policy(
            root,
            IndexPolicyResolutionOptions(
                content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
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
    return lifecycle, lifecycle.open_checkpoint(request), request


def _pipeline(
    root: Path, store: VaultStore, lifecycle: CodeGenerationLifecycle
) -> CodeConsumerPipeline:
    return CodeConsumerPipeline(
        CodePipelineBindings(
            root_dir=root,
            model=cast("EmbeddingModel", _CPUEncoder()),
            store=store,
            producer=CodeChunkProducer(
                root,
                chunk_execution_policy=ChunkExecutionPolicy(),
                prep_ctx=lambda: None,
            ),
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


def _segments(result: FileChunkResult) -> tuple[CodeFileSegment, ...]:
    return tuple(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=result.chunks,
                max_chunks=1,
                max_bytes=65536,
                dense_dimension=2,
                sparse_enabled=False,
                sparse_dimension=1,
            )
        )
    )


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
    limits = _limits()
    with VaultStore(tmp_path, embedding_dim=2) as store:
        store.upsert_code_chunks([old], write_policy=None)
        lifecycle, checkpoint, _request = _open_generation(tmp_path, store, limits)
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
        pipeline = _pipeline(tmp_path, store, lifecycle)
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


@pytest.mark.parametrize("batch_size", [1, 2, 6])
@pytest.mark.parametrize("path_count", [1, 2])
@pytest.mark.parametrize("collision", [False, True])
@pytest.mark.usefixtures("clean_config")
def test_resumed_partial_edit_preserves_confirmed_shared_chunk_ids(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    batch_size: int,
    path_count: int,
    collision: bool,
) -> None:
    from ..indexer._drift_owner import CodeDriftOwner

    source = "\n\n".join(
        f'def {name}():\n    return "{text * 1000}"\n'
        for name, text in (("first", "x"), ("changed", "y"), ("last", "w"))
    )
    paths = [tmp_path / f"sample{number}.py" for number in range(path_count)]
    for path in paths:
        path.write_text(source, encoding="utf-8")
    old = [chunk_and_hash_file(path, tmp_path) for path in paths]
    assert all(len(result.chunks) == 3 for result in old)
    with VaultStore(tmp_path, embedding_dim=2) as store:
        lifecycle, checkpoint, request = _open_generation(tmp_path, store, _limits())
        for result in old:
            for chunk in result.chunks:
                chunk.vector = [0.0, 1.0]
            store.upsert_code_chunks(result.chunks, write_policy=None)
            checkpoint.record_confirmed_segments(
                _segments(result), {result.rel_path: result.content_hash}
            )
        checkpoint.ledger.finish_generation(
            checkpoint.generation_id, RunTerminalState.CANCELLED
        )
        checkpoint = lifecycle.open_checkpoint(request)
        before = set(store.get_all_code_ids())
        for path in paths:
            path.write_text(source.replace("y" * 1000, "z" * 1000), encoding="utf-8")
        fresh = [chunk_and_hash_file(path, tmp_path) for path in paths]
        fresh_ids = {chunk.id for result in fresh for chunk in result.chunks}
        shared = before & fresh_ids
        assert len(shared) == path_count * 2
        if collision:
            # The cheap observation can miss a race; the real ledger remains
            # authoritative and raises its actual indexed-path collision.
            def missed_observation(
                _owner: CodeDriftOwner,
                segments: tuple[CodeFileSegment, ...],
                _digests: dict[str, str],
            ) -> tuple[CodeFileSegment, ...]:
                return segments

            monkeypatch.setattr(
                CodeDriftOwner, "_absorb_known_drift", missed_observation
            )
        segments = tuple(segment for result in fresh for segment in _segments(result))
        digests = {result.rel_path: result.content_hash for result in fresh}
        for start in range(0, len(segments), batch_size):
            batch = segments[start : start + batch_size]
            chunks = [chunk for segment in batch for chunk in segment.chunks]
            for chunk in chunks:
                chunk.vector = [0.0, 1.0]
            store.upsert_code_chunks(chunks, write_policy=None)
            lifecycle.drift_owner.record_segments(batch, digests)
            # Retiring every old-digest ID also deletes shared fresh IDs here.
            assert {chunk.id for chunk in chunks} <= set(store.get_all_code_ids())
        live = set(store.get_all_code_ids())
        assert live == fresh_ids
        assert shared <= live
        assert (before - fresh_ids).isdisjoint(live)
        assert (
            set(checkpoint.ledger.iter_retained_point_ids(checkpoint.generation_id))
            == fresh_ids
        )
        assert (
            lifecycle.drift_owner.collisions_observed > 0
            if collision
            else lifecycle.drift_owner.collisions_observed == 0
        )
        store.apply_ingest_barrier(
            store.CODE_TABLE_NAME,
            expected_points=len(fresh_ids),
            write_policy=checkpoint.run_policy.store_write_policy,
        )


@pytest.mark.parametrize("with_survivor", [False, True])
def test_reopened_pipeline_excludes_durable_deletion_identities(
    tmp_path: Path, clean_config: None, with_survivor: bool
) -> None:
    del clean_config
    path = tmp_path / "removed.py"
    path.write_text("def removed():\n    return 1\n", encoding="utf-8")
    old = chunk_and_hash_file(path, tmp_path)
    limits = _limits()
    with VaultStore(tmp_path, embedding_dim=2) as store:
        lifecycle, checkpoint, request = _open_generation(tmp_path, store, limits)
        for chunk in old.chunks:
            chunk.vector = [0.0, 1.0]
        store.upsert_code_chunks(old.chunks, write_policy=None)
        checkpoint.record_confirmed_segments(
            _segments(old), {old.rel_path: old.content_hash}
        )
        assert lifecycle.drift_owner.retire_retained_outcome(
            old.rel_path, remove_path=True
        )
        path.unlink()
        checkpoint.ledger.finish_generation(
            checkpoint.generation_id, RunTerminalState.CANCELLED
        )
        checkpoint = lifecycle.open_checkpoint(request)
        paths: list[Path] = []
        expected_ids: set[str] = set()
        if with_survivor:
            survivor = tmp_path / "survivor.py"
            survivor.write_text(
                'def survivor():\n    return "'
                + "s" * 1000
                + '"\n\ndef second():\n    return 2\n',
                encoding="utf-8",
            )
            paths.append(survivor)
            expected_ids.update(
                chunk.id for chunk in chunk_and_hash_file(survivor, tmp_path).chunks
            )
            assert len(expected_ids) == 2
        result = _pipeline(tmp_path, store, lifecycle).run(
            paths,
            CodePipelineRun(
                reporter=NullProgressReporter(),
                checkpoint=checkpoint,
                limits=limits,
                content_epoch=None,
                code_build_target=None,
            ),
        )
        assert not lifecycle.drift_owner.superseded_point_ids
        # Seeding from all operation kinds revives deleted IDs on resume.
        assert result.new_ids == expected_ids == set(store.get_all_code_ids())
        # All-operation reads retain deletion evidence for existing callers.
        assert {chunk.id for chunk in old.chunks} <= set(
            checkpoint.ledger.iter_point_ids(checkpoint.generation_id, batch_size=1)
        )
        assert (
            set(
                checkpoint.ledger.iter_point_ids(
                    checkpoint.generation_id,
                    batch_size=1,
                    unit_kind=CommitUnitKind.UPSERT,
                )
            )
            == expected_ids
        )
        store.apply_ingest_barrier(
            store.CODE_TABLE_NAME,
            expected_points=len(expected_ids),
            write_policy=checkpoint.run_policy.store_write_policy,
        )


def test_reopened_pipeline_keeps_unfinished_file_upsert_prefix(
    tmp_path: Path, clean_config: None
) -> None:
    del clean_config
    path = tmp_path / "partial.py"
    path.write_text(
        'def first():\n    return "' + "x" * 1000 + '"\n\ndef last():\n    return 2\n',
        encoding="utf-8",
    )
    source = chunk_and_hash_file(path, tmp_path)
    segments = _segments(source)
    assert len(segments) == 2 and not segments[0].is_file_end
    limits = _limits()
    with VaultStore(tmp_path, embedding_dim=2) as store:
        lifecycle, checkpoint, request = _open_generation(tmp_path, store, limits)
        chunk = segments[0].chunks[0]
        chunk.vector = [0.0, 1.0]
        store.upsert_code_chunks([chunk], write_policy=None)
        checkpoint.record_confirmed_segments(
            segments[:1], {source.rel_path: source.content_hash}
        )
        assert not set(
            checkpoint.ledger.iter_retained_point_ids(checkpoint.generation_id)
        )
        checkpoint.ledger.finish_generation(
            checkpoint.generation_id, RunTerminalState.CANCELLED
        )
        checkpoint = lifecycle.open_checkpoint(request)
        result = _pipeline(tmp_path, store, lifecycle).run(
            [],
            CodePipelineRun(
                reporter=NullProgressReporter(),
                checkpoint=checkpoint,
                limits=limits,
                content_epoch=None,
                code_build_target=None,
            ),
        )
        # Manifest-only seeding loses confirmed unfinished-file prefixes.
        assert result.new_ids == {chunk.id} == set(store.get_all_code_ids())
