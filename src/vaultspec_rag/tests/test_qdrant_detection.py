"""Qdrant holder/orphan detection primitive tests (plan W01.P02).

No mocks, no GPU: the endpoint probe runs against a real stdlib HTTP server on
an ephemeral loopback port, pid-liveness is checked against this process and a
never-used pid, and the orphan classifier is exercised across every state with
constructed probe/identity inputs.
"""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

from ..qdrant_runtime._resolve import (
    QdrantEndpointProbe,
    QdrantIdentity,
    classify_qdrant_state,
    pid_alive,
    probe_qdrant_endpoint,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class _FakeQdrantHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # stdlib handler contract
        if self.path == "/readyz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        elif self.path == "/":
            body = b'{"title":"qdrant","version":"1.18.2"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()


def _fake_qdrant_server() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeQdrantHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(port)
    finally:
        server.shutdown()
        server.server_close()


class TestEndpointProbe:
    def test_probe_dead_port_not_listening(self) -> None:
        probe = probe_qdrant_endpoint(59995, timeout=1.0)
        assert probe.listening is False
        assert probe.ready is False
        assert probe.version == ""

    def test_probe_live_server_ready_with_version(self) -> None:
        gen = _fake_qdrant_server()
        port = next(gen)
        try:
            probe = probe_qdrant_endpoint(port, timeout=2.0)
            assert probe.listening is True
            assert probe.ready is True
            assert probe.version == "1.18.2"
        finally:
            for _ in gen:
                pass


class TestPidLiveness:
    def test_self_is_alive_and_bogus_is_dead(self) -> None:
        assert pid_alive(os.getpid()) is True
        assert pid_alive(2_000_000_000) is False
        assert pid_alive(0) is False
        assert pid_alive(-1) is False


class TestClassification:
    def _identity(self, owner_pid: int) -> QdrantIdentity:
        return QdrantIdentity(
            storage_path="s", version="1.18.2", owner_pid=owner_pid, http_port=8765
        )

    def test_absent_when_nothing_listening_and_no_identity(self) -> None:
        probe = QdrantEndpointProbe(listening=False, ready=False, version="")
        assert classify_qdrant_state(probe, None) == "absent"

    def test_stale_identity_when_owner_dead_and_not_listening(self) -> None:
        probe = QdrantEndpointProbe(listening=False, ready=False, version="")
        assert (
            classify_qdrant_state(probe, self._identity(2_000_000_000))
            == "stale_identity"
        )

    def test_foreign_when_listening_without_identity(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        assert classify_qdrant_state(probe, None) == "foreign"

    def test_managed_orphan_when_listening_but_owner_dead(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=False, version="")
        assert (
            classify_qdrant_state(probe, self._identity(2_000_000_000))
            == "managed_orphan"
        )

    def test_managed_running_when_listening_and_owner_alive(self) -> None:
        probe = QdrantEndpointProbe(listening=True, ready=True, version="1.18.2")
        assert (
            classify_qdrant_state(probe, self._identity(os.getpid()))
            == "managed_running"
        )
