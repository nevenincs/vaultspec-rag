"""The code pipeline's progress counter measures consumer output, not input.

The "chunk + embed" phase totals files, and its counter used to be advanced
by the CPU producers as files were handed to the encode queue - so it pinned
at N/N while the GPU kept working invisibly, and measured embedding not at
all. The counter is now advanced by the GPU consumer as files finish
encoding and are durably upserted, and the consumer publishes the same
forward-pass boundaries the vault path publishes, so a long forward on the
code path is visible while it runs.

Replay completion is also counted after raw stream validation and actual ledger
confirmation. The real resume fixtures below retain local storage and durable
identities across checkpoint reopen; only the model forward is deterministic.

The encoder here is a deterministic implementation of the model's encode
call surface and the store records its upserts; everything between them -
the slice encode, the vector population, the accounting, the reporter, the
registry - is the shipped production path. The encoder also replays the
per-bucket boundary contract the real one emits, so the sub-slice progress
and encode-budget state those boundaries publish are covered without a GPU.
"""

from __future__ import annotations

import hashlib
import sys
import threading
from contextlib import nullcontext
from dataclasses import replace
from typing import TYPE_CHECKING, cast

import pytest

from .._job_progress import confirmed_chunk_progress, telemetry_block
from .._store_models import CodeChunk, _code_chunk_payload
from ..embeddings import EncodeBucketProgress
from ..indexer._chunk_producer import WeightedCodeSegmentQueue
from ..indexer._consumer_pipeline import (
    CodeConsumerPipeline,
    CodePipelineBindings,
    CodePipelineLimits,
    _WeightedConsumerRun,
)
from ..indexer._reuse import DonorReuseContext
from ..indexer._streaming import EncodeBucketReporter
from ..indexer._streaming_types import CodeFileSegment, WeightedCodeSlice
from ..job_models import JobSource
from ..jobs import JobProgressReporter, record_start, reset, snapshot
from ..memory_probe import MemoryProbe
from ..store_runtime import DonorPoint
from .test_weighted_code_resume import resume_run

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Sequence
    from pathlib import Path
    from types import FrameType

    from ..embeddings import EmbeddingModel
    from ..indexer._chunk_producer import CodeChunkProducer
    from ..indexer._content_policy import AdmissionReason
    from ..indexer._generation_lifecycle import CodeGenerationLifecycle
    from ..memory_probe import MemoryBudgetSnapshot
    from ..store_runtime import VaultStore
    from .test_weighted_code_resume import _ResumeRun

__all__ = ["resume_run"]

pytestmark = [pytest.mark.unit]


@pytest.fixture(autouse=True)
def own_status_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    from ._config_fixtures import reset_config

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
        self.texts: list[str] = []

    def encode_documents_on_device(
        self,
        texts: list[str],
        batch_size: int | None = None,
        gpu_lock: object | None = None,
        on_bucket: Callable[[str, EncodeBucketProgress], None] | None = None,
    ) -> list[list[float]]:
        del batch_size, gpu_lock
        self.texts.extend(texts)
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
        self.chunk_work_at_upsert: list[object] = []
        self.fail_write = False
        self.donors: dict[str, DonorPoint] = {}
        self.on_write_complete: Callable[[], None] | None = None

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
        work = confirmed_chunk_progress(self._job_id)
        self.chunk_work_at_upsert.append(
            work["completed"] if work is not None else None
        )
        if self.fail_write:
            raise RuntimeError("controlled upsert refused")
        self.upserts.append([chunk.id for chunk in chunks])
        if self.on_write_complete is not None:
            self.on_write_complete()

    def retrieve_donor_points(
        self, collection: str, chunk_ids: list[str]
    ) -> dict[str, DonorPoint]:
        del collection
        return {
            chunk_id: self.donors[chunk_id]
            for chunk_id in chunk_ids
            if chunk_id in self.donors
        }


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

        Mutation check: removing the consumer's completion-accounting call in
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
        assert store.completed_at_upsert == [0], (
            "file progress preceded confirmed store write"
        )
        assert consumer_run.total[0] == 3
        assert consumer_run.new_ids == {chunk_a0.id, chunk_a1.id, chunk_b0.id}
        work = confirmed_chunk_progress(job_id)
        assert work is not None
        assert work["completed"] == 3, "acknowledged chunks were not reported"
        assert store.chunk_work_at_upsert == [0], (
            "chunk work preceded store acknowledgement"
        )

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
                kind="dense",
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

        Mutation check: giving ``EncodeBucketReporter._publish`` back the
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

    def test_sparse_retries_drain_beside_a_larger_dense_count(self) -> None:
        """One slice's sparse retries reach the job record beside dense ones.

        The dense and sparse encodes of a slice share one boundary adapter,
        and each encode call's retry count restarts at zero.

        Mutation check: draining retries through one shared counter instead
        of one per encode kind - replacing ``progress.kind`` with a fixed
        key in ``_EncodeBucketReporter._publish`` - makes this fail on the
        ``oom_count == 3`` assertion below: the sparse series starts below
        the dense total, so its retry reads as already reported and the
        record stays at 2. Restoring the per-kind key returns it to green.
        """
        job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
        report = EncodeBucketReporter(JobProgressReporter(job_id), 0, 4)

        def _progress(
            kind: str,
            items_done: int,
            oom_count: int,
        ) -> EncodeBucketProgress:
            return EncodeBucketProgress(
                kind=kind,
                items_done=items_done,
                items_total=4,
                bucket_items=2,
                bucket_estimated_tokens=1000,
                token_budget=2000,
                oom_count=oom_count,
            )

        # The dense encode absorbs two retries...
        report("before", _progress("dense", 0, 0))
        report("before", _progress("dense", 0, 2))
        report("after", _progress("dense", 4, 2))
        # ...then the same slice's sparse encode absorbs one of its own,
        # its running count restarting from zero.
        report("before", _progress("sparse", 0, 0))
        report("before", _progress("sparse", 0, 1))
        report("after", _progress("sparse", 4, 1))

        encode = telemetry_block(job_id, "encode")
        assert encode is not None
        assert encode["oom_count"] == 3


