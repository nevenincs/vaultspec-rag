"""Tests for explicit combined-search partial outcomes."""

from __future__ import annotations

import ast
from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest

from .._search_state import (
    AbsenceAuthority,
    SearchAvailability,
    SearchFreshness,
    SearchSourceFact,
)
from .._source_types import IndexSource, PublicSourceType
from ..search import _outcomes
from ..search._models import DocumentSearchResult, SearchResult
from ..search._outcomes import (
    COMBINED_SEARCH_FAILED,
    COMBINED_SEARCH_FAILED_MESSAGE,
    FAILED_ACTIVITY_OUTCOMES,
    CombinedSearchOutcome,
    SearchDomainOutcome,
)
from ..server._routes_search import _dominant_combined_failure
from ._process_probe_guard_helpers import every_production_file

pytestmark = pytest.mark.unit


def _fact(  # noqa: PLR0913 - explicit fact dimensions keep fixtures truthful
    source: IndexSource,
    *,
    availability: SearchAvailability = SearchAvailability.USABLE,
    freshness: SearchFreshness = SearchFreshness.CURRENT,
    authority: AbsenceAuthority = AbsenceAuthority.AUTHORITATIVE,
    reason: str | None = None,
    retryable: bool = False,
    remediation: str | None = None,
) -> SearchSourceFact:
    return SearchSourceFact(
        source=source,
        availability=availability,
        freshness=freshness,
        absence_authority=authority,
        reason_code=reason,
        retryable=retryable,
        remediation=remediation,
    )


def _unavailable(
    source: IndexSource, *, remediation: str | None = "inspect"
) -> SearchSourceFact:
    return _fact(
        source,
        availability=SearchAvailability.UNAVAILABLE,
        freshness=SearchFreshness.UNVERIFIABLE,
        authority=AbsenceAuthority.NON_AUTHORITATIVE,
        reason="index_unavailable",
        retryable=True,
        remediation=remediation,
    )


def test_combined_outcome_retains_partial_failure_and_successful_hits() -> None:
    vault = SearchDomainOutcome.success(
        PublicSourceType.VAULT,
        [SearchResult("v", "v.md", "Vault", 0.7, "v", "vault")],
        source_fact=_fact("vault"),
    )
    code = SearchDomainOutcome.failure(
        PublicSourceType.CODE,
        "index_unavailable",
        "code collection is unavailable",
        source_fact=_unavailable("code"),
    )
    document = SearchDomainOutcome.success(
        PublicSourceType.DOCUMENT,
        [DocumentSearchResult("d", "d.bin", "Document", 0.8, "d")],
        source_fact=_fact(
            "document",
            freshness=SearchFreshness.UPDATING,
            authority=AbsenceAuthority.NON_AUTHORITATIVE,
            reason="index_updating",
            retryable=True,
            remediation="inspect document job",
        ),
    )
    outcome = CombinedSearchOutcome(vault, code, document, top_k=2)
    assert outcome.partial
    assert [result.id for result in outcome.results] == ["d", "v"]
    assert outcome.code.error_kind == "index_unavailable"
    assert outcome.readiness.availability is SearchAvailability.USABLE
    assert outcome.readiness.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    assert outcome.readiness.degraded_sources == ("code", "document")
    domains = outcome.domain_status_payload()
    assert domains["vault"]["results_count"] == 1
    assert domains["code"]["error_kind"] == "index_unavailable"
    assert domains["code"]["readiness"] == outcome.code.source_fact.as_dict()
    assert domains["document"]["results_count"] == 1


def test_failed_domain_cannot_smuggle_results() -> None:
    with pytest.raises(ValueError):
        SearchDomainOutcome(
            source=PublicSourceType.CODE,
            source_fact=_unavailable("code"),
            results=(SearchResult("c", "c.py", "Code", 0.5, "c", "codebase"),),
            error_kind="failed",
            detail="failure",
        )


