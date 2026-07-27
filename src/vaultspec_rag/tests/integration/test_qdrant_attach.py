"""Verified Qdrant attach-or-refuse integration tests.

No mocks, no GPU: the managed config is driven through the genuine env knobs
and the full `start_supervised_from_config` decision path is exercised. The
attach gate demands live process witnesses - a child pid whose OS image is
qdrant and which owns the loopback listener - so the attach test runs the real
provisioned binary; an in-process stand-in has no separate process to witness.
The refusal tests fail before any witness inspection, so a real stdlib HTTP
server answering /readyz and reporting a version is enough to stand in for the
port holder there.
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
from ._helpers import _get_ephemeral_qdrant_port, _mirror_managed_qdrant_binary

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
def _managed_qdrant_env(tmp_path: Path, *, port: int) -> Generator[Path]:
    """Point the managed config (port, storage, status) at *tmp_path*."""
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
        yield storage
    finally:
        set_active_supervisor(None)
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


@contextlib.contextmanager
def _running_managed_qdrant(
    tmp_path: Path, *, version: str
) -> Generator[tuple[int, Path]]:
    """Run a fake managed Qdrant and point the managed config at it."""
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler_for(version))
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with _managed_qdrant_env(tmp_path, port=port) as storage:
            yield port, storage
    finally:
        server.shutdown()
        server.server_close()


class TestVerifiedAttach:
    @pytest.mark.integration
    def test_attaches_to_healthy_owned_capable_server(
        self,
        tmp_path: Path,
        required_host_provisioned_qdrant_source: tuple[Path, Path],
    ) -> None:
        """A live, owned, witness-complete server is reused without spawning.

        The attach gate requires the recorded child pid to resolve to a live
        qdrant-image process owning the expected loopback listener, so the
        healthy holder here is a real provisioned binary spawned through the
        supervised start path - which records the complete owner/child witness
        in the identity sidecar. A second supervised start against that live
        holder must take the attach branch: no spawned child, and liveness
        reported through the endpoint it points at.
        """
        binary, manifest = required_host_provisioned_qdrant_source
        assert binary.is_file()
        assert manifest.is_file()
        with _managed_qdrant_env(tmp_path, port=_get_ephemeral_qdrant_port()):
            _mirror_managed_qdrant_binary(
                tmp_path / "status",
                required_host_provisioned_qdrant_source,
            )
            owner = None
            try:
                owner = start_supervised_from_config()
                assert owner.pid is not None
                assert owner.is_alive() is True
                set_active_supervisor(None)

                supervisor = start_supervised_from_config()
                # Attached: reuses the running server (no spawned child) and
                # is live.
                assert supervisor.pid is None
                assert supervisor.is_alive() is True
            finally:
                if owner is not None:
                    owner.stop()

    @pytest.mark.unit
    def test_refuses_foreign_holder_without_identity(self, tmp_path: Path) -> None:
        with _running_managed_qdrant(tmp_path, version=QDRANT_SERVER_VERSION):
            # No identity sidecar written -> the holder is foreign.
            with pytest.raises(RuntimeError) as excinfo:
                start_supervised_from_config()
            assert "refusing to start qdrant" in str(excinfo.value)

    @pytest.mark.unit
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
