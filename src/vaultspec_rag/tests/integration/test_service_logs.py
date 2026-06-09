"""Tests for the Tier-2a logs surface (#142, plan P03).

Three layers, no mocks/skips/monkeypatch:

- Unit: drive ``read_service_log`` against real temp files (``service.log`` +
  ``service.log.1``) asserting oldest-first ordering, the trailing-line clamp,
  and tolerance of a vanished backup.
- Starlette: exercise the real ``GET /logs`` route through
  ``starlette.testclient.TestClient`` (the real ASGI client, NOT a mock) built
  from ``_routes.ROUTES`` with a known ``_SERVICE_TOKEN`` - 401 without token,
  200 text with token.
- MCP + CLI parity: the real ``get_logs`` tool returns ``{"lines": [...]}`` and
  ``server logs`` reports exit 3 against a dead port.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from typer.testing import CliRunner

import vaultspec_rag.mcp._admin_tools as admin
import vaultspec_rag.server as _m

from ...cli import app
from ...logging_config import read_service_log
from ...server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59234"


# --------------------------------------------------------------------------- #
# Unit: read_service_log across the rotated set                               #
# --------------------------------------------------------------------------- #


def test_read_service_log_orders_oldest_first(tmp_path: Path) -> None:
    # .log.1 is the OLDER backup; service.log is the live (newer) file.
    (tmp_path / "service.log.1").write_text("old-1\nold-2\n", encoding="utf-8")
    (tmp_path / "service.log").write_text("new-1\nnew-2\n", encoding="utf-8")

    lines = read_service_log(10, status_dir=tmp_path)
    assert lines == ["old-1", "old-2", "new-1", "new-2"]


def test_read_service_log_spans_multiple_backups(tmp_path: Path) -> None:
    # Highest index is oldest: .log.2 < .log.1 < service.log chronologically.
    (tmp_path / "service.log.2").write_text("a\n", encoding="utf-8")
    (tmp_path / "service.log.1").write_text("b\n", encoding="utf-8")
    (tmp_path / "service.log").write_text("c\n", encoding="utf-8")

    assert read_service_log(10, status_dir=tmp_path) == ["a", "b", "c"]


def test_read_service_log_returns_last_n(tmp_path: Path) -> None:
    (tmp_path / "service.log.1").write_text("1\n2\n3\n", encoding="utf-8")
    (tmp_path / "service.log").write_text("4\n5\n6\n", encoding="utf-8")

    # Newest lines last; the last 2 are the tail of the live file.
    assert read_service_log(2, status_dir=tmp_path) == ["5", "6"]


def test_read_service_log_non_positive_is_empty(tmp_path: Path) -> None:
    (tmp_path / "service.log").write_text("x\n", encoding="utf-8")
    assert read_service_log(0, status_dir=tmp_path) == []
    assert read_service_log(-5, status_dir=tmp_path) == []


def test_read_service_log_missing_live_file(tmp_path: Path) -> None:
    # Only a backup exists; the live service.log has not been recreated yet.
    (tmp_path / "service.log.1").write_text("only-backup\n", encoding="utf-8")
    assert read_service_log(10, status_dir=tmp_path) == ["only-backup"]


def test_read_service_log_empty_dir(tmp_path: Path) -> None:
    assert read_service_log(10, status_dir=tmp_path) == []


# --------------------------------------------------------------------------- #
# Starlette: real ASGI TestClient against /logs gating                        #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _routes_app(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    """Build a real Starlette app from the read-only ROUTES.

    Sets a known ``_SERVICE_TOKEN`` on the package namespace (the route's
    ``require_token`` reads it through the alias) and points the log reader
    at a temp status dir via the RAG status-dir env var. Restores both on
    teardown so the suite stays isolated.
    """
    import os

    from ...config import EnvVar, reset_config

    (tmp_path / "service.log").write_text("line-a\nline-b\n", encoding="utf-8")

    prev_token = _m._SERVICE_TOKEN
    prev_env = os.environ.get(EnvVar.STATUS_DIR.value)
    _m._SERVICE_TOKEN = "test-token-abc"
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path)
    reset_config()

    app_under_test = Starlette(routes=ROUTES)
    client = TestClient(app_under_test)
    try:
        yield client, "test-token-abc"
    finally:
        _m._SERVICE_TOKEN = prev_token
        if prev_env is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev_env
        reset_config()


def test_logs_route_401_without_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = client.get("/logs")
    assert response.status_code == 401
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


def test_logs_route_401_with_wrong_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = client.get("/logs", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_logs_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = client.get("/logs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == "line-a\nline-b"


def test_logs_route_200_with_query_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = client.get("/logs", params={"token": token})
    assert response.status_code == 200
    assert response.text == "line-a\nline-b"


def test_logs_route_respects_lines_param(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = client.get(
        "/logs",
        params={"token": token, "lines": "1"},
    )
    assert response.status_code == 200
    assert response.text == "line-b"


# --------------------------------------------------------------------------- #
# MCP + CLI parity                                                            #
# --------------------------------------------------------------------------- #


@pytest.mark.subprocess_gpu
async def test_get_logs_tool_returns_lines(live_service: tuple[int, Path]) -> None:
    _port, status_dir = live_service

    # Append to the real log file so we can read it back via the API
    with open(status_dir / "service.log", "a", encoding="utf-8") as f:
        f.write("m1\nm2\n")

    result = await admin.get_logs(lines=10)

    assert "m1" in result["lines"]
    assert "m2" in result["lines"]


def test_logs_not_running_json() -> None:
    result = runner.invoke(
        app,
        ["server", "logs", "--port", _DEAD_PORT, "--json"],
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "service.logs"
    assert payload["error"] == "service_not_running"


def test_logs_not_running_prose() -> None:
    result = runner.invoke(app, ["server", "logs", "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert "not running" in result.stdout.lower()


def test_logs_subcommand_registered() -> None:
    result = runner.invoke(app, ["server", "logs", "--help"])
    assert result.exit_code == 0


def test_logs_cli_mcp_parity() -> None:
    assert callable(admin.get_logs)
    help_result = runner.invoke(app, ["server", "--help"])
    assert help_result.exit_code == 0
    assert "logs" in help_result.stdout
