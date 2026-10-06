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
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import grpc
import pytest

from ..._loopback_http import LOOPBACK_OPENER
from ..._qdrant_server_client import open_server_client
from ...config._types import EnvVar
from ...qdrant_runtime._constants import QDRANT_SERVER_VERSION
from ...qdrant_runtime._credential import read_managed_api_key
from ...qdrant_runtime._resolve import write_qdrant_identity
from ...qdrant_runtime._supervise import (
    set_active_supervisor,
    start_supervised_from_config,
)
from .._config_fixtures import reset_config
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


def _rest_listing_status(port: int, api_key: str | None) -> int:
    """List collections over REST the way any local process could."""
    request = urllib.request.Request(f"http://127.0.0.1:{port}/collections")
    if api_key is not None:
        request.add_header("api-key", api_key)
    try:
        with LOOPBACK_OPENER.open(request, timeout=5.0) as response:
            return int(response.status)
    except urllib.error.HTTPError as refused:
        return int(refused.code)


def _grpc_listing_status(grpc_port: int, api_key: str | None) -> grpc.StatusCode:
    """List collections over gRPC the way any local process could.

    A raw channel rather than the client library: an empty request message is
    zero bytes on the wire, and going through nothing of ours is the point.
    """
    with grpc.insecure_channel(f"127.0.0.1:{grpc_port}") as channel:
        listing = channel.unary_unary(
            "/qdrant.Collections/List",
            request_serializer=bytes,
            response_deserializer=bytes,
        )
        metadata = (("api-key", api_key),) if api_key is not None else None
        try:
            listing(b"", timeout=10.0, metadata=metadata)
        except grpc.RpcError as refused:
            # The status lives on the call half of the error the channel raises.
            if not isinstance(refused, grpc.Call):
                raise
            return refused.code()
    return grpc.StatusCode.OK


class TestManagedDataPlaneRequiresTheKey:
    """The real pinned binary, started the way the daemon starts it."""

    @pytest.mark.integration
    def test_neither_protocol_answers_a_local_process_without_the_key(
        self,
        tmp_path: Path,
        required_host_provisioned_qdrant_source: tuple[Path, Path],
    ) -> None:
        """Both listeners refuse an anonymous caller and accept the owner's key.

        Loopback binding does not separate local accounts, so an anonymous
        request here is exactly what another user on the host can send. The
        child gets one key setting; this is what shows the pinned server
        applies it to gRPC as well as REST, which no stand-in could.
        """
        port = _get_ephemeral_qdrant_port()
        with _managed_qdrant_env(tmp_path, port=port) as storage:
            _mirror_managed_qdrant_binary(
                tmp_path / "status",
                required_host_provisioned_qdrant_source,
            )
            owner = start_supervised_from_config()
            try:
                assert _rest_listing_status(port, None) == 401
                assert (
                    _grpc_listing_status(port - 1, None)
                    is grpc.StatusCode.UNAUTHENTICATED
                )
                assert _rest_listing_status(port, "not-the-key") == 401

                api_key = read_managed_api_key(storage)
                assert api_key is not None
                assert _rest_listing_status(port, api_key) == 200
                assert _grpc_listing_status(port - 1, api_key) is grpc.StatusCode.OK

                # The path every internal client takes: nothing configured,
                # the key found where the owner published it.
                client = open_server_client(owner.url, timeout=30)
                try:
                    assert client.get_collections().collections == []
                finally:
                    client.close()
            finally:
                owner.stop()

    @pytest.mark.integration
    def test_attach_is_refused_when_the_owner_credential_is_unusable(
        self,
        tmp_path: Path,
        required_host_provisioned_qdrant_source: tuple[Path, Path],
    ) -> None:
        """A second start never adopts a server it cannot authenticate to."""
        with _managed_qdrant_env(
            tmp_path, port=_get_ephemeral_qdrant_port()
        ) as storage:
            _mirror_managed_qdrant_binary(
                tmp_path / "status",
                required_host_provisioned_qdrant_source,
            )
            owner = start_supervised_from_config()
            try:
                set_active_supervisor(None)
                credential = storage.parent / "credential.json"

                credential.write_text('{"api_key": "not-the-key"}', encoding="utf-8")
                with pytest.raises(RuntimeError) as wrong:
                    start_supervised_from_config()
                assert "answered the managed credential with HTTP 401" in str(
                    wrong.value
                )

                credential.unlink()
                with pytest.raises(RuntimeError) as missing:
                    start_supervised_from_config()
                assert "its owner published no credential" in str(missing.value)
                # Refused, not replaced: the owner's child is still serving.
                assert owner.is_alive() is True
            finally:
                owner.stop()


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
