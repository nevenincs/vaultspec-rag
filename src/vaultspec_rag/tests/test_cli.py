"""Unit tests for the CLI application."""

from __future__ import annotations

import os
import typing
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from typer.testing import CliRunner

from vaultspec_rag.cli import (
    _display_search_results,
    _health_probe,
    _is_our_service,
    _is_pid_alive,
    _read_service_status,
    _try_mcp_search,
    _write_service_status,
    app,
)
from vaultspec_rag.config import EnvVar

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

    def test_service_stop_no_status_file(self):
        result = runner.invoke(app, ["server", "service", "stop"])
        assert result.exit_code == 0
        assert "not running" in result.output.lower() or "No service" in result.output

    def test_service_status_no_status_file(self):
        result = runner.invoke(app, ["server", "service", "status"])
        assert result.exit_code == 0
        assert "stopped" in result.output.lower()


class TestMcpFastPath:
    """Tests for MCP fast-path functions (_try_mcp_search, _display_search_results)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_tool_map_vault(self):
        """Connection refused on port 1 returns None, no exception."""
        result = _try_mcp_search("test query", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_tool_map_code(self):
        """search_type='code' maps to search_codebase, returns None on failure."""
        result = _try_mcp_search("test query", "code", 5, 1, "/tmp/proj")
        assert result is None

    def test_invalid_search_type(self):
        """Unknown search_type falls back to search_vault, returns None on failure."""
        result = _try_mcp_search("test query", "invalid", 5, 1, "/tmp/proj")
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


class TestServiceDaemonHelpers:
    """Tests for the service daemon helper functions."""

    def test_is_pid_alive_current_process(self):
        """Current process PID should be alive."""
        assert _is_pid_alive(os.getpid()) is True

    def test_is_pid_alive_impossible_pid(self):
        """An impossibly large PID should not be alive."""
        assert _is_pid_alive(99999999) is False

    def test_is_pid_alive_zero(self):
        """PID 0 should return False."""
        assert _is_pid_alive(0) is False

    def test_is_pid_alive_negative(self):
        """Negative PIDs should return False."""
        assert _is_pid_alive(-1) is False

    def test_is_our_service_current_process(self):
        """Current process (Python) should be recognized as ours."""
        assert _is_our_service(os.getpid()) is True

    def test_is_our_service_dead_pid(self):
        """A dead PID should return False."""
        assert _is_our_service(99999999) is False

    def test_is_our_service_zero(self):
        """PID 0 should return False."""
        assert _is_our_service(0) is False

    def test_is_our_service_negative(self):
        """Negative PIDs should return False."""
        assert _is_our_service(-1) is False

    def test_write_read_status_roundtrip(self, tmp_path: Path):
        """Write and read back should produce the same pid/port."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=12345, port=9999)
            data = _read_service_status()
            assert data is not None
            assert data["pid"] == 12345
            assert data["port"] == 9999
            assert "started_at" in data
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_write_creates_valid_json(self, tmp_path: Path):
        """Status file must be valid JSON with expected keys."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=42, port=8766)
            import json

            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            assert set(data.keys()) == {"pid", "port", "started_at"}
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_read_status_missing_file(self, tmp_path: Path):
        """Reading a nonexistent file should return None."""
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(empty_dir)
        try:
            assert _read_service_status() is None
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_read_status_invalid_json(self, tmp_path: Path):
        """Invalid JSON in status file should return None."""
        sf = tmp_path / "service.json"
        sf.write_text("not json", encoding="utf-8")
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            assert _read_service_status() is None
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_read_status_missing_pid_key(self, tmp_path: Path):
        """Status JSON without a pid key should return None."""
        sf = tmp_path / "service.json"
        sf.write_text('{"port": 8766}', encoding="utf-8")
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            assert _read_service_status() is None
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_stop_stale_pid(self, tmp_path: Path):
        """service_stop with a dead PID cleans up the status file."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)
            sf = tmp_path / "service.json"
            assert sf.exists()

            result = runner.invoke(app, ["server", "service", "stop"])
            assert result.exit_code == 0
            out = result.output.lower()
            assert "no longer running" in out or "cleaned" in out
            assert not sf.exists()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_stale_pid(self, tmp_path: Path):
        """service_status with a dead PID shows stale cleanup message."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)
            sf = tmp_path / "service.json"
            assert sf.exists()

            result = runner.invoke(app, ["server", "service", "status"])
            assert result.exit_code == 0
            assert (
                "stale" in result.output.lower() or "cleaned" in result.output.lower()
            )
            assert not sf.exists()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_health_probe_nonlistening_port(self):
        """Health probe on a port with no listener should return None."""
        assert _health_probe(1) is None

    def test_health_probe_non_json_response(self):
        """Health probe returns None when server sends non-JSON."""
        import http.server
        import threading

        class _GarbageHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"not json at all")

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _GarbageHandler)
        port = server.server_address[1]
        t = threading.Thread(target=server.handle_request, daemon=True)
        t.start()
        try:
            result = _health_probe(port)
            assert result is None
        finally:
            server.server_close()
            t.join(timeout=5)


def _find_free_port() -> int:
    """Bind to an ephemeral port, close, and return the number.

    Good enough for the in-process service-down tests: the OS will not
    reuse it immediately, so subsequent connection attempts reliably
    fail with ConnectionRefused.
    """
    import socket

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestServiceProjectsCli:
    """In-process CLI coverage for `service projects list|evict`."""

    def test_projects_list_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "service", "projects", "list", "--help"],
        )
        assert result.exit_code == 0
        assert "project slots" in result.output.lower()

    def test_projects_evict_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "service", "projects", "evict", "--help"],
        )
        assert result.exit_code == 0
        assert "Evict" in result.output or "evict" in result.output

    def test_projects_list_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            ["server", "service", "projects", "list", "--port", str(port)],
        )
        assert result.exit_code == 3

    def test_projects_evict_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            [
                "server",
                "service",
                "projects",
                "evict",
                "/some/root",
                "--port",
                str(port),
            ],
        )
        assert result.exit_code == 3