def _chunk_work_run(
    reporter: JobProgressReporter,
    reuse: DonorReuseContext | None = None,
) -> _WeightedConsumerRun:
    from ..job_control import NO_RUN_CONTROL

    return _WeightedConsumerRun(
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
        donor_reuse=reuse,
        reporter=reporter,
    )


@pytest.mark.parametrize("reused", [False, True], ids=["encoded", "donor-hits"])
def test_acknowledged_chunk_operations_include_reuse_and_repeated_point_ids(
    tmp_path: Path, reused: bool
) -> None:
    job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
    reporter = JobProgressReporter(job_id)
    reporter.phase_start("chunk + embed", 1)
    chunks = tuple(_chunk("pkg/a.py", ordinal) for ordinal in range(3))
    weighted = WeightedCodeSlice(
        segments=(_segment("pkg/a.py", 0, chunks, is_file_end=False),),
        chunks=chunks,
        estimated_bytes=sum(len(chunk.content) for chunk in chunks),
    )
    store = RecordingUpsertStore(job_id)
    reuse = None
    if reused:
        store.donors = {
            chunk.id: DonorPoint(
                [0.0, 1.0], None, None, dict(_code_chunk_payload(chunk))
            )
            for chunk in chunks
        }
        reuse = DonorReuseContext(cast("VaultStore", store), ("donor",))
    encoder = DeterministicEncoder()
    pipeline = _pipeline(tmp_path, store, encoder)
    run = _chunk_work_run(reporter, reuse)
    with MemoryProbe(name="acknowledged-chunk-operations") as probe:
        # Two successful writes of the same points are six work operations,
        # one segment each, three unique points, and zero completed files.
        for ordinal in range(2):
            pipeline._consume_weighted_slice(
                weighted, slice_index=ordinal, consumer_run=run, probe=probe
            )
    work = confirmed_chunk_progress(job_id)
    assert work is not None
    assert work["completed"] == 6, (
        "chunk work substituted encoded or unique point count"
    )
    assert store.chunk_work_at_upsert == [0, 3]
    assert len(run.new_ids) == 3
    assert _completed_files(job_id) == 0
    assert len(encoder.texts) == (0 if reused else 6)
    if reuse is not None:
        assert reuse.stats.reuse_hits == 6


