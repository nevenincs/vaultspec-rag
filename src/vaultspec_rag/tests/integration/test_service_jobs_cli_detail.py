"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import json
import time
import urllib.parse
from typing import cast

import pytest

import vaultspec_rag.mcp._admin_client as admin
from vaultspec_rag.cli import app

from ._service_jobs_support import (
    _ANSI_RE,
    _DEAD_PORT,
    _cli_jobs_payload,
    _jobs_http_server,
    _JobsHTTPHandler,
    _label_values,
    runner,
)


@pytest.mark.unit
def test_job_detail_uses_plain_runtime_and_resource_language(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs_presentation import render_job_detail

    render_job_detail(
        {
            "id": "runjob12",
            "source": "code",
            "trigger": "watcher",
            "phase": "running",
            "runtime_seconds": 12.0,
            "last_progress_age_seconds": 2.0,
            "progress": {"step": "embed", "completed": 2, "total": 5},
            "initiator": {
                "kind": "watcher",
                "command": "watcher_code_index",
                "project_root": r"C:\projects\proj-a",
            },
            "runtime": {
                "pid": 123,
                "user": "operator",
                "executable": r"C:\projects\.venv\Scripts\python.exe",
                "virtual_env": r"C:\projects\.venv",
            },
            "resources": {
                "current": {
                    "rss_mb": 10.0,
                    "cuda_allocated_mb": 20.0,
                    "cuda_reserved_mb": 30.0,
                }
            },
        }
    )

    output = capsys.readouterr().out
    values = _label_values(output)
    assert values["Status"] == "active"
    assert values["Started by"] == "automatic updates"
    assert values["Request"] == "automatic code index update"
    assert values["Job process id"] == "123"
    assert values["User"] == "operator"
    assert values["Python"] == ".venv/Scripts/python.exe"
    assert values["Python environment"] == ".venv"
    assert values["Memory"] == (
        "process 10.0 MiB, GPU used 20.0 MiB, GPU reserved 30.0 MiB"
    )
    assert r"C:\projects\.venv\Scripts\python.exe" not in output
    for forbidden in (
        "Initiator:",
        "Command:",
        "Process:",
        "watcher_code_index",
        "PID:",
        "OS user:",
        "Executable:",
        "Virtual env:",
    ):
        assert forbidden not in output
    assert "rss " not in output
    assert "cuda alloc" not in output
    assert "cuda reserved" not in output
    assert "Memory: memory " not in output
    assert "State:" not in output


@pytest.mark.unit
def test_jobs_job_id_detail_uses_precise_process_label() -> None:
    now = time.time()
    payload = _cli_jobs_payload(now)
    jobs = cast("list[dict[str, object]]", payload["jobs"])
    payload["jobs"] = [jobs[0]]
    payload["total"] = 1
    payload["returned"] = 1
    payload["filters"] = {"limit": 20, "job_id": "runjob12"}

    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--job-id", "runjob12", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert query["job_id"] == ["runjob12"]
    values = _label_values(result.output)
    assert values["Address"] == f"http://127.0.0.1:{port}"
    assert values["Status"] == "active"
    assert values["Project"] == "proj-a"
    assert values["Path"] == r"C:\projects\proj-a"
    assert values["Job process id"] == "123"
    assert values["User"] == "operator"
    assert values["Started by"] == "automatic updates"
    assert values["Request"] == "automatic code index update"
    assert "Project root:" not in result.output
    assert "State:" not in result.output
    assert "Process: 123" not in result.output
    assert "PID:" not in result.output


@pytest.mark.unit
def test_jobs_job_id_detail_humanizes_cleanup_progress() -> None:
    now = time.time()
    payload: dict[str, object] = {
        "jobs": [
            {
                "id": "cleanupjob",
                "source": "code",
                "trigger": "watcher",
                "phase": "error",
                "started_at": now - 12,
                "finished_at": now - 3,
                "result": "timed out",
                "progress": {"step": "delete removed", "completed": 0, "total": 1},
                "runtime_seconds": 9.0,
                "initiator": {
                    "kind": "watcher",
                    "command": "watcher_code_index",
                    "project_root": r"C:\projects\proj-a",
                },
            }
        ],
        "total": 1,
        "returned": 1,
        "summary": {"running": 0, "phases": {"error": 1}},
        "filters": {"limit": 20, "job_id": "cleanupjob"},
    }

    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--job-id", "cleanupjob", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    values = _label_values(result.output)
    assert values["Status"] == "failed"
    assert values["Progress"] == "removing stale source files 0 of 1"
    assert (
        values["Error"]
        == "the vector store did not respond in time; check qdrant health and retry"
    )
    assert "State:" not in result.output
    assert "delete removed" not in result.output


@pytest.mark.unit
def test_job_detail_only_reports_progress_freshness_while_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs_presentation import render_job_detail

    base_job = {
        "id": "job1",
        "source": "code",
        "trigger": "watcher",
        "runtime_seconds": 2.0,
        "last_progress_age_seconds": 600.0,
        "progress": {
            "step": "embed + upsert chunks",
            "completed": 0,
            "total": 180,
        },
        "initiator": {
            "kind": "watcher",
            "command": "watcher_code_index",
            "project_root": r"C:\projects\proj-a",
        },
    }

    render_job_detail({**base_job, "phase": "running"})
    running_output = capsys.readouterr().out

    render_job_detail(
        {
            **base_job,
            "id": "failed1",
            "phase": "error",
            "result": "[Errno 28] No space left on device",
        }
    )
    failed_output = capsys.readouterr().out

    assert "10 minutes" in running_output
    assert "10 minutes" not in failed_output


@pytest.mark.unit
def test_jobs_json_preserves_raw_service_payload() -> None:
    now = time.time()
    payload = _cli_jobs_payload(now)
    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--limit", "5", "--port", str(port), "--json"],
        )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["ok"] is True
    jobs = envelope["data"]["jobs"]
    assert jobs[0]["trigger"] == "watcher"
    assert jobs[2]["result"] == "+3 /1 -0 (22231ms)"


