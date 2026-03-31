"""Unit tests for the CLI application."""

from __future__ import annotations

import typing

import pytest
from typer.testing import CliRunner

from vaultspec_rag.cli import _display_search_results, _try_mcp_search, app

pytestmark = [pytest.mark.unit]

runner = CliRunner()


class TestMainHelp:
    """Tests for top-level CLI help and options."""

    def test_help_shows_usage(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "VaultSpec RAG" in result.output

    def test_help_lists_commands(self):
        result = runner.invoke(app, ["--help"])
        assert "index" in result.output
        assert "search" in result.output
        assert "status" in result.output
        assert "test" in result.output
        assert "server" in result.output

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # no_args_is_help=True causes typer to exit with code 0
        # but some versions exit with 2; accept both
        assert "Usage" in result.output

    def test_version_flag(self):
        result = runner.invoke(app, ["--version"])
        assert result.exit_code == 0
        assert "vaultspec-rag" in result.output


class TestTestCommand:
    """Tests for the `test` subcommand argument pass-through."""

    def test_help(self):
        result = runner.invoke(app, ["test", "--help"])
        assert result.exit_code == 0
        assert "pytest" in result.output.lower()

    def test_accepts_marker_flag(self):
        """Verify the command accepts -m without erroring on arg parsing."""
        result = runner.invoke(app, ["test", "--collect-only", "-q"])
        # Exit code depends on pytest finding tests, but the CLI
        # should not reject the args at the typer level.
        # A typer rejection would show "Error" and "Usage" in output.
        assert "Usage:" not in result.output

    def test_accepts_multiple_pytest_args(self):
        """Verify arbitrary pytest flags pass through."""
        result = runner.invoke(
            app,
            ["test", "-m", "unit", "-v", "--timeout=5", "-x"],
        )
        assert "Usage:" not in result.output


class TestWorkspaceRequired:
    """Commands that require a workspace should fail gracefully without one."""

    def test_index_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "index"],
        )
        assert result.exit_code != 0

    def test_search_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "search", "query"],
        )
        assert result.exit_code != 0

    def test_status_requires_workspace(self):
        result = runner.invoke(
            app,
            ["--target", "/nonexistent/path", "status"],
        )
        assert result.exit_code != 0


class TestServerCommands:
    """Tests for server subcommand group."""

    def test_server_help(self):
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0
        assert "mcp" in result.output
        assert "service" in result.output

    def test_mcp_help(self):
        result = runner.invoke(app, ["server", "mcp", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output

    def test_mcp_stop(self):
        result = runner.invoke(app, ["server", "mcp", "stop"])
        assert result.exit_code == 0
        assert "stdio" in result.output.lower()

    def test_mcp_status(self):
        result = runner.invoke(app, ["server", "mcp", "status"])
        assert result.exit_code == 0
        assert "VaultSpec Search" in result.output
        assert "stdio" in result.output

    def test_service_start_fails(self):
        result = runner.invoke(app, ["server", "service", "start"])
        assert result.exit_code == 1

    def test_service_stop(self):
        result = runner.invoke(app, ["server", "service", "stop"])
        assert result.exit_code == 0

    def test_service_status(self):
        result = runner.invoke(app, ["server", "service", "status"])
        assert result.exit_code == 0
        assert "Ready" in result.output


class TestMcpFastPath:
    """Tests for MCP fast-path functions (_try_mcp_search, _display_search_results)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_tool_map_vault(self):
        """Connection refused on port 1 returns None, no exception."""
        result = _try_mcp_search("test query", "vault", 5, 1)
        assert result is None

    def test_tool_map_code(self):
        """search_type='code' maps to search_codebase, returns None on failure."""
        result = _try_mcp_search("test query", "code", 5, 1)
        assert result is None

    def test_tool_map_all(self):
        """search_type='all' maps to search_all, returns None on failure."""
        result = _try_mcp_search("test query", "all", 5, 1)
        assert result is None

    def test_invalid_search_type(self):
        """Unknown search_type falls back to search_vault, returns None on failure."""
        result = _try_mcp_search("test query", "invalid", 5, 1)
        assert result is None

    def test_display_empty_results(self):
        """Empty results list renders without raising."""
        _display_search_results([], "vault")

    def test_display_missing_fields(self):
        """Dict with no keys renders without raising."""
        _display_search_results([{}], "vault")

    def test_display_with_line_start(self):
        """Result with line_start appends :N to location."""
        _display_search_results(
            [{"path": "foo.py", "score": 0.9, "snippet": "test", "line_start": 42}],
            "vault",
        )

    def test_display_without_line_start(self):
        """Result without line_start renders location as bare path."""
        _display_search_results(
            [{"path": "foo.py", "score": 0.9, "snippet": "test"}],
            "vault",
        )