@pytest.mark.parametrize("prior_ack", [False, True], ids=["no-ack", "partial-ack"])
def test_failed_slice_counts_only_prior_successful_acknowledgements(
    tmp_path: Path, prior_ack: bool
) -> None:
    job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
    reporter = JobProgressReporter(job_id)
    reporter.phase_start("chunk + embed", 1)
    chunks = tuple(_chunk("pkg/a.py", ordinal) for ordinal in range(3))
    weighted = WeightedCodeSlice(
        segments=(_segment("pkg/a.py", 0, chunks, is_file_end=False),),
        chunks=chunks,
        estimated_bytes=sum(len(chunk.content) for chunk in chunks),
    )
    store = RecordingUpsertStore(job_id)
    pipeline = _pipeline(tmp_path, store)
    run = _chunk_work_run(reporter)
    with MemoryProbe(name="failed-chunk-acknowledgement") as probe:
        if prior_ack:
            pipeline._consume_weighted_slice(
                weighted, slice_index=0, consumer_run=run, probe=probe
            )
        store.fail_write = True
        with pytest.raises(RuntimeError, match="controlled upsert refused"):
            pipeline._consume_weighted_slice(
                weighted, slice_index=1, consumer_run=run, probe=probe
            )
    work = confirmed_chunk_progress(job_id)
    assert work is not None
    assert work["completed"] == (3 if prior_ack else 0), (
        "failed unacknowledged slice advanced chunk work"
    )
    assert (work["last_updated"] is None) is (not prior_ack)


def test_acknowledged_work_survives_control_unwind_after_store_return(
    tmp_path: Path,
) -> None:
    from ..job_control import PauseRequested, RunControlToken

    job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
    reporter = JobProgressReporter(job_id)
    reporter.phase_start("chunk + embed", 1)
    chunks = (_chunk("pkg/a.py", 0), _chunk("pkg/a.py", 1))
    weighted = WeightedCodeSlice(
        segments=(_segment("pkg/a.py", 0, chunks, is_file_end=False),),
        chunks=chunks,
        estimated_bytes=sum(len(chunk.content) for chunk in chunks),
    )
    store = RecordingUpsertStore(job_id)
    pipeline = _pipeline(tmp_path, store)
    run = _chunk_work_run(reporter)
    control = RunControlToken()
    run = replace(run, run_control=control)

    def request_pause() -> None:
        control.request_pause()

    store.on_write_complete = request_pause
    with (
        MemoryProbe(name="acknowledgement-before-control") as probe,
        pytest.raises(PauseRequested, match="run pause requested"),
    ):
        pipeline._consume_weighted_slice(
            weighted, slice_index=0, consumer_run=run, probe=probe
        )
    work = confirmed_chunk_progress(job_id)
    assert work is not None
    assert work["completed"] == 2, "post-acknowledgement control lost confirmed work"
    assert run.total == [0]


def _completed_files(job_id: str) -> int:
    record = next(entry for entry in snapshot() if entry["id"] == job_id)
    progress = cast("dict[str, object]", record["progress"])
    completed = progress["completed"]
    assert isinstance(completed, int)
    return completed


def _consume_replay_progress(
    replay: _ResumeRun,
    *,
    raw_segments: tuple[CodeFileSegment, ...] | None = None,
    source_digests: dict[str, str] | None = None,
    queue_max_bytes: int = 8192,
    before_enqueue: Callable[[str], None] | None = None,
) -> tuple[_WeightedConsumerRun, str, list[bool]]:
    """Observe actual threaded consumer advancement against the real ledger."""
    from ..job_control import NO_RUN_CONTROL

    job_id = record_start(JobSource.CODE, "tool", command="reindex_codebase")
    reporter = JobProgressReporter(job_id)
    reporter.phase_start("chunk + embed", len(replay.files))
    metadata = dict(replay.digests if source_digests is None else source_digests)
    consumer_run = _WeightedConsumerRun(
        segment_queue=WeightedCodeSegmentQueue(max_chunks=2, max_bytes=queue_max_bytes),
        consumer_exceptions=[],
        limits=replay.limits,
        new_ids=set(),
        total=[0],
        metadata=metadata,
        checkpoint=replay.checkpoint,
        ingest_wait=True,
        run_control=NO_RUN_CONTROL,
        code_build_target=replay.lifecycle.active_build_target,
        donor_reuse=None,
        reporter=reporter,
    )
    completed_at_advancement: list[bool] = []

    def observe(frame: FrameType, event: str, _argument: object) -> None:
        if event == "call" and frame.f_code is JobProgressReporter.advance.__code__:
            completed_at_advancement.append(
                bool(consumer_run.completed_file_paths)
                and all(
                    replay.checkpoint.ledger.file_complete(
                        replay.checkpoint.generation_id, path
                    )
                    for path in consumer_run.completed_file_paths
                )
            )

    prior_profile = threading.getprofile()
    threading.setprofile(observe)
    consumer = replay.pipeline._spawn_weighted_consumer(consumer_run)
    try:
        if raw_segments is None:
            for result in replay.files:
                if before_enqueue is not None:
                    before_enqueue(result.rel_path)
                assert replay.pipeline._enqueue_code_result(
                    replace(
                        result,
                        content_hash=metadata[result.rel_path],
                        chunks=list(result.chunks),
                    ),
                    consumer_run=consumer_run,
                    consumer=consumer,
                ), "real producer stream was rejected"
        else:
            for segment in raw_segments:
                consumer_run.segment_queue.put(segment, timeout=5.0)
    finally:
        if consumer.is_alive():
            consumer_run.segment_queue.put(None, timeout=5.0)
        # Waits on the thread's actual completion rather than a wall-clock
        # guess: a contended machine can legitimately take longer than any
        # fixed number here to drain real encode and ledger writes, and the
        # suite's own timeout bound still catches a genuine hang.
        consumer.join()
        threading.setprofile(prior_profile)
    assert not consumer.is_alive(), "progress consumer did not terminate"
    return consumer_run, job_id, completed_at_advancement


