"""CLI coverage for server routing, logs, jobs, and projects verbs."""

from __future__ import annotations

import json
import os
import typing

import pytest

from ..cli._process import _DEFAULT_GRACEFUL_DRAIN_SECONDS
from ..cli._service_stop import (
    _STOP_GRACEFUL_DRAIN_SECONDS,
    _STOP_TERMINATION_BUDGET_SECONDS,
)
from ._cli_helpers import (
    _ANSI_RE,
    EnvVar,
    _assert_no_table_borders,
    _assert_project_summary_language,
    _find_free_port,
    _jobs_empty_contract_server,
    _jobs_populated_contract_server,
    _label_values,
    _plain_lines,
    _projects_list_contract_server,
    _projects_unload_contract_server,
    _write_service_status,
    app,
    reset_base_config,
    reset_rag_config,
    runner,
)

if typing.TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestServerCommands:
    """Tests for server subcommand group."""

    def test_server_help(self):
        result = runner.invoke(app, ["server", "--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "updates" in result.output
        assert "watcher" not in result.output.lower()
        assert "mcp" not in result.output.lower()

    @pytest.mark.parametrize(
        "argv",
        [
            ["server", "mcp", "--help"],
            ["server", "mcp", "start", "--help"],
            ["server", "mcp", "stop"],
            ["server", "mcp", "status"],
        ],
    )
    def test_server_mcp_is_not_a_user_facing_command(self, argv: list[str]):
        result = runner.invoke(app, argv)

        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_service_stop_no_status_file(self, tmp_path: Path):
        # Isolate both the status dir and the machine-global storage dir to
        # guaranteed-empty tmp locations. The defaults live under
        # ~/.vaultspec-rag/, so without this the assertion races any real
        # service: `server stop` reclaims a resident service through the
        # machine singleton lock, which is anchored to the storage dir (not the
        # status dir), so isolating the status dir alone is insufficient.
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        storage_dir = tmp_path / "qdrant-server" / "storage"
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(storage_dir)
        reset_base_config()
        reset_rag_config()
        try:
            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0
            assert (
                "not running" in result.output.lower() or "No service" in result.output
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            os.environ.pop(EnvVar.QDRANT_STORAGE_DIR, None)
            reset_base_config()
            reset_rag_config()

    def test_service_status_no_status_file(self, tmp_path: Path):
        """No status file → exit 3 (stopped)."""
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        reset_base_config()
        reset_rag_config()
        try:
            result = runner.invoke(app, ["server", "status"])
            assert result.exit_code == 3
            assert "stopped" in result.output.lower()
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            reset_base_config()
            reset_rag_config()

    def test_server_health_is_not_a_user_facing_command(self):
        """server status is the single user-facing readiness entry point."""
        help_result = runner.invoke(app, ["server", "--help"])
        assert help_result.exit_code == 0, help_result.output
        assert "health" not in help_result.output.lower()

        result = runner.invoke(app, ["server", "health", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_server_watcher_alias_is_not_a_user_facing_command(self):
        """server updates is the single user-facing automatic update surface."""
        updates_help = runner.invoke(app, ["server", "updates", "--help"])
        assert updates_help.exit_code == 0, updates_help.output
        assert "automatic index updates" in updates_help.output

        result = runner.invoke(app, ["server", "watcher", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output


class TestServerRoutingFlattened:
    """Verify the flattened `server` command surface (W03.P05.S12 #169).

    The `service` nesting level is removed; lifecycle commands and
    operator sub-groups now live directly under `server`.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_server_start_help(self):
        result = runner.invoke(app, ["server", "start", "--help"])
        assert result.exit_code == 0, result.output

    def test_server_status_help(self):
        result = runner.invoke(app, ["server", "status", "--help"])
        assert result.exit_code == 0, result.output
        assert "operator summary" in result.output
        assert "server readiness" in result.output
        assert "server health" not in result.output.lower()
        assert "service identity" in result.output
        assert "token" not in result.output.lower()
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output
        assert "full-fidelity" not in result.output

    def test_server_health_not_a_command(self):
        result = runner.invoke(app, ["server", "health", "--help"])
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_server_updates_status_help(self):
        result = runner.invoke(app, ["server", "updates", "status", "--help"])
        assert result.exit_code == 0, result.output
        assert "automatic index update" in result.output.lower()
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output

    def test_server_updates_status_explains_missing_timing(self, tmp_path: Path):
        import http.server
        import threading

        project = tmp_path / "project-alpha"
        project.mkdir()
        paths: list[str] = []

        class WatcherStateHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                paths.append(self.path)
                response = {
                    "watch_enabled": True,
                    "watching": [str(project)],
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(response).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), WatcherStateHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "updates",
                    "status",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert paths == ["/watcher"]

        output = _ANSI_RE.sub("", result.output)
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        assert lines[0] == f"Address: http://127.0.0.1:{server.server_port}"
        assert lines[1] == "Automatic index updates: enabled"
        assert lines[2] == "File changes: not reported by service."
        assert lines[3] == "Repeat updates: not reported by service."
        assert lines[4] == "Projects updating automatically: 1"
        assert lines[5] == "- Project: project-alpha"
        assert lines[6] == f"Path: {project}"
        assert "unknown" not in output.lower()
        assert "wait not reported" not in output.lower()

    def test_server_projects_list_help(self):
        result = runner.invoke(app, ["server", "projects", "list", "--help"])
        assert result.exit_code == 0, result.output
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output

    def test_server_service_not_a_command(self):
        """The `service` nesting level must no longer exist."""
        result = runner.invoke(app, ["server", "service", "--help"])
        assert result.exit_code != 0

    def test_qdrant_status_splits_service_managed_process_details(self, tmp_path: Path):
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        reset_base_config()
        reset_rag_config()
        try:
            _write_service_status(pid=os.getpid(), port=8766)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            data.update(
                {
                    "qdrant_pid": 43210,
                    "qdrant_alive": True,
                    "qdrant_port": 6334,
                }
            )
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "qdrant", "status"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Address"] == "http://127.0.0.1:6334"
            assert labels["Connection"] == "not accepting requests"
            assert labels["Process"] == "running, started by vaultspec-rag"
            assert labels["Process ID"] == "43210"
            assert labels["Process port"] == "6334"
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            reset_base_config()
            reset_rag_config()


class TestServiceLogsCli:
    """In-process CLI coverage for `server logs`."""

    def test_logs_lines_alias_is_not_supported(self) -> None:
        result = runner.invoke(app, ["server", "logs", "--lines", "7"])

        assert result.exit_code != 0
        assert "No such option" in result.output

    def test_logs_raw_compatibility_option_is_not_supported(self) -> None:
        result = runner.invoke(app, ["server", "logs", "--raw"])

        assert result.exit_code != 0
        assert "No such option" in result.output

    def test_logs_read_grouped_retained_sources_after_service_stops(
        self,
        tmp_path: Path,
    ) -> None:
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        (status_dir / "service.log").write_text(
            "service older\nservice newest\n",
            encoding="utf-8",
        )
        (status_dir / "qdrant.log").write_text(
            "qdrant older\nqdrant newest\n",
            encoding="utf-8",
        )
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        reset_base_config()
        reset_rag_config()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "logs",
                    "--limit",
                    "1",
                ],
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            reset_base_config()
            reset_rag_config()

        assert result.exit_code == 0, result.output
        assert _plain_lines(result.output) == [
            "[service]",
            "service newest",
            "[qdrant]",
            "qdrant newest",
        ]
        _assert_no_table_borders(result.output)

    def test_logs_offline_json_filters_one_source_with_production_contract(
        self,
        tmp_path: Path,
    ) -> None:
        status_dir = tmp_path / "status"
        status_dir.mkdir()
        (status_dir / "qdrant.log").write_text(
            "alpha JOB-7 other\nbeta job-7 needle\ngamma needle\n",
            encoding="utf-8",
        )
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        reset_base_config()
        reset_rag_config()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "logs",
                    "--source",
                    "qdrant",
                    "--limit",
                    "1",
                    "--job-id",
                    "job-7",
                    "--contains",
                    "NEEDLE",
                    "--json",
                ],
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
            reset_base_config()
            reset_rag_config()

        assert result.exit_code == 0, result.output
        envelope = json.loads(result.output)
        assert envelope == {
            "ok": True,
            "command": "server.logs",
            "data": {
                "source": "qdrant",
                "limit": 1,
                "groups": [
                    {
                        "source": "qdrant",
                        "lines": ["beta job-7 needle"],
                    }
                ],
                "filters": {"job_id": "job-7", "contains": "NEEDLE"},
            },
        }


class TestServiceJobsCli:
    """In-process CLI coverage for `server jobs`."""

    def test_jobs_empty_filtered_result_stays_actionable(self) -> None:
        server, thread, requests = _jobs_empty_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "jobs",
                    "--state",
                    "active",
                    "--limit",
                    "5",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == ["/jobs?limit=5&phase=running"]
        lines = _plain_lines(result.output)
        expected_present = [
            "Jobs",
            f"Address: http://127.0.0.1:{server.server_port}",
            "Displayed: 0 matching jobs",
            "Total: 0 jobs",
            "Displayed jobs: 0 active, 0 waiting, 0 finished, 0 failed",
            "Order: latest job appears last",
            "Filter: state active",
            "There are no active jobs.",
            "Next actions:",
            f"vaultspec-rag server status --port {server.server_port}",
            f"vaultspec-rag server logs --limit 20 --port {server.server_port}",
        ]
        missing = [text for text in expected_present if text not in lines]
        assert not missing, f"missing operator lines: {missing}"
        _assert_no_table_borders(result.output)
        assert "Jobs on service port" not in result.output
        assert "Recent jobs on service" not in result.output
        assert "States:" not in result.output
        assert "watcher" not in result.output.lower()

    def test_jobs_populated_feed_uses_visible_prefixes(self) -> None:
        server, thread, requests = _jobs_populated_contract_server()
        try:
            result = runner.invoke(
                app,
                ["server", "jobs", "--limit", "2", "--port", str(server.server_port)],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == ["/jobs?limit=2"]
        lines = _plain_lines(result.output)
        assert "Legend: * active, ~ waiting, ! failed, - finished" in lines
        finished = [
            line
            for line in lines
            if "finished code index refresh for finished-project" in line
        ]
        active = [
            line
            for line in lines
            if "active vault index update for running-project" in line
        ]
        assert len(finished) == 1
        assert len(active) == 1
        assert finished[0].startswith("- ")
        assert active[0].startswith("* ")
        assert lines.index(finished[0]) < lines.index(active[0])
        _assert_no_table_borders(result.output)


class TestServiceProjectsCli:
    """In-process CLI coverage for `server projects list|unload`."""

    def test_projects_list_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "list", "--help"],
        )
        assert result.exit_code == 0
        assert "projects currently loaded" in result.output.lower()
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output
        assert "project slots" not in result.output.lower()
        projects_help = runner.invoke(app, ["server", "projects", "--help"])
        assert projects_help.exit_code == 0
        assert "unload" in projects_help.output.lower()
        assert "evict" not in projects_help.output.lower()

    def test_projects_unload_help_renders(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "unload", "--help"],
        )
        assert result.exit_code == 0
        assert "Unload" in result.output or "unload" in result.output
        assert "PROJECT" in result.output
        assert " ROOT" not in result.output
        assert "Project root" not in result.output
        assert "Emit JSON for scripts" in result.output
        assert "JSON envelope" not in result.output

    def test_projects_evict_alias_is_not_supported(self) -> None:
        result = runner.invoke(
            app,
            ["server", "projects", "evict", "--help"],
        )
        assert result.exit_code != 0
        assert "No such command" in result.output

    def test_projects_list_summary_uses_operator_language(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from ..cli._service_projects import _print_projects_summary

        _print_projects_summary(
            [
                {
                    "root": r"Y:\code\example",
                    "idle_seconds": 125,
                    "ref_count": 1,
                    "last_access_iso": "2026-06-12T14:05:06Z",
                }
            ],
            max_projects=16,
            idle_ttl=1800,
        )

        out = capsys.readouterr().out
        _assert_project_summary_language(out)

    def test_projects_list_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            ["server", "projects", "list", "--port", str(port)],
        )
        assert result.exit_code == 3
        assert f"Address: http://127.0.0.1:{port}" in result.output

    def test_projects_unload_service_down_returns_exit_3(self) -> None:
        port = _find_free_port()
        result = runner.invoke(
            app,
            [
                "server",
                "projects",
                "unload",
                "/some/root",
                "--port",
                str(port),
            ],
        )
        assert result.exit_code == 3
        assert f"Address: http://127.0.0.1:{port}" in result.output

    def test_projects_list_command_humanizes_service_payload(self) -> None:
        server, thread, requests = _projects_list_contract_server()
        try:
            result = runner.invoke(
                app,
                ["server", "projects", "list", "--port", str(server.server_port)],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 0, result.output
        assert requests == ["/projects"]
        lines = _plain_lines(result.output)
        expected_present = [
            f"Address: http://127.0.0.1:{server.server_port}",
            "Capacity: 2 of 8 projects loaded",
            "Automatic unload: after 10 minutes idle",
            "- Project: busy",
            r"Path: Y:\code\busy",
            "Active requests: 2",
            "Last activity: 1 minute 5 seconds ago",
            "Last request: 14:05:06",
            "- Project: ready",
            r"Path: Y:\code\ready",
            "Active requests: none",
            "Last activity: 4 seconds ago",
        ]
        missing = [text for text in expected_present if text not in lines]
        assert not missing, f"missing operator lines: {missing}"
        ready_index = lines.index("- Project: ready")
        ready_block = lines[ready_index : ready_index + 4]
        assert ready_block == [
            "- Project: ready",
            r"Path: Y:\code\ready",
            "Active requests: none",
            "Last activity: 4 seconds ago",
        ]
        joined = "\n".join(lines).lower()
        forbidden_substrings = [
            "handling 2 active requests",
            "available for new requests",
            "last used: not recorded",
            "last used:",
            "no timestamp from service",
            "project handle",
            "references",
            "loaded projects:",
            "in use:",
            "active uses:",
            "not currently in use",
        ]
        leaked = [text for text in forbidden_substrings if text in joined]
        assert not leaked, f"internal phrasing leaked: {leaked}"
        leaked_prefixes = [
            line
            for line in lines
            if line.startswith("Requests:") or line in {"yes", "no"}
        ]
        assert not leaked_prefixes, f"internal fields leaked: {leaked_prefixes}"
        _assert_no_table_borders(result.output)

    def test_projects_unload_unexpected_response_stays_actionable(self) -> None:
        server, thread, requests = _projects_unload_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "projects",
                    "unload",
                    r"Y:\code\example",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 1, result.output
        assert requests == [{"root": r"Y:\code\example"}]
        labels = _label_values(result.output)
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert labels["Project"] == "example"
        assert labels["Path"] == r"Y:\code\example"
        assert labels["Unload"] == "service could not confirm unload"
        assert (
            labels["Next action"]
            == f"vaultspec-rag server status --port {server.server_port}"
        )
        assert "unexpected" not in result.output
        assert "{" not in result.output

    def test_projects_unload_not_found_uses_project_block(self) -> None:
        server, thread, requests = _projects_unload_contract_server(
            {"evicted": False, "reason": "not_found"}
        )
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "projects",
                    "unload",
                    r"Y:\code\not-loaded",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 2, result.output
        assert requests == [{"root": r"Y:\code\not-loaded"}]
        labels = _label_values(result.output)
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert labels["Project"] == "not-loaded"
        assert labels["Path"] == r"Y:\code\not-loaded"
        assert labels["Unload"] == "project is not loaded"
        assert "Project is not loaded:" not in result.output
        _assert_no_table_borders(result.output)

    def test_projects_unload_json_message_stays_user_facing(self) -> None:
        server, thread, requests = _projects_unload_contract_server()
        try:
            result = runner.invoke(
                app,
                [
                    "server",
                    "projects",
                    "unload",
                    r"Y:\code\example",
                    "--port",
                    str(server.server_port),
                    "--json",
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 1, result.output
        assert requests == [{"root": r"Y:\code\example"}]
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "service.projects.unload"
        assert envelope["error"] == "unexpected_response"
        assert r"Y:\code\example" in envelope["message"]
        assert "vaultspec-rag server status" in envelope["message"]
        assert "Eviction failed" not in envelope["message"]
        assert "reason=" not in envelope["message"]


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

            budgets: list[tuple[float, float]] = []

            def _stub_terminate_pid(
                _pid: int,
                timeout: float = 4.0,
                *,
                graceful_drain: float = 2.0,
            ) -> None:
                budgets.append((timeout, graceful_drain))

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
            assert f"Process ID: {os.getpid()}" in result.output
            assert "PID:" not in result.output
            # A console-detached daemon can never receive a console control
            # event, so Windows must not spend the long drain waiting for a
            # graceful shutdown that cannot be signalled; it goes straight to
            # the forced kill and reclaims the pointer afterwards.
            assert budgets == [
                (_STOP_TERMINATION_BUDGET_SECONDS, _DEFAULT_GRACEFUL_DRAIN_SECONDS)
            ]
            assert _DEFAULT_GRACEFUL_DRAIN_SECONDS < _STOP_GRACEFUL_DRAIN_SECONDS
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

    def test_service_stop_emits_log_on_posix_too(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ):
        """POSIX also gets the CLI-side initiator line (emitted on every platform)."""
        from .. import cli

        status_dir = tmp_path / "status"
        status_dir.mkdir()
        log_path = status_dir / "service.log"

        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        try:
            _write_service_status(pid=os.getpid(), port=18999)

            def _stub_is_our_service(*_a: object, **_kw: object) -> bool:
                return True

            def _stub_terminate_pid(
                _pid: int,
                timeout: float = 4.0,
                *,
                graceful_drain: float = 2.0,
            ) -> None:
                assert timeout > graceful_drain

            def _stub_is_pid_alive(_pid: int) -> bool:
                return False

            monkeypatch.setattr(cli, "_is_our_service", _stub_is_our_service)
            monkeypatch.setattr(cli, "_terminate_pid", _stub_terminate_pid)
            monkeypatch.setattr(cli, "_is_pid_alive", _stub_is_pid_alive)
            monkeypatch.setattr(cli.sys, "platform", "linux")

            result = runner.invoke(app, ["server", "stop"])
            assert result.exit_code == 0, result.output
            assert f"Process ID: {os.getpid()}" in result.output
            assert "PID:" not in result.output

            # The CLI-side initiator attribution is emitted on every
            # platform; POSIX additionally gets the daemon's own clean
            # shutdown line via the lifespan finally.
            assert log_path.exists(), (
                "every platform's stop must write the attribution audit line"
            )
            content = log_path.read_text(encoding="utf-8")
            assert "event=shutdown" in content
            assert "reason=cli_terminate" in content
            assert "platform=linux" in content
            assert "initiator_pid" in content
            assert "initiator_cmd" in content
            assert "initiator_cwd" in content
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)
