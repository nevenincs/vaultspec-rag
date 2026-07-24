"""CLI coverage for user-facing job progress warnings."""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
import time
from typing import ClassVar

from typer.testing import CliRunner

from ...cli import app
from .._http_stubs import QuietHandler

runner = CliRunner()


class _JobsHTTPHandler(QuietHandler):
    payloads: ClassVar[list[dict[str, object]]] = []

    def do_GET(self) -> None:
        payload = self.payloads[0]
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


@contextlib.contextmanager
def _jobs_http_server(
    payload: dict[str, object],
):
    _JobsHTTPHandler.payloads = [payload]
    server = http.server.HTTPServer(("127.0.0.1", 0), _JobsHTTPHandler)
    port = int(server.server_address[1])
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_jobs_running_output_flags_jobs_without_recent_progress() -> None:
    now = time.time()
    payload: dict[str, object] = {
        "jobs": [
            {
                "id": "freshjob",
                "source": "code",
                "trigger": "watcher",
                "phase": "running",
                "started_at": now - 40,
                "finished_at": None,
                "result": None,
                "progress": {"step": "embed", "completed": 2, "total": 5},
                "runtime_seconds": 40.0,
                "last_progress_age_seconds": 4.0,
                "initiator": {
                    "kind": "watcher",
                    "command": "watcher_code_index",
                    "project_root": "C:\\projects\\fresh-project",
                },
            },
            {
                "id": "quietjob",
                "source": "vault",
                "trigger": "watcher",
                "phase": "running",
                "started_at": now - 900,
                "finished_at": None,
                "result": None,
                "progress": {
                    "step": "embed + upsert documents",
                    "completed": 16064,
                    "total": 17601,
                },
                "runtime_seconds": 900.0,
                "last_progress_age_seconds": 600.0,
                "initiator": {
                    "kind": "watcher",
                    "command": "watcher_vault_index",
                    "project_root": "C:\\projects\\quiet-project",
                },
            },
        ],
        "total": 2,
        "returned": 2,
        "summary": {"running": 2, "phases": {"running": 2}},
        "filters": {"limit": 20, "phase": "running"},
    }
    with _jobs_http_server(payload) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--state", "active", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    lines = [line.strip() for line in result.output.splitlines() if line.strip()]
    fresh_line = next(line for line in lines if "fresh-project" in line)
    quiet_line = next(line for line in lines if "quiet-project" in line)
    assert "no progress for" not in fresh_line
    assert "no progress for 10 minutes" in quiet_line
    assert "last_progress_age_seconds" not in result.output
    assert "stale" not in result.output.lower()
