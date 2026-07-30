"""Strict search-response tests for the shared HTTP and MCP consumers."""

from __future__ import annotations

import socket
from typing import TYPE_CHECKING

import pytest

from .._source_types import PublicSourceType
from .._store_locks import VaultStoreLockedError
from ..mcp._tools import _search_envelope_or_raise
from ..server import (
    _local_store_locked_error_dict,
    _registry,
    _registry_full_error_dict,
)
from ..server._routes_search import (
    SearchAvailabilityContext,
    SearchRequest,
    _classify_completed_search,
    _search_response_status,
)
from ..service import RegistryFullError
from ..serviceclient._transport import _search_response_envelope, _try_http_search

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _http_search(port: int) -> dict[str, object] | None:
    return _try_http_search("response contract", "vault", 3, port, "")


def test_valid_search_envelope_is_unchanged() -> None:
    expected: dict[str, object] = {
        "results": [{"id": "doc-1", "score": 0.75}],
        "summary": "one result",
    }
    result = _search_response_envelope(expected, 8766)

    assert result is expected
    assert _search_envelope_or_raise(result) is result


def test_structured_search_error_is_unchanged() -> None:
    expected: dict[str, object] = {
        "ok": False,
        "error": "index_unavailable",
        "message": "The vault index is changing.",
        "remediation": [
            "vaultspec-rag server jobs --state active --index vault --port 8766",
            "Retry after the matching job reaches a terminal state.",
        ],
    }
    result = _search_response_envelope(expected, 8766)

    assert result is expected


@pytest.mark.parametrize(
    "response",
    [
        {},
        [],
        "legacy",
        None,
        {"summary": "missing results"},
        {"results": "legacy"},
    ],
    ids=[
        "empty-object",
        "legacy-list",
        "json-string",
        "json-null",
        "missing-results",
        "wrong-results-type",
    ],
)
def test_malformed_search_shapes_return_stable_failure(response: object) -> None:
    port = 8766
    result = _search_response_envelope(response, port)

    assert result == {
        "ok": False,
        "error": "invalid_service_response",
        "message": (
            f"HTTP search on port {port} returned an invalid service response; "
            "expected a non-empty JSON object envelope containing results or "
            "a structured error."
        ),
    }


def test_refused_search_connection_remains_unreachable() -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = int(sock.getsockname()[1])
        result = _http_search(port)

    assert result is None


@pytest.mark.parametrize(
    "result",
    [[], {}, "legacy", None, {"summary": "missing"}, {"results": "legacy"}],
)
def test_mcp_rejects_malformed_search_envelopes(result: object) -> None:
    with pytest.raises(RuntimeError, match=r"^invalid_service_response:"):
        _search_envelope_or_raise(result)


def _status_contract_request(root: Path) -> SearchRequest:
    return SearchRequest(
        root=root,
        query="response status contract",
        top_k=3,
        payload={},
        search_type=PublicSourceType.VAULT,
        request_id="response-status-contract",
    )


def _status_contract_context(root: Path) -> SearchAvailabilityContext:
    return SearchAvailabilityContext(
        job_snapshot_before=[],
        root=root,
        source="vault",
        request_id="response-status-contract",
        port=None,
    )


class TestSearchResponseStatus:
    """Retryable admission failures must not reach the wire as success."""

    def test_registry_full_envelope_reports_service_unavailable(self) -> None:
        envelope: dict[str, object] = _registry_full_error_dict(
            RegistryFullError(_registry.max_projects)
        )

        assert envelope["ok"] is False
        assert _search_response_status(envelope) == 503

    def test_local_store_locked_envelope_reports_service_unavailable(
        self,
        tmp_path: Path,
    ) -> None:
        db_path = tmp_path / ".vault" / "data" / "search-data" / "qdrant"
        envelope: dict[str, object] = _local_store_locked_error_dict(
            VaultStoreLockedError(str(db_path))
        )

        assert envelope["ok"] is False
        assert _search_response_status(envelope) == 503

    def test_retrieval_envelope_keeps_the_success_status(self) -> None:
        envelope: dict[str, object] = {"results": [], "summary": "no results"}

        assert _search_response_status(envelope) == 200

    def test_failure_status_does_not_depend_on_a_missing_results_key(self) -> None:
        """Status follows the failure declaration, not the payload's shape."""
        envelope: dict[str, object] = {
            "ok": False,
            "error": "registry_full",
            "message": "every slot is busy",
            "results": [],
        }

        assert _search_response_status(envelope) == 503


class TestCompletedSearchClassificationSkip:
    """Availability classification refines retrieval, never a failed envelope."""

    def test_failed_envelope_carrying_results_is_not_classified(
        self,
        tmp_path: Path,
    ) -> None:
        """A failure that carries hits is still a failure, not a 200 to refine."""
        envelope: dict[str, object] = {
            "ok": False,
            "error": "local_store_locked",
            "message": "the local index is already open",
            "results": [{"id": "doc-1", "score": 0.75}],
        }

        classification = _classify_completed_search(
            envelope,
            _status_contract_request(tmp_path),
            _status_contract_context(tmp_path),
            None,
            0.0,
        )

        assert classification is None
        assert "request_id" not in envelope


def test_mcp_preserves_structured_error_remediation() -> None:
    envelope: dict[str, object] = {
        "ok": False,
        "error": "index_unavailable",
        "message": "The vault index is changing.",
        "remediation": ["Inspect the matching job.", "Retry after convergence."],
    }

    with pytest.raises(RuntimeError) as raised:
        _search_envelope_or_raise(envelope)

    assert str(raised.value) == (
        "index_unavailable: The vault index is changing. Remediation: "
        "Inspect the matching job. | Retry after convergence."
    )
