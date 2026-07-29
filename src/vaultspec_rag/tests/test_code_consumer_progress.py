"""The code pipeline's progress counter measures consumer output, not input.

The "chunk + embed" phase totals files, and its counter used to be advanced
by the CPU producers as files were handed to the encode queue - so it pinned
at N/N while the GPU kept working invisibly, and measured embedding not at
all. The counter is now advanced by the GPU consumer as files finish
encoding and are durably upserted, and the consumer publishes the same
forward-pass boundaries the vault path publishes, so a long forward on the
code path is visible while it runs.

The encoder here is a deterministic implementation of the model's encode
call surface and the store records its upserts; everything between them -
the slice encode, the vector population, the accounting, the reporter, the
registry - is the shipped production path. The encoder also replays the
per-bucket boundary contract the real one emits, so the sub-slice progress
and encode-budget state those boundaries publish are covered without a GPU.
"""

from __future__ import annotations

from contextlib import nullcontext
from typing import TYPE_CHECKING, cast

import pytest

from .._store_models import CodeChunk
from ..embeddings import EncodeBucketProgress
from ..indexer._chunk_producer import WeightedCodeSegmentQueue
from ..indexer._consumer_pipeline import (
    CodeConsumerPipeline,
    CodePipelineBindings,
    CodePipelineLimits,
    _WeightedConsumerRun,
)
from ..indexer._streaming import CodeFileSegment, WeightedCodeSlice
from ..job_models import JobSource
from ..jobs import (
    JobProgressReporter,
    record_start,
    reset,
    snapshot,
    telemetry_block,
)
from ..memory_probe import MemoryProbe

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..indexer._chunk_producer import CodeChunkProducer
    from ..indexer._generation_lifecycle import CodeGenerationLifecycle
    from ..memory_probe import MemoryBudgetSnapshot
    from ..store_runtime import VaultStore

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def own_status_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    from ..config._settings import reset_config

    monkeypatch.setenv("VAULTSPEC_RAG_STATUS_DIR", str(tmp_path / "status"))
    # The dense-only encoder below exposes exactly the dense call surface.
    monkeypatch.setenv("VAULTSPEC_RAG_SPARSE_ENABLED", "0")
    reset_config()
    reset()
    yield
    reset()
    reset_config()


class DeterministicEncoder:
    """Deterministic encoder exposing the dense-encode call surface.

    ``bucket_events`` replays the real encoder's per-bucket boundary contract
    for one encode call, and ``on_event`` runs after each replayed boundary -
    the only way a test sees what a slice published while it ran rather than
    the single value it ended on. Left unset, no boundary is reported.
    """

    def __init__(
        self,
        *,
        bucket_events: Sequence[tuple[str, EncodeBucketProgress]] = (),
        on_event: Callable[[], None] | None = None,
    ) -> None:
        self.bucket_events = bucket_events
        self.on_event = on_event

    def encode_documents_on_device(
        self,
        texts: list[str],
        batch_size: int | None = None,
        gpu_lock: object | None = None,
        on_bucket: Callable[[str, EncodeBucketProgress], None] | None = None,
    ) -> list[list[float]]:
        del batch_size, gpu_lock
        if on_bucket is not None:
            for phase, progress in self.bucket_events:
                on_bucket(phase, progress)
                if self.on_event is not None:
                    self.on_event()
        return [[0.0, 1.0] for _ in texts]


class RecordingUpsertStore:
    """Records upserted chunk ids and the progress count at upsert time."""

    def __init__(self, job_id: str) -> None:
        self._job_id = job_id
        self.upserts: list[list[str]] = []
        self.completed_at_upsert: list[object] = []

    def upsert_code_chunks(
        self,
        chunks: list[CodeChunk],
        write_policy: object = None,
        wait: bool = True,
        collection: str | None = None,
    ) -> None:
        del write_policy, wait, collection
        record = next(e for e in snapshot() if e["id"] == self._job_id)
        progress = cast("dict[str, object]", record["progress"])
        self.completed_at_upsert.append(progress["completed"])
        self.upserts.append([chunk.id for chunk in chunks])


def _chunk(path: str, ordinal: int) -> CodeChunk:
    return CodeChunk(
        id=f"{path}#{ordinal}",
        path=path,
        language="python",
        content=f"def f_{ordinal}():\n    return {ordinal}\n",
        line_start=1,
        line_end=2,
    )


