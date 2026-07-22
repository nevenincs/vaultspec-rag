"""Strict search-response tests for the shared HTTP and MCP consumers."""

from __future__ import annotations

import socket

import pytest

from ..mcp._tools import _search_envelope_or_raise
from ..serviceclient._transport import _search_response_envelope, _try_http_search

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
