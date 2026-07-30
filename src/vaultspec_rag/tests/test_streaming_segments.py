"""Real-object coverage for bounded streaming segment primitives."""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from itertools import chain
from typing import TYPE_CHECKING

import numpy as np
import pytest

from .._store_models import CodeChunk, VaultChunk
from ..indexer._chunk_producer import (
    WeightedCodeSegmentQueue,
    drain_code_chunks,
)
from ..indexer._consumer_pipeline import CodeConsumerPipeline
from ..indexer._run_policy import DurableProgressKind, RunPolicy
from ..indexer._streaming import (
    CodeFileSegment,
    CodeFileSegmentRequest,
    WeightedCodeSlice,
    _dense_vector_to_list,
    _release_vector_fields,
    _transfer_to_cpu,
    estimate_code_chunk_bytes,
    iter_code_file_segments,
    iter_weighted_code_slices,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _chunk(
    chunk_id: str,
    *,
    path: str = "src/example.py",
    content: str = "def example() -> int:\n    return 1\n",
) -> CodeChunk:
    return CodeChunk(
        id=chunk_id,
        path=path,
        language="python",
        content=content,
        line_start=1,
        line_end=2,
    )


def test_file_segments_preserve_order_and_mark_only_the_final_unit() -> None:
    chunks = [_chunk(f"chunk-{index}") for index in range(5)]

    segments = list(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=chunks,
                max_chunks=2,
                max_bytes=1_000_000,
                dense_dimension=4,
                sparse_enabled=False,
            )
        )
    )

    assert [segment.ordinal for segment in segments] == [0, 1, 2]
    assert [segment.is_file_end for segment in segments] == [False, False, True]
    assert [chunk for segment in segments for chunk in segment.chunks] == chunks
    assert all(len(segment.chunks) <= 2 for segment in segments)
    assert all(segment.path == "src/example.py" for segment in segments)


def test_file_segments_obey_the_weighted_byte_boundary() -> None:
    chunks = [_chunk(f"chunk-{index}") for index in range(3)]
    one_chunk_bytes = estimate_code_chunk_bytes(
        chunks[0],
        dense_dimension=4,
        sparse_enabled=False,
    )

    segments = list(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=chunks,
                max_chunks=10,
                max_bytes=2 * one_chunk_bytes,
                dense_dimension=4,
                sparse_enabled=False,
            )
        )
    )

    assert [len(segment.chunks) for segment in segments] == [2, 1]
    assert all(segment.estimated_bytes <= 2 * one_chunk_bytes for segment in segments)


def test_sparse_weight_reserves_the_full_supported_model_output() -> None:
    chunks = [_chunk(f"sparse-{index}") for index in range(4)]

    segments = list(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=chunks,
                max_chunks=64,
                max_bytes=8 * 1024 * 1024,
                dense_dimension=1024,
                sparse_enabled=True,
            )
        )
    )

    assert [len(segment.chunks) for segment in segments] == [3, 1]
    assert segments[0].estimated_bytes < 8 * 1024 * 1024
    assert sum(segment.estimated_bytes for segment in segments) > 8 * 1024 * 1024


def test_weighted_slice_packs_safe_segments_up_to_the_larger_queue_budget() -> None:
    files = [
        [_chunk(f"{path}-{index}", path=f"{path}.py") for index in range(3)]
        for path in ("a", "b")
    ]
    segments = list(
        chain.from_iterable(
            iter_code_file_segments(
                CodeFileSegmentRequest(
                    chunks=chunks,
                    max_chunks=64,
                    max_bytes=8 * 1024 * 1024,
                    dense_dimension=1024,
                    sparse_enabled=True,
                )
            )
            for chunks in files
        )
    )

    slices = list(
        iter_weighted_code_slices(
            segments,
            max_chunks=64,
            max_bytes=128 * 1024 * 1024,
        )
    )

    assert len(segments) == 2
    assert len(slices) == 1
    assert slices[0].segments == tuple(segments)
    assert len(slices[0].chunks) == 6


def test_file_segment_stream_rejects_cross_file_and_overweight_input() -> None:
    cross_file = [_chunk("a", path="a.py"), _chunk("b", path="b.py")]
    with pytest.raises(ValueError, match="cannot cross file boundaries"):
        list(
            iter_code_file_segments(
                CodeFileSegmentRequest(
                    chunks=cross_file,
                    max_chunks=2,
                    max_bytes=1_000_000,
                    dense_dimension=4,
                    sparse_enabled=False,
                )
            )
        )

    large = _chunk("large", content="x" * 1_000)
    with pytest.raises(ValueError, match="exceeds index_segment_max_bytes"):
        list(
            iter_code_file_segments(
                CodeFileSegmentRequest(
                    chunks=[large],
                    max_chunks=2,
                    max_bytes=100,
                    dense_dimension=4,
                    sparse_enabled=False,
                )
            )
        )


