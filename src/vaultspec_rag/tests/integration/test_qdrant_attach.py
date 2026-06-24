"""Verified Qdrant attach-or-refuse integration tests (plan W02.P04).

No mocks, no real Qdrant, no GPU: a real stdlib HTTP server stands in for a
running managed Qdrant (it answers /readyz and reports a version), the managed
config is driven through the genuine env knobs, and the identity sidecar is
written to make the server "owned". The full `start_supervised_from_config`
decision path is exercised: it must attach to a healthy, owned, capable server
without spawning, and refuse fast otherwise.
"""

from __future__ import annotations

import contextlib
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from ...config import EnvVar, reset_config
from ...qdrant_runtime._constants import QDRANT_SERVER_VERSION
from ...qdrant_runtime._resolve import write_qdrant_identity
from ...qdrant_runtime._supervise import (
    set_active_supervisor,
    start_supervised_from_config,
)

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path


def _handler_for(version: str) -> type[BaseHTTPRequestHandler]:
    class _FakeQdrant(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # stdlib handler contract
            if self.path == "/readyz":
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ok")
            elif self.path == "/":
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(f'{{"version":"{version}"}}'.encode())
            else:
                self.send_response(404)
                self.end_headers()

    return _FakeQdrant


@contextlib.contextmanager
def _running_managed_qdrant(
    tmp_path: Path, *, version: str
) -> Generator[tuple[int, Path]]:
    """Run a fake managed Qdrant and point the managed config at it."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(version))
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    storage = tmp_path / "qdrant-server" / "storage"
    prior = {
        EnvVar.QDRANT_PORT.value: os.environ.get(EnvVar.QDRANT_PORT.value),
        EnvVar.QDRANT_STORAGE_DIR.value: os.environ.get(
            EnvVar.QDRANT_STORAGE_DIR.value
        ),
        EnvVar.STATUS_DIR.value: os.environ.get(EnvVar.STATUS_DIR.value),
    }
    os.environ[EnvVar.QDRANT_PORT.value] = str(port)
    os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(storage)
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
    reset_config()
    try:
        yield port, storage
    finally:
        set_active_supervisor(None)
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()
        server.shutdown()
        server.server_close()


class TestVerifiedAttach:
    def test_attaches_to_healthy_owned_capable_server(self, tmp_path: Path) -> None:
        with _running_managed_qdrant(
            tmp_path, version=QDRANT_SERVER_VERSION
        ) as (port, storage):
            write_qdrant_identity(
                storage_path=str(storage),
                version=QDRANT_SERVER_VERSION,
                owner_pid=os.getpid(),
                http_port=port,
            )
            supervisor = start_supervised_from_config()
            # Attached: reuses the running server (no spawned child) and is live.
            assert supervisor.pid is None
            assert supervisor.is_alive() is True

    def test_refuses_foreign_holder_without_identity(self, tmp_path: Path) -> None:
        with _running_managed_qdrant(tmp_path, version=QDRANT_SERVER_VERSION):
            # No identity sidecar written -> the holder is foreign.
            with pytest.raises(RuntimeError) as excinfo:
                start_supervised_from_config()
            assert "refusing to start qdrant" in str(excinfo.value)

    def test_refuses_on_version_mismatch(self, tmp_path: Path) -> None:
        with _running_managed_qdrant(tmp_path, version="0.0.1") as (port, storage):
            write_qdrant_identity(
                storage_path=str(storage),
                version=QDRANT_SERVER_VERSION,
                owner_pid=os.getpid(),
                http_port=port,
            )
            with pytest.raises(RuntimeError) as excinfo:
                start_supervised_from_config()
            assert "version" in str(excinfo.value)
