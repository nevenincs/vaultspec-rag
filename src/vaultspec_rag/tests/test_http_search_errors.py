"""Strict search-response tests for the shared HTTP and MCP consumers."""

from __future__ import annotations

import contextlib
import json
import socket
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from ..mcp._tools import _search_envelope_or_raise
from ..serviceclient._transport import _try_http_search

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = [pytest.mark.unit]


@contextmanager
def _search_service(body: bytes) -> Generator[int]:
    """Serve one fixed response body over a real loopback HTTP server."""

    class SearchHandler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(content_length)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            with contextlib.suppress(
                BrokenPipeError,
                ConnectionAbortedError,
                ConnectionResetError,
            ):
                self.wfile.write(body)

        def log_message(self, *_args: object, **_kwargs: object) -> None:
            """Silence the standard request log."""

    server = ThreadingHTTPServer(("127.0.0.1", 0), SearchHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        assert not thread.is_alive()


def _http_search(port: int) -> dict[str, object] | None:
    return _try_http_search("response contract", "vault", 3, port, "")


def test_valid_search_envelope_is_unchanged() -> None:
    expected: dict[str, object] = {
        "results": [{"id": "doc-1", "score": 0.75}],
        "summary": "one result",
    }
    with _search_service(json.dumps(expected).encode("utf-8")) as port:
        result = _http_search(port)

    assert result == expected
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
    with _search_service(json.dumps(expected).encode("utf-8")) as port:
        result = _http_search(port)

    assert result == expected


@pytest.mark.parametrize(
    "body",
    [
        b"{}",
        b"[]",
        b'"legacy"',
        b"null",
        b'{"summary":"missing results"}',
        b'{"results":"legacy"}',
        b"not-json",
    ],
    ids=[
        "empty-object",
        "legacy-list",
        "json-string",
        "json-null",
        "missing-results",
        "wrong-results-type",
        "non-json",
    ],
)
def test_malformed_search_shapes_return_stable_failure(body: bytes) -> None:
    with _search_service(body) as port:
        result = _http_search(port)

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
