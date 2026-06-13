"""Graph-aware re-ranking of vault search results.

Boosts vault hits using VaultGraph relationship data (in-link count
and neighbor feature-tag matches) and re-sorts the combined list.
Codebase hits pass through unchanged.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pathlib

    from vaultspec_core.graph import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
        VaultGraph,
    )

    from ._models import ParsedQuery, SearchResult

logger = logging.getLogger(__name__)


# Additive nudge magnitudes. The reranker emits calibrated [0, 1]
# scores; structural graph signals must only break ties and near-ties,
# never override semantic relevance. The in-link nudge tops out at one
# typical rank-gap (matching PREFER_SCORE_NUDGE's scale) and the
# feature-neighbor nudge is roughly half of one.
_IN_LINK_NUDGE_STEP = 0.005
_IN_LINK_NUDGE_CAP = 10
_FEATURE_NEIGHBOR_NUDGE = 0.03


def _boost_vault_result(
    result: SearchResult, graph: VaultGraph, feature_filter: str | None
) -> None:
    node = graph.nodes.get(result.id)
    if node is None:
        return

    in_link_count = len(node.in_links)
    result.score += _IN_LINK_NUDGE_STEP * min(in_link_count, _IN_LINK_NUDGE_CAP)

    if feature_filter:
        feature_tag = f"#{feature_filter}"
        neighbor_has_feature = False
        for neighbor_name in node.out_links | node.in_links:
            neighbor = graph.nodes.get(neighbor_name)
            if neighbor and feature_tag in neighbor.tags:
                neighbor_has_feature = True
                break
        if neighbor_has_feature:
            result.score += _FEATURE_NEIGHBOR_NUDGE


def rerank_with_graph(
    results: list[SearchResult],
    root_dir: pathlib.Path,
    query: ParsedQuery,
    graph: VaultGraph | None = None,
) -> list[SearchResult]:
    """Apply bounded graph-aware score nudges to vault search results.

    Adds a small tie-breaking nudge for in-link count (capped at one
    typical rank-gap) and for neighbor feature-tag matches. Codebase
    results pass through unmodified. The combined list is re-sorted
    by score descending.

    Args:
        results: Mixed vault/codebase results to rerank.
        root_dir: Project root used to build a VaultGraph when
            *graph* is ``None``.
        query: Parsed query; its ``feature`` filter drives the
            neighbor-feature boost.
        graph: Pre-built graph.  When ``None``, a new VaultGraph
            is constructed from *root_dir*.

    Returns:
        Re-sorted list of SearchResult with updated scores.
    """
    vault_results = [r for r in results if r.source == "vault"]
    code_results = [r for r in results if r.source == "codebase"]

    if not vault_results:
        return results

    if graph is None:
        from vaultspec_core.graph import (  # pyright: ignore[reportMissingTypeStubs]  # vaultspec_core ships no stubs
            VaultGraph as _VaultGraph,
        )

        try:
            graph = _VaultGraph(root_dir)
        except Exception as e:
            logger.error("Graph build failed: %s", e)
            return results

    feature_filter = query.filters.get("feature")
    for result in vault_results:
        _boost_vault_result(result, graph, feature_filter)

    all_results = vault_results + code_results
    all_results.sort(key=lambda r: r.score, reverse=True)
    return all_results