@pytest.mark.unit
def test_jobs_watch_refreshes_managed_terminal_view() -> None:
    now = time.time()
    payload = _cli_jobs_payload(now)
    with _jobs_http_server([payload, payload]) as (_server, port):
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--limit",
                "5",
                "--port",
                str(port),
                "--watch",
                "--interval",
                "0.01",
                "--refresh-count",
                "2",
            ],
        )

    assert result.exit_code == 0, result.output
    # Rich's per-refresh screen clear (\x1b[2J\x1b[H) precedes every "Jobs"
    # header, including the first, whenever the console believes it is
    # writing to a real terminal (e.g. FORCE_COLOR set to any non-empty
    # value, which some CI environments do even when trying to disable
    # color) - strip it before checking header boundaries so the assertion
    # verifies the render shape, not incidental clear-screen bytes.
    clean_output = _ANSI_RE.sub("", result.output)
    assert "Watch: refresh 2 of 2." in clean_output
    assert "press Ctrl+C" not in clean_output
    assert clean_output.count("\nJobs\n") == 1
    assert clean_output.startswith("Jobs\n")
    assert "Jobs on service port" not in clean_output


@pytest.mark.unit
def test_jobs_watch_bounded_empty_view_reports_refresh_count() -> None:
    payload: dict[str, object] = {
        "jobs": [],
        "total": 0,
        "returned": 0,
        "summary": {"running": 0, "phases": {}},
        "filters": {"limit": 5, "phase": "running"},
    }
    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--state",
                "active",
                "--port",
                str(port),
                "--watch",
                "--refresh-count",
                "1",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Watch: refresh 1 of 1." in result.output
    assert "press Ctrl+C" not in result.output
    assert "There are no active jobs." in result.output
    assert "There are no active or waiting jobs." not in result.output


@pytest.mark.unit
def test_jobs_watch_is_human_only() -> None:
    result = runner.invoke(
        app,
        ["server", "jobs", "--port", _DEAD_PORT, "--watch", "--json"],
    )
    assert result.exit_code == 2
    envelope = json.loads(result.output)
    assert envelope["error"] == "invalid_watch"


@pytest.mark.unit
def test_jobs_cli_mcp_parity() -> None:
    assert callable(admin.get_jobs)
    help_result = runner.invoke(app, ["server", "--help"])
    assert help_result.exit_code == 0
    assert "jobs" in help_result.stdout