def _segment(
    path: str,
    ordinal: int,
    chunks: tuple[CodeChunk, ...],
    *,
    is_file_end: bool,
) -> CodeFileSegment:
    return CodeFileSegment(
        path=path,
        ordinal=ordinal,
        chunks=chunks,
        estimated_bytes=sum(len(chunk.content) for chunk in chunks),
        is_file_end=is_file_end,
    )


def _limits() -> CodePipelineLimits:
    return CodePipelineLimits(
        segment_max_chunks=8,
        segment_max_bytes=1 << 16,
        queue_max_chunks=32,
        queue_max_bytes=1 << 20,
        slice_max_chunks=32,
        slice_max_bytes=1 << 20,
        dense_dimension=2,
        sparse_enabled=False,
        sparse_dimension=0,
        encode_batch_size=8,
        # High enough that this slice never triggers a CUDA cache flush.
        flush_slices=64,
    )


def _sample_memory_budget(_label: str) -> MemoryBudgetSnapshot:
    return cast("MemoryBudgetSnapshot", None)


def _pipeline(
    tmp_path: Path,
    store: RecordingUpsertStore,
    encoder: DeterministicEncoder | None = None,
) -> CodeConsumerPipeline:
    return CodeConsumerPipeline(
        CodePipelineBindings(
            root_dir=tmp_path,
            model=cast(
                "EmbeddingModel",
                encoder if encoder is not None else DeterministicEncoder(),
            ),
            store=cast("VaultStore", store),
            producer=cast("CodeChunkProducer", object()),
            lifecycle=cast("CodeGenerationLifecycle", object()),
            gpu_lock=None,
            begin_memory_budget=lambda: None,
            sample_memory_budget=_sample_memory_budget,
            forward_peak_recording=nullcontext,
            fail_cuda_oom=lambda _label, _exc: None,
            begin_support_measurement=lambda _paths: None,
            measure_code_segments=iter,
            record_extracted_bytes=lambda _n: None,
            record_preprocess_result=lambda _result: None,
        )
    )


