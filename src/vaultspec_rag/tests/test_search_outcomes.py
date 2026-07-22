"""Tests for explicit combined-search partial outcomes."""

from __future__ import annotations

import pytest

from .._source_types import PublicSourceType
from ..search._models import DocumentSearchResult, SearchResult
from ..search._outcomes import CombinedSearchOutcome, SearchDomainOutcome

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


def test_failed_domain_cannot_smuggle_results() -> None:
    with pytest.raises(ValueError):
        SearchDomainOutcome(
            PublicSourceType.CODE,
            (SearchResult("c", "c.py", "Code", 0.5, "c", "codebase"),),
            "failed",
            "failure",
        )
