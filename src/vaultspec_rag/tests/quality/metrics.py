"""Role-aware ranking metrics for intent-aware vault search evaluation.

Scores a ranked list of result doc_ids against graded gold judgments (the
0-3 grades authored from ``rubric.py``). Gain is the grade itself, so a ranker
that puts a high-grade document (an accepted ADR under an orientation intent)
first is rewarded, while one that leads with a topically-tight but low-grade
document (the exec record that implements it) is penalised - which is exactly
the failure the rework targets and the reason topical NDCG cannot measure it.

All functions are pure: they take the ranked doc_id list and the gold mapping,
and never touch a retriever. Documents absent from ``gold`` are grade 0.
"""

from __future__ import annotations

from math import log2
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

__all__ = [
    "authoritative_at_k",
    "mrr_at_first_grade",
    "ndcg_at_k",
    "rank_of_first_grade",
    "role_precision_at_k",
]


def _gain(grade: int) -> float:
    """Exponential gain ``2**grade - 1`` used by DCG."""
    return float(2**grade - 1)


def _dcg(grades: Sequence[int]) -> float:
    """Discounted cumulative gain of grades in rank order (rank 1 first)."""
    return sum(_gain(g) / log2(rank + 1) for rank, g in enumerate(grades, start=1))


def ndcg_at_k(
    ranked: Sequence[str],
    gold: Mapping[str, int],
    k: int,
) -> float:
    """Role-aware NDCG@k with gain = the graded relevance.

    Args:
        ranked: Result doc_ids in rank order (best first).
        gold: Mapping of doc_id to graded relevance (0-3); absent = 0.
        k: Cutoff.

    Returns:
        NDCG@k in ``[0.0, 1.0]``. Returns 0.0 when no positive-grade document
        exists in ``gold`` (the ideal DCG is zero).
    """
    actual = [gold.get(doc_id, 0) for doc_id in ranked[:k]]
    ideal = sorted(gold.values(), reverse=True)[:k]
    idcg = _dcg(ideal)
    if idcg <= 0.0:
        return 0.0
    return _dcg(actual) / idcg


def rank_of_first_grade(
    ranked: Sequence[str],
    gold: Mapping[str, int],
    min_grade: int,
) -> int | None:
    """Return the 1-based rank of the first doc with grade >= ``min_grade``.

    Returns ``None`` when no such document appears in ``ranked``.
    """
    for rank, doc_id in enumerate(ranked, start=1):
        if gold.get(doc_id, 0) >= min_grade:
            return rank
    return None


def authoritative_at_k(
    ranked: Sequence[str],
    gold: Mapping[str, int],
    k: int,
    *,
    min_grade: int = 3,
) -> bool:
    """Whether a grade >= ``min_grade`` document appears in the top ``k``.

    The orientation acceptance signal: did the authoritative (default grade 3,
    i.e. accepted-ADR-class) document reach the top ``k``.
    """
    rank = rank_of_first_grade(ranked, gold, min_grade)
    return rank is not None and rank <= k


def mrr_at_first_grade(
    ranked: Sequence[str],
    gold: Mapping[str, int],
    *,
    min_grade: int = 1,
) -> float:
    """Reciprocal rank of the first doc with grade >= ``min_grade``.

    The debugging signal (with ``min_grade`` set to the gold target's grade):
    how high the single best artifact lands. Returns 0.0 when none appears.
    """
    rank = rank_of_first_grade(ranked, gold, min_grade)
    return 1.0 / rank if rank is not None else 0.0


def role_precision_at_k(
    ranked: Sequence[str],
    gold: Mapping[str, int],
    k: int,
    *,
    min_grade: int = 2,
) -> float:
    """Fraction of the top ``k`` whose grade >= ``min_grade``.

    A sanity guard against a degenerate ranker that nails rank 1 but fills the
    rest of the page with grade-0 noise. Computed over ``k`` slots (a short
    result list is penalised for the empty slots).
    """
    if k <= 0:
        return 0.0
    hits = sum(1 for doc_id in ranked[:k] if gold.get(doc_id, 0) >= min_grade)
    return hits / k
