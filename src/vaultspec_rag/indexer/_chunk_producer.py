"""Bounded CPU chunk production and its submission into the encode queue.

Production and submission are one collaborator because they are one
back-pressure loop: the producers only ever reach the encode side through the
publish callback, and that callback blocks on the bounded queue. Splitting the
two would put a queue boundary between halves that have to agree on when to
stop, which is precisely the coupling the bound exists to express.

The producers know nothing about the GPU consumer, the run checkpoint, or the
preprocess and support-measurement accounting. Those run inside the publish
callback the caller supplies, so a caller that wants results without an encode
pipeline passes its own sink and drives the shipped code.
"""

from __future__ import annotations

import itertools
import logging
import multiprocessing
import os
import queue
import time
from collections import deque
from concurrent.futures import (
    FIRST_COMPLETED,
    Future,
    ProcessPoolExecutor,
    wait,
)
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..job_control import NO_RUN_CONTROL
from . import _chunk_worker
from ._pool_guard import spawn_pool
from ._preprocess_runner import PreprocessAbortError

if TYPE_CHECKING:
    import pathlib
    import threading
    from collections.abc import Callable, Iterable, Iterator
    from multiprocessing.context import BaseContext

    from .._store_models import CodeChunk
    from ..job_control import RunControl
    from ._chunk_worker import FileChunkResult
    from ._preprocess_config import PreprocessContext, PreprocessRule
    from ._run_policy import RunPolicy
    from ._streaming_types import CodeFileSegment

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _PoolDrainRequest:
    """Mutable worker-window state while results are drained in submission order."""

    pool: ProcessPoolExecutor
    pending: set[Future[FileChunkResult]]
    paths_iter: Iterator[pathlib.Path]
    publish_result: Callable[[FileChunkResult], bool]
    consumer_failed: Callable[[], bool]
    run_control: RunControl


@dataclass(frozen=True, slots=True)
class _PoolDrainPlan:
    """Inputs for one bounded spawned-worker drain."""

    workers: int
    ctx: BaseContext
    paths_iter: Iterator[pathlib.Path]
    window: int
    publish_result: Callable[[FileChunkResult], bool]
    consumer_failed: Callable[[], bool]
    run_control: RunControl = NO_RUN_CONTROL


@dataclass(frozen=True, slots=True)
class SingleProductionOptions:
    """Caller-owned collaborators for one ordinary-file production pass."""

    publish_result: Callable[[FileChunkResult], bool]
    consumer_failed: Callable[[], bool]
    total: list[int]
    run_control: RunControl = NO_RUN_CONTROL


@dataclass(frozen=True, slots=True)
class SegmentSubmission:
    """Queue and liveness ownership for segment publication."""

    segment_queue: WeightedCodeSegmentQueue
    consumer: threading.Thread
    consumer_exceptions: list[BaseException]
    on_wait: Callable[[str], object]
    run_control: RunControl
    #: The run's durable no-progress authority. Liveness alone cannot end the
    #: queue wait: a consumer wedged inside a CUDA or store call stays alive
    #: while draining nothing, and only this clock turns that stall into the
    #: run's typed no-progress failure instead of an unbounded poll loop.
    run_policy: RunPolicy | None = None


# Polling bound for cooperative control while the parent waits on CPU workers
# or either pipeline side waits on the bounded producer/consumer queue.
CONTROL_POLL_SECONDS = 0.1

# Maximum number of source paths handed to one batch preprocess spawn (#241).
# A batch rule's matched files are grouped into manifests of at most this many
# paths, each group running as a single pool task, so the hook's spawn cost is
# amortised across the group instead of paid per file.
BATCH_SIZE = 64

# Keep one queued single-file task behind each active worker. This absorbs the
# coordinator's result/accounting latency without retaining one Future (and
# potentially one completed chunk result) per source path on large trees.
_CHUNK_FUTURE_WINDOW_PER_WORKER = 2


