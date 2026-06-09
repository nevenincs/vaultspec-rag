"""CLI tests for the `server watcher` subcommands (plan P04).

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

from ..cli import app

runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59231"

_WATCHER_COMMANDS = [
    ["server", "watcher", "status"],
    ["server", "watcher", "start", "/tmp/x"],
    ["server", "watcher", "stop", "/tmp/x"],
    ["server", "watcher", "reconfigure", "/tmp/x"],
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
    result = runner.invoke(app, ["server", "watcher", "--help"])
    assert result.exit_code == 0
    for name in ("status", "start", "stop", "reconfigure"):
        assert name in result.stdout


def test_cli_mcp_control_parity() -> None:
    # Every watcher-control capability must exist as an MCP tool AND a
    # CLI subcommand (the cli-mcp-control-parity contract).
    import asyncio

    from vaultspec_rag.mcp import mcp

    tools = [t.name for t in asyncio.run(mcp.list_tools())]
    for tool in (
        "get_watcher_state",
        "start_watcher",
        "stop_watcher",
        "reconfigure_watcher",
    ):
        assert tool in tools
    help_result = runner.invoke(app, ["server", "watcher", "--help"])
    assert help_result.exit_code == 0
    for name in ("status", "start", "stop", "reconfigure"):
        assert name in help_result.stdout
