"""Intent-conditioned multiplicative ranking prior for vault results.

Implements the ADR's D2 decision: after the CrossEncoder rerank and chunk
grouping, each vault result's calibrated score is multiplied by a
per-(doc_type, status) weight drawn from the active intent profile, and the
list is re-sorted. Unlike the bounded graph nudges, this prior is allowed to
override semantic relevance - deliberately, only on the type x status axis, and
only under an explicitly declared intent - so an accepted ADR can outrank the
exec record that merely echoes the query. The weights are inspectable config
(``intent_weight_profiles``); the score change is visible under ``--scores``.

Codebase results pass through unchanged: the prior is a vault-pipeline concept.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from ._models import SearchResult

__all__ = [
    "apply_intent_prior",
    "apply_status_filter",
    "apply_type_cap",
    "intent_multiplier",
]

# An ADR with no parsed status (legacy ``# ADR:`` heading) is treated as this
# status key, matching the rubric's active-by-default handling.
_UNKNOWN_STATUS = "unknown"

# Statuses an ADR counts as active/authoritative (``unknown`` covers the legacy
# no-marker heading).
_ACTIVE_STATUSES = frozenset({"accepted", "unknown"})


def intent_multiplier(
    result: SearchResult,
    profile: Mapping[str, Mapping[str, float]],
) -> float:
    """Return the combined type x status multiplier for one vault result.

    The doc_type multiplier always applies. The status multiplier applies only
    to ADRs (a legacy no-marker ADR maps to ``unknown``); every other type has
    no status axis and contributes a neutral 1.0. A type or status absent from
    the profile defaults to 1.0, so an unlisted role leaves the score unchanged.
    """
    type_weights = profile.get("type", {})
    status_weights = profile.get("status", {})
    type_mult = type_weights.get(result.doc_type, 1.0)
    if result.doc_type == "adr":
        status_key = result.status or _UNKNOWN_STATUS
        status_mult = status_weights.get(status_key, 1.0)
    else:
        status_mult = 1.0
    return type_mult * status_mult


def apply_intent_prior(
    results: list[SearchResult],
    profile: Mapping[str, Mapping[str, float]],
) -> list[SearchResult]:
    """Multiply vault scores by the intent profile weight and re-sort.

    Mutates each vault result's ``score`` in place by its type x status
    multiplier, leaves codebase results untouched, and returns the combined
    list sorted by score descending. A no-op (returns the input order) when the
    profile is empty.

    Args:
        results: Mixed vault/codebase results (already reranked and grouped).
        profile: The active intent profile, ``{"type": {...}, "status": {...}}``.

    Returns:
        The results re-sorted by the post-prior score.
    """
    if not profile:
        return results
    for result in results:
        if result.source != "vault":
            continue
        result.score *= intent_multiplier(result, profile)
    results.sort(key=lambda r: r.score, reverse=True)
    return results


def apply_type_cap(results: list[SearchResult], cap: int) -> list[SearchResult]:
    """Drop vault results beyond ``cap`` occurrences of any one doc_type.

    Walks the (already sorted) list and keeps at most ``cap`` results per vault
    doc_type, preserving order, so a run of one type cannot crowd the returned
    page out of the higher-value types. Codebase results are never capped.
    ``cap <= 0`` disables the cap (returns the list unchanged).

    Args:
        results: Ranked results (sorted; the prior has already run).
        cap: Maximum results of one vault doc_type to retain.

    Returns:
        The order-preserving filtered list.
    """
    if cap <= 0:
        return results
    counts: dict[str, int] = {}
    kept: list[SearchResult] = []
    for result in results:
        if result.source != "vault":
            kept.append(result)
            continue
        seen = counts.get(result.doc_type, 0)
        if seen >= cap:
            continue
        counts[result.doc_type] = seen + 1
        kept.append(result)
    return kept


def apply_status_filter(results: list[SearchResult], spec: str) -> list[SearchResult]:
    """Hard-filter ADR results by status; leave non-ADR results untouched.

    ``spec`` is one of: ``all`` / empty (no filter), ``active`` (keep only
    active-status ADRs), or a comma-separated set of explicit status values
    (e.g. ``accepted,proposed``). Only ADRs carry a status, so every non-ADR
    result is always retained - the filter narrows the decision records, not
    the surrounding pipeline documents. Order is preserved.

    Args:
        results: Ranked results (the prior has already run).
        spec: The requested status set.

    Returns:
        The order-preserving filtered list.
    """
    normalized = spec.strip().lower()
    if not normalized or normalized == "all":
        return results
    wanted = (
        _ACTIVE_STATUSES
        if normalized == "active"
        else {s.strip() for s in normalized.split(",") if s.strip()}
    )
    kept: list[SearchResult] = []
    for result in results:
        if result.source != "vault" or result.doc_type != "adr":
            kept.append(result)
            continue
        if (result.status or _UNKNOWN_STATUS) in wanted:
            kept.append(result)
    return kept
