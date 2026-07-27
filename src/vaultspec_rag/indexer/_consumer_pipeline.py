"""Bounded CPU-produce / single GPU-consume pipeline for code chunks.

The producers (spawned worker processes or the in-process serial path) read,
hash, and chunk source files while one dedicated consumer thread encodes and
upserts completed weighted slices, so the GPU never idles waiting for the
whole tree to be chunked. Everything that keeps that handshake alive - the
bounded queue, the consumer thread's lifecycle, and turning one file's chunks
into segments the queue will admit - lives here rather than on the indexer,
which owns only the per-run state (support measurement, memory budget,
preprocess accounting) this pipeline reads and writes through the callables
it is constructed with.
"""

from __future__ import annotations

import hashlib
import logging
import queue
import time
from functools import partial
from typing import TYPE_CHECKING, NamedTuple

from .._job_errors import JobError, JobErrorKind
from ..job_control import NO_RUN_CONTROL, RunControlSignal
from ._chunk_producer import (
    CONTROL_POLL_SECONDS,
    WeightedCodeSegmentQueue,
    _SegmentSubmission,
    _SingleProductionOptions,
    drain_code_chunks,
)
from ._file_state import FileStateKind
from ._run_checkpoint import CodeRunConfiguration
from ._run_ledger_models import RunOperation
from ._streaming import (
    _release_cuda_cache,
    encode_and_upsert_code_slice,
    iter_code_file_segments,
    iter_weighted_code_slices,
)

if TYPE_CHECKING:
    import contextlib
    import pathlib
    import threading
    from collections.abc import Callable, Iterable, Iterator

    from ..embeddings import EmbeddingModel
    from ..job_control import RunControl
    from ..memory_probe import MemoryBudgetSnapshot, MemoryProbe
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._chunk_producer import CodeChunkProducer
    from ._chunk_worker import FileChunkResult
    from ._generation_lifecycle import CodeGenerationLifecycle
    from ._reuse import DonorReuseContext, ReuseStats
    from ._run_checkpoint import CodeRunCheckpoint
    from ._run_policy import RunPolicy
    from ._streaming import CodeFileSegment, WeightedCodeSlice

logger = logging.getLogger(__name__)

# Upper bound on how long pipeline shutdown waits for the GPU consumer thread
# to drain its final batch and terminate. Generous enough for any healthy
# final encode (a couple of slices) yet finite, so a wedged CUDA/Qdrant call
# escalates to a raised error instead of hanging the producer and holding the
# indexer's writer lock forever (#155).
_CONSUMER_SHUTDOWN_TIMEOUT_S = 300.0

#: Conservative chunks-per-file factor for the pre-pool disk pre-flight;
#: a measured large mixed-language tree averaged ~12 chunks per source file.
_CHUNKS_PER_FILE_ESTIMATE = 12

# The digest a zero-byte source hashes to. Comparing against it identifies an
# empty read exactly, from the hash the chunk worker already returned, without
# re-reading a file that may still be mid-write.
_EMPTY_SOURCE_DIGEST = hashlib.blake2b(b"").hexdigest()


class UnsettledCodeConsumerError(RuntimeError):
    """The code consumer remained live after its bounded shutdown wait."""


class CodePipelineLimits(NamedTuple):
    """Frozen weighted limits shared by code-index producers and consumer."""

    segment_max_chunks: int
    segment_max_bytes: int
    queue_max_chunks: int
    queue_max_bytes: int
    slice_max_chunks: int
    slice_max_bytes: int
    dense_dimension: int
    sparse_enabled: bool
    sparse_dimension: int
    encode_batch_size: int
    flush_slices: int

    @property
    def run_configuration(self) -> CodeRunConfiguration:
        """Project the limits a resumed generation must be compatible with."""
        return CodeRunConfiguration(
            segment_max_chunks=self.segment_max_chunks,
            segment_max_bytes=self.segment_max_bytes,
            queue_max_chunks=self.queue_max_chunks,
            queue_max_bytes=self.queue_max_bytes,
            slice_max_chunks=self.slice_max_chunks,
            slice_max_bytes=self.slice_max_bytes,
            sparse_enabled=self.sparse_enabled,
            sparse_dimension=self.sparse_dimension,
            encode_batch_size=self.encode_batch_size,
            flush_slices=self.flush_slices,
        )