class TestConsumerAdvancesProgress:
    """The consumer advances the file counter and publishes forwards."""

    def test_a_confirmed_slice_advances_completed_files(
        self,
        tmp_path: Path,
    ) -> None:
        """One slice covering two finished files advances the counter by two.

        Mutation check: removing the consumer's ``reporter.advance`` call in
        ``_consume_weighted_slice`` makes this fail on the
        ``completed == 2`` assertion below - not on an import - and
        restoring it returns the test to green.
        """
        from ..job_control import NO_RUN_CONTROL

        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        reporter = JobProgressReporter(job_id)
        reporter.phase_start("chunk + embed", 3)

        chunk_a0 = _chunk("pkg/a.py", 0)
        chunk_a1 = _chunk("pkg/a.py", 1)
        chunk_b0 = _chunk("pkg/b.py", 0)
        weighted_slice = WeightedCodeSlice(
            segments=(
                _segment("pkg/a.py", 0, (chunk_a0,), is_file_end=False),
                _segment("pkg/a.py", 1, (chunk_a1,), is_file_end=True),
                _segment("pkg/b.py", 0, (chunk_b0,), is_file_end=True),
            ),
            chunks=(chunk_a0, chunk_a1, chunk_b0),
            estimated_bytes=sum(
                len(chunk.content) for chunk in (chunk_a0, chunk_a1, chunk_b0)
            ),
        )
        store = RecordingUpsertStore(job_id)
        pipeline = _pipeline(tmp_path, store)
        consumer_run = _WeightedConsumerRun(
            segment_queue=WeightedCodeSegmentQueue(max_chunks=32, max_bytes=1 << 20),
            consumer_exceptions=[],
            limits=_limits(),
            new_ids=set(),
            total=[0],
            metadata={},
            checkpoint=None,
            ingest_wait=False,
            run_control=NO_RUN_CONTROL,
            code_build_target=None,
            donor_reuse=None,
            reporter=reporter,
        )

        with MemoryProbe(name="test-code-consumer-progress") as probe:
            pipeline._consume_weighted_slice(
                weighted_slice,
                slice_index=0,
                consumer_run=consumer_run,
                probe=probe,
            )

        record = next(e for e in snapshot() if e["id"] == job_id)
        progress = cast("dict[str, object]", record["progress"])
        # Two files ended in this slice; the third file has not been seen.
        assert progress["completed"] == 2
        assert progress["total"] == 3
        # The count moved only after the store confirmed the write: at
        # upsert time the counter still read the phase-start zero.
        assert store.upserts == [[chunk_a0.id, chunk_a1.id, chunk_b0.id]]
        assert store.completed_at_upsert == [0]
        assert consumer_run.total[0] == 3
        assert consumer_run.new_ids == {chunk_a0.id, chunk_a1.id, chunk_b0.id}

    def test_the_code_slice_publishes_forward_boundaries(
        self,
        tmp_path: Path,
    ) -> None:
        """The code consumer reports the same forward window the vault does.

        Mutation check: dropping ``before_forward`` from the slice request in
        ``_consume_weighted_slice`` makes this fail on the ``forward is not
        None`` assertion below, because nothing ever opens the window.
        """
        from ..job_control import NO_RUN_CONTROL

        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        reporter = JobProgressReporter(job_id)
        reporter.phase_start("chunk + embed", 1)
        chunk = _chunk("pkg/c.py", 0)
        weighted_slice = WeightedCodeSlice(
            segments=(_segment("pkg/c.py", 0, (chunk,), is_file_end=True),),
            chunks=(chunk,),
            estimated_bytes=len(chunk.content),
        )
        store = RecordingUpsertStore(job_id)
        pipeline = _pipeline(tmp_path, store)
        consumer_run = _WeightedConsumerRun(
            segment_queue=WeightedCodeSegmentQueue(max_chunks=32, max_bytes=1 << 20),
            consumer_exceptions=[],
            limits=_limits(),
            new_ids=set(),
            total=[0],
            metadata={},
            checkpoint=None,
            ingest_wait=False,
            run_control=NO_RUN_CONTROL,
            code_build_target=None,
            donor_reuse=None,
            reporter=reporter,
        )

        with MemoryProbe(name="test-code-consumer-forward") as probe:
            pipeline._consume_weighted_slice(
                weighted_slice,
                slice_index=5,
                consumer_run=consumer_run,
                probe=probe,
            )

        forward = telemetry_block(job_id, "forward")
        assert forward is not None
        assert isinstance(forward["entered_at"], float)
        exited = forward["exited_at"]
        assert isinstance(exited, float)
        assert exited >= forward["entered_at"]
        assert forward["slice_ordinal"] == 5
        assert forward["items"] == 1

    def _replay_bucket_slice(
        self,
        tmp_path: Path,
        job_id: str,
        chunks: tuple[CodeChunk, ...],
        sample: Callable[[], None],
    ) -> None:
        """Run one slice through the production consumer with replayed buckets.

        The replayed sequence is one four-chunk slice encoded as a two-item
        bucket, then a bucket whose first attempt runs out of memory (a
        "before" with no "after") and is replanned as two one-item buckets
        under a halved budget. *sample* runs after each replayed boundary,
        which is the only way a test sees what the slice published while it
        ran rather than the single value it ended on.
        """
        from ..job_control import NO_RUN_CONTROL

        reporter = JobProgressReporter(job_id)
        reporter.phase_start("chunk + embed", 1)
        weighted_slice = WeightedCodeSlice(
            segments=(_segment("pkg/d.py", 0, chunks, is_file_end=True),),
            chunks=chunks,
            estimated_bytes=sum(len(chunk.content) for chunk in chunks),
        )

        def _progress(
            items_done: int,
            bucket_items: int,
            token_budget: int,
            oom_count: int,
        ) -> EncodeBucketProgress:
            return EncodeBucketProgress(
                items_done=items_done,
                items_total=len(chunks),
                bucket_items=bucket_items,
                bucket_estimated_tokens=bucket_items * 500,
                token_budget=token_budget,
                oom_count=oom_count,
            )

        encoder = DeterministicEncoder(
            bucket_events=(
                ("before", _progress(0, 2, 4000, 0)),
                ("after", _progress(2, 2, 4000, 0)),
                # This attempt runs out of memory: no "after" follows it, and
                # the next boundary carries the raised retry count.
                ("before", _progress(2, 2, 4000, 0)),
                ("before", _progress(2, 1, 2000, 1)),
                ("after", _progress(3, 1, 2000, 1)),
                ("before", _progress(3, 1, 2000, 1)),
                ("after", _progress(4, 1, 2000, 1)),
            ),
            on_event=sample,
        )
        store = RecordingUpsertStore(job_id)
        pipeline = _pipeline(tmp_path, store, encoder)
        consumer_run = _WeightedConsumerRun(
            segment_queue=WeightedCodeSegmentQueue(max_chunks=32, max_bytes=1 << 20),
            consumer_exceptions=[],
            limits=_limits(),
            new_ids=set(),
            total=[0],
            metadata={},
            checkpoint=None,
            ingest_wait=False,
            run_control=NO_RUN_CONTROL,
            code_build_target=None,
            donor_reuse=None,
            reporter=reporter,
        )

        with MemoryProbe(name="test-code-consumer-buckets") as probe:
            pipeline._consume_weighted_slice(
                weighted_slice,
                slice_index=2,
                consumer_run=consumer_run,
                probe=probe,
            )

    def test_encode_buckets_publish_sub_slice_progress_and_retries(
        self,
        tmp_path: Path,
    ) -> None:
        """Each bucket boundary moves the published encode progress and budget.

        Mutation check: dropping ``on_encode_bucket`` from the slice request
        in ``_consume_weighted_slice`` makes this fail on the ``done ==
        [0, 2, 2, 2, 3, 3, 4]`` assertion below - the encoder is handed no
        callback, so nothing is published between the slice's own two
        boundaries and the list comes back empty - and restoring it returns
        the test to green.
        """
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        chunks = tuple(_chunk("pkg/d.py", ordinal) for ordinal in range(4))
        published: list[dict[str, object]] = []

        def _sample() -> None:
            encode = telemetry_block(job_id, "encode")
            if encode is not None:
                published.append(encode)

        self._replay_bucket_slice(tmp_path, job_id, chunks, _sample)

        # Progress resolves inside the slice: the count climbs bucket by
        # bucket and repeats across the failed attempt, which encoded nothing.
        assert [sample["items_done"] for sample in published] == [0, 2, 2, 2, 3, 3, 4]
        # The climb is only readable against a denominator, so the pair is
        # published together at every boundary.
        assert {sample["items_total"] for sample in published} == {len(chunks)}
        # The budget the last bucket was planned under, and one retry - the
        # count rose once across four boundaries carrying it.
        assert telemetry_block(job_id, "encode") == {
            "token_budget": 2000,
            "bucket_items": 1,
            "items_done": 4,
            "items_total": 4,
            "oom_count": 1,
        }

    def test_bucket_boundaries_keep_the_forward_count_slice_scoped(
        self,
        tmp_path: Path,
    ) -> None:
        """The forward window's item count is the slice's size, start to end.

        An operator reading an open window mid-encode has no second field to
        read the number against, so it has to mean the same thing at every
        boundary it is written at.

        Mutation check: giving ``_EncodeBucketReporter._publish`` back the
        completed-so-far count - ``items=progress.items_done`` in both its
        ``forward_started`` and ``forward_finished`` calls - makes this fail
        on the ``{len(chunks)}`` set assertion below, which comes back as
        ``{0, 2, 3, 4}``; restoring ``items=self._items`` returns it to green.
        """
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        chunks = tuple(_chunk("pkg/d.py", ordinal) for ordinal in range(4))
        published: list[dict[str, object]] = []

        def _sample() -> None:
            forward = telemetry_block(job_id, "forward")
            if forward is not None:
                published.append(forward)

        self._replay_bucket_slice(tmp_path, job_id, chunks, _sample)

        assert {sample["items"] for sample in published} == {len(chunks)}
        # Every bucket reopens the window, so an in-flight bucket reads as one
        # rather than as a slice that finished at its first boundary.
        assert [sample["exited_at"] is None for sample in published] == [
            True,
            False,
            True,
            True,
            False,
            True,
            False,
        ]
        assert {sample["slice_ordinal"] for sample in published} == {2}
        # The slice still ends on the window it always ended on.
        forward = telemetry_block(job_id, "forward")
        assert forward is not None
        assert forward["items"] == len(chunks)
        assert forward["slice_ordinal"] == 2
