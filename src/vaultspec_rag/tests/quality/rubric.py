"""Graded-relevance rubric for intent-aware vault search evaluation.

Encodes the ADR's D8 decision: a document's relevance grade (0-3) is a pure
function of the search *intent*, the document's pipeline role (``doc_type``),
and its ``status``. Grades are assigned mechanically from this declarative
table, never from a retriever's output, which is what keeps the gold
judgments non-tautological - the same corpus and rubric yield the same labels
regardless of which ranker is under test.

The grade is the gain used by the role-aware NDCG metric. The central encoded
principle: the same topical match earns a different grade depending on the
role the query intends to consume. For an orientation query an accepted ADR is
grade 3 while the exec record that implements it is grade 1, inverting the
score order the bare reranker produces.

Pure module: no I/O, no realistic exception surface.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "ACTIVE_ADR_STATUSES",
    "INACTIVE_ADR_STATUSES",
    "MAX_GRADE",
    "Intent",
    "grade_for",
    "is_active_status",
]


class Intent(StrEnum):
    """Declared search intent. Selects a column of the grade matrix.

    ``orientation`` is the default: the searcher wants the authoritative,
    active decision. ``debugging`` wants the concrete artifact that touched a
    symptom (exec records, audits, code). ``implementation`` wants the plan and
    its execution trail. The taxonomy is extensible; these three match the ADR
    rubric matrix.
    """

    ORIENTATION = "orientation"
    DEBUGGING = "debugging"
    IMPLEMENTATION = "implementation"


# ADR-status buckets. A legacy or no-marker ADR resolves to ``unknown`` at
# extraction time and is treated as active so historical decisions are not
# silently buried.
ACTIVE_ADR_STATUSES: frozenset[str] = frozenset({"accepted", "unknown"})
INACTIVE_ADR_STATUSES: frozenset[str] = frozenset(
    {"proposed", "superseded", "rejected", "deprecated"}
)

MAX_GRADE = 3

# Role keys collapse doc_type (and, for ADRs, active vs inactive status) into a
# single bucket. The matrix gives the grade for a *topically relevant* document;
# an off-topic document is grade 0 regardless of role (handled by callers, which
# only enumerate on-topic docs in the gold set).
_ADR_ACTIVE = "adr_active"
_ADR_INACTIVE = "adr_inactive"

# (intent -> role_key -> grade). Resolved from the ADR D8 rubric table; the
# documented ranges there are pinned to concrete integers here.
_MATRIX: dict[Intent, dict[str, int]] = {
    Intent.ORIENTATION: {
        _ADR_ACTIVE: 3,
        _ADR_INACTIVE: 1,
        "research": 2,
        "reference": 2,
        "plan": 1,
        "exec": 1,
        "audit": 1,
        "code": 0,
    },
    Intent.DEBUGGING: {
        _ADR_ACTIVE: 1,
        _ADR_INACTIVE: 1,
        "research": 1,
        "reference": 1,
        "plan": 1,
        "exec": 3,
        "audit": 2,
        "code": 2,
    },
    Intent.IMPLEMENTATION: {
        _ADR_ACTIVE: 2,
        _ADR_INACTIVE: 1,
        "research": 1,
        "reference": 1,
        "plan": 3,
        "exec": 2,
        "audit": 1,
        "code": 1,
    },
}


def is_active_status(status: str | None) -> bool:
    """Return True when an ADR ``status`` counts as active/authoritative.

    A missing or empty status is treated as ``unknown`` and therefore active,
    matching the extractor's legacy-ADR fallback.
    """
    normalized = (status or "unknown").strip().lower()
    return normalized in ACTIVE_ADR_STATUSES


def _role_key(doc_type: str, status: str | None) -> str:
    """Map a (doc_type, status) pair onto a matrix role key.

    ADRs split on active vs inactive status; every other type maps directly to
    its ``doc_type`` (with ``codebase`` normalised to ``code``).
    """
    dt = doc_type.strip().lower()
    if dt == "adr":
        return _ADR_ACTIVE if is_active_status(status) else _ADR_INACTIVE
    if dt in ("code", "codebase"):
        return "code"
    return dt


def grade_for(
    intent: Intent,
    doc_type: str,
    status: str | None = None,
    *,
    on_topic: bool = True,
) -> int:
    """Return the graded relevance (0-3) of a document under an intent.

    Args:
        intent: The declared search intent (matrix column).
        doc_type: The document's pipeline role (``adr``, ``plan``, ``exec``,
            ``research``, ``reference``, ``audit``, or ``code``).
        status: ADR status; ignored for non-ADR types. Missing/empty is
            treated as ``unknown`` (active).
        on_topic: When False the document is off-topic and scores 0 regardless
            of role - the precondition that role only modulates *relevant*
            documents.

    Returns:
        Integer grade in ``[0, MAX_GRADE]``. An unknown ``doc_type`` under a
        known intent scores 0 (it has no recognised pipeline role).
    """
    if not on_topic:
        return 0
    column = _MATRIX.get(intent)
    if column is None:
        return 0
    return column.get(_role_key(doc_type, status), 0)
