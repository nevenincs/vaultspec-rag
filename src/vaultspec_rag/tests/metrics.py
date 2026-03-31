"""Retrieval quality metric helpers for quality tests."""

from __future__ import annotations

import math


def precision_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Fraction of top-k results that are relevant."""
    top_k = retrieved[:k]
    if not top_k:
        return 0.0
    return sum(1 for r in top_k if r in relevant) / k


def reciprocal_rank(relevant: set[str], retrieved: list[str]) -> float:
    """Reciprocal rank of the first relevant result."""
    for i, r in enumerate(retrieved):
        if r in relevant:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(relevant: set[str], retrieved: list[str], k: int) -> float:
    """Normalized Discounted Cumulative Gain at k."""

    def dcg(items: list[str]) -> float:
        return sum(
            1.0 / math.log2(i + 2) for i, r in enumerate(items[:k]) if r in relevant
        )

    ideal_count = min(len(relevant), k)
    ideal = sum(1.0 / math.log2(i + 2) for i in range(ideal_count))
    actual = dcg(retrieved)
    return actual / ideal if ideal > 0 else 0.0