class WeightedCodeSegmentQueue:
    """Thread-safe queue bounded by queued chunk and byte weights."""

    __slots__ = (
        "_condition",
        "_items",
        "_max_bytes",
        "_max_chunks",
        "_queued_bytes",
        "_queued_chunks",
    )

    def __init__(self, *, max_chunks: int, max_bytes: int) -> None:
        import threading

        if isinstance(max_chunks, bool) or max_chunks <= 0:
            raise ValueError("max_chunks must be a positive integer")
        if isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self._max_chunks = max_chunks
        self._max_bytes = max_bytes
        self._queued_chunks = 0
        self._queued_bytes = 0
        self._items: deque[CodeFileSegment | None] = deque()
        self._condition = threading.Condition()

    @property
    def queued_chunks(self) -> int:
        """Return the number of chunks waiting in the queue."""
        with self._condition:
            return self._queued_chunks

    @property
    def queued_bytes(self) -> int:
        """Return the estimated bytes waiting in the queue."""
        with self._condition:
            return self._queued_bytes

    def _can_admit(self, segment: CodeFileSegment) -> bool:
        return (
            self._queued_chunks + len(segment.chunks) <= self._max_chunks
            and self._queued_bytes + segment.estimated_bytes <= self._max_bytes
        )

    def _wait_until_admitted(
        self,
        segment: CodeFileSegment,
        *,
        block: bool,
        timeout: float | None,
    ) -> None:
        if self._can_admit(segment):
            return
        if not block:
            raise queue.Full
        if timeout is None:
            while not self._can_admit(segment):
                self._condition.wait()
            return
        deadline = time.monotonic() + timeout
        while not self._can_admit(segment):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise queue.Full
            self._condition.wait(remaining)

    def put(
        self,
        item: CodeFileSegment | None,
        block: bool = True,
        timeout: float | None = None,
    ) -> None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        if item is not None and (
            len(item.chunks) > self._max_chunks
            or item.estimated_bytes > self._max_bytes
        ):
            raise ValueError(
                f"segment {item.path!r}#{item.ordinal} exceeds queue capacity"
            )
        with self._condition:
            if item is not None:
                self._wait_until_admitted(item, block=block, timeout=timeout)
                self._queued_chunks += len(item.chunks)
                self._queued_bytes += item.estimated_bytes
            self._items.append(item)
            self._condition.notify_all()

    def get(
        self,
        block: bool = True,
        timeout: float | None = None,
    ) -> CodeFileSegment | None:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout must be a non-negative number")
        with self._condition:
            if not block and not self._items:
                raise queue.Empty
            if timeout is None:
                while not self._items:
                    self._condition.wait()
            else:
                deadline = time.monotonic() + timeout
                while not self._items:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise queue.Empty
                    self._condition.wait(remaining)
            item = self._items.popleft()
            if item is not None:
                self._queued_chunks -= len(item.chunks)
                self._queued_bytes -= item.estimated_bytes
            self._condition.notify_all()
            return item


def drain_code_chunks(chunks: list[CodeChunk]) -> Iterator[CodeChunk]:
    """Yield a file's chunks in order while releasing its source list."""
    chunks.reverse()
    while chunks:
        yield chunks.pop()


