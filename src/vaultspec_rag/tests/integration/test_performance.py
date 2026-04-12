"""Performance and resource-usage tests for the RAG pipeline."""

from __future__ import annotations

import os

import pytest

from vaultspec_rag.progress import NullProgressReporter

pytestmark = [pytest.mark.performance]


# ---- Performance Tests ----


class TestPerformance:
    """Performance and resource-usage tests for the RAG pipeline.

    All tests require a CUDA-enabled GPU. CPU is not supported.
    """

    # -- Timing tests --

    def test_single_query_latency(self, rag_components):
        """End-to-end search should complete within 2 seconds.

        Note: _fts_dirty starts True on VaultStore init, so the first
        search rebuilds the FTS index. We do a warmup query first to
        isolate steady-state latency from FTS rebuild cost.
        """
        import time

        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

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

    def test_batch_query_latency(self, rag_components):
        """5 sequential vault queries should complete within 5 seconds total."""
        import time

        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

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

    def test_query_embedding_latency(self, rag_components):
        """Single query embedding should complete within 500ms."""
        import time

        model = rag_components["model"]

        start = time.perf_counter()
        vec = model.encode_query("test query for latency")
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert vec.shape == (model.dimension,)
        assert elapsed_ms < 500, (
            f"Query embedding took {elapsed_ms:.0f}ms, expected < 500ms"
        )

    def test_parse_query_latency(self):
        """Query parsing (pure regex) should be sub-millisecond."""
        import time

        from vaultspec_rag import parse_query

        start = time.perf_counter()
        for _ in range(100):
            parse_query("type:adr feature:connector-api pipeline decisions")
        elapsed_ms = (time.perf_counter() - start) * 1000

        per_call_ms = elapsed_ms / 100
        assert per_call_ms < 1.0, (
            f"parse_query took {per_call_ms:.3f}ms per call, expected < 1ms"
        )

    # -- Resource tests --

    def test_store_disk_footprint(self, rag_components_full):
        """The Qdrant data directory should be under 50MB for the full corpus."""
        from vaultspec_rag.config import get_config

        cfg = get_config()
        root = rag_components_full["root"]
        db_dir = root / cfg.data_dir / cfg.qdrant_dir
        assert db_dir.exists(), f"db_dir does not exist: {db_dir}"

        total_bytes = sum(f.stat().st_size for f in db_dir.rglob("*") if f.is_file())
        total_mb = total_bytes / (1024 * 1024)

        assert total_mb < 50, f"Qdrant directory is {total_mb:.1f}MB, expected < 50MB"

    def test_index_result_has_timing(self, rag_components):
        """IndexResult should report valid timing metadata."""
        result = rag_components["index_result"]

        assert result.duration_ms > 0, "duration_ms should be positive"
        assert result.duration_ms < 900_000, (
            f"Indexing took {result.duration_ms}ms (15 min), seems too long"
        )

    def test_document_count_matches_vault(self, rag_components_full):
        """Indexed count should match scannable docs with valid DocType."""
        from vaultspec_core.vaultcore import get_doc_type, scan_vault

        root = rag_components_full["root"]
        store = rag_components_full["store"]

        valid_count = sum(
            1 for p in scan_vault(root) if get_doc_type(p, root) is not None
        )
        indexed_count = store.count()

        assert indexed_count == valid_count, (
            f"Store has {indexed_count} docs, vault has {valid_count} valid docs"
        )

    def test_graph_cache_reused_across_searches(self, rag_components):
        """VaultSearcher should reuse cached VaultGraph across searches."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)

        # First search builds graph
        searcher.search_vault("architecture", top_k=1)
        graph1 = searcher._cached_graph

        # Second search should reuse same graph instance
        searcher.search_vault("editor", top_k=1)
        graph2 = searcher._cached_graph

        assert graph1 is graph2, "Graph should be reused across searches"

    def test_graph_cache_ttl_expiry(self, rag_components):
        """VaultSearcher with TTL=0 should rebuild graph on every search."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store, graph_ttl_seconds=0)

        searcher.search_vault("architecture", top_k=1)
        graph1 = searcher._cached_graph

        searcher.search_vault("editor", top_k=1)
        graph2 = searcher._cached_graph

        assert graph1 is not graph2, "Graph should be rebuilt with TTL=0"

    def test_graph_rebuild_cost_per_query(self, rag_components):
        """Measure the cost of VaultGraph construction, which is rebuilt on
        every search call by rerank_with_graph(). VaultGraph reads every
        file in the vault twice (metadata + links pass). This test documents
        the overhead so we can track it and optimize later if needed.
        """
        import time

        from vaultspec_core.graph import VaultGraph

        root = rag_components["root"]

        start = time.perf_counter()
        graph = VaultGraph(root)
        graph_ms = (time.perf_counter() - start) * 1000

        assert len(graph.nodes) > 0
        # Document the cost - this is informational, threshold is generous
        # since graph rebuild happens on every search query
        assert graph_ms < 2000, (
            f"VaultGraph build took {graph_ms:.0f}ms, expected < 2000ms"
        )

    def test_vault_full_index_peak_rss_bounded(
        self,
        embedding_model,
        tmp_path_factory,
    ):
        """Vault full_index must not leak — peak RSS delta stays under 8 GB.

        Regression test for issue #68, where a 135-document vault
        blew the indexer RSS up to ~24 GB because per-batch CUDA
        caching-allocator blocks were never returned to the driver.
        The synthetic corpus here is sized to match the real vault.
        """
        from vaultspec_rag import VaultIndexer, VaultStore
        from vaultspec_rag.memory_probe import MemoryProbe
        from vaultspec_rag.tests.corpus import build_synthetic_vault

        # Enable the background RSS sampler for this test only.
        os.environ["VAULTSPEC_RAG_MEMORY_PROBE"] = "1"
        try:
            root = tmp_path_factory.mktemp("vault-leak-regression")
            build_synthetic_vault(root, n_docs=135, seed=68)

            store = VaultStore(root)
            try:
                indexer = VaultIndexer(root, embedding_model, store)

                probe = MemoryProbe(name="regression-#68")
                probe.checkpoint("before-index")
                result = indexer.full_index(
                    clean=True,
                    reporter=NullProgressReporter(),
                )
                probe.checkpoint("after-index")
                probe.stop()

                # Hard ceiling: +8 GB from the pre-index baseline.
                # Empirically the fix lands at ~1 GB RSS growth on a
                # 16 GB RTX 4080 SUPER, so a 8 GB headroom is large
                # enough to avoid flakes on slower hardware while still
                # locking the regression.
                baseline_mb = probe.samples[0].rss_mb
                delta_mb = probe.peak_rss_mb - baseline_mb
                assert result.added >= 120, (
                    f"Expected ~135 docs indexed, got {result.added}"
                )
                assert delta_mb < 8 * 1024, (
                    f"Peak RSS grew by {delta_mb:.0f}MB during "
                    f"full_index (baseline={baseline_mb:.0f}MB, "
                    f"peak={probe.peak_rss_mb:.0f}MB) — "
                    f"regression of #68. Report:\n{probe.report()}"
                )
            finally:
                store.close()
        finally:
            os.environ.pop("VAULTSPEC_RAG_MEMORY_PROBE", None)

    def test_incremental_noop_latency(self, rag_components_full):
        """Incremental index with no changes should be fast (< 3s).

        Requires full corpus because incremental_index() scans the full
        vault and compares against stored ids.
        """
        import time

        indexer = rag_components_full["indexer"]

        start = time.perf_counter()
        result = indexer.incremental_index(reporter=NullProgressReporter())
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert result.added == 0
        assert elapsed_ms < 3000, (
            f"No-op incremental index took {elapsed_ms:.0f}ms, expected < 3000ms"
        )