@pytest.mark.parametrize(
    "committed",
    [(), (0,), (0, 1), (0, 1, 2, 3, 4, 5), (1, 3, 5, 7), (3, 7), tuple(range(8))],
    ids=["fresh", "prefix", "long-prefix", "cross-file", "gaps", "ends-first", "all"],
)
def test_replayed_complete_files_count_once_after_confirmation(
    resume_run: _ResumeRun, committed: tuple[int, ...]
) -> None:
    """Omitting replay advancement loses files; ignoring gaps counts too early."""
    resume_run.confirm(tuple(resume_run.segments[index] for index in committed))
    resume_run.restart()
    consumer, job_id, confirmations = _consume_replay_progress(resume_run)
    assert not consumer.consumer_exceptions
    # Removing the skip-side accounting loses fully committed file ends.
    assert _completed_files(job_id) == len(resume_run.files), (
        "validated complete replayed files were omitted from progress"
    )
    # Removing file_complete advances a committed tail before its pending gap.
    assert confirmations and all(confirmations), (
        "file progress advanced before its ledger gaps were confirmed"
    )
    assert consumer.completed_file_paths == set(resume_run.digests)
    assert resume_run.checkpoint.resumed_units == len(committed)
    assert consumer.total == [8 - len(committed)]
    assert len(resume_run.encoder.texts) == 8 - len(committed)
    work = confirmed_chunk_progress(job_id)
    assert work is not None
    assert work["completed"] == 8 - len(committed), (
        "committed replay was counted as new acknowledged chunk work"
    )
    assert (
        resume_run.checkpoint.ledger.committed_unit_count(
            resume_run.checkpoint.generation_id
        )
        == 8
    )
    assert not resume_run.checkpoint.ingestion_complete


def test_replayed_final_marker_counts_each_path_only_once(
    resume_run: _ResumeRun,
) -> None:
    """Removing the counted-path guard recounts a validated repeated file."""
    resume_run.confirm(resume_run.segments)
    resume_run.restart()
    raw = resume_run.segments + resume_run.segments[:4]
    consumer, job_id, confirmations = _consume_replay_progress(
        resume_run, raw_segments=raw
    )
    assert not consumer.consumer_exceptions
    assert _completed_files(job_id) == 2, "a replayed completed path was counted twice"
    assert confirmations and all(confirmations)
    assert consumer.total == [0] and not resume_run.encoder.texts


def test_changed_digest_is_counted_after_new_confirmation(
    resume_run: _ResumeRun,
) -> None:
    """Skipping a changed digest falsely credits old units instead of new writes."""
    from ._run_ledger_test_support import ledger_test_digest

    resume_run.confirm(resume_run.segments)
    resume_run.restart()
    digests = dict(resume_run.digests)
    digests["first.py"] = ledger_test_digest("changed first source")
    consumer, job_id, confirmations = _consume_replay_progress(
        resume_run, source_digests=digests
    )
    assert not consumer.consumer_exceptions
    assert _completed_files(job_id) == 2, "changed source lost confirmed progress"
    assert confirmations and all(confirmations), "changed source was counted too early"
    assert consumer.total == [4], "changed digest was credited without new writes"
    assert len(resume_run.encoder.texts) == 4
    assert resume_run.checkpoint.resumed_units == 4
    assert (
        resume_run.checkpoint.ledger.indexed_digests_for_paths(
            resume_run.checkpoint.generation_id, tuple(digests)
        )
        == digests
    )


