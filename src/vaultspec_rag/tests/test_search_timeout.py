"""Search timeout resolution tests with no CLI or service-process dependency."""

from __future__ import annotations

import contextlib
import os
import threading
import time
from contextlib import contextmanager
from http.server import ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest

from ..serviceclient._search_transport import get_search_timeout
from ..serviceclient._transport import (
    DEFAULT_ADMIN_TIMEOUT_SECONDS,
    DEFAULT_SEARCH_TIMEOUT_SECONDS,
    _get_admin_timeout,
    _try_http_reindex,
)
from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

_ENV_NAME = "VAULTSPEC_RAG_SEARCH_TIMEOUT"
_ADMIN_ENV_NAME = "VAULTSPEC_RAG_ADMIN_TIMEOUT"
_REINDEX_ENV_NAME = "VAULTSPEC_RAG_REINDEX_TIMEOUT"


@contextmanager
def _timeout_env(name: str, value: str | None) -> Generator[None]:
    previous = os.environ.get(name)
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = previous


@contextmanager
def _slow_reindex_server() -> Generator[int]:
    """Serve a real reindex response only after the configured bound expires."""

    class _SlowReindexHandler(QuietHandler):
        def do_POST(self) -> None:
            time.sleep(0.1)
            body = b'{"ok": true}'
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

    server = ThreadingHTTPServer(("127.0.0.1", 0), _SlowReindexHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_default_search_timeout_is_production_budget() -> None:
    with _timeout_env(_ENV_NAME, None):
        assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["not-a-number", "", "   "])
def test_invalid_env_timeout_uses_production_budget(env_timeout: str) -> None:
    # The settings lookup coerces and RAISES on any of these; the resolver
    # catches that so an operator typo degrades to the budget instead of
    # turning every search into a crash. Drop the catch and these fail with
    # ValueError, not an assertion.
    with _timeout_env(_ENV_NAME, env_timeout):
        assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["0", "-1", "nan", "inf", "-inf"])
def test_non_positive_or_non_finite_env_timeout_uses_production_budget(
    env_timeout: str,
) -> None:
    with _timeout_env(_ENV_NAME, env_timeout):
        assert get_search_timeout(None) == DEFAULT_SEARCH_TIMEOUT_SECONDS


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_explicit_timeout_uses_production_budget(
    timeout: float,
) -> None:
    assert get_search_timeout(timeout) == DEFAULT_SEARCH_TIMEOUT_SECONDS


def test_explicit_timeout_still_wins() -> None:
    assert get_search_timeout(0.25) == 0.25


def test_default_admin_timeout_is_bounded() -> None:
    with _timeout_env(_ADMIN_ENV_NAME, None):
        assert _get_admin_timeout(None) == DEFAULT_ADMIN_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["0", "-1", "nan", "inf", "-inf"])
def test_non_positive_or_non_finite_admin_env_uses_default(
    env_timeout: str,
) -> None:
    with _timeout_env(_ADMIN_ENV_NAME, env_timeout):
        assert _get_admin_timeout(None) == DEFAULT_ADMIN_TIMEOUT_SECONDS


@pytest.mark.parametrize("env_timeout", ["not-a-number", "", "   "])
def test_invalid_admin_env_timeout_uses_default(env_timeout: str) -> None:
    # As above: the settings lookup raises on these, and the catch is what
    # keeps a lifecycle verb emitting one envelope instead of a traceback.
    with _timeout_env(_ADMIN_ENV_NAME, env_timeout):
        assert _get_admin_timeout(None) == DEFAULT_ADMIN_TIMEOUT_SECONDS


@pytest.mark.parametrize("timeout", [0.0, -1.0, float("nan"), float("inf")])
def test_non_positive_or_non_finite_explicit_admin_timeout_uses_default(
    timeout: float,
) -> None:
    assert _get_admin_timeout(timeout) == DEFAULT_ADMIN_TIMEOUT_SECONDS


def test_finite_positive_admin_timeout_still_wins() -> None:
    with _timeout_env(_ADMIN_ENV_NAME, "0.75"):
        assert _get_admin_timeout(None) == 0.75
    assert _get_admin_timeout(0.25) == 0.25


def test_live_reindex_timeout_override_bounds_http_request(tmp_path: Path) -> None:
    """The configured reindex timeout reaches the real HTTP call boundary.

    Guard demonstrated: replacing `_try_http_reindex`'s `resolve_timeout(...)`
    argument with `DEFAULT_REINDEX_TIMEOUT_SECONDS` made this assertion fail
    because the delayed response succeeded. Restoring the runtime resolver made
    the configured 0.01-second bound fail the request again.
    """
    with _timeout_env(_REINDEX_ENV_NAME, "0.01"), _slow_reindex_server() as port:
        result = _try_http_reindex(
            "vault",
            False,
            port,
            str(tmp_path),
            initiator_kind="cli",
        )

    assert result is not None
    assert result["ok"] is False
    assert result["error"] == "http_call_failed"
    message = result["message"]
    assert isinstance(message, str)
    assert "whole HTTP call deadline=0.010s exhausted during initial request" in message
