"""Lifespan machine-lock release-on-startup-failure tests (plan W04.P09).

No mocks, no GPU: the failure is a real one. A real loopback HTTP server stands
on the configured qdrant port answering ``/readyz`` with no managed identity
sidecar, so the supervised-start decision classifies it ``foreign`` and refuses
- a genuine pre-yield startup failure raised before any GPU memory or model is
touched. The machine lock is isolated under a temp storage dir via the real
``VAULTSPEC_RAG_QDRANT_STORAGE_DIR`` env knob.

The contract under test: when startup fails before the lifespan yields, the
machine singleton lock is released, so a subsequent in-process acquire succeeds.
The shipping daemon self-heals via the OS releasing the lock on process exit;
this guard makes the in-process lifespan REUSE path a supported contract.
"""

from __future__ import annotations

import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette

from .._machine_lock import (
    acquire_machine_lock,
    machine_lock_path,
    release_machine_lock,
)
from ..config import EnvVar, reset_config
from ..server._lifespan import service_lifespan

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class _ForeignHolderHandler(BaseHTTPRequestHandler):
    """A non-managed HTTP server: ready, but with no managed identity sidecar."""

    def do_GET(self) -> None:  # stdlib handler contract
        if self.path == "/readyz":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok")
        elif self.path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"title":"qdrant","version":"1.18.2"}')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:  # noqa: ARG002
        # Silence stderr noise; the override matches the stdlib signature
        # (``format`` is the stdlib parameter name).
        return


def _foreign_holder() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ForeignHolderHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield port
    finally:
        server.shutdown()
        server.server_close()


@pytest.fixture
def isolated_machine_lock(tmp_path: Path) -> Iterator[Path]:
    """Relocate the machine lock and qdrant storage under a temp dir."""
    key = EnvVar.QDRANT_STORAGE_DIR.value
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path / "qdrant-server" / "storage")
    reset_config()
    try:
        yield machine_lock_path()
    finally:
        release_machine_lock()
        path = machine_lock_path()
        if path.exists():
            path.unlink()
        if previous is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous
        reset_config()


class TestLifespanReleasesLockOnStartupFailure:
    async def test_pre_yield_failure_frees_the_machine_lock(
        self, isolated_machine_lock: Path
    ) -> None:
        # The lock path is isolated under the temp storage dir (the fixture's
        # job), so this test never touches the real machine lock.
        assert isolated_machine_lock == machine_lock_path()
        # Stand a foreign holder on the configured qdrant port so supervised
        # start refuses (no managed identity) - a real pre-yield failure.
        gen = _foreign_holder()
        port = next(gen)
        port_key = EnvVar.QDRANT_PORT.value
        saved_port = os.environ.get(port_key)
        os.environ[port_key] = str(port)
        reset_config()
        try:
            cm = service_lifespan(Starlette())  # the app arg is unused by the lifespan
            with pytest.raises(RuntimeError):
                await cm.__aenter__()

            # The held lock must be free now: a fresh acquire in this same
            # process must succeed (the leak this guard prevents would fail it).
            acquired, holder = acquire_machine_lock()
            assert acquired is True
            assert holder == os.getpid()
            release_machine_lock()
        finally:
            if saved_port is None:
                os.environ.pop(port_key, None)
            else:
                os.environ[port_key] = saved_port
            for _ in gen:
                pass
            reset_config()

    async def test_clean_acquire_after_failure_is_not_double_held(
        self, isolated_machine_lock: Path
    ) -> None:
        assert isolated_machine_lock == machine_lock_path()
        # After a released-on-failure lock, a second independent failure path
        # must also leave the lock free - the release is not a one-shot.
        gen = _foreign_holder()
        port = next(gen)
        port_key = EnvVar.QDRANT_PORT.value
        saved_port = os.environ.get(port_key)
        os.environ[port_key] = str(port)
        reset_config()
        try:
            for _ in range(2):
                cm = service_lifespan(Starlette())
                with pytest.raises(RuntimeError):
                    await cm.__aenter__()
            acquired, _holder = acquire_machine_lock()
            assert acquired is True
            release_machine_lock()
        finally:
            if saved_port is None:
                os.environ.pop(port_key, None)
            else:
                os.environ[port_key] = saved_port
            for _ in gen:
                pass
            reset_config()
