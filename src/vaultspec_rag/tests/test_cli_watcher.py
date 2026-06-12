"""CLI tests for automatic index update subcommands (plan P04).

Verifies the CLI plumbing for the automatic-index-update parity surface: the
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


def test_update_timing_output_uses_user_language(capsys) -> None:
    from ..cli._service_watcher import _print_update_timing

    _print_update_timing({"debounce_ms": 2000, "cooldown_s": 30.0})

    output = capsys.readouterr().out
    assert "File changes: wait 2s before updating." in output
    assert "Same source: wait 30s before updating again." in output
    assert "debounce=" not in output
    assert "cooldown=" not in output


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
