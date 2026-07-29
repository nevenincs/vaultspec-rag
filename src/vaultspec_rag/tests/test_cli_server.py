"""CLI coverage for server routing, logs, jobs, and projects verbs."""

from __future__ import annotations

import contextlib
import inspect
import json
import os
import subprocess
import sys
import typing

import pytest

from .._process_probe import pid_alive
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
from ._http_stubs import QuietHandler

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

    def test_server_watch_selects_the_balanced_server_mode(self):
        """The root watch enters the canonical app in balanced server mode."""
        from ..cli._app import server_main

        source = inspect.getsource(server_main)

        assert 'watch_mode="server"' in source

    def test_server_without_watch_still_shows_help(self):
        """The bare group keeps printing help; --watch is the only new path."""
        result = runner.invoke(app, ["server"])
        assert result.exit_code == 0, result.output
        assert "Manage the background search service." in result.output

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
    """Verify the flattened `server` command surface (#169).

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

        class WatcherStateHandler(QuietHandler):
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
        # Typer renders a required positional as ``{name}`` in the usage line.
        assert "{project}" in result.output
        assert " ROOT" not in result.output
        assert "{root}" not in result.output
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
                    "root": r"C:\projects\example",
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
            r"Path: C:\projects\busy",
            "Active requests: 2",
            "Last activity: 1 minute 5 seconds ago",
            "Last request: 14:05:06",
            "- Project: ready",
            r"Path: C:\projects\ready",
            "Active requests: none",
            "Last activity: 4 seconds ago",
        ]
        missing = [text for text in expected_present if text not in lines]
        assert not missing, f"missing operator lines: {missing}"
        ready_index = lines.index("- Project: ready")
        ready_block = lines[ready_index : ready_index + 4]
        assert ready_block == [
            "- Project: ready",
            r"Path: C:\projects\ready",
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
                    r"C:\projects\example",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 1, result.output
        assert requests == [{"root": r"C:\projects\example"}]
        labels = _label_values(result.output)
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert labels["Project"] == "example"
        assert labels["Path"] == r"C:\projects\example"
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
                    r"C:\projects\not-loaded",
                    "--port",
                    str(server.server_port),
                ],
            )
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=1)

        assert result.exit_code == 2, result.output
        assert requests == [{"root": r"C:\projects\not-loaded"}]
        labels = _label_values(result.output)
        assert labels["Address"] == f"http://127.0.0.1:{server.server_port}"
        assert labels["Project"] == "not-loaded"
        assert labels["Path"] == r"C:\projects\not-loaded"
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
                    r"C:\projects\example",
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
        assert requests == [{"root": r"C:\projects\example"}]
        envelope = json.loads(result.output)
        assert envelope["ok"] is False
        assert envelope["command"] == "service.projects.unload"
        assert envelope["error"] == "unexpected_response"
        assert r"C:\projects\example" in envelope["message"]
        assert "vaultspec-rag server status" in envelope["message"]
        assert "Eviction failed" not in envelope["message"]
        assert "reason=" not in envelope["message"]


class TestLifecycleShutdownLog:
    """The CLI-side lifecycle shutdown line, written on every platform.

    A Windows stop is always a force-kill - the daemon is spawned
    console-detached, so it never runs its own atexit or lifespan
    ``finally`` - and the CLI parent emits a mirror line so the audit
    trail stays uniform with POSIX. The attribution it carries (who ran
    the stop) is worth having everywhere, so the line is unconditional.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_append_writes_expected_format(self) -> None:
        """The line lands in the log file the production resolver picks.

        Proven able to fail: dropping ``f"reason={reason}"`` from the parts
        list in ``_append_lifecycle_shutdown_log`` fails the
        ``reason=cli_terminate`` assertion below; restoring it passes.
        """
        from ..cli._service_status import (
            _append_lifecycle_shutdown_log,
            _log_file,
        )

        _append_lifecycle_shutdown_log(
            "cli_terminate",
            pid=123,
            platform="win32",
        )

        content = _log_file().read_text(encoding="utf-8")
        lines = content.splitlines()
        assert len(lines) == 1
        line = lines[0]
        assert "WARNING  cli.lifecycle" in line
        assert "event=shutdown" in line
        assert "reason=cli_terminate" in line
        assert "pid=123" in line
        assert "platform=win32" in line

    @pytest.mark.usefixtures("isolated_status_dir")
    def test_append_oserror_is_suppressed_and_debug_logged(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """OSError on the append must NOT crash the shutdown path.

        The unwritable log is real: a directory occupies the path the
        resolver returns, so the append raises from the same ``open`` call
        an operator's permission or device failure would. Pointing the
        status dir somewhere absent would not do it - the resolver creates
        the directory it returns.

        No-swallow rule: the helper must debug-log the exception so the
        suppression is observable. Proven able to fail: deleting the
        ``logger.debug`` call in the ``except OSError`` branch fails the
        debug-record assertion; restoring it passes.
        """
        from ..cli._service_status import (
            _append_lifecycle_shutdown_log,
            _log_file,
        )

        occupied = _log_file()
        occupied.mkdir(parents=True, exist_ok=True)

        with caplog.at_level("DEBUG", logger="vaultspec_rag.cli"):
            _append_lifecycle_shutdown_log("cli_terminate", pid=42)

        # No exception escapes; the debug line is present.
        debug_records = [
            r
            for r in caplog.records
            if r.name == "vaultspec_rag.cli"
            and "lifecycle log append failed" in r.getMessage()
        ]
        assert debug_records, (
            "OSError on append must be debug-logged so the swallow stays observable"
        )
        # Nothing was written where the append failed - confirms the
        # exception path, not a silently relocated write.
        assert occupied.is_dir()
        assert not any(occupied.iterdir())

    @pytest.mark.usefixtures("isolated_singleton_dirs")
    def test_service_stop_terminates_the_recorded_process_and_logs_it(self) -> None:
        """``server stop`` really stops the recorded process and attributes it.

        The service is a real child process recorded in a real discovery
        file, so the identity confirmation, the termination, the liveness
        poll, and the log append are all production code deciding the
        outcome. The child is a Python interpreter, which is what the
        tokenless identity fallback confirms as ours, and it is spawned into
        its own process group so the Windows ``CTRL_BREAK_EVENT`` reaches it
        and cannot reach the test runner's console group.

        Proven able to fail, both directions: removing the
        ``_append_lifecycle_shutdown_log`` call from ``_terminate_and_confirm``
        fails the "must write the attribution audit line" assertion, and
        returning early from ``_terminate_pid`` leaves the child running and
        fails the "must have stopped the process" assertion. Restoring each
        returns the test to green.

        What this does NOT bind, checked rather than assumed: returning True
        unconditionally from ``_is_our_service`` still passes here, because a
        confirmed identity is this path's precondition rather than its
        subject. The refusal to stop an unconfirmable process is covered
        where a live foreign pid is the recorded one.
        """
        from ..cli._service_status import _log_file

        creationflags = (
            subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        )
        # The stand-in has to satisfy the real identity fallback on BOTH
        # platforms, and they ask different questions: Windows checks the
        # image name is a Python interpreter, POSIX reads the cmdline for the
        # package name. A bare `-c` script answers only the first, so this
        # test passed on Windows and failed on Linux with an unconfirmed
        # identity. Naming the package in the script satisfies the POSIX check
        # the way a real daemon's cmdline does, rather than skipping the test
        # on the platform where the fallback is stricter.
        child = subprocess.Popen(
            [
                sys.executable,
                "-c",
                "# vaultspec_rag service stand-in\nimport time; time.sleep(120)",
            ],
            creationflags=creationflags,
        )
        try:
            _write_service_status(pid=child.pid, port=_find_free_port())

            result = runner.invoke(app, ["server", "stop"])

            assert result.exit_code == 0, result.output
            assert f"Process ID: {child.pid}" in result.output
            assert "PID:" not in result.output
            assert not pid_alive(child.pid), (
                "a stop that reports success must have stopped the process"
            )
        finally:
            with contextlib.suppress(OSError, subprocess.TimeoutExpired):
                child.kill()
                child.wait(timeout=10)

        log_path = _log_file()
        assert log_path.exists(), (
            "a terminating stop must write the attribution audit line"
        )
        content = log_path.read_text(encoding="utf-8")
        assert "event=shutdown" in content
        assert "reason=cli_terminate" in content
        assert f"pid={child.pid}" in content
        assert f"platform={sys.platform}" in content
        assert f"initiator_pid={os.getpid()}" in content
        assert "initiator_cmd=" in content
        assert f"initiator_cwd={os.getcwd()}" in content


class TestPlatformDrainBudget:
    """The drain window a stop funds is decided by platform, not by host.

    A daemon that can act on the termination signal cleans up after itself,
    which is the better outcome, so POSIX funds a real wait. Windows spawns
    the daemon console-detached and a console control event only reaches
    processes sharing the sender's console, so the signal never arrives and
    waiting buys latency before the forced kill and nothing else.

    Both branches are stated here because a host can only ever run one of
    them. Simulating the other by reassigning ``sys.platform`` proved that a
    module read a string someone had just written, and would keep passing if
    the rule moved somewhere the reassignment no longer reached.

    Proven able to fail: returning the POSIX window unconditionally from
    ``graceful_drain_seconds_for`` fails the Windows assertion below;
    returning the Windows window unconditionally fails the POSIX one.
    Restoring the branch returns both to green.
    """

    pytestmark: typing.ClassVar = [pytest.mark.unit]

    def test_windows_does_not_fund_a_drain_it_cannot_use(self) -> None:
        from ..cli._process import _DEFAULT_GRACEFUL_DRAIN_SECONDS
        from ..cli._service_stop import graceful_drain_seconds_for

        assert graceful_drain_seconds_for("win32") == _DEFAULT_GRACEFUL_DRAIN_SECONDS

    def test_posix_funds_the_full_drain(self) -> None:
        from ..cli._service_stop import (
            _STOP_GRACEFUL_DRAIN_SECONDS,
            graceful_drain_seconds_for,
        )

        for platform in ("linux", "darwin"):
            assert graceful_drain_seconds_for(platform) == _STOP_GRACEFUL_DRAIN_SECONDS

    def test_the_two_platforms_fund_different_windows(self) -> None:
        # The rule is only meaningful if the branches differ; a refactor that
        # collapsed them would leave both assertions above passing on one
        # constant.
        from ..cli._service_stop import graceful_drain_seconds_for

        assert graceful_drain_seconds_for("win32") != graceful_drain_seconds_for(
            "linux"
        )
