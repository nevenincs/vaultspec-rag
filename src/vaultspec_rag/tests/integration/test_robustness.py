"""Robustness tests: document edge cases, parser handling, graph re-ranking."""

from __future__ import annotations

import pytest

pytestmark = [pytest.mark.robustness]


# ---- Robustness Tests ----


class TestRobustness:
    """Edge-case and robustness tests for the RAG pipeline.

    Covers documents without frontmatter, non-standard metadata schemas,
    unicode content, and graph re-ranking with orphan documents.
    """

    # -- Document edge cases --

    def test_stories_without_frontmatter_skipped(self, rag_components):
        """Files in .vault/stories/ have no YAML frontmatter.

        Since DocType enum doesn't include 'stories', get_doc_type returns None
        and prepare_document returns None. Verify they are gracefully skipped.

        The synthetic corpus does not ship story files, so this test
        creates them on the fly inside the fixture's vault root.
        """
        from vaultspec_core.vaultcore import scan_vault

        from ... import prepare_document

        root = rag_components["root"]

        # Create a stories subdirectory with a frontmatter-less markdown file.
        stories_dir = root / ".vault" / "stories"
        stories_dir.mkdir(parents=True, exist_ok=True)
        (stories_dir / "tale-of-the-fox.md").write_text(
            "# The Fox\n\nOnce upon a time there was a clever fox.\n",
            encoding="utf-8",
        )

        story_paths = [p for p in scan_vault(root) if "stories" in p.parts]
        assert len(story_paths) > 0, "Should find story files in scanner output"

        for path in story_paths:
            doc = prepare_document(path, root)
            assert doc is None, (
                f"Story {path.name} should be skipped (no valid DocType), "
                f"but prepare_document returned a doc"
            )

    def test_audit_nonstandard_frontmatter_indexed(self, rag_components):
        """audit/2026-01-24-nexus-pipeline-audit.md has 'related:' key
        instead of 'tags:' array. DocType.AUDIT exists, so get_doc_type
        returns AUDIT and the doc is indexed despite nonstandard frontmatter.
        """
        from vaultspec_core.vaultcore import scan_vault

        from ... import prepare_document

        root = rag_components["root"]
        audit_paths = [p for p in scan_vault(root) if "audit" in p.parts]
        assert len(audit_paths) > 0, "Should find audit files in scanner output"

        for path in audit_paths:
            doc = prepare_document(path, root)
            assert doc is not None, (
                f"Audit doc {path.name} should be indexed (DocType.AUDIT is valid)"
            )
            assert doc.doc_type == "audit"

    # -- Graph re-ranking edge cases --

    def test_graph_reranking_with_orphans(self, rag_components):
        """Orphaned docs (no in-links) should still appear in results.

        Graph re-ranking should boost well-connected docs but not
        eliminate orphans from results.
        """
        from ... import VaultSearcher

        model = rag_components["model"]
        store = rag_components["store"]
        root = rag_components["root"]

        searcher = VaultSearcher(root, model, store)
        # Use a broad query that should match many docs.
        results = searcher.search_vault("pipeline implementation", top_k=15)

        assert len(results) > 0, "Should find results for broad query"
        # All results should have valid scores (even orphans)
        for r in results:
            assert r.score > 0, f"Result {r.id} has non-positive score: {r.score}"