class CodeChunkProducer:
    """Produce file chunk results and submit their segments under a bound.

    One instance serves every run on a root: the per-run preprocess context is
    read through *prep_ctx* at call time rather than captured, so a run that
    rebuilds its rules is seen by the producers already holding this object.
    """

    __slots__ = ("_chunk_execution_policy", "_prep_ctx", "_root_dir")

    def __init__(
        self,
        root_dir: pathlib.Path,
        *,
        chunk_execution_policy: _chunk_worker.ChunkExecutionPolicy,
        prep_ctx: Callable[[], PreprocessContext | None],
    ) -> None:
        """Bind the producer to one root and its per-run preprocess context.

        Args:
            root_dir: Project root every produced path is relative to.
            chunk_execution_policy: Execution policy handed to chunk workers.
            prep_ctx: Reader for the run's preprocess context, called at each
                use so a mid-run rebuild is picked up rather than captured.
        """
        self._root_dir = root_dir
        self._chunk_execution_policy = chunk_execution_policy
        self._prep_ctx = prep_ctx

    def resolve_workers(self, n_paths: int) -> int:
        """Resolve the number of chunk worker processes to use.

        Reads the ``index_chunk_workers`` config knob: ``0`` means auto
        (``os.process_cpu_count()``); any positive value is honoured verbatim.
        The result is clamped to ``[1, n_paths]`` so a tiny change set never
        spawns more workers than there are files.

        Args:
            n_paths: Number of files about to be chunked.

        Returns:
            Worker count, at least 1.
        """
        from ..config._settings import get_config

        configured = int(get_config().index_chunk_workers)
        workers = configured if configured > 0 else (os.process_cpu_count() or 1)
        return max(1, min(workers, n_paths))

    def plan_workers(self, paths: list[pathlib.Path]) -> int:
        """Decide the worker count for *paths*, gating auto mode on workload.

        Spawn workers cost ~0.3s each to start, so on small or medium trees the
        process pool loses to serial chunking (#155 benchmark). In AUTO mode
        (``index_chunk_workers=0``) the pool engages only once the total source
        size crosses ``index_parallel_min_bytes``; below that the path stays
        serial. An explicit ``index_chunk_workers`` >= 1 bypasses the gate so a
        caller can force parallelism (or serial) regardless of size.

        Args:
            paths: Files about to be chunked.

        Returns:
            Worker count; ``1`` means run the serial in-process path.
        """
        from ..config._settings import get_config

        cfg = get_config()
        workers = self.resolve_workers(len(paths))
        if workers <= 1:
            return 1
        if int(cfg.index_chunk_workers) > 0:
            return workers  # explicit request bypasses the byte gate

        min_bytes = int(cfg.index_parallel_min_bytes)
        total = 0
        for p in paths:
            try:
                total += p.stat().st_size
            except OSError:
                continue
            if total >= min_bytes:
                return workers
        return 1

    def partition_batch_work(
        self,
        paths: list[pathlib.Path],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[list[tuple[PreprocessRule, list[pathlib.Path]]], list[pathlib.Path]]:
        """Split paths into batch-rule groups and everything else (#241).

        Files matched by a ``batch = true`` rule are grouped per rule (keyed by
        rule identity - :meth:`PreprocessConfig.match` returns the same rule
        object each time) and chunked into manifests of at most
        :data:`BATCH_SIZE`, so each group runs as one batch spawn. Every other
        file - unmatched, or matched by a non-batch rule - stays a single, so
        the existing per-file flow is untouched.

        Returns:
            ``(batch_groups, singles)``: batch groups as ``(rule, paths)`` pairs
            and the single-file paths, together covering every input path.
        """
        prep = self._prep_ctx()
        if prep is None or not any(rule.batch for rule in prep.config.rules):
            # No batch rule configured: every file keeps the per-file flow and
            # pays zero extra per-path match cost.
            return [], list(paths)

        groups: dict[int, list[pathlib.Path]] = {}
        rules: dict[int, PreprocessRule] = {}
        singles: list[pathlib.Path] = []
        for p in paths:
            run_control.checkpoint()
            try:
                rel = str(p.relative_to(self._root_dir)).replace("\\", "/")
            except ValueError:
                singles.append(p)
                continue
            rule = prep.config.match(rel)
            if rule is not None and rule.batch and rule.command is not None:
                rid = id(rule)
                groups.setdefault(rid, []).append(p)
                rules[rid] = rule
            else:
                singles.append(p)
            run_control.checkpoint()

        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]] = []
        for rid, group in groups.items():
            run_control.checkpoint()
            rule = rules[rid]
            for start in range(0, len(group), BATCH_SIZE):
                batch_groups.append((rule, group[start : start + BATCH_SIZE]))
            run_control.checkpoint()
        return batch_groups, singles

    def run_batch_groups(
        self,
        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]],
        handle_group: Callable[[list[FileChunkResult]], None],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Run batch groups through a bounded spawned-worker window."""
        prep = self._prep_ctx()
        if not batch_groups or prep is None:
            return
        workers = self.resolve_workers(len(batch_groups))
        if workers <= 1:
            self._run_batch_groups_serial(
                batch_groups, handle_group, run_control=run_control
            )
            return

        completed = 0
        ctx = multiprocessing.get_context("spawn")
        try:
            with spawn_pool(max_workers=workers, mp_context=ctx) as pool:
                group_iter = iter(batch_groups)
                futures: dict[Future[list[FileChunkResult]], int] = {}

                def _submit_one() -> bool:
                    run_control.checkpoint()
                    try:
                        rule, group = next(group_iter)
                    except StopIteration:
                        return False
                    future = pool.submit(
                        _chunk_worker.chunk_batch_files,
                        group,
                        self._root_dir,
                        rule,
                        prep,
                        self._chunk_execution_policy,
                    )
                    futures[future] = len(group)
                    run_control.checkpoint()
                    return True

                try:
                    for _ in range(min(len(batch_groups), workers)):
                        _submit_one()
                    while futures:
                        run_control.checkpoint()
                        done, _pending = wait(
                            set(futures),
                            timeout=CONTROL_POLL_SECONDS,
                            return_when=FIRST_COMPLETED,
                        )
                        run_control.checkpoint()
                        while done:
                            completed += self._process_batch_future(
                                done.pop(), futures, handle_group
                            )
                            run_control.checkpoint()
                            _submit_one()
                except BaseException:
                    for future in futures:
                        future.cancel()
                    raise
        except BrokenProcessPool:
            if completed:
                logger.error(
                    "Batch process pool broke after %d files; aborting",
                    completed,
                )
                raise
            logger.warning(
                "Batch process pool could not start; running batch groups serially"
            )
            self._run_batch_groups_serial(
                batch_groups, handle_group, run_control=run_control
            )

    def _process_batch_future(
        self,
        future: Future[list[FileChunkResult]],
        futures: dict[Future[list[FileChunkResult]], int],
        handle_group: Callable[[list[FileChunkResult]], None],
    ) -> int:
        """Publish one completed worker group, propagating fatal failures."""
        group_len = futures.pop(future)
        try:
            results = future.result()
        except BrokenProcessPool:
            raise
        except PreprocessAbortError:
            raise
        except Exception:
            logger.error(
                "Batch worker failed for a group of %d files",
                group_len,
                exc_info=True,
            )
            raise
        handle_group(results)
        return group_len

    def _run_batch_groups_serial(
        self,
        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]],
        handle_group: Callable[[list[FileChunkResult]], None],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Run batch groups serially in-process."""
        prep = self._prep_ctx()
        if prep is None:
            return
        for rule, group in batch_groups:
            run_control.checkpoint()
            results = _chunk_worker.chunk_batch_files(
                group,
                self._root_dir,
                rule,
                prep,
                self._chunk_execution_policy,
            )
            handle_group(results)
            run_control.checkpoint()

    def _run_serial_chunk_producer(
        self,
        paths: list[pathlib.Path],
        publish_result: Callable[[FileChunkResult], bool],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> int:
        """Produce file results serially into the bounded queue."""
        produced = 0
        for path in paths:
            run_control.checkpoint()
            try:
                result = _chunk_worker.chunk_and_hash_file(
                    path,
                    self._root_dir,
                    self._prep_ctx(),
                    self._chunk_execution_policy,
                )
            except PreprocessAbortError:
                raise
            except Exception:
                logger.warning("Failed to chunk %s", path, exc_info=True)
                raise
            run_control.checkpoint()
            if not publish_result(result):
                run_control.checkpoint()
                raise RuntimeError("code-index segment consumer terminated")
            produced += 1
            run_control.checkpoint()
        return produced

    def produce_batch_groups(
        self,
        batch_groups: list[tuple[PreprocessRule, list[pathlib.Path]]],
        publish_result: Callable[[FileChunkResult], bool],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Produce batch-preprocessed results into the weighted queue."""

        def _publish_group(results: list[FileChunkResult]) -> None:
            for result in results:
                run_control.checkpoint()
                if not publish_result(result):
                    run_control.checkpoint()
                    raise RuntimeError("code-index segment consumer terminated")
                run_control.checkpoint()

        self.run_batch_groups(batch_groups, _publish_group, run_control=run_control)

    def _drain_pool(
        self,
        plan: _PoolDrainPlan,
    ) -> tuple[bool, bool, int]:
        """Drain a bounded spawned-worker window into the consumer."""
        broke = False
        consumer_died = False
        advanced = 0
        try:
            with spawn_pool(max_workers=plan.workers, mp_context=plan.ctx) as pool:
                pending: set[Future[FileChunkResult]] = set()
                try:
                    self._submit_pool_window(
                        pool,
                        itertools.islice(plan.paths_iter, plan.window),
                        pending,
                        plan.run_control,
                    )
                    consumer_died, advanced = self._drain_pending_pool(
                        _PoolDrainRequest(
                            pool=pool,
                            pending=pending,
                            paths_iter=plan.paths_iter,
                            publish_result=plan.publish_result,
                            consumer_failed=plan.consumer_failed,
                            run_control=plan.run_control,
                        )
                    )
                except BaseException:
                    for future in pending:
                        future.cancel()
                    raise
        except BrokenProcessPool:
            broke = True
        return broke, consumer_died, advanced

    def _submit_pool_window(
        self,
        pool: ProcessPoolExecutor,
        paths: Iterator[pathlib.Path],
        pending: set[Future[FileChunkResult]],
        run_control: RunControl,
    ) -> None:
        """Fill the initial bounded worker window before waiting on results."""
        for path in paths:
            run_control.checkpoint()
            pending.add(
                pool.submit(
                    _chunk_worker.chunk_and_hash_file,
                    path,
                    self._root_dir,
                    self._prep_ctx(),
                    self._chunk_execution_policy,
                )
            )
            run_control.checkpoint()

    def _drain_pending_pool(self, request: _PoolDrainRequest) -> tuple[bool, int]:
        """Drain submitted workers, stopping immediately when the consumer dies."""
        advanced = 0
        consumer_died = False
        while request.pending and not consumer_died:
            request.run_control.checkpoint()
            if request.consumer_failed():
                consumer_died = True
                break
            done, request.pending = wait(
                request.pending,
                timeout=CONTROL_POLL_SECONDS,
                return_when=FIRST_COMPLETED,
            )
            request.run_control.checkpoint()
            for future in done:
                died, advanced_inc = self._process_future(
                    future,
                    request,
                )
                advanced += advanced_inc
                if died:
                    consumer_died = True
                    break
        if consumer_died:
            for future in request.pending:
                future.cancel()
        return consumer_died, advanced

    def _process_future(
        self,
        future: Future[FileChunkResult],
        request: _PoolDrainRequest,
    ) -> tuple[bool, int]:
        """Publish one worker result and refill its bounded slot."""
        request.run_control.checkpoint()
        try:
            result = future.result()
        except BrokenProcessPool:
            raise
        except PreprocessAbortError:
            raise
        except Exception:
            logger.warning("Worker failed to chunk a file", exc_info=True)
            raise
        request.run_control.checkpoint()
        died = not request.publish_result(result)
        request.run_control.checkpoint()
        if died:
            return True, 1
        next_path = next(request.paths_iter, None)
        if next_path is not None:
            request.run_control.checkpoint()
            request.pending.add(
                request.pool.submit(
                    _chunk_worker.chunk_and_hash_file,
                    next_path,
                    self._root_dir,
                    self._prep_ctx(),
                    self._chunk_execution_policy,
                )
            )
            request.run_control.checkpoint()
        return False, 1

    def produce_singles(
        self,
        singles: list[pathlib.Path],
        options: SingleProductionOptions,
    ) -> int:
        """Produce ordinary files serially or through the CPU pool."""
        workers = self.plan_workers(singles)
        if workers <= 1:
            return self._run_serial_chunk_producer(
                singles,
                options.publish_result,
                run_control=options.run_control,
            )
        ctx = multiprocessing.get_context("spawn")
        window = min(
            len(singles),
            max(1, _CHUNK_FUTURE_WINDOW_PER_WORKER * workers),
        )
        broke, _consumer_died, advanced = self._drain_pool(
            _PoolDrainPlan(
                workers=workers,
                ctx=ctx,
                paths_iter=iter(singles),
                window=window,
                publish_result=options.publish_result,
                consumer_failed=options.consumer_failed,
                run_control=options.run_control,
            )
        )
        if not broke:
            return advanced
        if advanced or options.total[0]:
            logger.error(
                "Chunk process pool broke after %d files (%d chunks embedded); "
                "aborting. Set index_chunk_workers=1 to force the serial path.",
                advanced,
                options.total[0],
            )
            raise BrokenProcessPool("codebase chunk process pool broke mid-run")
        logger.warning(
            "Chunk process pool could not start; running chunk + embed serially"
        )
        return self._run_serial_chunk_producer(
            singles,
            options.publish_result,
            run_control=options.run_control,
        )

    def enqueue_segment(
        self,
        segment: CodeFileSegment,
        submission: SegmentSubmission,
    ) -> bool:
        """Place one segment on the bounded queue while the consumer is live.

        *on_wait* is called each time the queue refuses the segment, so the
        caller samples whatever it enforces while production is parked.
        """
        while not submission.consumer_exceptions and submission.consumer.is_alive():
            submission.run_control.checkpoint()
            try:
                submission.segment_queue.put(segment, timeout=CONTROL_POLL_SECONDS)
            except queue.Full:
                if submission.run_policy is not None:
                    submission.run_policy.checkpoint("code producer queue wait")
                submission.on_wait("code producer queue wait")
                continue
            submission.run_control.checkpoint()
            return True
        return False

    def submit_segments(
        self,
        segments: Iterable[CodeFileSegment],
        submission: SegmentSubmission,
    ) -> bool:
        """Submit every segment, stopping as soon as the consumer is gone."""
        return all(self.enqueue_segment(segment, submission) for segment in segments)
