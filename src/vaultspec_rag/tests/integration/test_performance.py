"""Performance and resource-usage tests for the RAG pipeline."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...progress import NullProgressReporter

if TYPE_CHECKING:
    from pathlib import Path

    import numpy as np
    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ...indexer import IndexResult, VaultIndexer
    from ...store import VaultStore
    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.performance]


# ---- Performance Tests ----


class TestPerformance:
    """Performance and resource-usage tests for the RAG pipeline.

    All tests require a CUDA-enabled GPU. CPU is not supported.
    """

    # -- Timing tests --

    def test_single_query_latency(self, rag_components: RagComponentsWithManifest):
        """End-to-end search should complete within 2 seconds.

        Note: _fts_dirty starts True on VaultStore init, so the first
        search rebuilds the FTS index. We do a warmup query first to
        isolate steady-state latency from FTS rebuild cost.
        """
        import time

        from ... import VaultSearcher

        model: EmbeddingModel = rag_components["model"]
        store: VaultStore = rag_components["store"]
        root: Path = rag_components["root"]

        searcher = VaultSearcher(root, model, store)

        # Warmup: ensure FTS index is built and model is warm
        searcher.search_vault("warmup", top_k=1)

        start = time.perf_counter()
        results = searcher.search_vault("architecture decision", top_k=5)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert len(results) > 0, "Should return results"
        assert elapsed_ms < 2000, (
            f"Single query took {elapsed_ms:.0f}ms, expected < 2000ms"
        )

    def test_batch_query_latency(self, rag_components: RagComponentsWithManifest):
        """5 sequential vault queries should complete within 5 seconds total."""
        import time

        from ... import VaultSearcher

        model: EmbeddingModel = rag_components["model"]
        store: VaultStore = rag_components["store"]
        root: Path = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        queries = [
            "architecture decision",
            "type:plan implementation",
            "pipeline executor dispatch",
            "connector protocol design",
            "security audit",
        ]

        # Warmup: ensure CrossEncoder is loaded and FTS index built.
        searcher.search_vault("warmup", top_k=1)

        start = time.perf_counter()
        for q in queries:
            searcher.search_vault(q, top_k=5)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 5000, (
            f"5 queries took {elapsed_ms:.0f}ms, expected < 5000ms"
        )

    def test_query_embedding_latency(self, rag_components: RagComponentsWithManifest):
        """Single query embedding should complete within 500ms."""
        import time

        model: EmbeddingModel = rag_components["model"]

        start = time.perf_counter()
        vec: np.ndarray = model.encode_query("test query for latency")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert vec.shape == (model.dimension,)
        assert elapsed_ms < 500, (
            f"Query embedding took {elapsed_ms:.0f}ms, expected < 500ms"
        )

    def test_parse_query_latency(self):
        """Query parsing (pure regex) should be sub-millisecond."""
        import time

        from ... import parse_query

        start = time.perf_counter()
        for _ in range(100):
            parse_query("type:adr feature:connector-api pipeline decisions")
        elapsed_ms = (time.perf_counter() - start) * 1000

        per_call_ms = elapsed_ms / 100
        assert per_call_ms < 1.0, (
            f"parse_query took {per_call_ms:.3f}ms per call, expected < 1ms"
        )

    # -- Resource tests --

    def test_store_disk_footprint(self, rag_components_full: RagComponentsWithManifest):
        """The Qdrant data directory should be under 50MB for the full corpus."""
        from ...config import get_config

        cfg = get_config()
        root: Path = rag_components_full["root"]
        db_dir: Path = root / cfg.data_dir / cfg.qdrant_dir
        assert db_dir.exists(), f"db_dir does not exist: {db_dir}"

        total_bytes = sum(f.stat().st_size for f in db_dir.rglob("*") if f.is_file())
        total_mb = total_bytes / (1024 * 1024)

        assert total_mb < 50, f"Qdrant directory is {total_mb:.1f}MB, expected < 50MB"

    def test_index_result_has_timing(self, rag_components: RagComponentsWithManifest):
        """IndexResult should report valid timing metadata."""
        result: IndexResult = rag_components["index_result"]

        assert result.duration_ms > 0, "duration_ms should be positive"
        assert result.duration_ms < 900_000, (
            f"Indexing took {result.duration_ms}ms (15 min), seems too long"
        )

    def test_document_count_matches_vault(
        self, rag_components_full: RagComponentsWithManifest
    ):
        """Indexed count should match scannable docs with valid DocType."""
        from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]
            get_doc_type,
            scan_vault,
        )

        root: Path = rag_components_full["root"]
        store: VaultStore = rag_components_full["store"]

        valid_count = sum(
            1 for p in scan_vault(root) if get_doc_type(p, root) is not None
        )
        indexed_count: int = store.count()

        assert indexed_count == valid_count, (
            f"Store has {indexed_count} docs, vault has {valid_count} valid docs"
        )

    def test_graph_cache_reused_across_searches(
        self, rag_components: RagComponentsWithManifest
    ):
        """VaultSearcher should reuse cached VaultGraph across searches."""
        from ... import VaultSearcher

        model: EmbeddingModel = rag_components["model"]
        store: VaultStore = rag_components["store"]
        root: Path = rag_components["root"]

        searcher = VaultSearcher(root, model, store)

        # First search builds graph
        searcher.search_vault("architecture", top_k=1)
        graph1 = searcher._cached_graph

        # Second search should reuse same graph instance
        searcher.search_vault("editor", top_k=1)
        graph2 = searcher._cached_graph

        assert graph1 is graph2, "Graph should be reused across searches"

    def test_graph_cache_ttl_expiry(self, rag_components: RagComponentsWithManifest):
        """VaultSearcher with TTL=0 should rebuild graph on every search."""
        from ... import VaultSearcher

        model: EmbeddingModel = rag_components["model"]
        store: VaultStore = rag_components["store"]
        root: Path = rag_components["root"]

        searcher = VaultSearcher(root, model, store, graph_ttl_seconds=0)

        searcher.search_vault("architecture", top_k=1)
        graph1 = searcher._cached_graph

        searcher.search_vault("editor", top_k=1)
        graph2 = searcher._cached_graph

        assert graph1 is not graph2, "Graph should be rebuilt with TTL=0"

    def test_graph_rebuild_cost_per_query(
        self, rag_components: RagComponentsWithManifest
    ):
        """Measure the cost of VaultGraph construction, which is rebuilt on
        every search call by rerank_with_graph(). VaultGraph reads every
        file in the vault twice (metadata + links pass). This test documents
        the overhead so we can track it and optimize later if needed.
        """
        import time

        from vaultspec_core.graph import (  # pyright: ignore[reportMissingTypeStubs]
            VaultGraph,
        )

        root: Path = rag_components["root"]

        start = time.perf_counter()
        graph = VaultGraph(root)  # pyright: ignore[reportUnknownVariableType]
        graph_ms = (time.perf_counter() - start) * 1000

        assert len(graph.nodes) > 0  # pyright: ignore[reportUnknownMemberType]
        # Document the cost - this is informational, threshold is generous
        # since graph rebuild happens on every search query
        assert graph_ms < 2000, (
            f"VaultGraph build took {graph_ms:.0f}ms, expected < 2000ms"
        )

    def test_vault_full_index_peak_rss_bounded(
        self,
        embedding_model: EmbeddingModel,
        tmp_path_factory: TempPathFactory,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """Vault full_index must not leak - RSS delta and wall time bounded.

        Regression guard for issue #68:

        - **Memory:** the original 135-doc corpus drove peak RSS to
          ~24 GB because per-batch CUDA caching-allocator blocks
          were never returned to the driver. After the streaming
          rebuild + per-slice ``empty_cache()`` fix, RSS delta on a
          135-doc synthetic corpus stays well under 4 GB on an
          RTX 4080 SUPER. The 4 GB ceiling here is a tight regression
          guard that still leaves headroom for slower hardware.
        - **Wall clock:** the original wall time was ~1117 s for the
          135-doc corpus (~8.3 s/doc). After the wall-clock fixes
          (length-sorted slicing, smaller encode sub-batches,
          ``max_seq_length=2048`` cap on Qwen3) the same corpus
          completes in well under 30 s on an RTX 4080 SUPER. The
          30 s ceiling here is generous (real measurements are
          ~5 s) but still locks the 200x regression.
        """
        import time

        from ... import VaultIndexer, VaultStore
        from ...memory_probe import MemoryProbe
        from ..corpus import build_synthetic_vault

        # monkeypatch.setenv scopes the mutation to this test so the
        # probe never bleeds into parallel pytest-xdist workers.
        monkeypatch.setenv("VAULTSPEC_RAG_MEMORY_PROBE", "1")

        root: Path = tmp_path_factory.mktemp("vault-leak-regression")
        build_synthetic_vault(root, n_docs=135, seed=68)

        store = VaultStore(root)
        try:
            indexer = VaultIndexer(root, embedding_model, store)

            # MemoryProbe is entered as a context manager so its
            # background sampler is always torn down - even if any
            # assertion below raises.
            with MemoryProbe(name="regression-#68") as probe:
                probe.checkpoint("before-index")
                start = time.perf_counter()
                result = indexer.full_index(
                    clean=True,
                    reporter=NullProgressReporter(),
                )
                wall_seconds = time.perf_counter() - start
                probe.checkpoint("after-index")

            baseline_mb: float = probe.samples[0].rss_mb
            delta_mb: float = probe.peak_rss_mb - baseline_mb
            assert result.added >= 120, (
                f"Expected ~135 docs indexed, got {result.added}"
            )
            # Memory ceiling: +4 GB from baseline. Empirical
            # measurement after the wall-clock fix is ~850 MB
            # delta on RTX 4080 SUPER; 4 GB leaves >4x headroom.
            assert delta_mb < 4 * 1024, (
                f"Peak RSS grew by {delta_mb:.0f}MB during full_index "
                f"(baseline={baseline_mb:.0f}MB, "
                f"peak={probe.peak_rss_mb:.0f}MB) - regression of #68 "
                f"memory fix. Report:\n{probe.report()}"
            )
            # Wall-clock ceiling: <30 s for 135 docs. Empirical
            # measurement is ~5 s on RTX 4080 SUPER; 30 s locks
            # the original 200x per-item slowdown without flaking
            # on slower hardware.
            assert wall_seconds < 30.0, (
                f"full_index of 135 docs took {wall_seconds:.1f}s, "
                f"expected <30s. Original baseline before #68 fix "
                f"was ~1117s."
            )
        finally:
            store.close()

    def test_incremental_noop_latency(
        self, rag_components_full: RagComponentsWithManifest
    ):
        """Incremental index with no changes should be fast (< 3s).

        Requires full corpus because incremental_index() scans the full
        vault and compares against stored ids.
        """
        import time

        indexer: VaultIndexer = rag_components_full["indexer"]

        start = time.perf_counter()
        result = indexer.incremental_index(reporter=NullProgressReporter())
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result.added == 0
        assert elapsed_ms < 3000, (
            f"No-op incremental index took {elapsed_ms:.0f}ms, expected < 3000ms"
        )