def test_empty_file_stream_has_no_durable_unit() -> None:
    assert (
        list(
            iter_code_file_segments(
                CodeFileSegmentRequest(
                    chunks=[],
                    max_chunks=2,
                    max_bytes=1_000,
                    dense_dimension=4,
                    sparse_enabled=False,
                )
            )
        )
        == []
    )


def test_file_chunk_drain_preserves_order_and_releases_source_list() -> None:
    chunks = [_chunk(f"chunk-{index}") for index in range(4)]
    expected = list(chunks)

    drained = list(drain_code_chunks(chunks))

    assert drained == expected
    assert chunks == []


def test_weighted_queue_backpressure_releases_on_consumer_transfer() -> None:
    chunks = [_chunk(f"queued-{index}") for index in range(2)]
    segments = list(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=chunks,
                max_chunks=1,
                max_bytes=1_000_000,
                dense_dimension=4,
                sparse_enabled=False,
            )
        )
    )
    queue_bytes = max(segment.estimated_bytes for segment in segments)
    segment_q = WeightedCodeSegmentQueue(max_chunks=1, max_bytes=queue_bytes)
    producer_released = threading.Event()

    segment_q.put(segments[0])

    def _put_second_segment() -> None:
        segment_q.put(segments[1], timeout=1.0)
        producer_released.set()

    producer = threading.Thread(target=_put_second_segment)
    producer.start()
    assert not producer_released.wait(0.05)
    assert segment_q.queued_chunks == 1
    assert segment_q.queued_bytes == segments[0].estimated_bytes

    assert segment_q.get(timeout=1.0) is segments[0]
    assert producer_released.wait(1.0)
    producer.join(timeout=1.0)
    assert not producer.is_alive()
    assert segment_q.get(timeout=1.0) is segments[1]
    assert segment_q.queued_chunks == 0
    assert segment_q.queued_bytes == 0

    with pytest.raises(queue.Empty):
        segment_q.get(block=False)


def test_weighted_queue_rejects_a_segment_above_its_byte_budget() -> None:
    chunk = _chunk("oversized")
    segment = next(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=[chunk],
                max_chunks=1,
                max_bytes=1_000_000,
                dense_dimension=4,
                sparse_enabled=False,
            )
        )
    )
    segment_q = WeightedCodeSegmentQueue(
        max_chunks=1,
        max_bytes=segment.estimated_bytes - 1,
    )

    with pytest.raises(ValueError, match="exceeds queue capacity"):
        segment_q.put(segment)


def test_normal_consumer_drain_extends_while_storage_progress_continues() -> None:
    chunks = [_chunk(f"drain-{index}") for index in range(4)]
    segments = list(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=chunks,
                max_chunks=1,
                max_bytes=1_000_000,
                dense_dimension=4,
                sparse_enabled=False,
            )
        )
    )
    queue_bytes = sum(segment.estimated_bytes for segment in segments)
    segment_q = WeightedCodeSegmentQueue(
        max_chunks=len(segments),
        max_bytes=queue_bytes,
    )
    for segment in segments:
        segment_q.put(segment)

    policy = RunPolicy(no_progress_timeout_seconds=0.4)
    consumed: list[CodeFileSegment] = []

    def _consume() -> None:
        while True:
            segment = segment_q.get(timeout=1.0)
            if segment is None:
                return
            time.sleep(0.15)
            consumed.append(segment)
            policy.record_durable_progress(
                kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
                label=f"stored {segment.path}#{segment.ordinal}",
            )

    consumer = threading.Thread(target=_consume, name="real-progressing-consumer")
    started = time.monotonic()
    consumer.start()
    CodeConsumerPipeline._drain_consumer(consumer, segment_q, policy)
    elapsed = time.monotonic() - started

    assert not consumer.is_alive()
    assert consumed == segments
    assert elapsed > policy.snapshot().timeout_seconds
    assert policy.snapshot().durable_progress_count == len(segments)