@pytest.mark.parametrize(
    ("indices", "message"),
    [
        ((1,), "must begin at ordinal zero"),
        ((0, 2), "same-file segments must be contiguous"),
        ((0, 1, 2), "must finish at a file-end marker"),
    ],
    ids=["initial", "gap", "missing-final"],
)
def test_invalid_replay_stream_cannot_seed_file_progress(
    resume_run: _ResumeRun, indices: tuple[int, ...], message: str
) -> None:
    """Ledger-only progress seeding credits files absent a validated final marker."""
    resume_run.confirm(resume_run.segments)
    resume_run.restart()
    consumer, job_id, confirmations = _consume_replay_progress(
        resume_run,
        raw_segments=tuple(resume_run.segments[index] for index in indices),
    )
    assert len(consumer.consumer_exceptions) == 1
    error = consumer.consumer_exceptions[0]
    assert isinstance(error, ValueError) and message in str(error)
    assert _completed_files(job_id) == 0, "unvalidated ledger files seeded progress"
    assert not confirmations and not consumer.completed_file_paths


def test_oversized_committed_final_cannot_advance_progress(
    resume_run: _ResumeRun,
) -> None:
    """Raw weight validation must precede skipped final-marker accounting."""
    resume_run.confirm(resume_run.segments)
    resume_run.restart()
    raw = (
        *resume_run.segments[:3],
        replace(
            resume_run.segments[3],
            estimated_bytes=resume_run.limits.slice_max_bytes + 1,
        ),
    )
    consumer, job_id, confirmations = _consume_replay_progress(
        resume_run,
        raw_segments=raw,
        # Admit the raw segment to the queue so the stricter slice boundary,
        # rather than the queue's capacity boundary, is actually exercised.
        queue_max_bytes=2 * resume_run.limits.slice_max_bytes,
    )
    assert len(consumer.consumer_exceptions) == 1
    error = consumer.consumer_exceptions[0]
    assert isinstance(error, ValueError) and "exceeds slice bounds" in str(error)
    assert _completed_files(job_id) == 0, "oversized replayed file seeded progress"
    assert not confirmations and not consumer.completed_file_paths


@pytest.mark.parametrize("outcome", ["empty", "blank", "skipped", "vanished"])
@pytest.mark.parametrize("retained", [False, True], ids=["fresh", "resumed"])
def test_resolved_zero_chunk_files_count_after_durable_outcome(
    resume_run: _ResumeRun, outcome: str, retained: bool
) -> None:
    """Removing zero-chunk advancement loses files; early credit precedes repair."""
    from ..indexer._file_state import FileStateKind

    if retained:
        resume_run.confirm(resume_run.segments[:4])
        resume_run.restart()
    first = replace(
        resume_run.files[0],
        chunks=[],
        blank=outcome == "blank",
        content_hash=(
            hashlib.blake2b(b"").hexdigest()
            if outcome == "empty"
            else resume_run.files[0].content_hash
        ),
        preprocess_status=outcome if outcome in {"skipped", "vanished"} else None,
    )
    resume_run.files = (first, resume_run.files[1])
    resume_run.digests[first.rel_path] = first.content_hash
    resolved_at_advancement: list[bool] = []

    def observe(frame: FrameType, event: str, _argument: object) -> None:
        if event != "call" or frame.f_code is not JobProgressReporter.advance.__code__:
            return
        checkpoint = resume_run.checkpoint
        states = checkpoint.ledger.file_states_for_paths(
            checkpoint.generation_id, (first.rel_path,)
        )
        state = states.get(first.rel_path)
        resolved_at_advancement.append(
            (
                state is None
                if outcome == "vanished"
                else state is not None and state.state is FileStateKind.POLICY_REJECTED
            )
            and not any(
                chunk.id
                in resume_run.store.get_all_code_ids(
                    resume_run.lifecycle.active_build_target
                )
                for segment in resume_run.segments[:4]
                for chunk in segment.chunks
            )
        )

    prior_profile = sys.getprofile()
    sys.setprofile(observe)
    try:
        consumer, job_id, confirmations = _consume_replay_progress(resume_run)
    finally:
        sys.setprofile(prior_profile)
    assert not consumer.consumer_exceptions
    assert _completed_files(job_id) == 2, "resolved zero-chunk file lost progress"
    assert resolved_at_advancement == [True], (
        "zero-chunk file progress preceded durable source resolution"
    )
    assert confirmations and all(confirmations)
    assert consumer.completed_file_paths == {"second.py"}
    assert consumer.total == [4] and len(resume_run.encoder.texts) == 4


