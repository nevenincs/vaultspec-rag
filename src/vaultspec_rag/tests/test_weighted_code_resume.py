"""Resume complete weighted streams through real queues, ledgers, and storage."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, cast
from uuid import NAMESPACE_URL, uuid5

import pytest

from .._store_models import CodeChunk
from ..config._settings import get_config
from ..indexer._chunk_producer import CodeChunkProducer, WeightedCodeSegmentQueue
from ..indexer._chunk_worker import ChunkExecutionPolicy, FileChunkResult
from ..indexer._consumer_pipeline import (
    CodeConsumerPipeline,
    CodePipelineBindings,
    CodePipelineLimits,
    _WeightedConsumerRun,
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
    RunAuthority,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
)
from ..indexer._slicing import (
    code_embed_text,
    iter_code_file_segments,
    iter_weighted_code_slices,
)
from ..indexer._streaming_types import CodeFileSegment, CodeFileSegmentRequest
from ..job_control import NO_RUN_CONTROL
from ..progress import NullProgressReporter
from ..store_runtime import VaultStore
from ._run_ledger_test_support import ledger_test_digest

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ..embeddings import EmbeddingModel, EncodeBucketProgress
    from ..indexer._run_checkpoint import CodeRunCheckpoint
    from ..memory_probe import MemoryBudgetSnapshot

pytestmark = [pytest.mark.unit]


class _CpuEncoder:
    """Only the model forward boundary is deterministic; storage is real."""

    def __init__(self) -> None:
        self.texts: list[str] = []

    def encode_documents_on_device(
        self,
        texts: list[str],
        batch_size: int | None = None,
        gpu_lock: object | None = None,
        on_bucket: Callable[[str, EncodeBucketProgress], None] | None = None,
    ) -> list[list[float]]:
        del batch_size, gpu_lock, on_bucket
        self.texts.extend(texts)
        return [[0.0, 1.0] for _ in texts]


@dataclass
class _ResumeRun:
    store: VaultStore
    lifecycle: CodeGenerationLifecycle
    open_request: CodeGenerationOpenRequest
    checkpoint: CodeRunCheckpoint
    pipeline: CodeConsumerPipeline
    encoder: _CpuEncoder
    limits: CodePipelineLimits
    files: tuple[FileChunkResult, ...]
    segments: tuple[CodeFileSegment, ...]
    digests: dict[str, str]

    def confirm(self, segments: tuple[CodeFileSegment, ...]) -> None:
        """Write real points before recording any completion evidence."""
        for segment in segments:
            for chunk in segment.chunks:
                chunk.vector = [0.0, 1.0]
            self.store.upsert_code_chunks(
                list(segment.chunks),
                write_policy=None,
                collection=self.lifecycle.active_build_target,
            )
            assert (
                self.checkpoint.record_confirmed_segments((segment,), self.digests) == 1
            )

    def restart(self) -> None:
        generation_id = self.checkpoint.generation_id
        self.checkpoint.ledger.finish_generation(
            generation_id, RunTerminalState.FAILED, detail="interrupted test attempt"
        )
        # A new checkpoint and SQLite open discard the prior attempt's state.
        self.lifecycle.forget_open_generation()
        self.checkpoint = self.lifecycle.open_checkpoint(self.open_request)
        assert self.checkpoint.generation_id == generation_id

    def consume(self) -> _WeightedConsumerRun:
        consumer_run = _WeightedConsumerRun(
            segment_queue=WeightedCodeSegmentQueue(max_chunks=2, max_bytes=8192),
            consumer_exceptions=[],
            limits=self.limits,
            new_ids=set(),
            total=[0],
            metadata={},
            checkpoint=self.checkpoint,
            ingest_wait=True,
            run_control=NO_RUN_CONTROL,
            code_build_target=self.lifecycle.active_build_target,
            donor_reuse=None,
            reporter=NullProgressReporter(),
        )
        consumer = self.pipeline._spawn_weighted_consumer(consumer_run)
        try:
            for result in self.files:
                assert self.pipeline._enqueue_code_result(
                    replace(result, chunks=list(result.chunks)),
                    consumer_run=consumer_run,
                    consumer=consumer,
                ), "complete producer stream was rejected before resume selection"
        finally:
            if consumer.is_alive():
                consumer_run.segment_queue.put(None, timeout=5.0)
            # Waits on the thread's actual completion rather than a wall-clock
            # guess: a contended machine can legitimately take longer than any
            # fixed number here, and the suite's own timeout bound still
            # catches a genuine hang.
            consumer.join()
        assert not consumer.is_alive(), "weighted consumer did not terminate"
        assert not consumer_run.consumer_exceptions, (
            "compatible resumed stream lost its framing: "
            f"{consumer_run.consumer_exceptions!r}"
        )
        return consumer_run


def _files() -> tuple[FileChunkResult, ...]:
    return tuple(
        FileChunkResult(
            path,
            ledger_test_digest(path),
            [
                CodeChunk(
                    id=str(uuid5(NAMESPACE_URL, f"resume:{path}:{ordinal}")),
                    path=path,
                    language="python",
                    content=f"def unit_{ordinal}():\n    return {ordinal}\n",
                    line_start=ordinal * 2 + 1,
                    line_end=ordinal * 2 + 2,
                )
                for ordinal in range(4)
            ],
        )
        for path in ("first.py", "second.py")
    )


@pytest.fixture
def resume_run(tmp_path: Path, clean_config: None) -> Generator[_ResumeRun]:
    del clean_config
    get_config(
        {
            "embedding_dimension": 2,
            "qdrant_url": None,
            "sparse_enabled": False,
            "index_chunk_workers": 1,
        }
    )
    limits = CodePipelineLimits(
        segment_max_chunks=1,
        segment_max_bytes=4096,
        queue_max_chunks=2,
        queue_max_bytes=8192,
        slice_max_chunks=3,
        slice_max_bytes=8192,
        dense_dimension=2,
        sparse_enabled=False,
        sparse_dimension=1,
        encode_batch_size=3,
        flush_slices=64,
    )
    policy = resolve_index_policy(
        tmp_path,
        IndexPolicyResolutionOptions(
            content_policy=RootContentPolicy(SourceProfileVersion.CONVENTIONAL_V1)
        ),
    )
    files = _files()
    segments = tuple(
        segment
        for result in files
        for segment in iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=result.chunks,
                max_chunks=1,
                max_bytes=4096,
                dense_dimension=2,
                sparse_enabled=False,
                sparse_dimension=1,
            )
        )
    )
    encoder = _CpuEncoder()
    with VaultStore(tmp_path, embedding_dim=2) as store:
        lifecycle = CodeGenerationLifecycle(
            CodeGenerationBindings(tmp_path, tmp_path / ".state", store)
        )
        open_request = CodeGenerationOpenRequest(
            policy=policy,
            operation=RunOperation.FULL,
            clean=True,
            configuration=limits.run_configuration,
            dense_dimensions=2,
            sparse_enabled=False,
            run_control=NO_RUN_CONTROL,
            authority=RunAuthority.REBUILD,
        )
        checkpoint = lifecycle.open_checkpoint(open_request)
        pipeline = CodeConsumerPipeline(
            CodePipelineBindings(
                root_dir=tmp_path,
                model=cast("EmbeddingModel", encoder),
                store=store,
                producer=CodeChunkProducer(
                    tmp_path,
                    chunk_execution_policy=ChunkExecutionPolicy(),
                    prep_ctx=lambda: None,
                ),
                lifecycle=lifecycle,
                gpu_lock=None,
                begin_memory_budget=lambda: None,
                sample_memory_budget=lambda _label: cast("MemoryBudgetSnapshot", None),
                forward_peak_recording=nullcontext,
                fail_cuda_oom=lambda _label, _exc: None,
                begin_support_measurement=lambda _paths: None,
                measure_code_segments=iter,
                record_extracted_bytes=lambda _n: None,
                record_preprocess_result=lambda _result: None,
            )
        )
        yield _ResumeRun(
            store,
            lifecycle,
            open_request,
            checkpoint,
            pipeline,
            encoder,
            limits,
            files,
            segments,
            {result.rel_path: result.content_hash for result in files},
        )


@pytest.mark.parametrize(
    "committed",
    [(), (0,), (0, 1), (0, 1, 2, 3, 4, 5), (1, 3, 5, 7), (3, 7), tuple(range(8))],
    ids=["fresh", "prefix", "long-prefix", "cross-file", "gaps", "ends-first", "all"],
)
def test_weighted_resume_preserves_durable_units(
    resume_run: _ResumeRun, committed: tuple[int, ...]
) -> None:
    """Producer filtering breaks framing; absent consumer selection re-encodes.

    Removing the skip-side slice flush also joins noncontiguous pending gaps.
    Those production mutations fail the framing or encoder assertions below.
    """
    committed_segments = tuple(resume_run.segments[index] for index in committed)
    resume_run.confirm(committed_segments)
    resume_run.restart()
    consumer = resume_run.consume()
    pending = tuple(
        segment
        for index, segment in enumerate(resume_run.segments)
        if index not in committed
    )
    assert sorted(resume_run.encoder.texts) == sorted(
        code_embed_text(chunk) for segment in pending for chunk in segment.chunks
    ), "confirmed units must never reach the encoder again"
    assert consumer.total == [len(pending)]
    checkpoint = resume_run.checkpoint
    assert checkpoint.resumed_units == len(committed)
    assert checkpoint.ledger.committed_unit_count(checkpoint.generation_id) == 8
    assert all(
        checkpoint.ledger.unit_committed(
            checkpoint.generation_id,
            checkpoint.unit_for(segment, resume_run.digests[segment.path]),
        )
        for segment in resume_run.segments
    ), "resume must retain original ordinals, digests, end markers, and point IDs"
    assert resume_run.store.get_all_code_ids(
        resume_run.lifecycle.active_build_target
    ) == {chunk.id for segment in resume_run.segments for chunk in segment.chunks}
    assert (
        checkpoint.ledger.indexed_digests_for_paths(
            checkpoint.generation_id, tuple(resume_run.digests)
        )
        == resume_run.digests
    ), "closing a resumed gap must converge indexed file state"
    assert not checkpoint.ingestion_complete, "unit resume must not invent publication"


def test_committed_end_marker_cannot_complete_a_file_with_gaps(
    resume_run: _ResumeRun,
) -> None:
    """End-marker-only confirmation or resume falsely indexes an incomplete file."""
    end = resume_run.segments[3]
    confirmation_error: RunLedgerStateError | None = None
    try:
        resume_run.confirm((end,))
    except RunLedgerStateError as exc:
        confirmation_error = exc
    assert confirmation_error is None, (
        "a stored end marker cannot certify missing earlier segments: "
        f"{confirmation_error}"
    )
    checkpoint = resume_run.checkpoint
    assert not checkpoint.ledger.file_complete(checkpoint.generation_id, end.path)
    assert not checkpoint.ledger.indexed_digests_for_paths(
        checkpoint.generation_id, (end.path,)
    ), "a stored end marker cannot certify missing earlier segments"
    resume_run.restart()
    checkpoint = resume_run.checkpoint
    resume_error: RunLedgerStateError | None = None
    try:
        assert checkpoint.segment_committed(end, resume_run.digests[end.path])
    except RunLedgerStateError as exc:
        resume_error = exc
    assert resume_error is None, (
        f"resume selection cannot certify missing earlier segments: {resume_error}"
    )
    assert not checkpoint.ledger.indexed_digests_for_paths(
        checkpoint.generation_id, (end.path,)
    ), "resume selection cannot certify missing earlier segments"
    resume_run.confirm(resume_run.segments[:3])
    assert checkpoint.ledger.indexed_digests_for_paths(
        checkpoint.generation_id, (end.path,)
    ) == {end.path: resume_run.digests[end.path]}, (
        "the last confirmed gap must complete the file without replaying its end marker"
    )


@pytest.mark.parametrize(
    ("indices", "message"),
    [
        ((1, 2, 3), "must begin at ordinal zero"),
        ((0, 2, 3), "same-file segments must be contiguous"),
        ((0, 4, 5, 6, 7), "must follow a file-end marker"),
        ((0, 1, 2, 3, 5, 6, 7), "begin at ordinal zero"),
        ((0, 1, 2, 3, 0), "cannot follow a file-end marker"),
        ((0, 1, 2), "must finish at a file-end marker"),
    ],
    ids=["initial", "gap", "missing-end", "new-file", "after-end", "eof"],
)
def test_committed_units_cannot_hide_malformed_raw_stream(
    resume_run: _ResumeRun, indices: tuple[int, ...], message: str
) -> None:
    """Moving resume selection ahead of validation hides each malformed boundary."""
    resume_run.confirm(resume_run.segments)
    resume_run.restart()
    checkpoint = resume_run.checkpoint
    with pytest.raises(ValueError, match=message):
        list(
            iter_weighted_code_slices(
                (resume_run.segments[index] for index in indices),
                max_chunks=3,
                max_bytes=8192,
                skip_segment=lambda segment: checkpoint.segment_committed(
                    segment, resume_run.digests[segment.path]
                ),
            )
        )


def test_committed_unit_must_still_fit_raw_weight_bounds(
    resume_run: _ResumeRun,
) -> None:
    """Moving resume selection ahead of bounds admits an oversized stored unit."""
    segment = resume_run.segments[0]
    resume_run.confirm((segment,))
    checkpoint = resume_run.checkpoint
    with pytest.raises(ValueError, match="exceeds slice bounds"):
        list(
            iter_weighted_code_slices(
                resume_run.segments,
                max_chunks=1,
                max_bytes=segment.estimated_bytes - 1,
                skip_segment=lambda item: checkpoint.segment_committed(
                    item, resume_run.digests[item.path]
                ),
            )
        )
    assert checkpoint.resumed_units == 0, "raw bounds must precede resume selection"


def test_resume_selection_requires_exact_unit_identity(resume_run: _ResumeRun) -> None:
    """Ignoring the canonical ledger identity silently skips changed work."""
    segment = resume_run.segments[0]
    resume_run.confirm((segment,))
    checkpoint = resume_run.checkpoint
    digest = resume_run.digests[segment.path]
    changed_chunk = replace(segment.chunks[0], id=str(uuid5(NAMESPACE_URL, "changed")))
    for changed, changed_digest in (
        (segment, ledger_test_digest("changed source")),
        (replace(segment, ordinal=1), digest),
        (replace(segment, is_file_end=True), digest),
        (replace(segment, chunks=(changed_chunk,)), digest),
    ):
        assert not checkpoint.segment_committed(changed, changed_digest), (
            "resume must not reuse evidence for a different durable unit"
        )
    assert checkpoint.resumed_units == 0
