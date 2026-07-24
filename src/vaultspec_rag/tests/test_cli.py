"""Unit tests for the CLI application: help surfaces and JSON output mode."""

from __future__ import annotations

import json
import os
import re
import typing

import pytest

from ._cli_helpers import (
    _FORBIDDEN_DOCSTRING_TOKENS,
    EnvVar,
    _help_option_descriptions,
    _write_service_status,
    app,
    runner,
)
from .conftest import managed_env

if typing.TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestMainHelp:
    """Tests for top-level CLI help and options."""

    def test_help_shows_usage(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "VaultSpec RAG" in result.output

    def test_help_lists_commands(self):
        result = runner.invoke(app, ["--help"])
        assert "index" in result.output
        assert "clean" in result.output
        assert "search" in result.output
        assert "status" in result.output
        assert "test" in result.output
        assert "server" in result.output

    def test_no_args_shows_help(self):
        result = runner.invoke(app, [])
        # no_args_is_help=True causes typer to exit with code 0
        # but some versions exit with 2; accept both
        assert "Usage" in result.output

    @pytest.mark.parametrize(
        ("args", "expected_commands"),
        [
            (["server"], ("status", "jobs", "logs")),
            (["server", "projects"], ("list", "unload")),
            (["server", "updates"], ("status", "start", "stop", "timing")),
            (["server", "qdrant"], ("install", "status", "clean")),
            (["preprocess"], ("list", "check", "run-one")),
        ],
    )
    def test_nested_groups_without_command_show_help(
        self,
        args: list[str],
        expected_commands: tuple[str, ...],
    ) -> None:
        result = runner.invoke(app, args)

        assert result.exit_code == 0, result.output
        assert "Usage:" in result.output
        assert "Missing command" not in result.output
        missing = [
            command for command in expected_commands if command not in result.output
        ]
        assert not missing, f"missing commands from help: {missing}"

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
        assert "Extra arguments are passed to pytest" in result.output
        for forbidden in ("Args:", "Raises:", "Examples::", "ctx:"):
            assert forbidden not in result.output

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


class TestHelpCleanup:
    """Verify --help output is operator-facing and free of developer sections.

    Each test invokes the command's --help via CliRunner and asserts:
    - No developer docstring tokens (Args:, Raises:, CLIState, ctx).
    - The operator summary is present.

    (#170).
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def _assert_clean(self, result: typing.Any) -> None:
        """Shared guard: no forbidden tokens in help output."""
        out = result.output
        for token in _FORBIDDEN_DOCSTRING_TOKENS:
            assert token not in out, (
                f"Forbidden token {token!r} found in help output:\n{out}"
            )

    def test_index_help_clean(self):
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        normalized = " ".join(result.output.split())
        assert "Build or update" in result.output
        assert "Uses the running service" in normalized
        assert "selected service is not reachable" in normalized
        assert "--dry-run-limit" in result.output
        assert "selected service is unavailable" not in normalized
        for forbidden in ("Qdrant", "tqdm", "agent / CI", "fast path"):
            assert forbidden not in normalized

    @pytest.mark.parametrize(
        "command",
        [
            ["--help"],
            ["index", "--help"],
            ["clean", "--help"],
            ["status", "--help"],
            ["search", "--help"],
            ["server", "warmup", "--help"],
        ],
        ids=["root", "index", "clean", "status", "search", "warmup"],
    )
    def test_help_is_self_documenting(self, command: list[str]):
        """Help must stand alone rather than point into the repo doc tree.

        An operator reading --help has the CLI, not a checkout. A
        ``docs/*.md`` pointer defers the explanation to a file they may
        not have, so the help text must carry the substance itself.
        """
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
        leaked = re.search(r"docs/\S+\.md", result.output)
        assert leaked is None, (
            f"Help for {' '.join(command)!r} defers to {leaked.group(0)!r} "
            f"instead of documenting itself:\n{result.output}"
        )

    def test_clean_help_clean(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        normalized = " ".join(result.output.split())
        assert "Delete selected index data" in normalized
        assert "search index data" not in normalized
        assert "Required so nothing is deleted by accident" in normalized
        for forbidden in ("Qdrant", "metadata sidecars", "collections", "footgun"):
            assert forbidden not in normalized

    def test_search_help_clean(self):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        normalized = " ".join(result.output.split())
        assert "selected service is not reachable" in normalized
        assert "selected service is unavailable" not in normalized
        assert "production, tests, or documentation" in normalized
        assert "'prod', 'tests', or 'docs'" not in normalized
        assert "default 300 seconds" in normalized
        assert "hybrid" in result.output.lower() or "Search" in result.output

    def test_search_help_filter_options_are_plain(self):
        """search --help must list filters without Rich box panels."""
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        descriptions = _help_option_descriptions(result.output)
        assert {"--language", "--structure", "--doc-type"} <= descriptions.keys()
        assert "--node-type" not in descriptions
        structure_help = descriptions["--structure"].lower()
        assert "code results" in structure_help
        assert any(word in structure_help for word in ("structure", "construct"))
        for jargon in ("syntax", "ast", "tree-sitter"):
            assert jargon not in structure_help
        for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
            assert forbidden not in result.output

    def test_root_help_uses_user_facing_language(self):
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0, result.output
        assert "search project documentation and source code" in result.output
        assert "Manage the background search service" in result.output
        assert "Inspect and validate document preprocessing rules" in result.output
        assert "Index data directory" in result.output
        assert "Index data subdirectory" in result.output
        assert "service runtime files" in result.output
        assert "Service log filename inside --status-dir" in result.output
        assert "--storage-dir" in result.output
        for forbidden in (
            "Qdrant",
            "Search data directory",
            "Search storage directory",
            "Index storage directory",
            "service status files",
            "relative to --status-dir",
            "--qdrant-dir",
            "--index-meta",
            "--code-index-meta",
            "MCP protocol adapter",
            "#185",
            "metadata filename",
        ):
            assert forbidden not in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["--qdrant-dir", "legacy-storage", "--help"],
            ["--index-meta", "index.json", "--help"],
            ["--code-index-meta", "code-index.json", "--help"],
        ],
    )
    def test_removed_root_config_aliases_are_not_supported(self, argv: list[str]):
        result = runner.invoke(app, argv)

        assert result.exit_code != 0
        assert "No such option" in result.output

    def test_server_help_uses_user_facing_language(self):
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0, result.output
        assert "Manage the background search service" in result.output
        assert "Manage the HTTP RAG service" not in result.output
        assert "Model Context Protocol" not in result.output
        assert "MCP" not in result.output
        assert "mcp" not in result.output.lower()
        assert "MCP protocol adapter" not in result.output

    def test_status_help_clean(self):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "index counts" in result.output
        assert "index data location" in result.output
        assert "storage location" not in result.output
        assert "search data location" not in result.output
        assert "Emit JSON for scripts" in result.output
        assert "MCP" not in result.output
        assert "get_index_status" not in result.output

    def test_search_help_includes_limit_alias(self):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        assert "--max-results" in result.output
        assert "--limit" in result.output
        assert "Maximum number of results" in result.output

    def test_server_start_help_clean(self):
        result = runner.invoke(app, ["server", "start", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        out = result.output.lower()
        assert "detached" in out or "background" in out
        assert "--updates" in result.output
        assert "--no-updates" in result.output
        assert "--update-delay-ms" in result.output
        assert "--repeat-update-delay-s" in result.output
        assert "--same-project-delay-s" not in result.output
        assert "--same-source-delay-s" not in result.output
        assert "--watch" not in result.output
        assert "--no-watch" not in result.output
        assert "--watch-debounce-ms" not in result.output
        assert "--watch-cooldown-s" not in result.output
        assert "/health" not in result.output
        assert "auto-reindex" not in out
        assert "watcher" not in out
        assert "VAULTSPEC_RAG_WATCH_ENABLED" not in result.output

    def test_server_start_port_in_use_gives_next_actions(self, tmp_path: Path):
        import socket

        # Isolate the status dir so the idempotent already-running check (now the
        # first guard) finds no recorded service and falls through to the port
        # guard - otherwise an ambient running service would make start return
        # `already_running` regardless of the bound port (service-tests-isolate-
        # status-dir).
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = int(sock.getsockname()[1])
        try:
            with managed_env(**{EnvVar.STATUS_DIR: str(tmp_path / "status")}):
                result = runner.invoke(app, ["server", "start", "--port", str(port)])
        finally:
            sock.close()

        assert result.exit_code == 1, result.output
        assert f"Port {port} is already in use." in result.output
        assert "Another process is already using this service address." in result.output
        assert "Next actions:" in result.output
        assert f"vaultspec-rag server status --port {port}" in result.output
        assert (
            f"vaultspec-rag server jobs --state active --port {port}" in result.output
        )
        assert "vaultspec-rag server start --port <free-port>" in result.output
        assert "Traceback" not in result.output

    def test_server_start_update_options_parse_before_port_guard(self, tmp_path: Path):
        import socket

        # Isolated status dir so the idempotent check falls through to the port
        # guard (service-tests-isolate-status-dir).
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = int(sock.getsockname()[1])
        try:
            with managed_env(**{EnvVar.STATUS_DIR: str(tmp_path / "status")}):
                result = runner.invoke(
                    app,
                    [
                        "server",
                        "start",
                        "--port",
                        str(port),
                        "--updates",
                        "--update-delay-ms",
                        "250",
                        "--repeat-update-delay-s",
                        "1.5",
                    ],
                )
        finally:
            sock.close()

        assert result.exit_code == 1, result.output
        assert f"Port {port} is already in use." in result.output
        assert "No such option" not in result.output

    @pytest.mark.parametrize(
        "argv",
        [
            ["server", "start", "--watch"],
            ["server", "start", "--no-watch"],
            ["server", "start", "--watch-debounce-ms", "250"],
            ["server", "start", "--same-project-delay-s", "1.5"],
            ["server", "start", "--same-source-delay-s", "1.5"],
            ["server", "start", "--watch-cooldown-s", "1.5"],
        ],
    )
    def test_server_start_removed_legacy_update_flags_are_not_supported(
        self,
        argv: list[str],
    ):
        result = runner.invoke(app, argv)

        assert result.exit_code != 0
        assert "No such option" in result.output
        assert "Starting service" not in result.output

    def test_server_warmup_help_clean(self):
        result = runner.invoke(app, ["server", "warmup", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "model" in result.output.lower() or "GPU" in result.output

    def test_mcp_start_help_removed(self):
        result = runner.invoke(app, ["server", "mcp", "start", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_benchmark_verb_removed(self):
        # Dev-only quality/benchmark tooling no longer ships as production
        # CLI verbs; the capability is retained in the marked test suite.
        result = runner.invoke(app, ["benchmark", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_quality_verb_removed(self):
        result = runner.invoke(app, ["quality", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_install_help_clean(self):
        result = runner.invoke(app, ["install", "--help"])
        assert result.exit_code == 0, result.output
        assert "Set up vaultspec-rag in a workspace" in result.output
        assert "Emit JSON for scripts" in result.output
        assert "use --yes or --no-torch-config" in result.output
        for forbidden in (
            "Torch-config gating",
            "MCP source files",
            "provider concept",
            "torch_config_action",
            "rag's bundled",
            "Output result as JSON",
            "``--yes``",
            "``--no-torch-config``",
        ):
            assert forbidden not in result.output

    def test_uninstall_help_clean(self):
        result = runner.invoke(app, ["uninstall", "--help"])
        assert result.exit_code == 0, result.output
        assert "Remove vaultspec-rag setup" in result.output
        assert "Emit JSON for scripts" in result.output
        assert "index data under .vault/data/" in result.output
        assert "search data" not in result.output
        assert "``--force``" not in result.output
        for forbidden in (
            "MCP source files",
            "rag's index",
            "forward compat",
            "vaultspec-core",
            "Output result as JSON",
        ):
            assert forbidden not in result.output


class TestJsonOutputMode:
    """Every command supports --json envelope output."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    @staticmethod
    def _parse_envelope(output: str) -> dict[str, typing.Any]:
        """Parse the single JSON document a --json invocation should emit."""
        stripped = output.strip()
        # Tolerate platform-specific trailing whitespace; the contract is
        # one JSON document per invocation.
        return typing.cast("dict[str, typing.Any]", json.loads(stripped))

    def test_search_json_filter_mismatch_envelope(self):
        """Filter on wrong --type yields ok=false envelope with exit 2."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--function-name",
                "foo",
                "--json",
            ],
        )
        assert result.exit_code == 2
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["command"] == "search"
        assert env["error"] == "invalid_filter_for_search_type"
        assert "--function-name" in env["message"]

    def test_search_json_glob_with_vault_envelope(self):
        """Glob + --type vault yields the same envelope shape."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--include-path",
                "src/**",
                "--json",
            ],
        )
        assert result.exit_code == 2
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["error"] == "invalid_filter_for_search_type"

    def test_search_json_port_unreachable_envelope(self, tmp_path: Path) -> None:
        """--port unreachable yields port_unreachable envelope, exit 1."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--port",
                "1",
                "--json",
            ],
        )
        assert result.exit_code == 1
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["error"] == "port_unreachable"
        assert env["port"] == 1
        assert "remediation" in env
        assert "one local user only" in env["message"]
        assert "single-agent" not in env["message"]
        assert "Qdrant lock" not in env["message"]
        assert "in-process" not in env["message"]

    def test_service_status_json_stopped_envelope(self, tmp_path: Path):
        """No service.json: exit 3 + ok=false envelope with error=stopped."""
        # Isolate STATUS_DIR to an empty dir so the assertion does not depend
        # on the developer machine's ambient ~/.vaultspec-rag/ service state;
        # a running service would otherwise return exit 0 here.
        with managed_env(**{EnvVar.STATUS_DIR: str(tmp_path)}):
            result = runner.invoke(
                app,
                ["server", "status", "--json"],
            )
            assert result.exit_code == 3
            env = self._parse_envelope(result.output)
            assert env["ok"] is False
            assert env["command"] == "service.status"
            assert env["error"] == "stopped"
            assert env["data"]["service_json_present"] is False

    def test_service_status_json_crashed_envelope(self, tmp_path: Path):
        """File present + dead PID: exit 4 + ok=false + state=crashed_*."""
        with managed_env(**{EnvVar.STATUS_DIR: str(tmp_path)}):
            _write_service_status(pid=99999999, port=8766)
            result = runner.invoke(app, ["server", "status", "--json"])
            assert result.exit_code == 4
            env = self._parse_envelope(result.output)
            assert env["ok"] is False
            assert env["command"] == "service.status"
            assert env["data"]["state"].startswith("crashed_")

    def test_clean_json_requires_yes(self, tmp_path: Path):
        """--json without --yes yields json_requires_yes envelope, exit 2."""
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "clean", "vault", "--json"],
        )
        assert result.exit_code == 2
        env = self._parse_envelope(result.output)
        assert env["ok"] is False
        assert env["error"] == "json_requires_yes"
        message = str(env["message"])
        assert "--yes" in message
        assert "one JSON result" in message
        assert "interactive confirmation prompt" in message
        assert "stdin" not in message
        assert "corrupt" not in message

    def test_envelope_is_pure_stdout_no_rich_bytes(self, tmp_path: Path) -> None:
        """Output is a single parseable JSON document, no Rich box chars."""
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--type",
                "vault",
                "--function-name",
                "foo",  # forces fast usage-error branch
                "--json",
            ],
        )
        # Trim a possible single trailing newline.
        text = result.output.rstrip("\n")
        # The Rich box-drawing block ─ │ ┌ ┐ └ ┘ must not appear in --json
        # mode; an envelope is plain ASCII JSON.
        for forbidden in ("─", "│", "┌", "┐", "└", "┘"):
            assert forbidden not in text, (
                f"Rich box-drawing leaked into --json stdout: {forbidden!r}"
            )
        # Exactly one JSON document.
        env = json.loads(text)
        assert env["ok"] is False


class TestTqdmSuppression:
    """gh #128: prove tqdm progress-bar bytes never leak to stdout."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_help_subprocess_stdout_has_no_bare_carriage_return(self):
        """Importing the package + emitting --help leaks no bare ``\\r``.

        tqdm rewrites lines via bare ``\\r`` (NOT ``\\r\\n``). A
        clean ``--help`` run proves no import-time side-effect
        (e.g. a stray ``tqdm.write`` in a third-party constructor)
        reaches the user's terminal. Windows ``\\r\\n`` line
        endings are normalised before the check so the assertion
        is platform-independent.
        """
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-m", "vaultspec_rag", "--help"],
            capture_output=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"--help exited {result.returncode}; stderr={result.stderr!r}"
        )
        normalised = result.stdout.replace(b"\r\n", b"\n")
        assert b"\r" not in normalised, (
            "bare carriage-return bytes leaked into --help stdout - "
            "a tqdm-like progress writer is escaping suppression"
        )


class TestJsonStdoutPurityAcrossCommands:
    """gh #128: ``--json`` envelope is parseable + Rich-free everywhere."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    # (id, argv-after-binary, expected_exit_code_predicate)
    _SCENARIOS: typing.ClassVar = [
        # service status with no daemon - exit 3, ok=false envelope
        ("service-status-stopped", ["server", "status", "--json"]),
        # search filter mismatch - exit 2, ok=false envelope
        (
            "search-filter-mismatch",
            [
                "search",
                "x",
                "--type",
                "vault",
                # Literal pattern with no glob meta-chars to avoid
                # Windows argv-globbing surprises in subprocess.
                "--include-path",
                "nonexistent/file.py",
                "--json",
            ],
        ),
        # search port unreachable - exit 1, ok=false envelope
        (
            "search-port-unreachable",
            ["search", "x", "--port", "1", "--json"],
        ),
    ]

    _FORBIDDEN_CHARS: typing.ClassVar = (
        "─",
        "│",
        "┌",
        "┐",
        "└",
        "┘",
        "╭",
        "╮",
        "╰",
        "╯",
    )

    @pytest.mark.parametrize(
        ("scenario_id", "argv"),
        _SCENARIOS,
        ids=[s[0] for s in _SCENARIOS],
    )
    def test_envelope_is_pure_json(
        self, scenario_id: str, argv: list[str], tmp_path: Path
    ) -> None:
        """Every --json invocation: parseable JSON, no Rich glyphs, no ANSI."""
        import subprocess
        import sys

        (tmp_path / ".vaultspec").mkdir()
        (tmp_path / ".vault").mkdir()
        full_argv: list[str] = [
            sys.executable,
            "-m",
            "vaultspec_rag",
            "--target",
            str(tmp_path),
            *argv,
        ]
        result = subprocess.run(
            full_argv,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "NO_COLOR": "1",
                "FORCE_COLOR": "0",
            },
        )
        stdout = result.stdout.decode("utf-8", errors="replace")
        text = stdout.strip()
        assert text, (
            f"{scenario_id}: empty stdout - exit={result.returncode} "
            f"stderr={result.stderr!r}"
        )
        # ANSI escape sequences (`\x1b[`) must not appear.
        assert "\x1b[" not in text, (
            f"{scenario_id}: ANSI escape leaked into --json stdout"
        )
        for forbidden in self._FORBIDDEN_CHARS:
            assert forbidden not in text, (
                f"{scenario_id}: Rich box char {forbidden!r} leaked into --json stdout"
            )
        # The contract is one JSON document per invocation.
        env = json.loads(text)
        assert "ok" in env, f"{scenario_id}: envelope missing 'ok' key"