def test_combined_outcome_distinguishes_complete_failure_from_empty_success() -> None:
    outcome = CombinedSearchOutcome(
        SearchDomainOutcome.failure(
            PublicSourceType.VAULT,
            "vault_unavailable",
            "vault count failed",
            source_fact=_unavailable("vault"),
        ),
        SearchDomainOutcome.failure(
            PublicSourceType.CODE,
            "code_unavailable",
            "code count failed",
            source_fact=_unavailable("code"),
        ),
        SearchDomainOutcome.failure(
            PublicSourceType.DOCUMENT,
            "document_unavailable",
            "document count failed",
            source_fact=_unavailable("document"),
        ),
        top_k=5,
    )

    assert not outcome.ok
    assert not outcome.partial
    assert outcome.results == []
    assert all(not domain["ok"] for domain in outcome.domain_status_payload().values())


def test_combined_empty_is_authoritative_only_when_every_source_is() -> None:
    # Changing aggregate authority from all to any (and temporarily bypassing
    # its contradiction validator) failed the exact degraded-authority
    # assertion as AUTHORITATIVE is not NON_AUTHORITATIVE (exit 1); restoration
    # passed (exit 0).
    authoritative = CombinedSearchOutcome(
        SearchDomainOutcome.success(
            PublicSourceType.VAULT, [], source_fact=_fact("vault")
        ),
        SearchDomainOutcome.success(
            PublicSourceType.CODE, [], source_fact=_fact("code")
        ),
        SearchDomainOutcome.success(
            PublicSourceType.DOCUMENT, [], source_fact=_fact("document")
        ),
        top_k=5,
    )
    degraded = CombinedSearchOutcome(
        authoritative.vault,
        SearchDomainOutcome.success(
            PublicSourceType.CODE, [], source_fact=_unavailable("code")
        ),
        authoritative.document,
        top_k=5,
    )

    assert authoritative.results == []
    assert authoritative.readiness.absence_authority is AbsenceAuthority.AUTHORITATIVE
    assert degraded.results == []
    assert degraded.readiness.absence_authority is AbsenceAuthority.NON_AUTHORITATIVE
    assert degraded.readiness.degraded_sources == ("code",)


def test_combined_has_no_omitted_domain_state() -> None:
    outcome = CombinedSearchOutcome(
        SearchDomainOutcome.success(
            PublicSourceType.VAULT, [], source_fact=_fact("vault")
        ),
        SearchDomainOutcome.success(
            PublicSourceType.CODE, [], source_fact=_fact("code")
        ),
        SearchDomainOutcome.success(
            PublicSourceType.DOCUMENT, [], source_fact=_fact("document")
        ),
        top_k=1,
    )

    # Code-domain include/exclude filters shape code hits; they do not omit a
    # requested corpus from combined readiness or authority.
    assert tuple(outcome.domain_status_payload()) == ("vault", "code", "document")
    assert outcome.readiness.source_count == 3


def test_domain_outcome_rejects_unknown_enum_and_mismatched_fact() -> None:
    # Disabling exact source/fact identity failed here with DID NOT RAISE
    # ValueError (exit 1); restoration passed (exit 0).
    with pytest.raises(
        ValueError, match=r"^a domain outcome source must be a PublicSourceType$"
    ):
        SearchDomainOutcome.success(
            cast("PublicSourceType", "vault"), [], source_fact=_fact("vault")
        )
    with pytest.raises(
        ValueError, match=r"^a domain outcome source fact carries the wrong source$"
    ):
        SearchDomainOutcome.success(
            PublicSourceType.CODE, [], source_fact=_fact("vault")
        )


def test_dominant_failure_is_stable_for_same_reason_and_null_remediation() -> None:
    # Reversing same-reason selection failed the tuple's retryable element
    # (`True != False`, exit 1); restoration passed (exit 0), while remediation
    # still comes from the first same-reason fact that actually supplies it.
    first = replace(_unavailable("vault", remediation=None), retryable=False)
    second = replace(_unavailable("code"), remediation="inspect code")
    third = _fact("document")

    assert _dominant_combined_failure((first, second, third)) == (
        "index_unavailable",
        False,
        "inspect code",
    )


