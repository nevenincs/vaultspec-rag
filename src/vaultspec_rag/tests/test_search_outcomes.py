"""Tests for explicit combined-search partial outcomes."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from .._source_types import PublicSourceType
from ..search import _outcomes
from ..search._models import DocumentSearchResult, SearchResult
from ..search._outcomes import (
    COMBINED_SEARCH_FAILED,
    COMBINED_SEARCH_FAILED_MESSAGE,
    CombinedSearchOutcome,
    SearchDomainOutcome,
)
from ._process_probe_guard_helpers import every_production_file

pytestmark = pytest.mark.unit


def test_combined_outcome_retains_partial_failure_and_successful_hits() -> None:
    vault = SearchDomainOutcome.success(
        PublicSourceType.VAULT,
        [SearchResult("v", "v.md", "Vault", 0.7, "v", "vault")],
    )
    code = SearchDomainOutcome.failure(
        PublicSourceType.CODE,
        "index_unavailable",
        "code collection is unavailable",
    )
    document = SearchDomainOutcome.success(
        PublicSourceType.DOCUMENT,
        [DocumentSearchResult("d", "d.bin", "Document", 0.8, "d")],
    )
    outcome = CombinedSearchOutcome(vault, code, document, top_k=2)
    assert outcome.partial
    assert [result.id for result in outcome.results] == ["d", "v"]
    assert outcome.code.error_kind == "index_unavailable"
    assert outcome.domain_status_payload() == {
        "vault": {
            "ok": True,
            "results_count": 1,
            "error_kind": None,
            "detail": None,
        },
        "code": {
            "ok": False,
            "results_count": 0,
            "error_kind": "index_unavailable",
            "detail": "code collection is unavailable",
        },
        "document": {
            "ok": True,
            "results_count": 1,
            "error_kind": None,
            "detail": None,
        },
    }


def test_failed_domain_cannot_smuggle_results() -> None:
    with pytest.raises(ValueError):
        SearchDomainOutcome(
            PublicSourceType.CODE,
            (SearchResult("c", "c.py", "Code", 0.5, "c", "codebase"),),
            "failed",
            "failure",
        )


def test_combined_outcome_distinguishes_complete_failure_from_empty_success() -> None:
    outcome = CombinedSearchOutcome(
        SearchDomainOutcome.failure(
            PublicSourceType.VAULT,
            "vault_unavailable",
            "vault count failed",
        ),
        SearchDomainOutcome.failure(
            PublicSourceType.CODE,
            "code_unavailable",
            "code count failed",
        ),
        SearchDomainOutcome.failure(
            PublicSourceType.DOCUMENT,
            "document_unavailable",
            "document count failed",
        ),
        top_k=5,
    )

    assert not outcome.ok
    assert not outcome.partial
    assert outcome.results == []
    assert all(not domain["ok"] for domain in outcome.domain_status_payload().values())


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