class ChunkEmbedResult(NamedTuple):
    """What one chunk+embed pipeline run produced, for the caller to commit."""

    new_ids: set[str]
    total: int
    metadata: dict[str, str]
    reuse_stats: ReuseStats | None


class CodeConsumerPipeline:
    """Own one root's bounded code chunk-production and GPU-encode pipeline.

    Stable dependencies (the model, the store, the producer, the generation
    lifecycle) are bound once at construction, mirroring the indexer's other
    long-lived collaborators. Per-run support measurement, memory budget, and
    preprocess accounting stay owned by the indexer and are reached only
    through the callables passed in here, so this pipeline never mutates
    state it does not own.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        producer: CodeChunkProducer,
        lifecycle: CodeGenerationLifecycle,
        *,
        gpu_lock: threading.Lock | None,
        begin_memory_budget: Callable[[], None],
        sample_memory_budget: Callable[[str], MemoryBudgetSnapshot],
        forward_peak_recording: Callable[[], contextlib.AbstractContextManager[None]],
        fail_cuda_oom: Callable[[str, BaseException], None],
        begin_support_measurement: Callable[[Iterable[pathlib.Path]], None],
        measure_code_segments: Callable[
            [Iterable[CodeFileSegment]], Iterator[CodeFileSegment]
        ],
        record_extracted_bytes: Callable[[int], None],
        record_preprocess_result: Callable[[FileChunkResult], None],
    ) -> None:
        """Bind the pipeline to one root's model, store, and run bookkeeping.

        Args:
            root_dir: Project root every produced path is relative to.
            model: Embedding model the GPU consumer encodes with.
            store: Vector store the consumer upserts confirmed slices into.
            producer: The root's chunk producer, shared with the caller.
            lifecycle: The root's generation lifecycle, for drift ownership
                and checkpoint content-hash normalization.
            gpu_lock: Optional lock serializing GPU operations with search.
            begin_memory_budget: Freeze and sample one run's memory budget.
            sample_memory_budget: Enforce the current budget at a label.
            forward_peak_recording: Context manager routing this thread's
                forward-peak captures into the run's budget.
            fail_cuda_oom: Translate allocator exhaustion through the budget.
            begin_support_measurement: Measure a run's source dimensions.
            measure_code_segments: Measure generated workload per segment.
            record_extracted_bytes: Add extractor output bytes to the run.
            record_preprocess_result: Score one worker result's disposition.
        """
        self._root_dir = root_dir
        self._model = model
        self._store = store
        self._producer = producer
        self._lifecycle = lifecycle
        self._gpu_lock = gpu_lock
        self._begin_memory_budget = begin_memory_budget
        self._sample_memory_budget = sample_memory_budget
        self._forward_peak_recording = forward_peak_recording
        self._fail_cuda_oom = fail_cuda_oom
        self._begin_support_measurement = begin_support_measurement
        self._measure_code_segments = measure_code_segments
        self._record_extracted_bytes = record_extracted_bytes
        self._record_preprocess_result = record_preprocess_result

    def resolve_limits(self) -> CodePipelineLimits:
        """Freeze code segment, queue, slice, and model limits."""
        from ..config import get_config
        from ..store_schema import effective_sparse_dim

        config = get_config()
        sparse_enabled = bool(config.sparse_enabled)
        sparse_dimension = effective_sparse_dim(self._model)
        return CodePipelineLimits(
            segment_max_chunks=int(config.index_segment_max_chunks),
            segment_max_bytes=int(config.index_segment_max_bytes),
            queue_max_chunks=int(config.index_queue_max_chunks),
            queue_max_bytes=int(config.index_queue_max_bytes),
            slice_max_chunks=int(config.index_queue_max_chunks),
            slice_max_bytes=int(config.index_queue_max_bytes),
            dense_dimension=int(config.embedding_dimension),
            sparse_enabled=sparse_enabled,
            sparse_dimension=sparse_dimension,
            encode_batch_size=int(config.embedding_code_encode_batch_size),
            flush_slices=max(1, int(config.index_cache_flush_slices)),
        )

    def run(
        self,
        paths: list[pathlib.Path],
        *,
        reporter: ProgressReporter,
        checkpoint: CodeRunCheckpoint,
        limits: CodePipelineLimits,
        content_epoch: str | None,
        code_build_target: str | None,
        ingest_wait: bool = True,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> ChunkEmbedResult:
        """Overlap bounded CPU production with one weighted GPU consumer."""
        from ._donor_candidates import CollectionKind
        from ._reuse import resolve_donor_reuse

        # One donor resolution per run: the consumer thread reads the
        # resolved context per slice, outside the GPU lock.
        reuse_stats, donor_reuse = resolve_donor_reuse(
            self._root_dir,
            CollectionKind.CODE,
            self._store,
            expected_content_epoch=content_epoch or "",
        )
        new_ids: set[str] = set()
        new_ids.update(checkpoint.ledger.iter_point_ids(checkpoint.generation_id))
        if checkpoint.generation.signature.operation is not RunOperation.FULL:
            new_ids.update(
                checkpoint.ledger.iter_retained_point_ids(checkpoint.generation_id)
            )
        metadata: dict[str, str] = {}
        total = [len(new_ids)]
        self._begin_support_measurement(paths)
        # A generation build holds both collections at once, so the served
        # points are part of what has to fit. Charged through the one existing
        # estimator rather than a second sizing rule: a root that cannot afford
        # the duplicate is refused here and keeps serving what it has, which is
        # the whole reason the build never touches the served collection.
        duplicate_points = (
            self._store.count_code() if code_build_target is not None else 0
        )
        self._store.disk_headroom_preflight(
            len(paths) * _CHUNKS_PER_FILE_ESTIMATE + duplicate_points
        )
        run_control.checkpoint()
        reporter.phase_start("chunk + embed", len(paths))
        try:
            if not paths:
                return ChunkEmbedResult(new_ids, total[0], metadata, reuse_stats)
            self._begin_memory_budget()
            segment_queue = WeightedCodeSegmentQueue(
                max_chunks=limits.queue_max_chunks,
                max_bytes=limits.queue_max_bytes,
            )
            consumer_exceptions: list[BaseException] = []
            consumer = self._spawn_weighted_consumer(
                segment_queue,
                consumer_exceptions,
                limits,
                new_ids,
                total,
                metadata,
                checkpoint,
                code_build_target=code_build_target,
                donor_reuse=donor_reuse,
                ingest_wait=ingest_wait,
                run_control=run_control,
            )

            def _publish_result(result: FileChunkResult) -> bool:
                return self._enqueue_code_result(
                    result,
                    limits=limits,
                    segment_queue=segment_queue,
                    consumer=consumer,
                    consumer_exceptions=consumer_exceptions,
                    metadata=metadata,
                    checkpoint=checkpoint,
                    run_control=run_control,
                )

            producer_exception: BaseException | None = None
            try:
                batch_groups, singles = self._producer.partition_batch_work(
                    paths, run_control=run_control
                )
                if batch_groups:
                    self._producer.produce_batch_groups(
                        batch_groups,
                        _publish_result,
                        reporter,
                        run_control=run_control,
                    )
                if singles:
                    self._producer.produce_singles(
                        singles,
                        _SingleProductionOptions(
                            publish_result=_publish_result,
                            consumer_failed=lambda: (
                                bool(consumer_exceptions) or not consumer.is_alive()
                            ),
                            reporter=reporter,
                            total=total,
                            run_control=run_control,
                        ),
                    )
            except BaseException as exc:
                producer_exception = exc
            finally:
                self._finish_weighted_consumer(
                    consumer,
                    segment_queue,
                    consumer_exceptions,
                    producer_exception,
                    checkpoint,
                )
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return ChunkEmbedResult(new_ids, total[0], metadata, reuse_stats)

    def raise_code_result_failure(
        self,
        result: FileChunkResult,
        checkpoint: CodeRunCheckpoint | None,
    ) -> None:
        """Record and raise a typed failure for a non-indexable file result."""
        if self._record_empty_source(result, checkpoint):
            return
        failure = self._code_result_failure(result)
        if failure is None:
            return
        failure_state, failure_kind, detail = failure
        if checkpoint is not None:
            checkpoint.record_processing_failure(
                result.rel_path,
                failure_state,
                detail,
                content_hash=self._lifecycle.checkpoint_content_hash(
                    result.content_hash
                ),
            )
        raise JobError(failure_kind, detail)

    @staticmethod
    def _code_result_failure(
        result: FileChunkResult,
    ) -> tuple[FileStateKind, JobErrorKind, str] | None:
        """Return the durable state and typed error for a failed file result."""
        if result.preprocess_status == "skipped":
            return (
                FileStateKind.EXTRACT_RETRYABLE,
                JobErrorKind.EXTRACTION_RETRYABLE,
                result.preprocess_reason or "preprocessor skipped the file",
            )
        if result.chunks:
            return None
        if result.preprocess_status == "ok":
            return (
                FileStateKind.EXTRACT_RETRYABLE,
                JobErrorKind.EXTRACTION_RETRYABLE,
                "admitted code source produced no indexable chunks",
            )
        return (
            FileStateKind.CHUNK_FAILED,
            JobErrorKind.CHUNK_FAILED,
            "admitted code source produced no indexable chunks",
        )

    def _record_empty_source(
        self,
        result: FileChunkResult,
        checkpoint: CodeRunCheckpoint | None,
    ) -> bool:
        """Converge an empty source instead of failing the run over it.

        A file that reads as zero bytes yields no chunks, which is not a
        chunking defect - there was nothing to chunk. Treating it as one let a
        single file caught mid-save abort an entire indexing job, which is how
        one editor save became a failed generation and, through resume, a
        sustained outage.

        The rejection is stable only against the hash that evidenced it, so a
        file caught mid-save converges against the empty hash and is classified
        again under its real content once the save lands, while a genuinely
        empty file keeps that hash and stays converged. Neither retries
        forever, and neither needs the run to fail.

        Returns:
            True when the result was an empty source and has been recorded.
        """
        if result.chunks or result.content_hash != _EMPTY_SOURCE_DIGEST:
            return False
        if checkpoint is not None:
            checkpoint.record_empty_source(
                result.rel_path,
                content_hash=self._lifecycle.checkpoint_content_hash(
                    result.content_hash
                ),
            )
        logger.debug(
            "Converged empty source %s with no indexable content",
            result.rel_path,
        )
        return True

    def _enqueue_code_result(
        self,
        result: FileChunkResult,
        *,
        limits: CodePipelineLimits,
        segment_queue: WeightedCodeSegmentQueue,
        consumer: threading.Thread,
        consumer_exceptions: list[BaseException],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> bool:
        """Drain one file result into bounded weighted segments."""
        run_control.checkpoint()
        self._record_preprocess_result(result)
        self.raise_code_result_failure(result, checkpoint)
        if result.preprocess_status == "ok":
            self._record_extracted_bytes(
                sum(len(chunk.content.encode("utf-8")) for chunk in result.chunks)
            )
        metadata[result.rel_path] = result.content_hash
        segments = iter_code_file_segments(
            drain_code_chunks(result.chunks),
            max_chunks=limits.segment_max_chunks,
            max_bytes=limits.segment_max_bytes,
            dense_dimension=limits.dense_dimension,
            sparse_enabled=limits.sparse_enabled,
            sparse_dimension=limits.sparse_dimension,
            run_control=run_control,
        )
        measured_segments = self._measure_code_segments(segments)
        pending_segments = (
            checkpoint.pending_segments(measured_segments, result.content_hash)
            if checkpoint is not None
            else measured_segments
        )
        return self._producer.submit_segments(
            pending_segments,
            _SegmentSubmission(
                segment_queue=segment_queue,
                consumer=consumer,
                consumer_exceptions=consumer_exceptions,
                on_wait=self._sample_memory_budget,
                run_control=run_control,
            ),
        )

    def _iter_consumer_segments(
        self,
        segment_queue: WeightedCodeSegmentQueue,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> Iterator[CodeFileSegment]:
        """Yield queued segments until the producer supplies its sentinel."""
        while True:
            run_control.checkpoint()
            try:
                segment = segment_queue.get(timeout=CONTROL_POLL_SECONDS)
            except queue.Empty:
                self._sample_memory_budget("code consumer queue wait")
                continue
            run_control.checkpoint()
            if segment is None:
                return
            yield segment

    def _record_confirmed_slice(
        self,
        segments: tuple[CodeFileSegment, ...],
        metadata: dict[str, str],
    ) -> None:
        """Persist the file units covered by one confirmed store mutation.

        Routed through the drift owner rather than straight at the checkpoint:
        the store write has already been confirmed here, so a path that moved
        since its digest was observed must be superseded and re-recorded, not
        allowed to fail a run that has otherwise succeeded.
        """
        self._lifecycle.drift_owner.record_segments(segments, metadata)

    def _consume_weighted_slice(
        self,
        weighted_slice: WeightedCodeSlice,
        *,
        slice_index: int,
        limits: CodePipelineLimits,
        new_ids: set[str],
        total: list[int],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        probe: MemoryProbe,
        ingest_wait: bool,
        run_control: RunControl,
        code_build_target: str | None,
        donor_reuse: DonorReuseContext | None,
    ) -> None:
        """Encode, store, and account for one bounded weighted slice."""
        run_control.checkpoint()
        self._sample_memory_budget(f"slice-{slice_index}-before-encode")
        slice_chunks = sorted(
            weighted_slice.chunks,
            key=lambda chunk: -len(chunk.content),
        )
        try:
            probe.checkpoint(f"slice-{slice_index}-before-encode")
            completed_slice_index = slice_index + 1
            on_storage_confirmed = (
                partial(
                    self._record_confirmed_slice,
                    weighted_slice.segments,
                    metadata,
                )
                if checkpoint is not None
                else None
            )

            def _after_forward(kind: str) -> None:
                run_control.checkpoint()
                self._sample_memory_budget(
                    f"slice-{completed_slice_index}-after-{kind}-forward"
                )
                run_control.checkpoint()

            def _on_cuda_oom(exc: BaseException) -> None:
                self._fail_cuda_oom(
                    f"slice-{completed_slice_index}-allocator-oom",
                    exc,
                )

            # Route the lock-bracketed forward captures of this consumer
            # thread into this job's own budget, so checkpoints enforce
            # the job's demand rather than a process-wide high-water.
            with self._forward_peak_recording():
                encode_and_upsert_code_slice(
                    slice_chunks,
                    model=self._model,
                    store=self._store,
                    gpu_lock=self._gpu_lock,
                    release_cache=(completed_slice_index % limits.flush_slices == 0),
                    encode_batch_size=limits.encode_batch_size,
                    write_policy=(
                        checkpoint.run_policy.store_write_policy
                        if checkpoint is not None
                        else None
                    ),
                    ingest_wait=ingest_wait,
                    collection=code_build_target,
                    on_storage_confirmed=on_storage_confirmed,
                    after_forward=_after_forward,
                    on_cuda_oom=_on_cuda_oom,
                    run_control=run_control,
                    reuse=donor_reuse,
                )
            run_control.checkpoint()
            new_ids.update(chunk.id for chunk in slice_chunks)
            total[0] += len(slice_chunks)
            probe.checkpoint(f"slice-{completed_slice_index}-after-store")
            self._sample_memory_budget(f"slice-{completed_slice_index}-after-store")
        finally:
            del slice_chunks

    def _finish_consumer_probe(
        self,
        probe: MemoryProbe | None,
        consumer_exceptions: list[BaseException],
    ) -> None:
        """Release consumer resources while retaining every cleanup failure."""
        try:
            self._sample_memory_budget("code consumer cleanup")
        except BaseException as exc:
            consumer_exceptions.append(exc)
        try:
            _release_cuda_cache()
            if probe is not None and probe.samples:
                logger.info("%s", probe.report())
        except BaseException as exc:
            consumer_exceptions.append(exc)

    def _run_weighted_consumer(
        self,
        segment_queue: WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        limits: CodePipelineLimits,
        new_ids: set[str],
        total: list[int],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        ingest_wait: bool,
        run_control: RunControl,
        code_build_target: str | None,
        donor_reuse: DonorReuseContext | None,
    ) -> None:
        """Run the sole weighted consumer and retain failures for the producer."""
        from ..memory_probe import MemoryProbe

        probe: MemoryProbe | None = None
        try:
            probe = MemoryProbe(name="codebase-index")
            with probe:
                self._sample_memory_budget("code consumer start")
                segments = self._iter_consumer_segments(
                    segment_queue,
                    run_control=run_control,
                )
                for slice_index, weighted_slice in enumerate(
                    iter_weighted_code_slices(
                        segments,
                        max_chunks=limits.slice_max_chunks,
                        max_bytes=limits.slice_max_bytes,
                        run_control=run_control,
                    )
                ):
                    self._consume_weighted_slice(
                        weighted_slice,
                        slice_index=slice_index,
                        limits=limits,
                        new_ids=new_ids,
                        total=total,
                        metadata=metadata,
                        checkpoint=checkpoint,
                        probe=probe,
                        ingest_wait=ingest_wait,
                        run_control=run_control,
                        code_build_target=code_build_target,
                        donor_reuse=donor_reuse,
                    )
        except BaseException as exc:
            consumer_exceptions.append(exc)
        finally:
            self._finish_consumer_probe(probe, consumer_exceptions)

    def _spawn_weighted_consumer(
        self,
        segment_queue: WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        limits: CodePipelineLimits,
        new_ids: set[str],
        total: list[int],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        *,
        code_build_target: str | None,
        donor_reuse: DonorReuseContext | None,
        ingest_wait: bool = True,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> threading.Thread:
        """Start the sole GPU consumer for weighted file segments."""
        import contextvars
        import threading

        # The consumer runs under a copy of the spawning attempt's context
        # so its timed GPU-lock waits accumulate on the owning job record;
        # a bare Thread would silently detach the attribution.
        consumer = threading.Thread(
            target=contextvars.copy_context().run,
            args=(
                self._run_weighted_consumer,
                segment_queue,
                consumer_exceptions,
                limits,
                new_ids,
                total,
                metadata,
                checkpoint,
                ingest_wait,
                run_control,
                code_build_target,
                donor_reuse,
            ),
            name="codebase-indexer-consumer",
        )
        consumer.start()
        return consumer

    @staticmethod
    def _drain_consumer(
        consumer: threading.Thread,
        segment_queue: WeightedCodeSegmentQueue,
        run_policy: RunPolicy,
        sample_memory: Callable[[str], object] | None = None,
    ) -> None:
        """Finish normal work under the durable no-progress authority."""
        sentinel_delivered = False
        while consumer.is_alive() and not sentinel_delivered:
            run_policy.checkpoint("code consumer drain sentinel")
            timeout = min(
                CONTROL_POLL_SECONDS,
                run_policy.remaining_seconds(),
            )
            try:
                segment_queue.put(None, timeout=timeout)
            except queue.Full:
                if sample_memory is not None:
                    sample_memory("code consumer drain sentinel wait")
                continue
            sentinel_delivered = True
        while consumer.is_alive():
            run_policy.checkpoint("code consumer drain")
            consumer.join(
                timeout=min(
                    CONTROL_POLL_SECONDS,
                    run_policy.remaining_seconds(),
                )
            )
            if consumer.is_alive() and sample_memory is not None:
                sample_memory("code consumer drain wait")

    @staticmethod
    def _cleanup_consumer(
        consumer: threading.Thread,
        segment_queue: WeightedCodeSegmentQueue,
    ) -> bool:
        """Bound cleanup after a producer, control, or liveness failure."""
        deadline = time.monotonic() + _CONSUMER_SHUTDOWN_TIMEOUT_S
        while consumer.is_alive():
            try:
                segment_queue.put(None, timeout=CONTROL_POLL_SECONDS)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    break
        consumer.join(timeout=max(0.0, deadline - time.monotonic()))
        return consumer.is_alive()

    def _finish_weighted_consumer(
        self,
        consumer: threading.Thread,
        segment_queue: WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        producer_exception: BaseException | None,
        checkpoint: CodeRunCheckpoint,
    ) -> None:
        """Stop the consumer and preserve cleanup/error precedence."""
        drain_failure: BaseException | None = None
        if producer_exception is None:
            try:
                self._drain_consumer(
                    consumer,
                    segment_queue,
                    checkpoint.run_policy,
                    self._sample_memory_budget,
                )
            except BaseException as exc:
                drain_failure = exc
        cleanup_required = producer_exception is not None or drain_failure is not None
        if cleanup_required and self._cleanup_consumer(consumer, segment_queue):
            logger.error(
                "GPU consumer cleanup did not terminate within %.0fs after "
                "failure; aborting (a CUDA or Qdrant call may be wedged)",
                _CONSUMER_SHUTDOWN_TIMEOUT_S,
            )
            error = UnsettledCodeConsumerError(
                "codebase index GPU consumer thread did not terminate"
            )
            if drain_failure is not None:
                raise error from drain_failure
            if producer_exception is not None:
                raise error from producer_exception
            raise error
        if drain_failure is not None:
            raise drain_failure
        consumer_failure = next(
            (
                exc
                for exc in consumer_exceptions
                if not isinstance(exc, RunControlSignal)
            ),
            None,
        )
        if consumer_failure is not None:
            raise consumer_failure
        if producer_exception is not None:
            raise producer_exception
        if consumer_exceptions:
            raise consumer_exceptions[0]
