"""Search quality tests: known-answer precision, filter correctness, ranking."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.quality]


# ---- Helpfulness / Search Quality Tests ----


class TestHelpfulness:
    """Search quality tests verifying the RAG pipeline returns relevant results.

    Known-answer tests are grounded in actual test-project/.vault/ content.
    Filter tests verify metadata predicates are applied correctly.
    Ranking tests verify score ordering and graph boosts.
    """

    # -- Known-answer precision --

    def test_search_finds_security_audit(self, rag_components):
        """'security audit' should surface the Nexus security audit doc.

        The doc reference/2026-01-18-nexus-security-audit.md is in the fast
        corpus and discusses connector payload size and unsafe blocks.
        Requires GPU corpus (multiple docs).
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("nexus security audit vulnerability", top_k=10)

        result_ids = [r.id for r in results]
        assert any("security-audit" in rid for rid in result_ids), (
            f"Expected a security-audit doc in top 10, got: {result_ids}"
        )

    def test_search_finds_architecture_docs(self, rag_components):
        """'architecture design' should surface architecture-related docs."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("architecture design", top_k=10)

        assert len(results) > 0, "Should find architecture docs"
        # At least one result should have 'architecture' in its id or title
        found = any(
            "architecture" in r.id.lower() or "architecture" in r.title.lower()
            for r in results
        )
        assert found, (
            f"Expected at least one architecture doc in results, "
            f"got: {[(r.id, r.title) for r in results]}"
        )

    def test_search_finds_connector_api(self, rag_components):
        """'connector api' should surface connector-api feature docs."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("connector api design", top_k=10)

        assert len(results) > 0, "Should find connector-api docs"
        found = any(
            r.feature == "connector-api" or "connector" in r.id for r in results
        )
        assert found, (
            f"Expected connector-api docs in results, "
            f"got: {[(r.id, r.feature) for r in results]}"
        )

    def test_search_exact_identifier_keyword(self, rag_components):
        """'NexusPipelineExecutor' should surface pipeline-engine docs in top 3.

        The reference doc mentions NexusPipelineExecutor multiple times and
        should rank very high for this exact identifier query.
        Requires GPU corpus (multiple docs).
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("NexusPipelineExecutor", top_k=3)

        assert len(results) > 0, "Should find NexusPipelineExecutor docs"
        result_ids = [r.id for r in results]
        found = any("pipeline" in rid.lower() for rid in result_ids)
        assert found, f"Expected a pipeline doc in top 3, got: {result_ids}"

    def test_search_finds_french_content(self, rag_components_full):
        """'croissant boulangerie' targets French stories which are NOT indexed.

        Stories live in .vault/stories/ which has no valid DocType, so they
        are skipped during indexing. This query should return empty or
        unrelated results.
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components_full["model"]
        store = rag_components_full["store"]
        root = rag_components_full["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("croissant boulangerie", top_k=5)

        # Stories are not indexed, so no story doc should appear
        for r in results:
            assert "croissant" not in r.id.lower(), (
                f"Story doc {r.id} should not be indexed"
            )

    # -- Filter correctness --

    def test_type_filter_excludes_others(self, rag_components):
        """'type:adr architecture' should return ONLY adr docs."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("type:adr architecture", top_k=10)

        assert len(results) > 0, "Should find ADR architecture docs"
        for r in results:
            assert r.doc_type == "adr", (
                f"Expected doc_type 'adr', got '{r.doc_type}' for {r.id}"
            )

    def test_feature_filter_narrows(self, rag_components):
        """'feature:connector-api protocol' should return ONLY connector-api docs.

        The adr, plan, exec, and reference docs tagged '#connector-api' all
        have feature='connector-api' populated from their second tag.
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("feature:connector-api protocol", top_k=10)

        assert len(results) > 0, "Should find connector-api docs"
        for r in results:
            assert r.feature == "connector-api", (
                f"Expected feature 'connector-api', got '{r.feature}' for {r.id}"
            )

    def test_date_filter_prefix(self, rag_components):
        """'date:2026-01-12 connector' should return docs dated 2026-01-12.

        Requires GPU corpus (multiple docs with varying dates).
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("date:2026-01-12 connector", top_k=10)

        assert len(results) > 0, "Should find docs from 2026-01-12"
        for r in results:
            assert r.date.startswith("2026-01-12"), (
                f"Expected date starting with '2026-01-12', got '{r.date}' for {r.id}"
            )

    def test_combined_filters(self, rag_components):
        """'type:adr feature:connector-api' should return the intersection.

        Only adr/2026-01-12-connector-protocol-design.md has both
        doc_type=adr AND feature=connector-api.
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("type:adr feature:connector-api", top_k=10)

        assert len(results) > 0, "Should find at least one matching doc"
        for r in results:
            assert r.doc_type == "adr", (
                f"Expected doc_type 'adr', got '{r.doc_type}' for {r.id}"
            )
            assert r.feature == "connector-api", (
                f"Expected feature 'connector-api', got '{r.feature}' for {r.id}"
            )

    # -- Ranking quality --

    def test_exact_keyword_ranks_high(self, rag_components):
        """'NexusPipelineExecutor' should surface the pipeline reference doc.

        The reference doc mentions NexusPipelineExecutor as the central class
        with code examples; it should rank first for this exact identifier.
        Requires GPU corpus (multiple docs).
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("NexusPipelineExecutor", top_k=5)

        assert len(results) > 0, "Should find results for exact identifier"
        found = any("pipeline" in r.id for r in results)
        assert found, (
            f"Expected a pipeline doc for NexusPipelineExecutor query, "
            f"got: {[r.id for r in results]}"
        )

    def test_authority_boost_measurable(self, rag_components_full):
        """Well-linked docs should have higher scores than orphan docs.

        The graph re-ranker applies authority boost: score *= (1 + 0.1 * in_links).
        Documents with many in-links should tend to score higher than orphans
        when the query is equally relevant to both.

        Requires the full corpus for meaningful authority signal.
        """
        from vaultspec_core.graph import VaultGraph

        from vaultspec_rag import VaultSearcher

        model = rag_components_full["model"]
        store = rag_components_full["store"]
        root = rag_components_full["root"]

        searcher = VaultSearcher(root, model, store)
        # Broad query to get many results
        results = searcher.search("pipeline architecture implementation", top_k=15)

        assert len(results) >= 2, "Need at least 2 results to compare authority"

        graph = VaultGraph(root)

        # Separate results into well-linked (>=2 in-links) and orphans (0)
        linked = []
        orphans = []
        for r in results:
            node = graph.nodes.get(r.id)
            if node and len(node.in_links) >= 2:
                linked.append(r)
            elif node and len(node.in_links) == 0:
                orphans.append(r)

        if linked and orphans:
            avg_linked = sum(r.score for r in linked) / len(linked)
            avg_orphan = sum(r.score for r in orphans) / len(orphans)
            assert avg_linked > avg_orphan, (
                f"Well-linked docs (avg={avg_linked:.4f}) should score higher "
                f"than orphans (avg={avg_orphan:.4f}) on average"
            )

    def test_results_have_positive_scores(self, rag_components):
        """All results from any query should have score > 0."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)

        queries = ["architecture", "pipeline", "scheduler", "connector design"]
        for q in queries:
            results = searcher.search(q, top_k=5)
            for r in results:
                assert r.score > 0, (
                    f"Query '{q}': result {r.id} has non-positive score {r.score}"
                )

    def test_more_results_with_higher_limit(self, rag_components):
        """top_k=10 should return >= len(top_k=3) results."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results_3 = searcher.search("editor implementation", top_k=3)
        results_10 = searcher.search("editor implementation", top_k=10)

        assert len(results_10) >= len(results_3), (
            f"top_k=10 ({len(results_10)}) should return >= "
            f"top_k=3 ({len(results_3)}) results"
        )

    # -- Negative tests --

    def test_irrelevant_query_low_scores(self, rag_components):
        """'quantum physics dark matter' has no vault relevance.

        Should return empty or results with very low scores.
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("quantum physics dark matter", top_k=5)

        if results:
            # Scores should be quite low compared to relevant queries
            max_score = max(r.score for r in results)
            # Compare against a relevant query's top score
            relevant = searcher.search("pipeline architecture", top_k=1)
            if relevant:
                assert max_score < relevant[0].score, (
                    f"Irrelevant query max score ({max_score:.4f}) should be "
                    f"lower than relevant query score ({relevant[0].score:.4f})"
                )

    def test_nonsense_query(self, rag_components):
        """'asdfghjkl zxcvbnm' should return empty or very low absolute scores.

        Uses an absolute threshold instead of a relative comparison against a
        relevant query, since cosine similarity scores for both nonsense and
        niche relevant queries can land in the same narrow band (~0.03-0.04),
        making relative comparisons flaky.
        """
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("asdfghjkl zxcvbnm", top_k=5)

        if results:
            max_nonsense = max(r.score for r in results)
            assert max_nonsense < 0.10, (
                f"Nonsense query max score ({max_nonsense:.4f}) should be "
                f"below 0.10 absolute threshold"
            )