@pytest.mark.parametrize("failure", ["extraction", "ledger"])
def test_failed_zero_chunk_outcomes_do_not_advance_progress(
    resume_run: _ResumeRun, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """Crediting before result validation or its ledger write counts failed files."""
    from .._job_errors import JobError
    from ..indexer._run_checkpoint import CodeRunCheckpoint

    first = replace(resume_run.files[0], chunks=[], preprocess_status="ok")
    expected: type[Exception] = JobError
    if failure == "ledger":
        first = replace(first, blank=True)
        expected = OSError

        def fail_write(*_args: object, **_kwargs: object) -> None:
            raise OSError("injected source-outcome ledger failure")

        monkeypatch.setattr(CodeRunCheckpoint, "record_policy_rejection", fail_write)
    resume_run.files = (first, resume_run.files[1])
    with pytest.raises(expected):
        _consume_replay_progress(resume_run)
    records = snapshot()
    assert len(records) == 1
    job_id = records[0]["id"]
    assert isinstance(job_id, str)
    assert _completed_files(job_id) == 0, "failed zero-chunk outcome was counted"
    assert not resume_run.encoder.texts


def test_producer_and_consumer_publish_file_progress_in_order(
    resume_run: _ResumeRun, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Removing the shared lock lets an older consumer publication overwrite 2."""
    from ..indexer._run_checkpoint import CodeRunCheckpoint

    resume_run.confirm(resume_run.segments[:4])
    resume_run.restart()
    resume_run.files = (
        resume_run.files[0],
        replace(resume_run.files[1], chunks=[], blank=True),
    )
    first_waiting = threading.Event()
    zero_resolved = threading.Event()
    release_first = threading.Event()
    second_published = threading.Event()
    publication_order: list[int] = []
    coordination: list[bool] = []
    publish = JobProgressReporter._publish
    record_rejection = CodeRunCheckpoint.record_policy_rejection

    def delayed_publish(
        reporter: JobProgressReporter, step: str, *, completed: int, total: int | None
    ) -> bool:
        if completed == 1:
            first_waiting.set()
            assert release_first.wait(10), "progress publication was never released"
        accepted = publish(reporter, step, completed=completed, total=total)
        if completed:
            publication_order.append(completed)
        if completed == 2:
            second_published.set()
        return accepted

    def record_zero_outcome(
        checkpoint: CodeRunCheckpoint,
        rel_path: str,
        reason: AdmissionReason,
        *,
        content_hash: str | None = None,
    ) -> None:
        record_rejection(checkpoint, rel_path, reason, content_hash=content_hash)
        zero_resolved.set()

    def before_enqueue(rel_path: str) -> None:
        if rel_path == "second.py":
            assert first_waiting.wait(10), (
                "real replay consumer did not reach publication"
            )

    def coordinate() -> None:
        try:
            coordination.append(zero_resolved.wait(10))
            # Give the actual producer publication a window to overtake the
            # blocked consumer. With the lock it waits until release instead.
            coordination.append(not second_published.wait(0.2))
        finally:
            release_first.set()

    monkeypatch.setattr(JobProgressReporter, "_publish", delayed_publish)
    monkeypatch.setattr(
        CodeRunCheckpoint, "record_policy_rejection", record_zero_outcome
    )
    coordinator = threading.Thread(target=coordinate)
    coordinator.start()
    try:
        consumer, job_id, confirmations = _consume_replay_progress(
            resume_run, before_enqueue=before_enqueue
        )
    finally:
        release_first.set()
        coordinator.join(timeout=15)
    assert not coordinator.is_alive() and not consumer.consumer_exceptions
    assert _completed_files(job_id) == 2, (
        "older file progress overwrote newer completion"
    )
    assert publication_order == [1, 2] and coordination == [True, True]
    assert confirmations and all(confirmations)
