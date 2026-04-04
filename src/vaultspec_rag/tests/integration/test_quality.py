"""Search quality tests: known-answer precision, filter correctness, ranking."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.quality]


# ---- Helpfulness / Search Quality Tests ----


class TestHelpfulness:
    """Search quality tests verifying the RAG pipeline returns relevant results.

    Known-answer tests use needle keywords from the synthetic corpus.
    Filter tests verify metadata predicates are applied correctly.
    Ranking tests verify score ordering and graph boosts.
    """

    # -- Known-answer precision --

    def test_search_finds_audit_docs(self, rag_components):
        """'audit report security compliance' should surface audit docs."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("audit report security compliance", top_k=10)

        result_ids = [r.id for r in results]
        assert any("audit" in rid for rid in result_ids), (
            f"Expected an audit doc in top 10, got: {result_ids}"
        )

    def test_search_finds_architecture_docs(self, rag_components):
        """'architecture decision trade-offs' should surface ADR docs."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("architecture decision trade-offs", top_k=10)

        assert len(results) > 0, "Should find architecture docs"
        found = any(r.doc_type == "adr" for r in results)
        assert found, (
            f"Expected at least one ADR doc in results, "
            f"got: {[(r.id, r.doc_type) for r in results]}"
        )

    def test_search_finds_plan_docs(self, rag_components):
        """'implementation plan milestones' should surface plan docs."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search(
            "implementation plan milestones deliverables",
            top_k=10,
        )

        assert len(results) > 0, "Should find plan docs"
        found = any(r.doc_type == "plan" for r in results)
        assert found, (
            f"Expected plan docs in results, "
            f"got: {[(r.id, r.doc_type) for r in results]}"
        )

    def test_search_needle_precision(self, rag_components):
        """Searching for a needle keyword should surface the exact document."""
        from vaultspec_rag import VaultSearcher

        manifest = rag_components["manifest"]
        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        # Pick the first needle from the manifest
        needle = next(iter(manifest.needles))
        expected_doc_id = manifest.needles[needle]

        results = searcher.search(needle, top_k=3)

        assert len(results) > 0, f"Should find results for needle {needle}"
        result_ids = [r.id for r in results]
        assert expected_doc_id in result_ids, (
            f"Expected {expected_doc_id} in top 3 for needle {needle}, "
            f"got: {result_ids}"
        )

    def test_search_irrelevant_type_returns_empty(self, rag_components):
        """Searching for content that belongs to no indexed doc_type returns empty."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("croissant boulangerie patisserie", top_k=5)

        # No such content exists in the synthetic corpus
        if results:
            max_score = max(r.score for r in results)
            assert max_score < 0.10, (
                f"Irrelevant query max score ({max_score:.4f}) should be low"
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
        """'feature:<feature> ...' should return ONLY docs with that feature."""
        from vaultspec_rag import VaultSearcher

        manifest = rag_components["manifest"]
        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        # Pick a feature that has docs in the corpus
        target_feature = manifest.docs[0].feature
        searcher = VaultSearcher(root, model, store)
        results = searcher.search(
            f"feature:{target_feature} implementation",
            top_k=10,
        )

        assert len(results) > 0, f"Should find {target_feature} docs"
        for r in results:
            assert r.feature == target_feature, (
                f"Expected feature '{target_feature}', got '{r.feature}' for {r.id}"
            )

    def test_date_filter_prefix(self, rag_components):
        """'date:2026-01-01 ...' should return docs dated 2026-01-01."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search("date:2026-01-01 architecture", top_k=10)

        assert len(results) > 0, "Should find docs from 2026-01-01"
        for r in results:
            assert r.date.startswith("2026-01-01"), (
                f"Expected date starting with '2026-01-01', got '{r.date}' for {r.id}"
            )

    def test_combined_filters(self, rag_components):
        """'type:adr feature:<feature>' should return the intersection."""
        from vaultspec_rag import VaultSearcher

        manifest = rag_components["manifest"]
        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        # Find a feature that has an ADR doc
        adr_docs = [d for d in manifest.docs if d.doc_type == "adr"]
        assert adr_docs, "Synthetic corpus must have ADR docs"
        target_feature = adr_docs[0].feature

        searcher = VaultSearcher(root, model, store)
        results = searcher.search(
            f"type:adr feature:{target_feature}",
            top_k=10,
        )

        assert len(results) > 0, "Should find at least one matching doc"
        for r in results:
            assert r.doc_type == "adr", (
                f"Expected doc_type 'adr', got '{r.doc_type}' for {r.id}"
            )
            assert r.feature == target_feature, (
                f"Expected feature '{target_feature}', got '{r.feature}' for {r.id}"
            )

    # -- Ranking quality --

    def test_needle_ranks_high(self, rag_components):
        """A needle keyword should rank its target doc in top 3."""
        from vaultspec_rag import VaultSearcher

        manifest = rag_components["manifest"]
        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)

        # Test with multiple needles
        tested = 0
        for needle, expected_id in list(manifest.needles.items())[:5]:
            results = searcher.search(needle, top_k=5)
            if results:
                result_ids = [r.id for r in results]
                assert expected_id in result_ids, (
                    f"Expected {expected_id} in top 5 for needle {needle}, "
                    f"got: {result_ids}"
                )
                tested += 1
        assert tested > 0, "Should have tested at least one needle"

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
        results = searcher.search("implementation plan architecture", top_k=15)

        assert len(results) >= 2, "Need at least 2 results to compare authority"

        graph = VaultGraph(root)

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

        queries = ["architecture", "implementation", "research", "audit"]
        for q in queries:
            results = searcher.search_vault(q, top_k=5)
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
        results_3 = searcher.search("implementation plan", top_k=3)
        results_10 = searcher.search("implementation plan", top_k=10)

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
        results = searcher.search_vault("quantum physics dark matter", top_k=5)

        if results:
            max_score = max(r.score for r in results)
            relevant = searcher.search_vault("architecture decision", top_k=1)
            if relevant:
                assert max_score < relevant[0].score, (
                    f"Irrelevant query max score ({max_score:.4f}) should be "
                    f"lower than relevant query score ({relevant[0].score:.4f})"
                )

    def test_nonsense_query(self, rag_components):
        """'asdfghjkl zxcvbnm' should return empty or very low absolute scores."""
        from vaultspec_rag import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        results = searcher.search_vault("asdfghjkl zxcvbnm", top_k=5)

        if results:
            max_nonsense = max(r.score for r in results)
            assert max_nonsense < 0.10, (
                f"Nonsense query max score ({max_nonsense:.4f}) should be "
                f"below 0.10 absolute threshold"
            )
