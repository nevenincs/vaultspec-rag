"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import time
import urllib.parse

import pytest

from vaultspec_rag.cli import app

from ._service_jobs_support import (
    _jobs_feed_rows,
    _jobs_http_server,
    _JobsHTTPHandler,
    _plain_lines,
    runner,
)


@pytest.mark.unit
def test_jobs_state_active_only_shows_processing_jobs() -> None:
    now = time.time()
    payload: dict[str, object] = {
        "jobs": [
            {
                "id": "waiting-job",
                "source": "code",
                "trigger": "watcher",
                "phase": "running",
                "started_at": now - 30,
                "progress": {"step": "queued", "completed": 0},
                "runtime_seconds": 30.0,
                "initiator": {"project_root": r"C:\projects\waiting-project"},
            },
            {
                "id": "active-job",
                "source": "vault",
                "trigger": "tool",
                "phase": "running",
                "started_at": now - 10,
                "progress": {"step": "embed", "completed": 2, "total": 4},
                "runtime_seconds": 10.0,
                "initiator": {"project_root": r"C:\projects\active-project"},
            },
        ],
        "total": 7,
        "returned": 2,
        "summary": {"running": 2, "phases": {"running": 2, "done": 5}},
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
                "--limit",
                "5",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert query["phase"] == ["running"]
    lines = _plain_lines(result.output)
    assert "Displayed: 1 matching job" in lines
    assert "Total: 7 jobs" in lines
    assert "Displayed jobs: 1 active, 0 waiting, 0 finished, 0 failed" in lines
    assert "Filter: state active" in lines
    rows = _jobs_feed_rows(result.output)
    assert [row["id"] for row in rows] == ["active-j"]
    assert rows[0]["marker"] == "*"
    assert rows[0]["state"] == "active"
    assert "waiting-job" not in result.output
    assert "active or waiting" not in result.output


@pytest.mark.unit
def test_jobs_state_waiting_only_shows_queued_jobs() -> None:
    now = time.time()
    payload: dict[str, object] = {
        "jobs": [
            {
                "id": "active-job",
                "source": "vault",
                "trigger": "tool",
                "phase": "running",
                "started_at": now - 10,
                "progress": {"step": "embed", "completed": 2, "total": 4},
                "runtime_seconds": 10.0,
                "initiator": {"project_root": r"C:\projects\active-project"},
            },
            {
                "id": "waiting-job",
                "source": "code",
                "trigger": "watcher",
                "phase": "running",
                "started_at": now - 30,
                "progress": {"step": "queued", "completed": 0},
                "runtime_seconds": 30.0,
                "initiator": {"project_root": r"C:\projects\waiting-project"},
            },
        ],
        "total": 7,
        "returned": 2,
        "summary": {"running": 2, "phases": {"running": 2, "done": 5}},
        "filters": {"limit": 5, "phase": "running"},
    }

    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--state",
                "waiting",
                "--limit",
                "5",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert query["phase"] == ["running"]
    lines = _plain_lines(result.output)
    assert "Displayed: 1 matching job" in lines
    assert "Total: 7 jobs" in lines
    assert "Displayed jobs: 0 active, 1 waiting, 0 finished, 0 failed" in lines
    assert "Filter: state waiting" in lines
    rows = _jobs_feed_rows(result.output)
    assert [row["id"] for row in rows] == ["waiting-"]
    assert rows[0]["marker"] == "~"
    assert rows[0]["state"] == "waiting"
    assert "active-job" not in result.output
    assert "active or waiting" not in result.output


@pytest.mark.unit
def test_jobs_waiting_progress_uses_user_language() -> None:
    from ...cli._service_jobs_presentation import human_progress

    waiting = human_progress(
        {"phase": "running", "progress": {"step": "queued", "completed": 0}}
    )
    compound = human_progress(
        {
            "phase": "running",
            "progress": {
                "step": "embed + upsert chunks",
                "completed": 64,
                "total": 196,
            },
        }
    )

    assert waiting == "waiting to write the index"
    assert "writer lock" not in waiting
    assert waiting != "waiting to write the index 0"
    assert compound == "embedding and writing sections 64 of 196"
    assert "upsert" not in compound


@pytest.mark.unit
def test_jobs_missing_context_uses_reported_absence_language(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs_presentation import render_jobs_result

    render_jobs_result(
        {
            "jobs": [
                {
                    "source": "code",
                    "trigger": "tool",
                    "phase": "running",
                    "runtime_seconds": 4.0,
                    "progress": {"step": "embed", "completed": 1, "total": 2},
                }
            ],
            "total": 1,
            "returned": 1,
            "summary": {"running": 1, "phases": {"running": 1}},
            "filters": {"limit": 1},
        },
        job_id=None,
        port=8766,
    )

    output = capsys.readouterr().out
    rows = _jobs_feed_rows(output)
    assert len(rows) == 1
    row = rows[0]
    assert row["time"] == "time not reported"
    assert row["id"] == "not reported"
    assert row["operation"] == "code index operation"
    assert "project unknown" not in output
    assert "unknown" not in output


@pytest.mark.unit
def test_jobs_humanizes_cancelled_automatic_update(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs_presentation import render_jobs_result

    now = time.time()
    render_jobs_result(
        {
            "jobs": [
                {
                    "id": "cancelled-job",
                    "phase": "cancelled",
                    "source": "vault",
                    "trigger": "watcher",
                    "started_at": now - 10,
                    "finished_at": now,
                    "result": "watcher task cancelled",
                    "initiator": {
                        "kind": "watcher",
                        "project_root": r"C:\projects\example",
                    },
                }
            ],
            "total": 1,
            "returned": 1,
            "summary": {"running": 0, "phases": {"cancelled": 1}},
            "filters": {"limit": 1},
        },
        job_id=None,
        port=8766,
    )

    output = capsys.readouterr().out
    rows = _jobs_feed_rows(output)
    assert len(rows) == 1
    row = rows[0]
    assert row["state"] == "cancelled"
    assert row["operation"] == "vault index update for example"
    assert row["detail"] == "automatic update cancelled"
    assert "watcher" not in output
