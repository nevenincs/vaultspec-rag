"""Reap-to-spawn port-release poll tests.

No mocks, no GPU: the helper is exercised against real loopback sockets. After a
successful orphan reap the supervisor must wait for the prior child's listening
socket to be fully released before spawning, or the fresh child loses the bind
race. A real bound socket stands in for the not-yet-released port; closing it
frees the port the same way a reaped child's socket release does.
"""

from __future__ import annotations

import threading
import time
from http.server import ThreadingHTTPServer

import pytest

from ..qdrant_runtime._supervise import _port_is_listening, _wait_for_port_release
from ._http_stubs import QuietHandler
from ._ports import free_loopback_port

pytestmark = [pytest.mark.unit]


class _SilentHandler(QuietHandler):
    def do_GET(self) -> None:  # stdlib handler contract
        self.send_response(200)
        self.end_headers()


def _accepting_server() -> ThreadingHTTPServer:
    """A real server that actually accepts connections, like the qdrant child."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _SilentHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


class TestPortIsListening:
    def test_accepting_server_port_is_detected(self) -> None:
        server = _accepting_server()
        port = int(server.server_address[1])
        try:
            assert _port_is_listening(port) is True
        finally:
            server.shutdown()
            server.server_close()

    def test_free_port_is_not_listening(self) -> None:
        assert _port_is_listening(free_loopback_port()) is False


class TestWaitForPortRelease:
    def test_free_port_returns_true_fast(self) -> None:
        start = time.monotonic()
        assert _wait_for_port_release(free_loopback_port(), timeout=2.0) is True
        # A free port resolves on the first probe (plus the settle), not the
        # whole timeout.
        assert time.monotonic() - start < 1.5

    def test_held_port_times_out(self) -> None:
        server = _accepting_server()
        port = int(server.server_address[1])
        try:
            # The server stays up for the whole call, so the poll never observes
            # the port free and times out (False), exactly the named-cause
            # failure the supervisor surfaces.
            assert _wait_for_port_release(port, timeout=0.6) is False
        finally:
            server.shutdown()
            server.server_close()

    def test_port_released_mid_wait_returns_true(self) -> None:
        server = _accepting_server()
        port = int(server.server_address[1])

        def _close_soon() -> None:
            time.sleep(0.3)
            server.shutdown()
            server.server_close()

        closer = threading.Thread(target=_close_soon)
        closer.start()
        try:
            # The port is held, then freed mid-wait; the poll must observe the
            # release and return True before the timeout.
            assert _wait_for_port_release(port, timeout=5.0) is True
        finally:
            closer.join(timeout=5.0)
