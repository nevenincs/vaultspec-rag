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
