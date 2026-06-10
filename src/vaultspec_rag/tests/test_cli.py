"""Unit tests for the CLI application."""

from __future__ import annotations

import json
import os
import typing
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from ..cli import (
    _add_backend_contract_rows,
    _display_search_results,
    _display_service_error,
    _health_probe,
    _is_our_service,
    _is_pid_alive,
    _read_service_status,
    _try_http_search,
    _write_service_status,
    app,
)
from ..config import EnvVar
from ..torch_config import TorchConfigAction

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


class TestCleanCommand:
    """Tests for the wipe-only ``clean`` command."""

    @staticmethod
    def _workspace(tmp_path: Path) -> Path:
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        return tmp_path

    def test_clean_help_renders(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0
        assert "wipe" in result.output.lower()

    def test_clean_all_clears_collections_and_metadata(self, tmp_path: Path):
        from ..config import get_config
        from ..store import VaultStore

        root = self._workspace(tmp_path)
        cfg = get_config()
        data_dir = root / cfg.data_dir
        data_dir.mkdir(parents=True)
        (data_dir / cfg.index_metadata_file).write_text('{"x": "y"}', encoding="utf-8")
        (data_dir / cfg.code_index_metadata_file).write_text(
            '{"src/app.py": "hash"}',
            encoding="utf-8",
        )

        store = VaultStore(root)
        try:
            store.ensure_table()
            store.ensure_code_table()
        finally:
            store.close()

        result = runner.invoke(app, ["--target", str(root), "clean", "all", "--yes"])
        assert result.exit_code == 0, result.output
        assert "Clean Summary" in result.output

        store = VaultStore(root)
        try:
            assert store.count() == 0
            assert store.count_code() == 0
        finally:
            store.close()
        assert not (data_dir / cfg.index_metadata_file).exists()
        assert not (data_dir / cfg.code_index_metadata_file).exists()


class TestIndexRebuild:
    """Tests for the drop-and-reindex flag."""

    def test_index_rebuild_parses_with_dry_run(self, tmp_path: Path):
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "code",
                "--rebuild",
                "--dry-run",
            ],
        )
        assert result.exit_code == 0, result.output
        assert "files would be indexed" in result.output

    def test_index_rebuild_without_explicit_type_exits_2(self, tmp_path: Path):
        """--rebuild without --type is rejected.

        The audit found --rebuild silently inherited --type all from the
        default and the in-process branch destroyed both collections.
        Require explicit --type when --rebuild is set; bare `index` stays
        frictionless.
        """
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--rebuild"],
        )
        assert result.exit_code == 2
        assert "explicit --type" in result.output

    def test_index_rebuild_without_explicit_type_json_envelope(
        self,
        tmp_path: Path,
    ):
        """The same guard surfaces a rebuild_requires_explicit_type envelope."""
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--rebuild", "--json"],
        )
        assert result.exit_code == 2
        env = json.loads(result.output.strip())
        assert env["ok"] is False
        assert env["command"] == "index"
        assert env["error"] == "rebuild_requires_explicit_type"
        # Remediation lists the three valid forms.
        rem = env["remediation"]
        assert any("--type vault" in r for r in rem)
        assert any("--type code" in r for r in rem)
        assert any("--type all" in r for r in rem)

    def test_index_bare_invocation_still_works(self, tmp_path: Path):
        """Bare `vaultspec-rag index` (no --rebuild) keeps the all default.

        Cannot fully exercise the indexers without a GPU + corpus, but the
        guard must not fire on this canonical quick-start invocation. We
        invoke with --dry-run (codebase-only path that short-circuits
        before the guard) to confirm the daily-driver pattern lands in
        the dry-run branch and does not hit the guard.
        """
        (tmp_path / ".vault").mkdir()
        (tmp_path / ".vaultspec").mkdir()
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "index", "--dry-run"],
        )
        # Dry-run with default --type all picks up code only and exits
        # cleanly. The new --rebuild guard must NOT have been triggered.
        assert "explicit --type" not in result.output
        assert result.exit_code == 0, result.output


