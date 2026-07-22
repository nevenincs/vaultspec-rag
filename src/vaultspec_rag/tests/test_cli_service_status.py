"""CLI coverage for the service daemon status helpers and summaries."""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest

from ..serviceclient._transport import _try_http_health
from ._cli_helpers import (
    EnvVar,
    _assert_default_status_summary,
    _assert_verbose_status_summary,
    _find_free_port,
    _is_our_service,
    _is_pid_alive,
    _label_values,
    _plain_lines,
    _read_service_status,
    _status_contract_server,
    _write_service_status,
    app,
    runner,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


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
            assert set(data.keys()) == {
                "schema",
                "version",
                "pid",
                "port",
                "started_at",
            }
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
            assert "recorded process 99999999 is no longer running" in out
            assert "pid:" not in out
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

    def test_service_status_stale_pid_verbose_uses_condition_language(
        self, tmp_path: Path
    ):
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=8766)

            result = runner.invoke(app, ["server", "status", "--verbose"])

            assert result.exit_code == 4
            assert "Process: not running" in result.output
            assert (
                "Process check: not verified because the process is not running"
                in result.output
            )
            assert "Network: not accepting connections" in result.output
            assert "Service process:" not in result.output
            assert "not checked" not in result.output
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_health_probe_nonlistening_port(self):
        """Health probe on a port with no listener should return None."""
        assert _try_http_health(1) is None

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
            result = _try_http_health(port)
            assert result is None
        finally:
            server.server_close()
            t.join(timeout=5)

    def test_service_status_default_human_output_is_plain_summary(self, tmp_path: Path):
        """service status renders the W06.P01 plain operator summary by default."""
        import json

        server, thread = _status_contract_server()
        port = server.server_address[1]
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
            _assert_default_status_summary(result.output, port)

            verbose = runner.invoke(app, ["server", "status", "--verbose"])
            assert verbose.exit_code == 0
            _assert_verbose_status_summary(verbose.output, port)
            assert "Service record:" not in verbose.output
            assert "Service process:" not in verbose.output
            assert "Service identity:" not in verbose.output
            assert "Identity check: not checked" not in verbose.output
            assert "Started: 2026-" not in verbose.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_lists_multiple_active_jobs(self, tmp_path: Path):
        import json

        server, thread = _status_contract_server(extra_running_job=True)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            assert "Busy: processing 2 jobs" in result.output
            assert "Queue: nothing waiting; 2 active jobs" in result.output
            assert "Active jobs:" in result.output
            active_rows = [
                line for line in result.output.splitlines() if line.startswith("  * ")
            ]
            assert len(active_rows) == 2
            assert active_rows[0].startswith("  * vault index update for other-project")
            assert "index documents 5 of 9" in active_rows[0]
            assert active_rows[1].startswith(
                "  * code index refresh for feature-server-supervision"
            )
            assert "embedding source code sections 7 of 20" in active_rows[1]
            assert all(row.count("no progress for") <= 1 for row in active_rows)
            assert "Current job:" not in result.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_summary_reports_failed_jobs(self, tmp_path: Path):
        import json

        server, thread = _status_contract_server(failed_jobs=2)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert (
                labels["Processed jobs"] == "2 finished, 1 active, 0 waiting, 2 failed"
            )
            assert "recent jobs" not in result.output
            assert "Jobs:" not in result.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_omits_missing_current_job_project(self, tmp_path: Path):
        import json

        server, thread = _status_contract_server(omit_project=True)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            lines = _plain_lines(result.output)
            assert "Current job:" in lines
            assert "Operation: code index operation" in lines
            assert not any(line.startswith("Project:") for line in lines)
            assert "project not reported" not in result.output
            assert "project unknown" not in result.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_missing_start_times_use_reported_absence_language(
        self, tmp_path: Path
    ):
        import json

        server, thread = _status_contract_server(omit_job_started_at=True)
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            data.pop("started_at", None)
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status", "--verbose"])

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Started"] == "not reported by local record"
            assert labels["Runtime"] == "not reported by service"
            assert "unknown" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def _service_status_current_job_output(
        self,
        tmp_path: Path,
        *,
        last_progress_age_seconds: float,
    ) -> str:
        import json

        server, thread = _status_contract_server(
            last_progress_age_seconds=last_progress_age_seconds,
        )
        port = server.server_address[1]
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=os.getpid(), port=port)
            sf = tmp_path / "service.json"
            data = json.loads(sf.read_text(encoding="utf-8"))
            from datetime import UTC, datetime

            data["last_heartbeat"] = datetime.now(UTC).isoformat(timespec="seconds")
            sf.write_text(json.dumps(data), encoding="utf-8")

            result = runner.invoke(app, ["server", "status"])

            assert result.exit_code == 0, result.output
            return " ".join(result.output.split())
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_current_job_flags_no_recent_progress(
        self,
        tmp_path: Path,
    ):
        fresh_status = self._service_status_current_job_output(
            tmp_path / "fresh",
            last_progress_age_seconds=2.0,
        )
        stalled_status = self._service_status_current_job_output(
            tmp_path / "stalled",
            last_progress_age_seconds=600.0,
        )

        assert "Current job:" in fresh_status
        assert "Current job:" in stalled_status
        assert "Progress: embedding source code sections 7 of 20" in stalled_status
        assert "no progress for" not in fresh_status
        assert "Warning: no progress for 10 minutes" in stalled_status
        assert stalled_status != fresh_status

    def test_service_status_distinguishes_waiting_from_processing(self):
        from ..cli._service_lifecycle import (
            _status_busy_label,
            _status_jobs_label,
            _status_queue_label,
        )

        jobs: dict[str, object] = {"available": True, "running": 1, "queued": 1}

        assert _status_busy_label(jobs) == "1 job waiting to write"
        assert _status_queue_label(jobs) == "1 waiting job; 0 active jobs"
        assert (
            _status_jobs_label({**jobs, "total": 3, "phases": {"done": 2}})
            == "2 finished, 0 active, 1 waiting, 0 failed"
        )

    def test_service_status_port_only_json(self, tmp_path: Path):
        """server status --port can inspect a reachable service without service.json."""
        import http.server
        import json
        import threading

        class _StatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {
                        "status": "ready",
                        "cuda": True,
                        "models_loaded": True,
                        "project_count": 1,
                        "backend_capabilities": {
                            "same_project_search_strategy": "serialized",
                            "cross_project_search_strategy": "parallel",
                            "local_storage_process_model": "exclusive",
                        },
                    }
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _StatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--json"],
            )

            assert result.exit_code == 0
            envelope = json.loads(result.stdout)
            data = envelope["data"]
            assert data["service_json_present"] is False
            assert data["port"] == port
            assert data["state"] == "running"
            operational = data["operational"]
            assert f"--port {port}" in operational["next_action"]
            assert "server info" not in operational["next_action"]
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_sparse_health_uses_reported_absence_language(
        self, tmp_path: Path
    ):
        import http.server
        import threading

        class _SparseHealthHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {"status": "ready"}
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _SparseHealthHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--verbose"],
            )

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Requests"] == "ready for requests"
            assert "Health" not in labels
            assert labels["Compute"] == "not reported by service"
            assert labels["Search models"] == "not reported by service"
            assert labels["Reranking"] == "not reported by service"
            assert labels["Loaded projects"] == "not reported by service"
            assert labels["Uptime"] == "not reported by service"
            assert "unknown" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_missing_health_status_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        class _MissingHealthStatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {"uptime_s": 12}
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _MissingHealthStatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port)],
            )

            assert result.exit_code == 4, result.output
            labels = _label_values(result.output)
            assert labels["Server"] == "unreachable"
            assert labels["Requests"] == "not reported by service"
            assert "Health" not in labels
            assert labels["Uptime"] == "12 seconds"
            assert "unknown" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_jobs_error_is_reported_absence(
        self, tmp_path: Path
    ) -> None:
        import http.server
        import threading

        class _JobsErrorStatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == "/health":
                    payload = {"status": "ready", "uptime_s": 60}
                    status_code = 200
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": False,
                        "error": "jobs_unavailable",
                        "message": "Job summary is not available.",
                    }
                    status_code = 503
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(status_code)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _JobsErrorStatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port)],
            )

            assert result.exit_code == 0, result.output
            labels = _label_values(result.output)
            assert labels["Server"] == "running"
            assert labels["Requests"] == "ready for requests"
            assert "Health" not in labels
            assert labels["Busy"] == "not reported by service"
            assert labels["Queue"] == "not reported by service"
            assert labels["Processed jobs"] == "not reported by service"
            assert labels["Current job"] == "not reported by service"
            assert "unknown" not in result.output.lower()
            assert "unavailable" not in result.output.lower()
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)

    def test_service_status_port_only_verbose_uses_network_language(
        self, tmp_path: Path
    ) -> None:
        """Port-only verbose output should not expose raw yes/no socket labels."""
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            port = _find_free_port()
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--verbose"],
            )

            assert result.exit_code == 3
            assert "Local record: not found" in result.output
            assert "Process: not reported" in result.output
            assert f"Address: http://127.0.0.1:{port}" in result.output
            assert "Network: not accepting connections" in result.output
            labels = _label_values(result.output)
            assert labels["Server"] == "stopped"
            assert "State" not in labels
            assert "Process ID:" not in result.output
            assert "not checked" not in result.output
            assert "not recorded" not in result.output
            assert "PID:" not in result.output
            assert "Port:" not in result.output
            assert "Port listening" not in result.output
            assert "Port listening: yes" not in result.output
            assert "Port listening: no" not in result.output
            assert "Service file:" not in result.output
            assert "Service record:" not in result.output
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

    def test_service_status_port_ignores_stale_service_json(self, tmp_path: Path):
        """server status --port ignores stale service.json."""
        import http.server
        import json
        import threading

        class _StatusHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                payload: dict[str, object]
                if self.path == "/health":
                    payload = {
                        "status": "ready",
                        "cuda": True,
                        "models_loaded": True,
                        "project_count": 1,
                        "backend_capabilities": {
                            "same_project_search_strategy": "serialized",
                            "cross_project_search_strategy": "parallel",
                            "local_storage_process_model": "exclusive",
                        },
                    }
                elif self.path.startswith("/jobs"):
                    payload = {
                        "ok": True,
                        "jobs": [],
                        "total": 0,
                        "returned": 0,
                        "summary": {"running": 0, "phases": {}},
                    }
                else:
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode("utf-8"))

            def log_message(self, format: str, *args: object) -> None:
                _ = format, args

        server = http.server.HTTPServer(("127.0.0.1", 0), _StatusHandler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            _write_service_status(pid=99999999, port=1)
            result = runner.invoke(
                app,
                ["server", "status", "--port", str(port), "--json"],
            )

            assert result.exit_code == 0
            envelope = json.loads(result.stdout)
            data = envelope["data"]
            assert data["service_json_present"] is True
            assert data["pid_alive"] is False
            assert data["port"] == port
            assert data["state"] == "running"
            assert data["operational"]["status_file_port"] == 1

            human = runner.invoke(
                app,
                ["server", "status", "--port", str(port)],
            )

            assert human.exit_code == 0, human.output
            lines = _plain_lines(human.output)
            assert (
                lines[0] == "Local record points to http://127.0.0.1:1; "
                f"checking http://127.0.0.1:{port}."
            )
            assert f"Address: http://127.0.0.1:{port}" in human.output
            assert "probing" not in human.output
            assert "Status file port" not in human.output
        finally:
            server.shutdown()
            server.server_close()
            os.environ.pop(EnvVar.STATUS_DIR, None)
            thread.join(timeout=5)


class TestUnreachableStaysASentinelNotAnEscape:
    """Repointing the health call must not turn unreachability into an exception.

    The health owner returns a sentinel rather than raising precisely because
    these two verbs are broker-facing: each must emit exactly one structured
    outcome on every exit path. If an exception escaped the probe, a supervising
    caller would see a crash instead of an envelope, so this asserts the
    property at the verb rather than at the function.
    """

    def _one_envelope(self, output: str) -> dict[str, object]:
        payloads = [
            json.loads(line)
            for line in output.splitlines()
            if line.strip().startswith("{")
        ]
        assert len(payloads) == 1, f"expected exactly one envelope, got {payloads}"
        return payloads[0]

    def test_stop_against_a_dead_port_emits_one_success_envelope(
        self, tmp_path: Path
    ) -> None:
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            port = _find_free_port()
            result = runner.invoke(
                app, ["server", "stop", "--port", str(port), "--json"]
            )
            envelope = self._one_envelope(result.output)
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

        # Nothing was listening, so the probe returned its sentinel and the verb
        # treated it as an ordinary branch: an idempotent success, exit 0.
        assert result.exit_code == 0
        assert envelope["ok"] is True
        data = envelope["data"]
        assert isinstance(data, dict)
        assert data["status"] == "already_stopped"

    def test_status_against_a_dead_port_emits_one_envelope(
        self, tmp_path: Path
    ) -> None:
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path)
        try:
            port = _find_free_port()
            result = runner.invoke(
                app, ["server", "status", "--port", str(port), "--json"]
            )
            envelope = self._one_envelope(result.output)
        finally:
            os.environ.pop(EnvVar.STATUS_DIR, None)

        # Whatever the verdict, it is a rendered envelope rather than a
        # traceback: the unreachable probe did not escape as an exception.
        assert isinstance(envelope, dict)
        assert "Traceback" not in result.output