def test_producer_queue_wait_expires_with_the_no_progress_authority(
    tmp_path: Path,
) -> None:
    """A live consumer that drains nothing must end the wait via the clock.

    The producer's queue wait is liveness-guarded against consumer death,
    but a consumer wedged inside a CUDA or store call stays alive while
    draining nothing. Only the run's durable no-progress authority can end
    that wait, so the submission must raise its typed expiry rather than
    poll behind the live consumer forever.
    """
    from .._job_errors import JobError, JobErrorKind
    from ..indexer import _chunk_worker
    from ..indexer._chunk_producer import CodeChunkProducer, SegmentSubmission
    from ..job_control import NO_RUN_CONTROL

    chunks = [_chunk(f"parked-{index}") for index in range(2)]
    segments = list(
        iter_code_file_segments(
            CodeFileSegmentRequest(
                chunks=chunks,
                max_chunks=1,
                max_bytes=1_000_000,
                dense_dimension=4,
                sparse_enabled=False,
            )
        )
    )
    segment_q = WeightedCodeSegmentQueue(
        max_chunks=1,
        max_bytes=max(segment.estimated_bytes for segment in segments),
    )
    # Fill the queue so the second submission has to wait for a drain that
    # never comes.
    segment_q.put(segments[0])

    release = threading.Event()
    consumer = threading.Thread(target=release.wait, name="wedged-consumer")
    consumer.start()
    producer = CodeChunkProducer(
        tmp_path,
        chunk_execution_policy=_chunk_worker.ChunkExecutionPolicy(),
        prep_ctx=lambda: None,
    )
    submission = SegmentSubmission(
        segment_queue=segment_q,
        consumer=consumer,
        consumer_exceptions=[],
        on_wait=lambda _label: None,
        run_control=NO_RUN_CONTROL,
        run_policy=RunPolicy(no_progress_timeout_seconds=0.2),
    )
    failures: list[BaseException] = []
    finished = threading.Event()

    def _submit() -> None:
        try:
            producer.enqueue_segment(segments[1], submission)
        except BaseException as exc:
            # Caught broadly on purpose: the exception's type IS the assertion.
            failures.append(exc)
        finally:
            finished.set()

    submitter = threading.Thread(target=_submit, name="parked-producer")
    submitter.start()
    try:
        # Termination is itself the guarded behaviour: without the authority
        # the wait polls forever behind the live consumer.
        assert finished.wait(5.0), "producer queue wait outlived its no-progress budget"
        assert len(failures) == 1
        failure = failures[0]
        assert isinstance(failure, JobError)
        assert failure.error_kind is JobErrorKind.NO_PROGRESS_TIMEOUT
    finally:
        release.set()
        submitter.join(timeout=1.0)
        consumer.join(timeout=1.0)
    assert not submitter.is_alive()
    assert not consumer.is_alive()


def test_explicit_stream_limits_do_not_resolve_global_configuration() -> None:
    env = os.environ.copy()
    env["VAULTSPEC_RAG_INDEX_SEGMENT_MAX_CHUNKS"] = "0"
    env["VAULTSPEC_RAG_INDEX_QUEUE_MAX_CHUNKS"] = "0"
    script = """
from vaultspec_rag._store_models import CodeChunk  # absolute-import-ok
from vaultspec_rag.indexer._streaming import (  # absolute-import-ok
    CodeFileSegmentRequest,
    iter_code_file_segments,
    iter_weighted_code_slices,
)

chunk = CodeChunk(
    id="explicit",
    path="explicit.py",
    language="python",
    content="value = 1",
    line_start=1,
    line_end=1,
)
segments = list(iter_code_file_segments(
    CodeFileSegmentRequest(
        chunks=[chunk],
        max_chunks=1,
        max_bytes=1_000_000,
        dense_dimension=4,
        sparse_enabled=False,
    )
))
slices = list(iter_weighted_code_slices(
    segments,
    max_chunks=1,
    max_bytes=1_000_000,
))
assert len(slices) == 1
"""

    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr


def test_weighted_slices_pack_whole_segments_without_reordering() -> None:
    first_file = [_chunk(f"a-{index}", path="a.py") for index in range(3)]
    second_file = [_chunk("b-0", path="b.py")]
    segments = list(
        chain(
            iter_code_file_segments(
                CodeFileSegmentRequest(
                    chunks=first_file,
                    max_chunks=2,
                    max_bytes=1_000_000,
                    dense_dimension=4,
                    sparse_enabled=False,
                )
            ),
            iter_code_file_segments(
                CodeFileSegmentRequest(
                    chunks=second_file,
                    max_chunks=2,
                    max_bytes=1_000_000,
                    dense_dimension=4,
                    sparse_enabled=False,
                )
            ),
        )
    )

    slices = list(
        iter_weighted_code_slices(
            segments,
            max_chunks=2,
            max_bytes=1_000_000,
        )
    )

    assert [list(item.segments) for item in slices] == [
        [segments[0]],
        [segments[1], segments[2]],
    ]
    assert [chunk for item in slices for chunk in item.chunks] == [
        *first_file,
        *second_file,
    ]
    assert all(len(item.chunks) <= 2 for item in slices)
    assert all(item.estimated_bytes <= 1_000_000 for item in slices)