class TestServerCommands:
    """Tests for server subcommand group."""

    def test_server_help(self):
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "mcp" in result.output

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

    def test_service_stop_no_status_file(self, tmp_path: Path):
        # Isolate the status dir to a guaranteed-empty tmp location: the
        # default is ~/.vaultspec-rag/, so without this the assertion races
        # any real service running on the machine (or a concurrent test).
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        try:
            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0
            assert (
                "not running" in result.output.lower() or "No service" in result.output
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_no_status_file(self, tmp_path: Path):
        """No status file → exit 3 (stopped)."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        try:
            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 3
            assert "stopped" in result.output.lower()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)


class TestServerRoutingFlattened:
    """Verify the flattened `server` command surface (W03.P05.S12 #169).

    The `service` nesting level is removed; lifecycle commands and
    sub-groups now live directly under `server`.  `server mcp` is
    unchanged.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_server_start_help(self):
        result = runner.invoke(app, ["server", "start", "--help"])
        assert result.exit_code == 0, result.output

    def test_server_status_help(self):
        result = runner.invoke(app, ["server", "status", "--help"])
        assert result.exit_code == 0, result.output

    def test_server_watcher_status_help(self):
        result = runner.invoke(app, ["server", "watcher", "status", "--help"])
        assert result.exit_code == 0, result.output

    def test_server_projects_list_help(self):
        result = runner.invoke(app, ["server", "projects", "list", "--help"])
        assert result.exit_code == 0, result.output

    def test_server_mcp_start_help(self):
        result = runner.invoke(app, ["server", "mcp", "start", "--help"])
        assert result.exit_code == 0, result.output

    def test_server_service_not_a_command(self):
        """The `service` nesting level must no longer exist."""
        result = runner.invoke(app, ["server", "service", "--help"])
        assert result.exit_code != 0


class TestServiceLifecycleHelpers:
    """_port_is_listening + _heartbeat_age_seconds helpers."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_port_is_listening_true_for_open_socket(self):
        """A socket bound and listening locally is reported as listening."""
        import socket

        from ..cli import _port_is_listening

        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        port = sock.getsockname()[1]
        try:
            assert _port_is_listening(port) is True
        finally:
            sock.close()

    def test_port_is_listening_false_for_closed_port(self):
        """An unbound ephemeral port returns False without raising."""
        import socket

        from ..cli import _port_is_listening

        # Bind to find a free port, then close so it's unbound.
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        sock.close()
        assert _port_is_listening(port) is False

    def test_heartbeat_age_missing_field(self):
        """No last_heartbeat → None (caller treats as 'no data')."""
        from ..cli import _heartbeat_age_seconds

        assert _heartbeat_age_seconds({"pid": 1, "port": 2}) is None

    def test_heartbeat_age_malformed_timestamp(self):
        """Unparseable timestamp → None, no exception."""
        from ..cli import _heartbeat_age_seconds

        assert _heartbeat_age_seconds({"last_heartbeat": "not-a-date"}) is None

    def test_heartbeat_age_fresh(self):
        """Just-written heartbeat → near-zero seconds."""
        from datetime import UTC, datetime

        from ..cli import _heartbeat_age_seconds

        ts = datetime.now(UTC).isoformat(timespec="seconds")
        age = _heartbeat_age_seconds({"last_heartbeat": ts})
        assert age is not None
        assert 0 <= age < 5

    def test_heartbeat_age_stale(self):
        """Old heartbeat → seconds matching the synthesized delta."""
        from datetime import UTC, datetime, timedelta

        from ..cli import _heartbeat_age_seconds

        old = (datetime.now(UTC) - timedelta(seconds=120)).isoformat(
            timespec="seconds",
        )
        age = _heartbeat_age_seconds({"last_heartbeat": old})
        assert age is not None
        assert 115 < age < 125

    def test_heartbeat_age_naive_timestamp_assumed_utc(self):
        """Pre-3.13-style naive ISO timestamps must not crash."""
        from datetime import UTC, datetime, timedelta

        from ..cli import _heartbeat_age_seconds

        old = (
            (datetime.now(UTC) - timedelta(seconds=10))
            .replace(
                tzinfo=None,
            )
            .isoformat(timespec="seconds")
        )
        age = _heartbeat_age_seconds({"last_heartbeat": old})
        assert age is not None
        assert 8 < age < 15

    def test_service_status_stale_heartbeat_exits_4(self, tmp_path: Path):
        """File present + PID alive + heartbeat stale → exit 4."""
        from datetime import UTC, datetime, timedelta

        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=1)  # port 1 unbound
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            # 5 minutes old: well past the 60s staleness threshold.
            data["last_heartbeat"] = (
                datetime.now(UTC) - timedelta(seconds=300)
            ).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 4
            # Port 1 likely yields "crashed (port silent)" first because
            # port-not-listening is checked before heartbeat staleness in
            # the State derivation. Either message is acceptable; the
            # contract being tested is the non-zero exit code.
            assert "crashed" in result.output.lower()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)


class TestMcpFastPath:
    """Tests for MCP fast-path functions (_try_http_search, _display_search_results)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_tool_map_vault(self):
        """Connection refused on port 1 returns None, no exception."""
        result = _try_http_search("test query", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_tool_map_code(self):
        """search_type='code' maps to search_codebase, returns None on failure."""
        result = _try_http_search("test query", "code", 5, 1, "/tmp/proj")
        assert result is None

    def test_invalid_search_type(self):
        """Unknown search_type falls back to search_vault, returns None on failure."""
        result = _try_http_search("test query", "invalid", 5, 1, "/tmp/proj")
        assert result is None

    def test_code_filters_with_vault_returns_usage_error(self):
        """Filter kwargs with --type vault yield a structured usage error."""
        result = _try_http_search(
            "test query",
            "vault",
            5,
            1,
            "/tmp/proj",
            function_name="foo",
        )
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--function-name" in str(result.get("message", ""))

    def test_code_filters_with_all_returns_usage_error(self):
        """search_type='all' is also incompatible with code-only filters."""
        result = _try_http_search(
            "q",
            "all",
            5,
            1,
            "/tmp/proj",
            language="python",
            class_name="Foo",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        msg = str(result.get("message", ""))
        assert "--language" in msg and "--class-name" in msg

    def test_code_filters_unset_dont_short_circuit(self):
        """All filters None must not trigger the usage error path."""
        # No service running on port 1 → expect transport None, NOT usage-error dict.
        result = _try_http_search("q", "vault", 5, 1, "/tmp/proj")
        assert result is None

    def test_code_filters_with_code_attempts_call(self):
        """Filters paired with --type code reach the call path; no service → None."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            language="python",
            function_name="foo",
        )
        # No live service → transport failure → None (not a usage-error dict).
        assert result is None

    def test_search_cmd_rejects_filter_with_vault(self):
        """The CLI ``search`` command refuses filter flags when --type vault."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--function-name",
                "foo",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_vault_filter_with_code(self):
        """Vault filters with --type code error explicitly."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "code",
                "--feature",
                "auth",
            ],
        )
        assert result.exit_code == 2
        assert "require --type vault" in result.output

    def test_path_filter_with_vault_returns_usage_error(self):
        """--path is a code filter; pairing it with vault must error."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            path="src/foo.py",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "path" in str(result.get("message", ""))

    def test_vault_filter_with_code_returns_usage_error(self):
        """doc_type/feature/date/tag with --type code must error."""
        result = _try_http_search(
            "test",
            "code",
            5,
            1,
            "/tmp/proj",
            doc_type="adr",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--doc-type" in str(result.get("message", ""))

    def test_vault_filters_with_code_attempt_call(self):
        """doc_type/feature/date/tag with --type vault reach the call path."""
        result = _try_http_search(
            "q",
            "vault",
            5,
            1,
            "/tmp/proj",
            doc_type="adr",
            feature="auth",
            date="2026-05-28",
            tag="auth",
        )
        # No live service → ConnectionRefused → None.
        assert result is None

    def test_include_path_with_vault_returns_usage_error(self):
        """--include-path is a code filter; --type vault must error."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            include_paths=["src/foo/**"],
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--include-path" in str(result.get("message", ""))

    def test_exclude_path_with_vault_returns_usage_error(self):
        """--exclude-path with --type vault errors out symmetrically."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            exclude_paths=["locales/*.yml"],
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--exclude-path" in str(result.get("message", ""))

    def test_glob_filters_with_code_attempt_call(self):
        """--include-path/--exclude-path with --type code reach the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            include_paths=["src/**"],
            exclude_paths=["tests/**"],
        )
        assert result is None

    def test_search_cmd_rejects_include_path_with_vault(self):
        """CLI: --include-path + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--include-path",
                "src/**",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_exclude_path_with_vault(self):
        """CLI: --exclude-path + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--exclude-path",
                "locales/*.yml",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_dedup_locales_with_vault_returns_usage_error(self):
        """--dedup-locales is a code-only post-process flag."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            dedup_locales=True,
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--dedup-locales" in str(result.get("message", ""))

    def test_prefer_with_vault_returns_usage_error(self):
        """--prefer is a code-only post-process flag."""
        result = _try_http_search(
            "test",
            "vault",
            5,
            1,
            "/tmp/proj",
            prefer="prod",
        )
        assert isinstance(result, dict)
        assert result.get("error") == "invalid_filter_for_search_type"
        assert "--prefer" in str(result.get("message", ""))

    def test_postproc_flags_with_code_attempt_call(self):
        """dedup_locales/prefer with --type code reach the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            dedup_locales=True,
            prefer="tests",
        )
        assert result is None

    def test_search_cmd_rejects_dedup_locales_with_vault(self):
        """CLI: --dedup-locales + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--dedup-locales",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_prefer_with_vault(self):
        """CLI: --prefer + --type vault exits 2 with usage error."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "vault",
                "--prefer",
                "prod",
            ],
        )
        assert result.exit_code == 2
        assert "require --type code" in result.output

    def test_search_cmd_rejects_invalid_prefer_value(self):
        """CLI: --prefer must be prod|tests|docs."""
        result = runner.invoke(
            app,
            [
                "search",
                "anything",
                "--type",
                "code",
                "--prefer",
                "bogus",
            ],
        )
        assert result.exit_code == 2
        assert "must be one of" in result.output

    def test_path_filter_with_code_attempts_call(self):
        """--path with --type code reaches the call path."""
        result = _try_http_search(
            "q",
            "code",
            5,
            1,
            "/tmp/proj",
            path="src/foo.py",
        )
        assert result is None

    def test_live_but_broken_returns_structured_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Non-connection-refused exception yields ok=False dict, not None.

        Without this discrimination the caller would treat a
        live-but-broken service the same as a dead one and silently
        relane to the unsafe in-process path. The fix preserves the
        ``None`` -> dead-service semantic for ConnectionRefused only.
        """

        from .. import cli as cli_mod

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError("synthetic live-but-broken tool failure")

        monkeypatch.setattr("vaultspec_rag.cli._http_search._do_http_call", _boom)

        result = cli_mod._try_http_search(
            "q",
            "code",
            5,
            8766,
            "/tmp/proj",
        )
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "http_call_failed"
        assert "synthetic live-but-broken" in str(result.get("message", ""))

    def test_live_but_broken_reindex_returns_structured_error(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Same discrimination for _try_http_reindex."""

        from .. import cli as cli_mod

        def mock_timeout(*_a: object, **_kw: object) -> None:
            raise TimeoutError("synthetic mcp timeout")

        monkeypatch.setattr(
            "vaultspec_rag.cli._http_search._do_http_call", mock_timeout
        )

        result = cli_mod._try_http_reindex(
            "reindex_vault",
            False,
            8766,
            "/tmp/proj",
        )
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "http_call_failed"

    def test_connection_refused_still_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ):
        """Explicit ConnectionRefusedError must keep the dead-service path."""

        from .. import cli as cli_mod

        def _refuse(*_args: object, **_kwargs: object) -> None:
            raise ConnectionRefusedError("port closed")

        monkeypatch.setattr("vaultspec_rag.cli._http_search._do_http_call", _refuse)

        result = cli_mod._try_http_search(
            "q",
            "code",
            5,
            8766,
            "/tmp/proj",
        )
        assert result is None


class TestSearchSafetyContract:
    """Fail-hard fast path + path indicator + tqdm suppression."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_port_dead_default_fails_hard(self, tmp_path: Path):
        """--port unreachable + no --allow-fallback exits non-zero."""
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
            ],
        )
        assert result.exit_code != 0
        assert "unreachable" in result.output.lower()
        assert "allow-fallback" in result.output.lower()

    def test_search_port_dead_with_allow_fallback_no_warning(self, tmp_path: Path):
        """--allow-fallback does NOT emit the legacy fallthrough warning."""
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
                "--allow-fallback",
            ],
        )
        normalized = " ".join(result.output.split())
        assert "falling back to in-process" not in normalized

    def test_search_results_via_service_indicator(self):
        """via='service' renders '(via service)' in the table title."""
        from io import StringIO

        from rich.console import Console

        out = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "vaultspec_rag.cli.console",
                Console(file=out, force_terminal=False, width=400),
            )
            _display_search_results(
                [{"path": "foo.py", "score": 0.9, "snippet": "x"}],
                "code",
                via="service",
            )
        rendered = " ".join(out.getvalue().split())
        assert "Search Results: code" in rendered
        assert "(via service)" in rendered

    def test_search_results_via_in_process_indicator(self):
        """via='in-process' renders '(via in-process)' in the title."""
        from io import StringIO

        from rich.console import Console

        out = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "vaultspec_rag.cli.console",
                Console(file=out, force_terminal=False, width=400),
            )
            _display_search_results(
                [{"path": "foo.py", "score": 0.9, "snippet": "x"}],
                "code",
                via="in-process",
            )
        rendered = " ".join(out.getvalue().split())
        assert "Search Results: code" in rendered
        assert "(via in-process)" in rendered

    def test_suppress_hf_progress_sets_env(self, monkeypatch: pytest.MonkeyPatch):
        """_suppress_hf_progress sets the HF env vars idempotently."""
        from ..cli import _suppress_hf_progress

        monkeypatch.delenv("HF_HUB_DISABLE_PROGRESS_BARS", raising=False)
        monkeypatch.delenv("TRANSFORMERS_VERBOSITY", raising=False)
        _suppress_hf_progress()
        assert os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] == "1"
        assert os.environ["TRANSFORMERS_VERBOSITY"] == "error"

    def test_search_locked_store_raises_actionable_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Locked store in direct search prints a friendly routing-mode message."""
        from ..store import VaultStoreLockedError

        (tmp_path / ".vaultspec").mkdir()

        def mock_search(*_args: object, **_kwargs: object) -> None:
            raise VaultStoreLockedError(str(tmp_path / "db"))

        monkeypatch.setattr("vaultspec_rag.search_vault", mock_search)
        monkeypatch.setattr(
            "vaultspec_rag.cli._search._default_service_port", lambda: None
        )

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
            ],
        )
        assert result.exit_code != 0
        normalized = " ".join(result.output.split())
        assert "routing mode: direct local-store search" in normalized

    def test_search_locked_store_json_mode(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Locked store in direct search under --json outputs local_store_locked."""
        import json

        from ..store import VaultStoreLockedError

        (tmp_path / ".vaultspec").mkdir()

        def mock_search(*_args: object, **_kwargs: object) -> None:
            raise VaultStoreLockedError(str(tmp_path / "db"))

        monkeypatch.setattr("vaultspec_rag.search_vault", mock_search)
        monkeypatch.setattr(
            "vaultspec_rag.cli._search._default_service_port", lambda: None
        )

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
                "--json",
            ],
        )
        assert result.exit_code != 0
        data = json.loads(result.output.strip())
        assert data["ok"] is False
        assert data["error"] == "local_store_locked"
        assert "direct local-store search" in data["message"]

    def test_search_mcp_timeout_diagnostics(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        """Timeout in client inside _try_http_search returns http_search_timeout."""
        from ..cli import _try_http_search

        def mock_timeout(*_args: object, **_kwargs: object) -> None:
            raise TimeoutError("connection timed out")

        monkeypatch.setattr(
            "vaultspec_rag.cli._http_search._do_http_call", mock_timeout
        )

        res = _try_http_search(
            query="test",
            search_type="vault",
            top_k=5,
            port=8766,
            project_root=str(tmp_path),
            timeout=0.01,
        )
        assert isinstance(res, dict)
        assert res["ok"] is False
        assert res["error"] == "http_search_timeout"
        msg = res["message"]
        assert isinstance(msg, str)
        assert "timed out after" in msg


_FORBIDDEN_DOCSTRING_TOKENS = ("Args:", "Raises:", "CLIState", " ctx ")


class TestHelpCleanup:
    """Verify --help output is operator-facing and free of developer sections.

    Each test invokes the command's --help via CliRunner and asserts:
    - No developer docstring tokens (Args:, Raises:, CLIState, ctx).
    - The operator summary is present.

    W03.P06.S13 (#170).
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def _assert_clean(self, result: Result) -> None:
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
        assert "Build or update" in result.output

    def test_index_help_cross_ref(self):
        """index --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["index", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_clean_help_clean(self):
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "Drop selected" in result.output

    def test_clean_help_cross_ref(self):
        """clean --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["clean", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_search_help_clean(self):
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "hybrid" in result.output.lower() or "Search" in result.output

    def test_search_help_panels(self):
        """search --help must show Code filters and Vault filters panels."""
        result = runner.invoke(app, ["search", "--help"])
        assert result.exit_code == 0, result.output
        assert "Code filters" in result.output
        assert "Vault filters" in result.output

    def test_status_help_clean(self):
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "index" in result.output.lower() or "GPU" in result.output.lower()

    def test_status_help_cross_ref(self):
        """status --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_server_start_help_clean(self):
        result = runner.invoke(app, ["server", "start", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        out = result.output.lower()
        assert "detached" in out or "background" in out

    def test_server_warmup_help_clean(self):
        result = runner.invoke(app, ["server", "warmup", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "model" in result.output.lower() or "GPU" in result.output

    def test_server_warmup_help_cross_ref(self):
        """server warmup --help must reference docs/indexing.md."""
        result = runner.invoke(app, ["server", "warmup", "--help"])
        assert result.exit_code == 0, result.output
        assert "docs/indexing.md" in result.output

    def test_mcp_start_help_clean(self):
        result = runner.invoke(app, ["server", "mcp", "start", "--help"])
        assert result.exit_code == 0, result.output
        self._assert_clean(result)
        assert "stdio" in result.output.lower() or "MCP" in result.output


class TestCleanRequiredTarget:
    """Clean target is required (no default)."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_clean_no_target_errors(self, tmp_path: Path):
        """`vaultspec-rag clean` without a target exits non-zero."""
        result = runner.invoke(
            app,
            ["--target", str(tmp_path), "clean"],
        )
        # Typer surfaces missing required argument with exit code 2
        # and "Missing argument" in stderr.
        assert result.exit_code != 0


class TestNoTruncateFlag:
    """--no-truncate bypasses snippet truncation."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def _render(self, snippet: str, no_truncate: bool) -> str:
        from io import StringIO

        from rich.console import Console

        out = StringIO()
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                "vaultspec_rag.cli.console",
                Console(file=out, force_terminal=False, width=400),
            )
            _display_search_results(
                [{"path": "foo.py", "score": 0.9, "snippet": snippet}],
                "code",
                via="service",
                no_truncate=no_truncate,
            )
        # Strip Rich wrapping whitespace before substring matching.
        return "".join(out.getvalue().split())

    def test_no_truncate_keeps_full_snippet(self):
        """no_truncate=True renders the snippet untruncated."""
        rendered = self._render("a" * 300, no_truncate=True)
        assert "a" * 250 in rendered

    def test_default_truncates_at_120(self):
        """Default behaviour caps the snippet at 120 chars."""
        rendered = self._render("a" * 300, no_truncate=False)
        # 300 chars truncated to 120 - a 200-a run cannot appear.
        assert "a" * 200 not in rendered

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

    def test_backend_contract_rows_render(self):
        """Backend contract rows render stable concurrency wording."""
        from rich.table import Table

        table = Table(show_header=False)
        table.add_column("Key")
        table.add_column("Value")

        _add_backend_contract_rows(
            table,
            {
                "same_project_search_strategy": "serialized",
                "cross_project_search_strategy": "parallel",
                "local_storage_process_model": "exclusive",
            },
        )

        from io import StringIO

        from rich.console import Console

        out = StringIO()
        Console(file=out, force_terminal=False, width=120).print(table)
        rendered = out.getvalue()
        assert "Search Concurrency" in rendered
        assert "supported; same-project local backend access serialized" in rendered
        assert "Storage Process Model" in rendered

    def test_display_service_lock_error_renders_contract(
        self, capsys: pytest.CaptureFixture[str]
    ):
        """Structured local-store errors show remediation and backend contract."""
        _display_service_error(
            {
                "ok": False,
                "error": "local_store_locked",
                "message": "Route concurrent searches through one service.",
                "db_path": "/tmp/qdrant",
                "backend_capabilities": {
                    "same_project_search_strategy": "serialized",
                    "cross_project_search_strategy": "parallel",
                    "local_storage_process_model": "exclusive",
                },
            },
        )

        out = capsys.readouterr().out
        assert "Route concurrent searches through one service." in out
        assert "local_store_locked" in out
        assert "same-project local backend access" in out
        assert "serialized" in out


class TestWinShutdownLog:
    """CLI appends a lifecycle shutdown line on win32.

    The daemon's atexit / lifespan ``finally`` never fire under
    Windows ``TerminateProcess`` (which is what ``os.kill(SIGTERM)``
    becomes on win32). The CLI parent emits a mirror line so the
    audit trail stays uniform with POSIX.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_append_writes_expected_format(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        from .. import cli

        log_path = tmp_path / "service.log"
        monkeypatch.setattr(cli, "_log_file", lambda: log_path)

        cli._append_lifecycle_shutdown_log(
            "cli_terminate",
            pid=123,
            platform="win32",
        )

        content = log_path.read_text(encoding="utf-8")
        lines = content.splitlines()
        assert len(lines) == 1
        line = lines[0]
        assert "WARNING  cli.lifecycle" in line
        assert "event=shutdown" in line
        assert "reason=cli_terminate" in line
        assert "pid=123" in line
        assert "platform=win32" in line

    def test_append_oserror_is_suppressed_and_debug_logged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ):
        """OSError on the append must NOT crash the shutdown path.

        No-swallow rule: the helper must debug-log the exception so
        the suppression is observable.
        """
        from .. import cli

        missing_dir = tmp_path / "nonexistent" / "service.log"
        monkeypatch.setattr(cli, "_log_file", lambda: missing_dir)

        with caplog.at_level("DEBUG", logger="vaultspec_rag.cli"):
            cli._append_lifecycle_shutdown_log("cli_terminate", pid=42)

        # No exception escapes; the debug line is present.
        debug_records = [
            r
            for r in caplog.records
            if r.name == "vaultspec_rag.cli"
            and "lifecycle log append failed" in r.getMessage()
        ]
        assert debug_records, (
            "OSError on append must be debug-logged per the no-swallow rule"
        )
        # The log file was never created (the parent directory does
        # not exist) - confirms the exception path was exercised.
        assert not missing_dir.exists()

    def test_service_stop_emits_log_on_win32(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """End-to-end: ``server stop`` on win32 appends the line."""
        from .. import cli

        status_dir = tmp_path / "status"
        status_dir.mkdir()
        log_path = status_dir / "service.log"

        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        try:
            # Set up a status file pointing at the current process so
            # _is_our_service returns True for the test.
            _write_service_status(pid=os.getpid(), port=18999)

            # Treat the current process as the service so service_stop
            # walks past the validation guard, into the stubbed termination,
            # the unlink, and the new log-append branch we want to exercise.
            def _stub_is_our_service(*_a: object, **_kw: object) -> bool:
                return True

            def _stub_terminate_pid(_pid: int) -> None: ...

            def _stub_is_pid_alive(_pid: int) -> bool:
                return False

            monkeypatch.setattr(cli, "_is_our_service", _stub_is_our_service)
            monkeypatch.setattr(cli, "_terminate_pid", _stub_terminate_pid)
            # The post-terminate poll iterates until _is_pid_alive returns
            # False; stub False so the wait collapses immediately.
            monkeypatch.setattr(cli, "_is_pid_alive", _stub_is_pid_alive)
            monkeypatch.setattr(cli.sys, "platform", "win32")

            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0, result.output
            assert log_path.exists(), (
                f"Expected CLI to create {log_path}; result: {result.output}"
            )

            content = log_path.read_text(encoding="utf-8")
            assert "event=shutdown" in content
            assert "reason=cli_terminate" in content
            assert f"pid={os.getpid()}" in content
            assert "platform=win32" in content
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_stop_skips_log_on_posix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """POSIX path keeps the daemon-side lifecycle finally as source of truth."""
        from .. import cli

        status_dir = tmp_path / "status"
        status_dir.mkdir()
        log_path = status_dir / "service.log"

        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        try:
            _write_service_status(pid=os.getpid(), port=18999)

            def _stub_is_our_service(*_a: object, **_kw: object) -> bool:
                return True

            def _stub_terminate_pid(_pid: int) -> None: ...

            def _stub_is_pid_alive(_pid: int) -> bool:
                return False

            monkeypatch.setattr(cli, "_is_our_service", _stub_is_our_service)
            monkeypatch.setattr(cli, "_terminate_pid", _stub_terminate_pid)
            monkeypatch.setattr(cli, "_is_pid_alive", _stub_is_pid_alive)
            monkeypatch.setattr(cli.sys, "platform", "linux")

            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0, result.output

            # No CLI-emitted line on POSIX.
            assert not log_path.exists(), (
                "POSIX must rely on the daemon's own shutdown log line"
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)


class TestServiceTokenIdentity:
    """Per-process service_token round-trip.

    Daemon writes a uuid4 token into service.json + returns it from
    /health. The CLI compares both - mismatch reports a recycled-PID
    or unrelated-HTTP-server scenario instead of trusting a stale
    truth-lying executable-name check.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_token_match_returns_true(self, monkeypatch: pytest.MonkeyPatch):
        from .. import cli

        def _probe_abc(_port: int) -> dict[str, object]:
            return {"service_token": "abc"}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe_abc)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        assert cli._is_our_service(123, port=8766, expected_token="abc")

    def test_token_mismatch_returns_false(self, monkeypatch: pytest.MonkeyPatch):
        from .. import cli

        def _probe_abc(_port: int) -> dict[str, object]:
            return {"service_token": "abc"}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe_abc)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        # Token mismatch is authoritative - return False regardless of
        # whether the executable-name check would have passed.
        assert not cli._is_our_service(123, port=8766, expected_token="xyz")

    def test_token_absent_in_response_falls_back(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ):
        """Pre-upgrade daemon (no token in response) → exe-name fallback."""
        from .. import cli

        def _probe_empty(_port: int) -> dict[str, object]:
            return {}

        def _alive(_pid: int) -> bool:
            return True

        monkeypatch.setattr(cli, "_health_probe", _probe_empty)
        monkeypatch.setattr(cli, "_is_pid_alive", _alive)
        # On Windows the exe-name check inspects the running pytest
        # process (always "python") so this hits the True branch.
        # No-swallow rule: the fallback must debug-log.
        with caplog.at_level("DEBUG", logger="vaultspec_rag.cli"):
            result = cli._is_our_service(
                os.getpid(),
                port=8766,
                expected_token="abc",
            )
        # Result True or False is platform-dependent; the contract
        # under test is the debug log line.
        assert any(
            "service_token absent" in r.getMessage()
            for r in caplog.records
            if r.name == "vaultspec_rag.cli"
        ), "token-absent fallback must debug-log per the no-swallow rule"
        # Sanity: a result was returned (didn't raise).
        assert isinstance(result, bool)

    def test_no_token_in_status_skips_token_check(self, monkeypatch):
        """No expected_token (pre-upgrade service.json) → exe-name only."""
        from .. import cli

        probe_called = {"n": 0}

        def _probe(_port):
            probe_called["n"] += 1
            return {"service_token": "irrelevant"}

        monkeypatch.setattr(cli, "_health_probe", _probe)
        monkeypatch.setattr(cli, "_is_pid_alive", lambda _pid: True)
        # No expected_token → don't probe.
        cli._is_our_service(os.getpid(), port=8766, expected_token=None)
        assert probe_called["n"] == 0

    def test_health_probe_failure_falls_back(self, monkeypatch):
        """Network failure on /health → exe-name fallback, no exception."""
        from .. import cli

        monkeypatch.setattr(cli, "_health_probe", lambda _port: None)
        monkeypatch.setattr(cli, "_is_pid_alive", lambda _pid: True)
        # Should fall back without raising.
        result = cli._is_our_service(
            os.getpid(),
            port=8766,
            expected_token="abc",
        )
        assert isinstance(result, bool)


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

            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0
            out = result.output.lower()
            assert "no longer running" in out or "cleaned" in out
            assert not sf.exists()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_stale_pid(self, tmp_path: Path):
        """service_status with a dead PID exits 4 and cleans the file.

        Divergent/crashed states exit 4 so scripts can branch on
        "known-bad" without parsing prose.
        """
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)
            sf = tmp_path / "service.json"
            assert sf.exists()

            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 4
            lower = result.output.lower()
            assert "crashed" in lower or "stale" in lower
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

    def test_service_status_renders_health_contract(self, tmp_path: Path):
        """service status renders project_count and backend capabilities."""
        import http.server
        import json
        import threading

        class _HealthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps(
                        {
                            "status": "ready",
                            "cuda": True,
                            "models_loaded": True,
                            "project_count": 3,
                            "uptime_s": 12.0,
                            "backend_capabilities": {
                                "same_project_search_strategy": "serialized",
                                "cross_project_search_strategy": "parallel",
                                "local_storage_process_model": "exclusive",
                            },
                        },
                    ).encode("utf-8"),
                )

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _HealthHandler)
        port = server.server_address[1]
        # service_status calls _port_is_listening first (one TCP
        # connect that the HTTPServer accepts but cannot satisfy
        # with HTTP). Use serve_forever so multiple incoming
        # connections are handled - the listening probe plus
        # the /health probe.
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            # A healthy running service writes last_heartbeat to
            # service.json. Without it the divergence check
            # correctly flags "absent + PID alive" as crashed.
            # Inject a fresh heartbeat to model a running daemon.
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0
            assert "Projects" in result.output
            assert "3" in result.output
            assert "Search Concurrency" in result.output
            assert "Cross-project Search" in result.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            server.server_close()
            thread.join(timeout=5)


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
    """In-process CLI coverage for `server projects list|evict`."""

    def test_projects_list_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "list", "--help"],
        )
        assert result.exit_code == 0
        assert "project slots" in result.output.lower()

    def test_projects_evict_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "evict", "--help"],
        )
        assert result.exit_code == 0
        assert "Evict" in result.output or "evict" in result.output

    def test_projects_list_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            ["server", "projects", "list", "--port", str(port)],
        )
        assert result.exit_code == 3

    def test_projects_evict_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            [
                "server",
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
    user-visible bytes - without it, a future copy edit can silently
    break the snippet shown to a user already looking at the wrong
    wheel.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli import _cpu_only_message

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
        """Rich passes ``\\]`` through verbatim - only ``[`` is escapable.
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

        from ..cli import _no_gpu_message

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

        from ..cli import _no_torch_message

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
    via ``markup=True`` silently drops the bracketed substrings - a
    direct repeat of the bug Gemini caught for the CPU_ONLY copy, in
    a different channel.
    """

    @staticmethod
    def _render(report: object) -> str:
        import io

        from rich.console import Console

        from .. import cli as cli_mod

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
        from ..commands import InstallReport

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
        from ..commands import InstallReport

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
        before this PR - guard it now with a rendering test so a
        future maintainer cannot accidentally collapse the two-line
        treatment back into a single ``f"... {conflict}"`` print).
        """
        from ..commands import InstallReport

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
        from ..commands import InstallReport

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

        from .. import cli as cli_mod

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
        from ..commands import UninstallReport

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
        from ..commands import UninstallReport

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
        # CliRunner's stdin is not a TTY, so confirm_fn=None - emulates
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
        """CUSTOMISED block - user-state, not a runtime failure.
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
        """``--no-torch-config`` opts out - exits 0 even on a non-TTY."""
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

    def test_search_json_port_unreachable_envelope(self, tmp_path):
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

    def test_service_status_json_stopped_envelope(self, tmp_path: Path):
        """No service.json: exit 3 + ok=false envelope with error=stopped."""
        # Isolate STATUS_DIR to an empty dir so the assertion does not depend
        # on the developer machine's ambient ~/.vaultspec-rag/ service state;
        # a running service would otherwise return exit 0 here.
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
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
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_json_crashed_envelope(self, tmp_path: Path):
        """File present + dead PID: exit 4 + ok=false + state=crashed_*."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)
            result = runner.invoke(app, ["server", "status", "--json"])
            assert result.exit_code == 4
            env = self._parse_envelope(result.output)
            assert env["ok"] is False
            assert env["command"] == "service.status"
            assert env["data"]["state"].startswith("crashed_")
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

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

    def test_envelope_is_pure_stdout_no_rich_bytes(self, tmp_path):
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
    def test_envelope_is_pure_json(self, scenario_id, argv, tmp_path):
        """Every --json invocation: parseable JSON, no Rich glyphs, no ANSI."""
        import subprocess
        import sys

        (tmp_path / ".vaultspec").mkdir()
        (tmp_path / ".vault").mkdir()
        full_argv = [
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


class TestAutoDelegation:
    """Verify CLI search and index auto-detect and delegate to a running service."""

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_search_auto_delegates_when_service_running(self, tmp_path, monkeypatch):
        """If service is running, search auto-delegates to it."""
        (tmp_path / ".vaultspec").mkdir()

        # Mock _read_service_status to return active port and pid
        monkeypatch.setattr(
            "vaultspec_rag.cli._read_service_status",
            lambda: {"pid": 12345, "port": 8766, "service_token": "token123"},
        )
        # Mock _is_our_service to return True
        monkeypatch.setattr(
            "vaultspec_rag.cli._is_our_service",
            lambda _pid, _port, _expected_token: True,
        )

        # Mock _try_http_search to return dummy results (so we know it got called)
        called = []

        def mock_try_search(*args, **_kwargs):
            # args: query, search_type, max_results, port, target
            called.append(args[3])
            return {"ok": True, "results": []}

        monkeypatch.setattr(
            "vaultspec_rag.cli._search._try_http_search", mock_try_search
        )

        runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "search",
                "anything",
            ],
        )
        assert len(called) == 1
        assert called[0] == 8766

    def test_index_auto_delegates_when_service_running(self, tmp_path, monkeypatch):
        """If service is running, index auto-delegates to it."""
        (tmp_path / ".vaultspec").mkdir()

        monkeypatch.setattr(
            "vaultspec_rag.cli._read_service_status",
            lambda: {"pid": 12345, "port": 8766, "service_token": "token123"},
        )
        monkeypatch.setattr(
            "vaultspec_rag.cli._is_our_service",
            lambda _pid, _port, _expected_token: True,
        )

        called = []

        def mock_try_reindex(tool_name, _rebuild, port, _target):
            called.append((tool_name, port))
            return {
                "ok": True,
                "added": 1,
                "updated": 0,
                "removed": 0,
                "total": 1,
                "duration_ms": 10,
            }

        monkeypatch.setattr(
            "vaultspec_rag.cli._index._try_http_reindex", mock_try_reindex
        )

        runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "index",
                "--type",
                "vault",
            ],
        )
        assert len(called) == 1
        assert called[0] == ("reindex_vault", 8766)


class TestBenchmarkAndQualityCommands:
    """Tests for the benchmark and quality subcommands, asserting delegation to APIs."""

    def test_benchmark_command_delegation(self, tmp_path, monkeypatch):
        (tmp_path / ".vaultspec").mkdir()

        called = []

        def mock_run_benchmark(root, n_queries):
            called.append((root, n_queries))
            return {
                "p50": 1.2,
                "p95": 3.4,
                "p99": 5.6,
                "mean": 2.3,
                "stdev": 0.5,
                "vault_count": 42,
                "code_count": 100,
                "gpu": "GeForce RTX 4090",
                "vram_mb": 512.0,
            }

        monkeypatch.setattr("vaultspec_rag.api.run_benchmark", mock_run_benchmark)

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "benchmark",
                "--n-queries",
                "10",
            ],
        )
        assert result.exit_code == 0
        assert len(called) == 1
        assert called[0][1] == 10
        assert "GeForce RTX 4090" in result.output
        assert "512.0 MB" in result.output
        assert "42" in result.output

    def test_benchmark_empty_vault(self, tmp_path, monkeypatch):
        (tmp_path / ".vaultspec").mkdir()

        def mock_run_benchmark(*args, **kwargs):
            del args, kwargs
            raise ValueError("No vault documents indexed.")

        monkeypatch.setattr("vaultspec_rag.api.run_benchmark", mock_run_benchmark)

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "benchmark",
            ],
        )
        assert result.exit_code == 1
        assert "No vault documents indexed" in result.output

    def test_quality_command_delegation_pass(self, tmp_path, monkeypatch):
        (tmp_path / ".vaultspec").mkdir()

        called = []

        def mock_run_quality_probe():
            called.append(True)
            return {
                "passed": 8,
                "total": 8,
                "precision": 1.0,
                "threshold": 0.75,
                "probes": [
                    {"query": "q1", "label": "L1", "passed": True},
                ],
            }

        monkeypatch.setattr(
            "vaultspec_rag.api.run_quality_probe",
            mock_run_quality_probe,
        )

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "quality",
            ],
        )
        assert result.exit_code == 0
        assert len(called) == 1
        assert "PASS" in result.output
        assert "100%" in result.output

    def test_quality_command_delegation_fail(self, tmp_path, monkeypatch):
        (tmp_path / ".vaultspec").mkdir()

        def mock_run_quality_probe():
            return {
                "passed": 4,
                "total": 8,
                "precision": 0.5,
                "threshold": 0.75,
                "probes": [
                    {"query": "q1", "label": "L1", "passed": False},
                ],
            }

        monkeypatch.setattr(
            "vaultspec_rag.api.run_quality_probe",
            mock_run_quality_probe,
        )

        result = runner.invoke(
            app,
            [
                "--target",
                str(tmp_path),
                "quality",
            ],
        )
        assert result.exit_code == 1
        assert "FAILED" in result.output
        assert "50%" in result.output
