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

import contextlib
import http.server
import json
import threading
from typing import TYPE_CHECKING, ClassVar, cast

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from typer.testing import CliRunner

if TYPE_CHECKING:
    import httpx

import vaultspec_rag.mcp._admin_tools as admin
import vaultspec_rag.server as _m

from ...cli import app
from ...logging_config import read_service_log
from ...server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59234"


class _LogsHTTPHandler(http.server.BaseHTTPRequestHandler):
    payloads: ClassVar[list[dict[str, object]]] = []
    request_paths: ClassVar[list[str]] = []
    request_count = 0

    def do_GET(self) -> None:
        payload_index = min(self.request_count, len(self.payloads) - 1)
        payload = self.payloads[payload_index]
        type(self).request_count += 1
        type(self).request_paths.append(self.path)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


@contextlib.contextmanager
def _logs_http_server(
    payloads: list[dict[str, object]],
) -> Generator[tuple[http.server.HTTPServer, int]]:
    _LogsHTTPHandler.payloads = payloads
    _LogsHTTPHandler.request_paths = []
    _LogsHTTPHandler.request_count = 0
    server = http.server.HTTPServer(("127.0.0.1", 0), _LogsHTTPHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _activity_payload() -> dict[str, object]:
    return {
        "lines": [
            (
                "2026-06-12 08:46:27,900 INFO     uvicorn.access: "
                '127.0.0.1:60001 - "POST /search HTTP/1.1" 200'
            ),
            (
                "2026-06-12 08:46:28,123 WARNING  vaultspec_rag.server: "
                "service.lifecycle event=search "
                "request_id=6793374dabcdef001122334455667788 "
                "search_type=vault "
                "root=chore-476-restructure-execution "
                "results=10 total_seconds=1.383"
            ),
            (
                "2026-06-12 08:46:29,000 WARNING  vaultspec_rag.server: "
                "service.lifecycle event=startup pid=4242"
            ),
        ],
        "total": 3,
        "filters": {},
    }


def _store_update_payload() -> dict[str, object]:
    return {
        "lines": [
            (
                "2026-06-12 13:12:09,845 INFO     vaultspec_rag.store: "
                "Upserted 64 codebase chunk(s)"
            ),
            (
                "2026-06-12 13:12:10,845 INFO     vaultspec_rag.store: "
                "Deleted 2 document(s)"
            ),
        ],
        "total": 2,
        "filters": {},
    }


def _unstructured_warning_payload() -> dict[str, object]:
    return {
        "lines": [
            (
                "2026-06-12 13:14:09,845 WARNING  vaultspec_rag.server: "
                "unexpected service-side warning"
            ),
        ],
        "total": 1,
        "filters": {},
    }


def _plain_lines(output: str) -> list[str]:
    return [line.strip() for line in output.splitlines() if line.strip()]


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
def _routes_app(  # pyright: ignore[reportUnusedFunction]
    tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    """Build a real Starlette app from the read-only ROUTES.

    Sets a known ``_SERVICE_TOKEN`` on the package namespace (the route's
    ``require_token`` reads it through the alias) and points the log reader
    at a temp status dir via the RAG status-dir env var. Restores both on
    teardown so the suite stays isolated.
    """
    import os

    from ...config import EnvVar, reset_config

    (tmp_path / "service.log").write_text(
        "line-a\n"
        "job_id=abc123 phase=running message=started\n"
        "job_id=def456 phase=done message=finished\n"
        "line-b\n",
        encoding="utf-8",
    )

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
    response = cast("httpx.Response", client.get("/logs"))  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    assert response.status_code == 401
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


def test_logs_route_401_with_wrong_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/logs", headers={"Authorization": "Bearer wrong"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 401


def test_logs_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/logs", headers={"Authorization": f"Bearer {token}"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == (
        "line-a\n"
        "job_id=abc123 phase=running message=started\n"
        "job_id=def456 phase=done message=finished\n"
        "line-b"
    )


def test_logs_route_200_with_query_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast("httpx.Response", client.get("/logs", params={"token": token}))  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    assert response.status_code == 200
    assert response.text == (
        "line-a\n"
        "job_id=abc123 phase=running message=started\n"
        "job_id=def456 phase=done message=finished\n"
        "line-b"
    )


def test_logs_route_respects_lines_param(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get(  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
            "/logs",
            params={"token": token, "lines": "1"},
        ),
    )
    assert response.status_code == 200
    assert response.text == "line-b"


def test_logs_route_filters_by_job_id(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get(  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
            "/logs",
            params={"token": token, "lines": "10", "job_id": "abc123"},
        ),
    )
    assert response.status_code == 200
    assert response.text == "job_id=abc123 phase=running message=started"


def test_logs_route_filter_searches_before_tail_limit(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get(  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
            "/logs",
            params={"token": token, "lines": "1", "job_id": "abc123"},
        ),
    )
    assert response.status_code == 200
    assert response.text == "job_id=abc123 phase=running message=started"


def test_logs_json_route_filters_by_contains(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get(  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
            "/logs/json",
            params={"token": token, "lines": "10", "contains": "finished"},
        ),
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["lines"] == ["job_id=def456 phase=done message=finished"]
    assert payload["total"] == 1
    assert payload["filters"] == {"contains": "finished"}


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
    assert f"Address: http://127.0.0.1:{_DEAD_PORT}" in result.stdout
    assert "not running" in result.stdout.lower()


def test_logs_subcommand_registered() -> None:
    result = runner.invoke(app, ["server", "logs", "--help"])
    assert result.exit_code == 0
    assert "--limit" in result.stdout
    assert "--lines" not in result.stdout
    assert "--raw" in result.stdout
    assert "Emit JSON for scripts" in result.stdout
    assert "Number of recent service log lines to inspect" in result.stdout
    assert "Only inspect log lines for this job ID" in result.stdout
    assert "Only inspect log lines containing this text" in result.stdout
    assert "Show original log lines" in result.stdout
    assert "activity entries" not in result.stdout
    assert "Number of trailing log lines" not in result.stdout
    assert "Only show lines containing" not in result.stdout
    assert "diagnostic log lines" not in result.stdout
    assert "JSON envelope" not in result.stdout
    assert "raw implementation" not in result.stdout


def test_logs_lines_alias_is_not_supported() -> None:
    result = runner.invoke(app, ["server", "logs", "--lines", "8", "--help"])

    assert result.exit_code != 0
    assert "No such option" in result.output


def test_logs_human_output_is_activity_feed() -> None:
    with _logs_http_server([_activity_payload()]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "logs", "--limit", "8", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    output = result.output
    lines = _plain_lines(output)
    assert lines[:4] == [
        "Activity",
        f"Address: http://127.0.0.1:{port}",
        "Shown: 2 entries",
        "Source: last 8 log lines",
    ]
    assert (
        "08:46:28 search vault 10 results 1.38s "
        "chore-476-restructure-execution request 6793374d"
    ) in output
    assert "08:46:29 service started process 4242" in output
    assert "request=" not in output
    assert "pid=" not in output
    assert "service.lifecycle" not in output
    assert "POST /search" not in output
    assert "uvicorn.access" not in output
    for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
        assert forbidden not in output


def test_logs_human_output_shows_index_updates() -> None:
    with _logs_http_server([_store_update_payload()]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "logs", "--limit", "8", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    output = result.output
    lines = _plain_lines(output)
    assert lines[:4] == [
        "Activity",
        f"Address: http://127.0.0.1:{port}",
        "Shown: 2 entries",
        "Source: last 8 log lines",
    ]
    assert "13:12:09 index updated 64 source code sections" in output
    assert "13:12:10 index removed 2 vault documents" in output
    assert "2 docs" not in output
    assert "No activity entries" not in output
    assert "vaultspec_rag.store" not in output


def test_logs_human_output_uses_plain_warning_detail_hint() -> None:
    with _logs_http_server([_unstructured_warning_payload()]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "logs", "--limit", "8", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    output = result.output
    lines = _plain_lines(output)
    assert lines[:4] == [
        "Activity",
        f"Address: http://127.0.0.1:{port}",
        "Shown: 1 entry",
        "Source: last 8 log lines",
    ]
    assert len(lines) == 5
    head, hint = lines[4].split("; ", 1)
    clock, level, source = head.split()
    assert clock == "13:14:09"
    assert level == "warning"
    assert source == "server"
    assert hint == "run with --raw for original log line"
    assert "unexpected service-side warning" not in output
    assert "vaultspec_rag.server" not in output
    assert "details=use --raw" not in output
    assert "details available" not in output


def test_logs_empty_output_routes_operator_to_next_commands() -> None:
    with _logs_http_server([{"lines": [], "total": 0, "filters": {}}]) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            ["server", "logs", "--limit", "8", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    assert lines[0] == f"Address: http://127.0.0.1:{port}"
    assert lines[1] == "Activity: none found in the last 8 log lines."
    assert "Next actions:" in lines
    assert "Try:" not in lines
    commands = [line for line in lines if line.startswith("vaultspec-rag ")]
    assert {
        f"vaultspec-rag server jobs --running --port {port}",
        f"vaultspec-rag server status --port {port}",
        f"vaultspec-rag server logs --raw --limit 8 --port {port}",
    } == set(commands)
    assert "No recent activity found" not in result.output
    assert "entries were returned" not in result.output


def test_logs_empty_output_preserves_filters_in_raw_followup() -> None:
    with _logs_http_server([{"lines": [], "total": 0, "filters": {}}]) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            [
                "server",
                "logs",
                "--limit",
                "12",
                "--job-id",
                "abc123456789",
                "--contains",
                "disk space",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    assert (
        'Activity: none found matching job abc12345 and text "disk space" '
        "in the last 12 log lines."
    ) in result.output
    assert (
        "vaultspec-rag server logs --raw --limit 12 "
        f'--port {port} --job-id abc123456789 --contains "disk space"'
    ) in result.output


def test_logs_activity_header_reports_filters() -> None:
    with _logs_http_server([_activity_payload()]) as (_server, port):
        result = runner.invoke(
            app,
            [
                "server",
                "logs",
                "--limit",
                "8",
                "--contains",
                "6793374d",
                "--job-id",
                "job-abcdef123",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    lines = _plain_lines(result.output)
    assert lines[:5] == [
        "Activity",
        f"Address: http://127.0.0.1:{port}",
        "Shown: 2 entries",
        "Source: last 8 log lines",
        'Filter: job job-abcd and text "6793374d"',
    ]
    request_path = _LogsHTTPHandler.request_paths[-1]
    assert request_path.startswith("/logs/json?")
    assert "lines=8" in request_path
    assert "contains=6793374d" in request_path
    assert "job_id=job-abcdef123" in request_path


def test_logs_raw_mode_preserves_log_lines() -> None:
    with _logs_http_server([_activity_payload()]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "logs", "--limit", "8", "--port", str(port), "--raw"],
        )

    assert result.exit_code == 0, result.output
    output = result.output
    assert "service.lifecycle event=search" in output
    assert "POST /search HTTP/1.1" in output
    assert "request_id=6793374dabcdef001122334455667788" in output


def test_logs_json_preserves_raw_service_payload() -> None:
    payload = _activity_payload()
    with _logs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "logs", "--limit", "8", "--port", str(port), "--json"],
        )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is True
    assert envelope["command"] == "service.logs"
    assert envelope["data"]["lines"] == payload["lines"]
    assert "service.lifecycle event=search" in envelope["data"]["lines"][1]


def test_logs_cli_filters_are_passed_to_service() -> None:
    with _logs_http_server([_activity_payload()]) as (_server, port):
        result = runner.invoke(
            app,
            [
                "server",
                "logs",
                "--limit",
                "8",
                "--contains",
                "6793374d",
                "--job-id",
                "job-abc",
                "--port",
                str(port),
                "--raw",
            ],
        )

    assert result.exit_code == 0, result.output
    request_path = _LogsHTTPHandler.request_paths[-1]
    assert request_path.startswith("/logs/json?")
    assert "lines=8" in request_path
    assert "contains=6793374d" in request_path
    assert "job_id=job-abc" in request_path


def test_logs_cli_mcp_parity() -> None:
    assert callable(admin.get_logs)
    help_result = runner.invoke(app, ["server", "--help"])
    assert help_result.exit_code == 0
    assert "logs" in help_result.stdout