def test_segment_and_slice_types_reject_corrupt_boundaries() -> None:
    chunk = _chunk("a", path="a.py")
    with pytest.raises(ValueError, match="at least one chunk"):
        CodeFileSegment(
            path="a.py",
            ordinal=0,
            chunks=(),
            estimated_bytes=1,
            is_file_end=True,
        )
    with pytest.raises(ValueError, match="cannot cross file boundaries"):
        CodeFileSegment(
            path="b.py",
            ordinal=0,
            chunks=(chunk,),
            estimated_bytes=1,
            is_file_end=True,
        )

    segment = CodeFileSegment(
        path="a.py",
        ordinal=0,
        chunks=(chunk,),
        estimated_bytes=10,
        is_file_end=True,
    )
    with pytest.raises(ValueError, match="byte total"):
        WeightedCodeSlice(
            segments=(segment,),
            chunks=(chunk,),
            estimated_bytes=11,
        )
    with pytest.raises(ValueError, match="exactly flatten"):
        WeightedCodeSlice(
            segments=(segment,),
            chunks=(_chunk("other", path="a.py"),),
            estimated_bytes=10,
        )


def test_weighted_stream_validates_transitions_across_slice_flushes() -> None:
    first_chunk = _chunk("a-0", path="a.py")
    duplicate_chunk = _chunk("a-duplicate", path="a.py")
    first = CodeFileSegment(
        path="a.py",
        ordinal=0,
        chunks=(first_chunk,),
        estimated_bytes=10,
        is_file_end=True,
    )
    duplicate = CodeFileSegment(
        path="a.py",
        ordinal=0,
        chunks=(duplicate_chunk,),
        estimated_bytes=10,
        is_file_end=True,
    )

    with pytest.raises(ValueError, match="cannot follow a file-end marker"):
        list(
            iter_weighted_code_slices(
                [first, duplicate],
                max_chunks=1,
                max_bytes=10,
            )
        )

    unfinished = CodeFileSegment(
        path="a.py",
        ordinal=0,
        chunks=(first_chunk,),
        estimated_bytes=10,
        is_file_end=False,
    )
    next_file = CodeFileSegment(
        path="b.py",
        ordinal=0,
        chunks=(_chunk("b-0", path="b.py"),),
        estimated_bytes=10,
        is_file_end=True,
    )
    with pytest.raises(ValueError, match="must follow a file-end marker"):
        list(
            iter_weighted_code_slices(
                [unfinished, next_file],
                max_chunks=1,
                max_bytes=10,
            )
        )


def test_weight_estimate_tracks_payload_dense_and_sparse_lifetimes() -> None:
    base = _chunk("base", content="x")
    base_bytes = estimate_code_chunk_bytes(
        base,
        dense_dimension=2,
        sparse_enabled=True,
    )

    expanded = _chunk("expanded-id", content="x" * 100)
    expanded.source_path = "source/" + ("nested/" * 10) + "input.py"
    expanded.vector = [0.1] * 8
    expanded.sparse_indices = list(range(100))
    expanded.sparse_values = [0.2] * 100
    expanded_bytes = estimate_code_chunk_bytes(
        expanded,
        dense_dimension=2,
        sparse_enabled=True,
    )

    assert expanded_bytes > base_bytes
    assert expanded_bytes > estimate_code_chunk_bytes(
        expanded,
        dense_dimension=2,
        sparse_enabled=False,
    )


def test_vector_fields_are_released_from_real_chunk_types() -> None:
    code = _chunk("code")
    code.vector = [0.1, 0.2]
    code.sparse_indices = [1]
    code.sparse_values = [0.3]
    vault = VaultChunk(
        doc_id="doc",
        ordinal=0,
        chunk_count=1,
        text="body",
        path="doc.md",
        doc_type="adr",
        feature="streaming",
        date="2026-07-22",
        tags=[],
        related=[],
        title="Document",
        vector=[0.4, 0.5],
        sparse_indices=[2],
        sparse_values=[0.6],
    )

    _release_vector_fields([code, vault])

    assert code.vector == []
    assert code.sparse_indices == []
    assert code.sparse_values == []
    assert vault.vector == []
    assert vault.sparse_indices == []
    assert vault.sparse_values == []


def test_real_numpy_and_cpu_torch_rows_convert_to_store_vectors() -> None:
    numpy_row = np.asarray([1.25, 2.5], dtype=np.float32)
    assert _transfer_to_cpu(numpy_row) is numpy_row
    assert _dense_vector_to_list(numpy_row) == [1.25, 2.5]

    import torch

    torch_row = torch.tensor([3.0, 4.5], device="cpu")
    transferred = _transfer_to_cpu(torch_row)
    assert isinstance(transferred, torch.Tensor)
    assert transferred.device.type == "cpu"
    assert _dense_vector_to_list(transferred) == [3.0, 4.5]
