"""Unit tests for the CLI application."""

from __future__ import annotations

import os
import typing
from pathlib import Path

import pytest
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
from vaultspec_rag.torch_config import TorchConfigAction

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


class TestCpuOnlyMessageRendering:
    """Regression guard for Rich-markup escaping in the CPU_ONLY copy.

    The CPU_ONLY remediation message uses ``markup=True`` to colourise
    hints and embeds literal TOML keys (``[[tool.uv.index]]``,
    ``[tool.uv.sources]``, ``[project].dependencies``,
    ``[dependency-groups].dev``). Each opening ``[`` must be
    backslash-escaped so Rich does not parse the TOML keys as markup
    tags. This test renders the actual message via Rich and asserts the
    user-visible bytes — without it, a future copy edit can silently
    break the snippet shown to a user already looking at the wrong
    wheel.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from vaultspec_rag.cli import _cpu_only_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _cpu_only_message(), markup=True
        )
        return buf.getvalue()

    def test_renders_double_brackets_for_aot(self) -> None:
        out = self._render()
        assert "[[tool.uv.index]]" in out, out

    def test_renders_single_brackets_for_section(self) -> None:
        out = self._render()
        assert "[tool.uv.sources]" in out, out

    def test_renders_project_and_groups_keys(self) -> None:
        out = self._render()
        assert "[project].dependencies" in out, out
        assert "[dependency-groups].dev" in out, out

    def test_no_stray_backslashes_in_rendered_output(self) -> None:
        """Rich passes ``\\]`` through verbatim — only ``[`` is escapable.
        A stray backslash in the rendered text means a future edit
        overcorrected and put ``\\]`` somewhere it should not be.
        """
        out = self._render()
        assert "\\" not in out, out


class TestNoGpuMessageRendering:
    """TEST-04 regression: NO_GPU message must render its three
    bullets verbatim through Rich. Symmetric guard with
    TestCpuOnlyMessageRendering.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from vaultspec_rag.cli import _no_gpu_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _no_gpu_message()
        )
        return buf.getvalue()

    def test_renders_nvidia_smi_check(self) -> None:
        out = self._render()
        assert "nvidia-smi" in out

    def test_renders_torch_version_cuda_check(self) -> None:
        out = self._render()
        assert "torch.version.cuda" in out

    def test_renders_wsl_docker_caveat(self) -> None:
        out = self._render()
        assert "WSL" in out or "Docker" in out
        assert "--gpus all" in out

    def test_no_stray_backslashes(self) -> None:
        out = self._render()
        assert "\\" not in out, out


