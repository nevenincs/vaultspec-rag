"""Orientation selection, adapter guidance, and requested-source readiness."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

import pytest

from .._public_search import CombinedSearchRequest, VaultCombinedSearchFilters
from .._source_types import PublicSourceType
from ..mcp._tools import _validated_search_result
from ..search._models import SearchResult
from ..search._outcomes import CombinedSearchOutcome, SearchDomainOutcome
from ..server._routes_search import SearchRequest, _normalise_search_request
from ._cli_helpers import app, runner
from .test_cli_search import (
    _readiness_block,
    _readiness_source,
    _search_envelope_service,
)
from .test_search_outcomes import _fact, _unavailable

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("include_documents", "query", "explicit", "expected"),
    [
        (False, "locking", None, "adr"),
        (False, "locking type:plan", None, None),
        (False, "locking", "research", "research"),
        (True, "locking", None, None),
    ],
)
def test_combined_vault_selection(
    tmp_path: Path,
    include_documents: bool,
    query: str,
    explicit: str | None,
    expected: str | None,
) -> None:
    request = CombinedSearchRequest(
        tmp_path,
        query,
        include_documents=include_documents,
        vault_filters=VaultCombinedSearchFilters(doc_type=explicit),
    )
    assert request.vault_filters.doc_type == expected


@pytest.mark.parametrize("include_documents", [False, True])
def test_route_tracks_only_requested_sources(
    tmp_path: Path, include_documents: bool
) -> None:
    request = SearchRequest(
        tmp_path,
        "locking",
        10,
        {"include_documents": include_documents},
        PublicSourceType.COMBINED,
        "test-request",
    )
    assert request.sources == (
        ("vault", "code", "document") if include_documents else ("vault", "code")
    )


def test_orientation_ranks_both_sources_and_retains_partial_failure() -> None:
    vault = SearchDomainOutcome.success(
        PublicSourceType.VAULT,
        [
            SearchResult(
                "adr",
                "adr/locking.md",
                "Locking",
                0.7,
                "locks",
                "vault",
                doc_type="adr",
            )
        ],
        source_fact=_fact("vault"),
    )
    code = SearchDomainOutcome.success(
        PublicSourceType.CODE,
        [SearchResult("code", "src/lock.py", "lock", 0.9, "lock()", "codebase")],
        source_fact=_fact("code"),
    )
    outcome = CombinedSearchOutcome(vault, code, None, top_k=2)
    assert [hit.id for hit in outcome.results] == ["code", "adr"]
    assert tuple(outcome.domain_status_payload()) == ("vault", "code")
    assert outcome.readiness.source_count == 2
    failed = CombinedSearchOutcome(
        vault,
        SearchDomainOutcome.failure(
            PublicSourceType.CODE,
            "unavailable",
            "code unavailable",
            source_fact=_unavailable("code"),
        ),
        None,
        top_k=2,
    )
    assert failed.partial
    assert [hit.id for hit in failed.results] == ["adr"]
    assert failed.readiness.degraded_sources == ("code",)


@pytest.mark.parametrize(
    "selection",
    [
        [],
        ["--type", "combined"],
        ["--type", "vault"],
        ["--type", "code"],
        ["--type", "document"],
    ],
)
def test_cli_default_and_explicit_selection(
    tmp_path: Path, selection: list[str]
) -> None:
    (tmp_path / ".vaultspec").mkdir()
    with _search_envelope_service({"results": []}) as (port, requests):
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "locking",
                "--port",
                str(port),
                "--json",
                *selection,
            ],
        )
    assert result.exit_code == 0, result.output
    assert requests[0]["type"] == (selection[-1] if selection else "combined")
    assert requests[0].get("include_documents", True) == bool(selection)
    envelope = json.loads(result.output)
    assert "--doc-type adr" in envelope["data"]["advisory"]


def test_cli_human_advisory_is_emitted_once(tmp_path: Path) -> None:
    (tmp_path / ".vaultspec").mkdir()
    with _search_envelope_service({"results": []}) as (port, _requests):
        result = runner.invoke(
            app, ["--target", str(tmp_path), "search", "locking", "--port", str(port)]
        )
    assert result.exit_code == 0, result.output
    assert result.output.count("Filter with --type") == 1


def test_mcp_schema_and_response_explain_orientation() -> None:
    from ..mcp._mcp import mcp

    tools = asyncio.run(mcp.list_tools())
    combined = next(tool for tool in tools if tool.name == "search_combined")
    assert combined.input_schema["properties"]["include_documents"]["default"] is False
    response = _validated_search_result(
        {
            "results": [],
            "readiness": _readiness_block(
                [_readiness_source("vault"), _readiness_source("code")]
            ),
        }
    )
    assert 'search_vault(doc_type="adr")' in response.advisory
    assert "source/doc_type" in response.model_dump()["advisory"]


def test_route_rejects_non_boolean_domain_selection(tmp_path: Path) -> None:
    # Removing boolean validation failed the SearchRouteError assertion;
    # restoring it passed (mutation exit 1, restored exit 0).
    from ..server._routes_search import SearchRouteError

    (tmp_path / ".vault").mkdir()
    result = _normalise_search_request(
        {
            "query": "locking",
            "type": "combined",
            "project_root": str(tmp_path),
            "include_documents": "false",
        },
        "test",
    )
    assert isinstance(result, SearchRouteError)
    assert result.error_code == "invalid_include_documents"


def test_orientation_dispatch_searches_adrs_and_code_only(tmp_path: Path) -> None:
    # Removing the document exclusion failed the document-is-None assertion;
    # restoring it passed (mutation exit 1, restored exit 0).
    from unittest.mock import create_autospec

    from .._public_search import _search_combined_domains
    from ..search._searcher import VaultSearcher

    searcher = create_autospec(VaultSearcher, instance=True)
    searcher.search_vault.return_value = [
        SearchResult(
            "adr", "adr/locks.md", "Locks", 0.8, "locks", "vault", doc_type="adr"
        )
    ]
    searcher.search_codebase.return_value = [
        SearchResult("code", "src/lock.py", "lock", 0.9, "lock()", "codebase")
    ]
    request = CombinedSearchRequest(tmp_path, "locking", include_documents=False)
    counts = {
        PublicSourceType.VAULT: 1,
        PublicSourceType.CODE: 1,
        PublicSourceType.DOCUMENT: 1,
    }
    facts = {
        PublicSourceType.VAULT: _fact("vault"),
        PublicSourceType.CODE: _fact("code"),
        PublicSourceType.DOCUMENT: _fact("document"),
    }
    vault, code, document = _search_combined_domains(
        request, searcher, counts, {}, facts
    )
    assert [hit.id for hit in vault.results] == ["adr"]
    assert [hit.id for hit in code.results] == ["code"]
    assert searcher.search_vault.call_args.kwargs["doc_type"] == "adr"
    assert document is None
    searcher.search_document.assert_not_called()


def test_document_filters_require_an_explicit_document_selection() -> None:
    # Reversing the exclusion condition failed with DID NOT RAISE; restoring
    # it passed (mutation exit 1, restored exit 0).
    from ..search._validation import (
        InvalidFilterForSearchTypeError,
        SearchFilterOptions,
        validate_search_filters,
    )

    options = SearchFilterOptions(source_path="records/report.pdf")
    with pytest.raises(
        InvalidFilterForSearchTypeError,
        match="Document filters require include_documents=true",
    ):
        validate_search_filters("combined", options, include_documents=False)
    validate_search_filters("combined", options, include_documents=True)


def test_empty_orientation_needs_no_models(tmp_path: Path) -> None:
    from .._public_search import search_combined
    from ..registry import get_registry
    from .conftest import managed_env

    with managed_env(VAULTSPEC_RAG_LOCAL_ONLY="true", VAULTSPEC_RAG_QDRANT_URL=None):
        try:
            outcome = search_combined(
                CombinedSearchRequest(tmp_path, "query", include_documents=False)
            )
            assert tuple(outcome.domain_status_payload()) == ("vault", "code")
            assert outcome.readiness.source_count == 2
            assert outcome.vault.ok and outcome.code.ok
            assert outcome.results == []
        finally:
            get_registry().close_project(tmp_path.resolve())
