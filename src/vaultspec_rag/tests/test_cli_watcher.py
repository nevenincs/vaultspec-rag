"""CLI tests for the `server service watcher` subcommands (plan P04).

Verifies the CLI plumbing for the watcher-control parity surface: the
service-unreachable path (exit code 3 + JSON envelope) for every
subcommand, and CLI<->MCP structural parity. No mocks: commands run
through the real Typer app against a dead port so ``_try_mcp_admin``
genuinely fails to connect.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from vaultspec_rag import mcp_server
from vaultspec_rag.cli import app

runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59231"

_WATCHER_COMMANDS = [
    ["server", "service", "watcher", "status"],
    ["server", "service", "watcher", "start", "/tmp/x"],
    ["server", "service", "watcher", "stop", "/tmp/x"],
    ["server", "service", "watcher", "reconfigure", "/tmp/x"],
]


@pytest.mark.parametrize("argv", _WATCHER_COMMANDS)
def test_watcher_command_not_running_json(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT, "--json"])
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"] == "service_not_running"


@pytest.mark.parametrize("argv", _WATCHER_COMMANDS)
def test_watcher_command_not_running_prose(argv: list[str]) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert "not running" in result.stdout.lower()


def test_watcher_subcommands_registered() -> None:
    result = runner.invoke(app, ["server", "service", "watcher", "--help"])
    assert result.exit_code == 0
    for name in ("status", "start", "stop", "reconfigure"):
        assert name in result.stdout


def test_cli_mcp_control_parity() -> None:
    # Every watcher-control capability must exist as an MCP tool AND a
    # CLI subcommand (the cli-mcp-control-parity contract).
    for tool in (
        "get_watcher_state",
        "start_watcher",
        "stop_watcher",
        "reconfigure_watcher",
    ):
        assert callable(getattr(mcp_server, tool))
    help_result = runner.invoke(app, ["server", "service", "watcher", "--help"])
    assert help_result.exit_code == 0
    for name in ("status", "start", "stop", "reconfigure"):
        assert name in help_result.stdout
