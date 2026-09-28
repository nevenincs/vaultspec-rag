"""Concurrent search and CUDA headroom during a large index publication."""

from __future__ import annotations

import threading
from dataclasses import asdict
from typing import TYPE_CHECKING

import pytest

from ...config._settings import get_config
from ...progress import NullProgressReporter
from ...store_runtime import VaultStore
from ..benchmarks.bench_large_index_resilience import (
    CorpusSpec,
    measure_full_index,
    prepare_corpus,
    retain_benchmark_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

    from sentence_transformers import CrossEncoder

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]


class TestLargeIndexSearchHeadroom:
    """Concurrent code search remains live under bounded production load."""

    @pytest.mark.performance
    @pytest.mark.timeout(900)
    def test_search_completes_while_large_index_retains_cuda_headroom(
        self,
        tmp_path: Path,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
    ) -> None:
        from concurrent.futures import ThreadPoolExecutor

        from ... import CodebaseIndexer, VaultSearcher
        from ...memory_probe import cuda_device_total_mib

        root = tmp_path / "large-index-search-headroom"
        spec = CorpusSpec(files=256, chunks_per_file=3)
        prepare_corpus(root, spec)
        store = VaultStore(root)
        gpu_lock = threading.Lock()
        try:
            bootstrap_indexer = CodebaseIndexer(
                root,
                embedding_model,
                store,
                options=CodebaseIndexer.Options(
                    gpu_lock=gpu_lock,
                    extra_excludes=[
                        "src/acceptance_workload/**/module_*.py",
                        "!src/acceptance_workload/000/module_000000.py",
                    ],
                ),
            )
            # Incremental indexing requires a served publication. Seed one
            # file explicitly before exercising search during the full build.
            seeded = bootstrap_indexer.full_index(
                reporter=NullProgressReporter(),
                preflight=bootstrap_indexer.preflight_content(),
            )
            assert seeded.total == spec.chunks_per_file
            indexer = CodebaseIndexer(
                root,
                embedding_model,
                store,
                options=CodebaseIndexer.Options(gpu_lock=gpu_lock),
            )
            searcher = VaultSearcher(
                root,
                embedding_model,
                store,
                gpu_lock=gpu_lock,
                reranker=shared_reranker,
            )
            index_started = threading.Event()
            index_finished = threading.Event()

            def _index():
                index_started.set()
                try:
                    return measure_full_index(
                        indexer,
                        indexer.preflight_content(),
                        clean=False,
                    )
                finally:
                    index_finished.set()

            def _search(task: int) -> tuple[int, bool]:
                results = searcher.search_codebase(
                    f"acceptance workload value offset {task}",
                    top_k=5,
                )
                return len(results), index_finished.is_set()

            with ThreadPoolExecutor(max_workers=5) as pool:
                index_future = pool.submit(_index)
                assert index_started.wait(timeout=10.0)
                search_futures = [pool.submit(_search, task) for task in range(8)]
                search_outcomes = [future.result() for future in search_futures]
                measured = index_future.result()

            assert measured.result.total == spec.expected_chunks
            assert all(count > 0 for count, _finished in search_outcomes)
            assert any(not finished for _count, finished in search_outcomes), (
                "no search completed while bounded indexing was still progressing"
            )

            total_cuda_mib = cuda_device_total_mib()
            assert total_cuda_mib is not None, "no CUDA device reported total memory"
            configured_fraction = float(get_config().index_cuda_allocator_fraction)
            required_headroom_mib = total_cuda_mib * (1.0 - configured_fraction)
            observed_headroom_mib = (
                total_cuda_mib - measured.resources.peak_cuda_reserved_mib
            )
            retained_headroom = observed_headroom_mib >= required_headroom_mib - 128.0
            retain_benchmark_evidence(
                "concurrent-search-headroom",
                {
                    "files": spec.files,
                    "chunks": measured.result.total,
                    "wall_seconds": measured.wall_seconds,
                    "resources": asdict(measured.resources),
                    "searches": len(search_outcomes),
                    "nonempty_searches": sum(
                        count > 0 for count, _finished in search_outcomes
                    ),
                    "searches_completed_before_index": sum(
                        not finished for _count, finished in search_outcomes
                    ),
                    "total_cuda_mib": total_cuda_mib,
                    "configured_allocator_fraction": configured_fraction,
                    "required_headroom_mib": required_headroom_mib,
                    "observed_headroom_mib": observed_headroom_mib,
                    "headroom_tolerance_mib": 128.0,
                    "checks": {"retained_reserved_headroom": retained_headroom},
                },
            )
            assert observed_headroom_mib >= required_headroom_mib - 128.0
        finally:
            store.close()
