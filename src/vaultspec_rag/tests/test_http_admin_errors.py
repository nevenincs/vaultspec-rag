"""Admin-path error-surfacing tests for the shared service-client transport.

No mocks: a real in-process HTTP server stands in for the daemon and is driven
over the genuine ``urllib`` wire path through ``_try_http_admin``. The regression
guard (GitHub #199) is that an unexpected (non-refused, non-timeout) failure -
here a live route returning a malformed, non-JSON body - surfaces as the
structured ``http_call_failed`` envelope rather than a bare ``{}`` that a caller
cannot tell apart from a genuinely empty result.
"""

from __future__ import annotations

import os
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from ..config import EnvVar
from ..serviceclient._transport import _try_http_admin

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.unit]


class _MalformedJSONHandler(BaseHTTPRequestHandler):
    """Answer every GET with a 200 whose body is not valid JSON."""

    def do_GET(self) -> None:
        body = b"this is not json"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object, **_kwargs: object) -> None:
        """Silence the default stderr request logging."""


class _EmptyJSONHandler(BaseHTTPRequestHandler):
    """Answer every GET with a valid, genuinely-empty JSON object."""

    def do_GET(self) -> None:
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args: object, **_kwargs: object) -> None:
        """Silence the default stderr request logging."""


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


@pytest.fixture
def refused_port() -> Iterator[int]:
    """Yield a port that deterministically refuses connections.

    A socket bound to an ephemeral port but never put into ``listen()`` rejects
    every connect with ECONNREFUSED for as long as it is held - so there is no
    bind/close/reuse window (which returning a closed port number would leave).
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    try:
        yield sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture
def isolated_status_dir(tmp_path: object) -> Iterator[None]:
    """Point the status dir at an empty temp dir so no ambient token couples in."""
    key = EnvVar.STATUS_DIR.value
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path)
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous


@pytest.mark.usefixtures("isolated_status_dir")
class TestAdminErrorSurfacing:
    def test_malformed_response_returns_http_call_failed_envelope(self) -> None:
        server, port = _serve(_MalformedJSONHandler)
        try:
            result = _try_http_admin("list_projects", {}, port)
        finally:
            server.shutdown()
        assert result is not None, "a live-but-broken call must not look unreachable"
        assert result != {}, "the failure must not be swallowed into a bare empty dict"
        assert result.get("ok") is False
        assert result.get("error") == "http_call_failed"
        assert result.get("message")

    def test_genuinely_empty_result_stays_empty_dict(self) -> None:
        # A successful call whose body is an empty object is a legitimate empty
        # result and must remain distinguishable from the failure envelope above.
        server, port = _serve(_EmptyJSONHandler)
        try:
            result = _try_http_admin("list_projects", {}, port)
        finally:
            server.shutdown()
        assert result == {}

    def test_unreachable_service_returns_none(self, refused_port: int) -> None:
        # Nothing listening on the port: the refused connection is the
        # service-down sentinel and must stay None, not an envelope.
        result = _try_http_admin("list_projects", {}, refused_port)
        assert result is None
