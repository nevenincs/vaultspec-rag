"""Regression: vault search results carry status and related from the payload.

Exercises the full extract -> payload -> search path on a freshly indexed
synthetic corpus (which now emits the three ADR heading formats and pipeline
edges). Confirms that ADR status reaches the result object with the right
value, that legacy/no-marker ADRs resolve to empty status, that related-edge
stems are surfaced, and that the displayed title no longer leaks the status
marker.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from ... import VaultSearcher
    from ..conftest import RagComponentsWithManifest

pytestmark = [pytest.mark.quality]


def _searcher(components: RagComponentsWithManifest) -> VaultSearcher:
    from ... import VaultSearcher

    return VaultSearcher(
        components["root"], components["model"], components["store"]
    )


class TestVaultPayloadFields:
    """Status and related must survive indexing and reach SearchResult."""

    def test_modern_adr_status_is_extracted(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """An ADR with a modern status marker surfaces that exact status."""
        manifest = rag_components["manifest"]
        target = next(
            d
            for d in manifest.docs
            if d.doc_type == "adr" and d.status not in ("", "unknown")
        )
        results = _searcher(rag_components).search_vault(target.needle, top_k=5)
        match = next((r for r in results if r.id == target.doc_id), None)
        assert match is not None, f"expected {target.doc_id} for needle {target.needle}"
        assert match.status == target.status

    def test_legacy_adr_status_is_empty(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """The legacy no-marker ADR heading resolves to empty status."""
        manifest = rag_components["manifest"]
        target = next(
            d for d in manifest.docs if d.doc_type == "adr" and d.status == "unknown"
        )
        results = _searcher(rag_components).search_vault(target.needle, top_k=5)
        match = next((r for r in results if r.id == target.doc_id), None)
        assert match is not None, f"expected {target.doc_id} for needle {target.needle}"
        assert match.status == ""

    def test_related_edges_surface(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """A document with related edges exposes them on the result."""
        manifest = rag_components["manifest"]
        target = next(d for d in manifest.docs if d.related_ids)
        results = _searcher(rag_components).search_vault(target.needle, top_k=5)
        match = next((r for r in results if r.id == target.doc_id), None)
        assert match is not None, f"expected {target.doc_id} for needle {target.needle}"
        assert isinstance(match.related, list)
        assert match.related, "a linked document must surface its related edges"

    def test_title_omits_status_marker(
        self, rag_components: RagComponentsWithManifest
    ) -> None:
        """No result title leaks the raw status marker."""
        results = _searcher(rag_components).search_vault(
            "architecture decision trade-offs", top_k=10
        )
        assert results, "expected ADR results for the architecture query"
        for r in results:
            assert "(**status:" not in r.title, f"status marker leaked into {r.title!r}"