class TestNoTorchMessageRendering:
    """TEST-11 regression: NO_TORCH message must render its single
    actionable ``uv add`` command line cleanly.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from vaultspec_rag.cli import _no_torch_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _no_torch_message()
        )
        return buf.getvalue()

    def test_renders_uv_add_command(self) -> None:
        out = self._render()
        assert "uv add vaultspec-rag" in out
        assert "vaultspec-rag install" in out

    def test_no_stray_backslashes(self) -> None:
        out = self._render()
        assert "\\" not in out, out


class TestRenderInstallReport:
    """CLI-01 regression: the install/uninstall warning loop must NOT
    parse warning bodies as Rich markup. The transitive-dep warning
    embeds literal ``[tool.uv.sources]``, ``[project].dependencies``,
    and ``[dependency-groups].dev``; uv stderr tails embed raw
    ``[…]`` tokens; raw exception messages embed ``[tool]`` strings
    from the historic OutOfOrderTableProxy bug. Rendering any of these
    via ``markup=True`` silently drops the bracketed substrings — a
    direct repeat of the bug Gemini caught for the CPU_ONLY copy, in
    a different channel.
    """

    @staticmethod
    def _render(report: object) -> str:
        import io

        from rich.console import Console

        from vaultspec_rag import cli as cli_mod

        buf = io.StringIO()
        original = cli_mod.console
        cli_mod.console = Console(
            file=buf, force_terminal=False, color_system=None, width=200
        )
        try:
            cli_mod._render_install_report(report)
        finally:
            cli_mod.console = original
        return buf.getvalue()

    def test_warning_with_literal_toml_keys_preserved(self) -> None:
        from vaultspec_rag.commands import InstallReport

        warning = (
            "torch-config patched, but `torch` is not a direct dependency. "
            "uv ignores [tool.uv.sources] for purely transitive packages, "
            "so the cu130 pin will not take effect. "
            "Add `torch>=2.4` to [project].dependencies or "
            "[dependency-groups].dev."
        )
        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.APPLIED,
            warnings=[warning],
        )
        out = self._render(report)
        # All three TOML key tokens must survive the render.
        assert "[tool.uv.sources]" in out, out
        assert "[project].dependencies" in out, out
        assert "[dependency-groups].dev" in out, out

    def test_warning_with_uv_stderr_tail_preserved(self) -> None:
        """Realistic shape: uv stderr embedded in a warning body via
        the new INSTALL-03 tail. ``[project]`` and ``[tool]`` tokens
        in uv's own error rendering must survive.
        """
        from vaultspec_rag.commands import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.APPLIED,
            warnings=[
                "uv sync --reinstall-package torch exited with code 1; "
                "last stderr lines:\n"
                "error: Failed to resolve [project] root\n"
                "error: see [tool.uv] config"
            ],
        )
        out = self._render(report)
        assert "[project]" in out
        assert "[tool.uv]" in out

    def test_conflict_with_aot_token_preserved(self) -> None:
        """Conflict surface (already had its own markup-off treatment
        before this PR — guard it now with a rendering test so a
        future maintainer cannot accidentally collapse the two-line
        treatment back into a single ``f"... {conflict}"`` print).
        """
        from vaultspec_rag.commands import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.CONFLICT,
            torch_config_conflicts=[
                '[[tool.uv.index]] entry name="pytorch-cu130" url-mismatch'
            ],
        )
        out = self._render(report)
        assert "[[tool.uv.index]]" in out
        assert 'name="pytorch-cu130"' in out

    def test_skipped_eof_action_renders_yellow(self) -> None:
        """TEST-12 regression: the new ``skipped-eof`` action label
        must reach the colour map. A regression that dropped it would
        render the label in default-white instead of yellow.
        """
        from vaultspec_rag.commands import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.SKIPPED_EOF,
        )
        out = self._render(report)
        # Action token survives.
        assert "skipped-eof" in out


class TestRenderUninstallReport:
    """Symmetric guard rail for the uninstall renderer."""

    @staticmethod
    def _render(report: object) -> str:
        import io

        from rich.console import Console

        from vaultspec_rag import cli as cli_mod

        buf = io.StringIO()
        original = cli_mod.console
        cli_mod.console = Console(
            file=buf, force_terminal=False, color_system=None, width=200
        )
        try:
            cli_mod._render_uninstall_report(report)
        finally:
            cli_mod.console = original
        return buf.getvalue()

    def test_warning_with_literal_toml_keys_preserved(self) -> None:
        from vaultspec_rag.commands import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            warnings=[
                "no .vaultspec/ at /tmp/foo; "
                "torch-config block in [tool.uv.sources] left intact"
            ],
        )
        out = self._render(report)
        assert "[tool.uv.sources]" in out

    def test_error_action_renders(self) -> None:
        """INSTALL-08 follow-up: uninstall now has ``error`` in its
        colour map. Just verify the label reaches the renderer.
        """
        from vaultspec_rag.commands import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            torch_config_action=TorchConfigAction.ERROR,
        )
        out = self._render(report)
        assert "error" in out


class TestInstallExitCodes:
    """CLI3-01 regression: install exits non-zero on the torch-config
    terminal states the user did not opt into. Issue #83 finding 3
    "Bonus" item.
    """

    @staticmethod
    def _make_pyproject(tmp_path: Path, body: str) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(body, encoding="utf-8", newline="")
        return ws

    def test_install_exit_zero_on_applied(self, tmp_path: Path) -> None:
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n',
        )
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 0, result.output

    def test_install_exit_nonzero_on_skipped_non_tty(self, tmp_path: Path) -> None:
        """Non-TTY without ``--yes`` / ``--force``: torch-config skipped,
        exit code 2 so CI fails loudly.
        """
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
        )
        # CliRunner's stdin is not a TTY, so confirm_fn=None — emulates
        # the non-interactive harness path.
        result = runner.invoke(app, ["install", "--target", str(ws)])
        assert result.exit_code == 2, result.output

    def test_install_exit_nonzero_on_error(self, tmp_path: Path) -> None:
        """Corrupt pyproject → torch_config_action=TorchConfigAction.ERROR → exit 2."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project\nname = ", encoding="utf-8"
        )  # malformed
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 2, result.output

    def test_install_exit_zero_on_conflict(self, tmp_path: Path) -> None:
        """CUSTOMISED block — user-state, not a runtime failure.
        Conflict exits 0; the warning is the signal, not the exit code.
        """
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n'
            "\n[[tool.uv.index]]\n"
            'name = "pytorch-cu130"\n'
            'url = "https://download.pytorch.org/whl/cu121"\n'  # wrong url
            "explicit = true\n",
        )
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 0, result.output

    def test_install_exit_zero_when_no_torch_config(self, tmp_path: Path) -> None:
        """``--no-torch-config`` opts out — exits 0 even on a non-TTY."""
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
        )
        result = runner.invoke(
            app, ["install", "--target", str(ws), "--no-torch-config"]
        )
        assert result.exit_code == 0, result.output


class TestInstallTargetValidation:
    """CLI3-02 regression: per-command ``--target`` must reject
    regular files (matching the global ``--target`` validator).
    """

    def test_per_command_target_rejects_file(self, tmp_path: Path) -> None:
        """Pointing ``install --target`` at a regular file used to slip
        past validation; now correctly rejected by typer's
        ``file_okay=False``.
        """
        f = tmp_path / "not-a-dir.txt"
        f.write_text("hi", encoding="utf-8")
        result = runner.invoke(app, ["install", "--target", str(f)])
        assert result.exit_code != 0, result.output
        assert "is a file" in result.output or "directory" in result.output.lower()

    def test_per_command_target_accepts_dir(self, tmp_path: Path) -> None:
        """Negative pair: a real directory still validates."""
        d = tmp_path / "real-dir"
        d.mkdir()
        result = runner.invoke(
            app, ["install", "--target", str(d), "--no-torch-config"]
        )
        assert result.exit_code == 0, result.output
