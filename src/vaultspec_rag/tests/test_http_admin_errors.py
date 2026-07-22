"""Admin-path error-surfacing tests for the shared service-client transport.

No mocks: a real in-process HTTP server stands in for the daemon and is driven
over the genuine ``urllib`` wire path through ``_try_http_admin``. The regression
guard (GitHub #199) is that an unexpected (non-refused, non-timeout) failure -
here a live route returning a malformed, non-JSON body - surfaces as the
structured ``http_call_failed`` envelope rather than a bare ``{}`` that a caller
cannot tell apart from a genuinely empty result.
"""

from __future__ import annotations

import contextlib
import os
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, ClassVar

import pytest

from ..config import EnvVar
from ..serviceclient._transport import (
    DEFAULT_ADMIN_TIMEOUT_SECONDS,
    _get_admin_timeout,
    _try_http_admin,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

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


class _AuthDeadlineHandler(BaseHTTPRequestHandler):
    """Exercise the real 401, health-token, authenticated-retry sequence."""

    service_token = "live-loopback-token"
    requests: ClassVar[list[str]] = []

    # The 401 and health-token stages are deliberately cheap and the
    # authenticated retry deliberately far longer than the whole-call budget,
    # so the sequence deterministically reaches the third request and expires
    # there. Tight per-stage sleeps made the budget expire a stage earlier on
    # a loaded host, which is a property of the host clock rather than of the
    # deadline contract under test.
    def do_GET(self) -> None:
        authorization = self.headers.get("Authorization", "")
        type(self).requests.append(f"{self.path} {authorization}".rstrip())
        if self.path == "/health":
            time.sleep(0.005)
            self._json(200, {"service_token": self.service_token})
            return
        if authorization == f"Bearer {self.service_token}":
            time.sleep(0.300)
            self._json(200, {"projects": []})
            return
        time.sleep(0.005)
        self._json(401, {"ok": False, "error": "unauthorized"})

    def _json(self, status: int, payload: dict[str, object]) -> None:
        import json

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
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


@pytest.fixture
def isolated_admin_timeout_env() -> Iterator[None]:
    """Isolate the admin-timeout environment override for precedence tests."""
    key = "VAULTSPEC_RAG_ADMIN_TIMEOUT"
    previous = os.environ.pop(key, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[key] = previous


@pytest.mark.usefixtures("isolated_admin_timeout_env")
class TestAdminTimeoutResolution:
    def test_default_allows_real_service_observability_work(self) -> None:
        assert DEFAULT_ADMIN_TIMEOUT_SECONDS == 30.0
        assert _get_admin_timeout() == 30.0

    def test_explicit_timeout_wins(self) -> None:
        os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "17"
        assert _get_admin_timeout(2.5) == 2.5

    def test_environment_override_wins_over_default(self) -> None:
        os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "17"
        assert _get_admin_timeout() == 17.0


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

    def test_auth_recovery_obeys_one_whole_call_deadline(self) -> None:
        """401, health-token recovery, and retry share one 120ms budget.

        The invariant is that re-authentication does not buy a fresh budget:
        the call must expire against the ORIGINAL deadline somewhere at or
        after the health-token stage. Which of those stages the clock lands in
        is a host-timing detail, so the assertion names the set rather than one
        member - a reset deadline would let the 300ms retry complete and return
        a result instead of timing out at all.
        """
        _AuthDeadlineHandler.requests = []
        server, port = _serve(_AuthDeadlineHandler)
        started = time.monotonic()
        try:
            result = _try_http_admin("list_projects", {}, port, timeout=0.120)
            elapsed = time.monotonic() - started
        finally:
            server.shutdown()
            server.server_close()

        assert result is not None
        assert result.get("ok") is False
        assert result.get("error") == "admin_timeout"
        message = str(result.get("message"))
        assert "0.12 seconds" in message
        assert any(
            stage in message
            for stage in (
                "health-token request",
                "health-token response",
                "authenticated retry",
                "authenticated retry response",
            )
        ), message
        # Bounded well below the 300ms retry sleep: had the deadline been
        # reset at re-auth, the call would have run to ~0.3s and succeeded.
        assert 0.100 <= elapsed < 0.280
        assert _AuthDeadlineHandler.requests[:2] == ["/projects", "/health"]
        assert len(_AuthDeadlineHandler.requests) <= 3


class TestDegradedDiscoveryPropagation:
    """Port resolution fails fast with evidence, never a guessed address.

    Driven against a real held machine lock and real on-disk pointers, with
    both managed singleton paths relocated under the test's own temp root.
    """

    @staticmethod
    def _isolate(tmp_path: Path) -> None:
        from ..config import reset_config

        os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
        os.environ[EnvVar.QDRANT_STORAGE_DIR.value] = str(
            tmp_path / "qdrant-server" / "storage"
        )
        (tmp_path / "status").mkdir(parents=True, exist_ok=True)
        reset_config()

    @staticmethod
    def _restore() -> None:
        from .._machine_lock import release_machine_lock
        from ..config import reset_config

        release_machine_lock()
        os.environ.pop(EnvVar.STATUS_DIR.value, None)
        os.environ.pop(EnvVar.QDRANT_STORAGE_DIR.value, None)
        reset_config()

    def test_absent_singleton_raises_without_a_holder(self, tmp_path: Path) -> None:
        from ..serviceclient._transport import (
            ServiceUnavailableError,
            resolve_service_port,
        )

        self._isolate(tmp_path)
        try:
            with pytest.raises(ServiceUnavailableError) as caught:
                resolve_service_port()
            assert caught.value.is_degraded is False
            assert caught.value.holder_pid == 0
        finally:
            self._restore()

    @pytest.mark.parametrize(
        ("pointer", "expected_reason"),
        [
            (None, "pointer_missing"),
            ("{not json", "pointer_missing"),
            ('{"pid": 1, "port": 0}', "pointer_foreign"),
        ],
    )
    def test_degraded_resolution_carries_its_reason(
        self,
        tmp_path: Path,
        pointer: str | None,
        expected_reason: str,
    ) -> None:
        """Every degraded shape fails fast naming the holder and the reason."""
        from .._machine_lock import acquire_machine_lock, machine_discovery_path
        from ..serviceclient._transport import (
            ServiceUnavailableError,
            resolve_service_port,
        )

        self._isolate(tmp_path)
        try:
            acquired, _holder = acquire_machine_lock()
            assert acquired
            if pointer is not None:
                path = machine_discovery_path()
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(pointer, encoding="utf-8")

            with pytest.raises(ServiceUnavailableError) as caught:
                resolve_service_port()

            error = caught.value
            assert error.is_degraded is True
            assert error.reason == expected_reason
            assert error.holder_pid == os.getpid()
            # The message a caller surfaces carries the evidence itself.
            assert str(os.getpid()) in str(error)
        finally:
            self._restore()

    def test_stale_pointer_never_yields_a_guessed_address(self, tmp_path: Path) -> None:
        """A stale pointer must not be accepted through any fallback.

        A status file naming a different port is present, so a compatibility
        fallback would resolve an address the singleton owner never published.
        """
        import json as _json
        from datetime import UTC, datetime, timedelta

        from .._machine_lock import acquire_machine_lock, machine_discovery_path
        from ..serviceclient._discovery import _status_file
        from ..serviceclient._transport import (
            ServiceUnavailableError,
            resolve_service_port,
        )

        self._isolate(tmp_path)
        try:
            acquired, _holder = acquire_machine_lock()
            assert acquired
            stamp = (datetime.now(UTC) - timedelta(hours=2)).isoformat(
                timespec="seconds"
            )
            path = machine_discovery_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                _json.dumps(
                    {
                        "pid": os.getpid(),
                        "port": 8801,
                        "last_heartbeat": stamp,
                        "stale_after_s": 60,
                    }
                ),
                encoding="utf-8",
            )
            _status_file().write_text(
                _json.dumps({"pid": 4242, "port": 9999}), encoding="utf-8"
            )

            with pytest.raises(ServiceUnavailableError) as caught:
                resolve_service_port()

            assert caught.value.reason == "pointer_stale"
            # Neither the refused pointer port nor the status file's port is
            # handed back as a usable address.
            assert "9999" not in str(caught.value)
        finally:
            self._restore()
