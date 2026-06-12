"""CLI tests for automatic index update subcommands (plan P04).

Verifies the CLI plumbing for the automatic-index-update parity surface: the
service-unreachable path (exit code 3 + JSON envelope) for every
subcommand, and CLI<->MCP structural parity. No mocks: commands run
through the real Typer app against a dead port so ``_try_mcp_admin``
genuinely fails to connect.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from typing import TYPE_CHECKING, ClassVar

import pytest
from typer.testing import CliRunner

from ..cli import app

if TYPE_CHECKING:
    from collections.abc import Iterator

runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59231"


class _UpdatesHTTPHandler(http.server.BaseHTTPRequestHandler):
    payloads: ClassVar[list[dict[str, object]]] = []

    def do_GET(self) -> None:
        payload = self.payloads[0]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


@contextlib.contextmanager
def _updates_http_server(
    payload: dict[str, object],
) -> Iterator[tuple[http.server.HTTPServer, int]]:
    _UpdatesHTTPHandler.payloads = [payload]
    server = http.server.HTTPServer(("127.0.0.1", 0), _UpdatesHTTPHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


_UPDATES_COMMANDS = [
    ["server", "updates", "status"],
    ["server", "updates", "start", "/tmp/x"],
    ["server", "updates", "stop", "/tmp/x"],
    ["server", "updates", "reconfigure", "/tmp/x"],
]


@pytest.mark.parametrize("argv", _UPDATES_COMMANDS)
def test_updates_command_not_running_json(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT, "--json"])
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "service_not_running"


@pytest.mark.parametrize("argv", _UPDATES_COMMANDS)
def test_updates_command_not_running_prose(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert "not running" in result.stdout.lower()


def test_updates_subcommands_registered() -> None:
    result = runner.invoke(app, ["server", "updates", "--help"])
    assert result.exit_code == 0
    for name in ("status", "start", "stop", "reconfigure"):
        assert name in result.stdout
    assert "automatic index update" in result.stdout.lower()
    assert "active roots" not in result.stdout.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["server", "updates", "status", "--help"],
        ["server", "updates", "start", "--help"],
        ["server", "updates", "stop", "--help"],
        ["server", "updates", "reconfigure", "--help"],
    ],
)
def test_updates_help_uses_script_json_language(argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    assert "Emit JSON for scripts" in result.stdout
    assert "JSON envelope" not in result.stdout


def test_updates_status_help_uses_project_language() -> None:
    result = runner.invoke(app, ["server", "updates", "status", "--help"])
    assert result.exit_code == 0
    assert "settings and projects" in result.stdout
    assert "active roots" not in result.stdout.lower()


@pytest.mark.parametrize(
    "argv",
    [
        ["server", "updates", "start", "--help"],
        ["server", "updates", "stop", "--help"],
        ["server", "updates", "reconfigure", "--help"],
    ],
)
def test_updates_project_argument_uses_project_language(argv: list[str]) -> None:
    result = runner.invoke(app, argv)
    assert result.exit_code == 0
    assert "PROJECT" in result.stdout
    assert " ROOT" not in result.stdout
    assert "Project root" not in result.stdout


def test_update_timing_output_uses_user_language(capsys) -> None:
    from ..cli._service_watcher import _print_update_timing

    _print_update_timing({"debounce_ms": 2000, "cooldown_s": 30.0})

    output = capsys.readouterr().out
    assert "File changes: wait 2s before updating." in output
    assert "Same source: wait 30s before updating again." in output
    assert "debounce=" not in output
    assert "cooldown=" not in output


def test_updates_status_empty_output_uses_project_language() -> None:
    payload: dict[str, object] = {
        "watch_enabled": True,
        "debounce_ms": 2000,
        "cooldown_s": 30.0,
        "watching": [],
    }
    with _updates_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "updates", "status", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    assert "No projects currently have automatic index updates." in result.output
    assert "No roots" not in result.output


def test_updates_reconfigure_help_uses_user_facing_timing_flags() -> None:
    result = runner.invoke(app, ["server", "updates", "reconfigure", "--help"])
    assert result.exit_code == 0
    assert "--update-delay-ms" in result.stdout
    assert "--same-source-delay-s" in result.stdout
    assert "--debounce-ms" not in result.stdout
    assert "--cooldown-s" not in result.stdout


@pytest.mark.parametrize(
    "argv",
    [
        [
            "server",
            "updates",
            "reconfigure",
            "/tmp/x",
            "--update-delay-ms",
            "500",
            "--same-source-delay-s",
            "2",
        ],
        [
            "server",
            "updates",
            "reconfigure",
            "/tmp/x",
            "--debounce-ms",
            "500",
            "--cooldown-s",
            "2",
        ],
    ],
)
def test_updates_reconfigure_timing_flags_parse(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert "not running" in result.stdout.lower()


def test_watcher_alias_hidden_but_still_compatible() -> None:
    server_help = runner.invoke(app, ["server", "--help"])
    assert server_help.exit_code == 0
    assert "updates" in server_help.stdout
    assert "watcher" not in server_help.stdout.lower()

    legacy = runner.invoke(app, ["server", "watcher", "status", "--port", _DEAD_PORT])
    assert legacy.exit_code == 3
    assert "not running" in legacy.stdout.lower()


def test_cli_mcp_control_parity() -> None:
    # Every backend watcher-control capability must remain available, while
    # the CLI exposes it with human-facing "updates" language.
    import asyncio

    from ..mcp import mcp

    tools = [t.name for t in asyncio.run(mcp.list_tools())]
    for tool in (
        "get_watcher_state",
        "start_watcher",
        "stop_watcher",
        "reconfigure_watcher",
    ):
        assert tool in tools
    help_result = runner.invoke(app, ["server", "updates", "--help"])
    assert help_result.exit_code == 0
    for name in ("status", "start", "stop", "reconfigure"):
        assert name in help_result.stdout