def _string_literal_sites(needle: str) -> list[str]:
    """Return every production site writing *needle* as a string literal."""
    home = Path(_outcomes.__file__)
    sites: list[str] = []
    for path in every_production_file():
        if path == home:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:  # pragma: no cover - parse errors are checked elsewhere
            continue
        sites.extend(
            f"{path.name}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            if isinstance(node.value, str)
            if node.value == needle
        )
    return sites


class TestCombinedFailureVocabularyHasOneHome:
    """The failed-combined-search wording and kind are written exactly once.

    Both the service route and the in-process CLI path report this condition.
    While each spelled it out for itself, an operator hitting the same failure
    through the two surfaces could be told two different things, and nothing
    would notice. The scan is over literals rather than over the two known
    files, so a third surface restating it also fails here.

    Mutation check: reinstating either literal in ``server/_routes_search.py``
    or ``cli/_search.py`` fails this test naming that file and line.
    """

    def test_the_sentence_is_written_only_in_the_search_domain(self) -> None:
        sites = _string_literal_sites(COMBINED_SEARCH_FAILED_MESSAGE)
        assert sites == [], (
            f"{COMBINED_SEARCH_FAILED_MESSAGE!r} is restated at {sites}; import "
            "COMBINED_SEARCH_FAILED_MESSAGE from the search domain instead"
        )

    def test_the_error_kind_is_written_only_in_the_search_domain(self) -> None:
        sites = _string_literal_sites(COMBINED_SEARCH_FAILED)
        assert sites == [], (
            f"{COMBINED_SEARCH_FAILED!r} is restated at {sites}; import "
            "COMBINED_SEARCH_FAILED from the search domain instead"
        )


_SERVED_ACTIVITY_OUTCOMES = frozenset({"partial_success", "success"})


def _classifier_outcomes() -> set[str]:
    """Return every outcome the route's activity classifier can return.

    Parsed rather than imported: the route module pulls the whole service
    stack, and this only needs the literals the classifier returns.
    """
    route_source = Path(_outcomes.__file__).parents[1] / "server" / "_routes_search.py"
    tree = ast.parse(route_source.read_text(encoding="utf-8"))
    classifier = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        if node.name == "_activity_outcome"
    )
    # Only the returned expression itself. Walking the whole Return sweeps up
    # nested lookups too, and one branch reads a ``result["partial"]`` flag on
    # its way to deciding between two outcomes.
    returned: list[ast.expr] = []
    for node in ast.walk(classifier):
        if not isinstance(node, ast.Return) or node.value is None:
            continue
        if isinstance(node.value, ast.IfExp):
            returned.extend((node.value.body, node.value.orelse))
        else:
            returned.append(node.value)
    return {
        expression.value
        for expression in returned
        if isinstance(expression, ast.Constant)
        if isinstance(expression.value, str)
    }


class TestActivityOutcomeVocabularyIsAccountedFor:
    """Every outcome the route can classify is either served or failed.

    A console marks the failed ones. While that set was restated on the
    display side it silently fell behind: the two admission-side outcomes
    were missing, so a registry refusing every search on the box rendered in
    the same tone as a completed one. An outcome that reaches an operator
    unclassified is worse than an ugly one, because nothing reports it.

    Mutation check: dropping ``admission_failed`` or ``combined_failed`` from
    ``FAILED_ACTIVITY_OUTCOMES`` fails the test below naming that outcome;
    adding a new ``return "throttled"`` branch to the classifier fails it too,
    which is the drift this exists to catch.
    """

    def test_the_classifier_returns_nothing_the_vocabulary_omits(self) -> None:
        unaccounted = _classifier_outcomes() - (
            FAILED_ACTIVITY_OUTCOMES | _SERVED_ACTIVITY_OUTCOMES
        )
        assert unaccounted == set(), (
            f"the activity classifier returns {sorted(unaccounted)}, which no "
            "surface can classify; add each to FAILED_ACTIVITY_OUTCOMES or to "
            "the served set beside it"
        )
