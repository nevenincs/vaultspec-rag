"""Drive the shipped code chunk-production path from tests.

The indexer streams each file's result into a bounded queue through a publish
callback, and that callback is the only sink the producers know about. A test
can therefore pass its own collecting callback and drive the exact code that
ships - no GPU consumer, no weighted queue, and no run checkpoint required.

Tests that assert anything about chunk production must go through here. A
second, test-only chunking pipeline maintained alongside the real one is worse
than no coverage: it goes green while the shipped path drifts underneath it,
and a parity assertion between two implementations that production never calls
proves nothing about production.

The collecting callback reproduces the sink's own accounting - preprocess
disposition recording and typed failure raising - because those run inside the
publish callback in the pipeline, not inside the producers. Omitting them would
silently drop the ``_prep_ok`` counts and the failure propagation that tests
assert on.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..indexer._chunk_producer import _SingleProductionOptions
from ..progress import NullProgressReporter

if TYPE_CHECKING:
    import pathlib

    from .. import CodebaseIndexer
    from .._store_models import CodeChunk
    from ..indexer._chunk_worker import FileChunkResult
    from ..progress import ProgressReporter


def produce_file_results(
    indexer: CodebaseIndexer,
    paths: list[pathlib.Path],
    *,
    reporter: ProgressReporter | None = None,
) -> list[FileChunkResult]:
    """Run *paths* through the production producers and collect the results.

    Partitions exactly as the pipeline does, then drives the batch-group and
    single-file producers with a collecting publish callback.

    Whether the singles run serially or through the spawn pool is decided by
    the production worker planner, so a caller forces a mode the same way an
    operator does - by setting the chunk-worker count in the environment.

    Args:
        indexer: A chunk-capable indexer; needs no model or vector store.
        paths: Absolute file paths to produce results for.
        reporter: Progress reporter, advanced once per file.

    Returns:
        Every file's result, ordered by relative path so a pooled run and a
        serial run of the same inputs are directly comparable.
    """
    progress = NullProgressReporter() if reporter is None else reporter
    collected: list[FileChunkResult] = []

    def _publish(result: FileChunkResult) -> bool:
        # Mirror the pipeline's sink: it records the preprocess disposition and
        # raises the typed failure before anything reaches the queue.
        indexer._record_preprocess_result(result)  # pyright: ignore[reportPrivateUsage]
        indexer._consumer_pipeline.raise_code_result_failure(  # pyright: ignore[reportPrivateUsage]
            result, None
        )
        collected.append(result)
        return True

    producer = indexer._producer  # pyright: ignore[reportPrivateUsage]
    batch_groups, singles = producer.partition_batch_work(paths)
    if batch_groups:
        producer.produce_batch_groups(batch_groups, _publish, progress)
    if singles:
        producer.produce_singles(
            singles,
            _SingleProductionOptions(
                publish_result=_publish,
                consumer_failed=lambda: False,
                reporter=progress,
                total=[0],
            ),
        )
    return sorted(collected, key=lambda result: result.rel_path)


def produce_chunks(
    indexer: CodebaseIndexer,
    paths: list[pathlib.Path],
    *,
    reporter: ProgressReporter | None = None,
) -> list[CodeChunk]:
    """Return every chunk the production path produces for *paths*.

    Chunks keep their emitted order within a file, and files are ordered by
    relative path, so two runs over the same inputs compare element-wise.
    """
    return [
        chunk
        for result in produce_file_results(indexer, paths, reporter=reporter)
        for chunk in result.chunks
    ]
