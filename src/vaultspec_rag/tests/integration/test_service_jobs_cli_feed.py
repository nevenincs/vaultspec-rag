"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import time
from typing import cast

import pytest

from ...cli import app
from ._service_jobs_support import (
    _cli_jobs_payload,
    _jobs_feed_rows,
    _jobs_http_server,
    _plain_lines,
    runner,
)


def _assert_jobs_feed_header(lines: list[str], *, port: int) -> None:
    """Assert the stable operator summary and header order."""
    assert lines[:6] == [
        "Jobs",
        f"Address: http://127.0.0.1:{port}",
        "Displayed: 3 jobs",
        "Total: 3 jobs",
        "Displayed jobs: 1 active, 0 waiting, 1 finished, 1 failed",
        "Showing: active, waiting, failed, then latest finished",
    ]
    order_line = "Order: latest job appears last"
    legend_line = "Legend: * active, ~ waiting, ! failed, - finished"
    scripting_line = (
        "Scripting: use --json (this summary always contains the word 'active')"
    )
    assert order_line in lines
    assert legend_line in lines
    assert scripting_line in lines
    assert lines.index(order_line) < lines.index(legend_line)
    assert lines.index(legend_line) < lines.index(scripting_line)


def _assert_finished_jobs_feed_row(row: dict[str, str]) -> None:
    assert row["marker"] == "-"
    assert row["state"] == "finished"
    assert row["operation"] == "code index refresh for proj-c"
    assert row["detail"] == "added 3, updated 1, removed 0, finished in 22 seconds"


def _assert_failed_jobs_feed_row(row: dict[str, str]) -> None:
    assert row["marker"] == "!"
    assert row["state"] == "failed"
    assert row["operation"] == "vault index refresh for proj-b"


def _assert_active_jobs_feed_row(row: dict[str, str]) -> None:
    assert row["marker"] == "*"
    assert row["state"] == "active"
    assert row["operation"] == "code index update for proj-a"
    assert row["detail"] == (
        "embedding source code sections 2 of 5; running for 10 seconds"
    )


def _assert_jobs_feed_content(output: str) -> None:
    """Assert row ordering and the content of every rendered state."""
    rows = _jobs_feed_rows(output)
    assert [row["id"] for row in rows] == ["donejob1", "failjob1", "runjob12"]
    _assert_finished_jobs_feed_row(rows[0])
    _assert_failed_jobs_feed_row(rows[1])
    _assert_active_jobs_feed_row(rows[2])


def _assert_no_internal_jobs_fragments(output: str) -> None:
    """Assert service-internal and table phrasing stays out of the operator feed."""
    forbidden_fragments = (
        "3/3 shown:",
        "Displayed: 3 of 3",
        "Latest shown last.",
        "Filtered by",
        "Jobs on service port",
        "Recent jobs on service",
        "States:",
        "FAILED",
        "project=",
        " project proj-",
        " id runjob12",
        " done code index refresh",
        "watcher",
        "─",
        "│",
        "┌",
        "┐",
        "└",
        "┘",
    )
    leaked = [text for text in forbidden_fragments if text in output]
    assert not leaked, f"internal or table fragments leaked: {leaked}"


@pytest.mark.unit
def test_jobs_human_output_is_line_oriented_operator_feed() -> None:
    now = time.time()
    with _jobs_http_server([_cli_jobs_payload(now)]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--limit", "5", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    output = result.output
    lines = _plain_lines(output)
    _assert_jobs_feed_header(lines, port=port)
    _assert_jobs_feed_content(output)
    _assert_no_internal_jobs_fragments(output)


@pytest.mark.unit
def test_jobs_sparse_service_payload_uses_reported_absence_language() -> None:
    payload: dict[str, object] = {
        "jobs": [
            {
                "source": "code",
                "trigger": "tool",
                "phase": "running",
                "progress": {"step": "embed", "completed": 1, "total": 2},
            }
        ],
        "total": 1,
        "returned": 1,
        "summary": {"running": 1, "phases": {"running": 1}},
        "filters": {"limit": 1},
    }
    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--limit", "1", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    rows = _jobs_feed_rows(result.output)
    assert len(rows) == 1
    row = rows[0]
    assert row["time"] == "time not reported"
    assert row["id"] == "not reported"
    assert row["operation"] == "code index operation"
    assert row["detail"] == (
        "embedding source code sections 1 of 2; runtime not reported"
    )
    assert "?" not in result.output
    assert "unknown" not in result.output.lower()


@pytest.mark.unit
def test_jobs_humanizes_disk_space_failures() -> None:
    now = time.time()
    payload = _cli_jobs_payload(now)
    jobs = cast("list[dict[str, object]]", payload["jobs"])
    failed_job = jobs[1]
    failed_job["result"] = "[Errno 28] No space left on device"
    filters = cast("dict[str, object]", payload["filters"])
    filters["failed"] = True

    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--failed", "--limit", "5", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    assert "Displayed: 3 matching jobs" in result.output
    assert "Total: 3 jobs" in result.output
    assert "Filter: failed only" in result.output
    assert "Filtered by failed only" not in result.output
    assert "not enough disk space; free disk space and retry" in result.output
    assert "[Errno 28]" not in result.output
    assert "No space left on device" not in result.output


@pytest.mark.unit
def test_jobs_humanizes_subsecond_finish_duration() -> None:
    now = time.time()
    payload: dict[str, object] = {
        "jobs": [
            {
                "id": "fastjob1",
                "source": "vault",
                "trigger": "tool",
                "phase": "done",
                "started_at": now - 1,
                "finished_at": now,
                "runtime_seconds": 0.1,
                "result": "+0/1-0 (50ms)",
                "initiator": {"kind": "tool", "project_root": r"C:\projects\fast"},
            }
        ],
        "total": 1,
        "returned": 1,
        "summary": {"running": 0, "phases": {"done": 1}},
        "filters": {"limit": 5},
    }

    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--limit", "5", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    rows = _jobs_feed_rows(result.output)
    assert len(rows) == 1
    assert rows[0]["detail"] == (
        "added 0, updated 1, removed 0, finished in less than 1 second"
    )
    assert "finished in 0 seconds" not in result.output


@pytest.mark.unit
def test_jobs_failure_detail_stays_on_one_feed_line() -> None:
    now = time.time()
    payload: dict[str, object] = {
        "jobs": [
            {
                "id": "failcuda",
                "source": "code",
                "trigger": "tool",
                "phase": "failed",
                "started_at": now - 2,
                "finished_at": now - 1,
                "runtime_seconds": 1.0,
                "result": (
                    "CUDA error: an illegal memory access was encountered\n"
                    "Search for cudaErrorIllegalAddress in the CUDA docs.\n"
                    "For debugging consider passing CUDA_LAUNCH_BLOCKING=1"
                ),
                "initiator": {"kind": "tool", "project_root": r"C:\projects\proj-cuda"},
            }
        ],
        "total": 1,
        "returned": 1,
        "summary": {"running": 0, "phases": {"failed": 1}},
        "filters": {"limit": 5},
    }

    with _jobs_http_server([payload]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--limit", "5", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    rows = _jobs_feed_rows(result.output)
    assert [row["id"] for row in rows] == ["failcuda"]
    assert rows[0]["detail"] == (
        "error: CUDA error: an illegal memory access was encountered "
        "Search for cudaErrorIllegalAddress in the CUDA docs. "
        "For debugging consider passing CUDA_LAUNCH_BLOCKING=1"
    )
    lines = _plain_lines(result.output)
    assert "Showing: active, waiting, failed, then latest finished" in lines
    assert "Legend: * active, ~ waiting, ! failed, - finished" in lines
    assert lines[-1].endswith(rows[0]["detail"])


@pytest.mark.unit
def test_jobs_header_counts_waiting_jobs(capsys: pytest.CaptureFixture[str]) -> None:
    from ...cli._service_jobs_presentation import render_jobs_result

    now = time.time()
    render_jobs_result(
        {
            "jobs": [
                {
                    "id": "waiting-job",
                    "source": "code",
                    "trigger": "watcher",
                    "phase": "running",
                    "started_at": now - 20,
                    "finished_at": None,
                    "result": None,
                    "progress": {"step": "queued", "completed": 0},
                    "runtime_seconds": 20.0,
                    "initiator": {
                        "kind": "watcher",
                        "project_root": r"C:\projects\proj-waiting",
                    },
                }
            ],
            "total": 1,
            "returned": 1,
            "summary": {"running": 1, "phases": {"running": 1}},
            "filters": {"limit": 5},
        },
        job_id=None,
        port=8766,
    )

    output = capsys.readouterr().out
    lines = _plain_lines(output)
    assert lines[:6] == [
        "Jobs",
        "Address: http://127.0.0.1:8766",
        "Displayed: 1 job",
        "Total: 1 job",
        "Displayed jobs: 0 active, 1 waiting, 0 finished, 0 failed",
        "Showing: active, waiting, failed, then latest finished",
    ]
    assert lines[6] == "Order: latest job appears last"
    rows = _jobs_feed_rows(output)
    assert len(rows) == 1
    row = rows[0]
    assert row["marker"] == "~"
    assert row["state"] == "waiting"
    assert row["operation"] == "code index update for proj-waiting"
    assert row["detail"] == "waiting to write the index for 20 seconds"


@pytest.mark.unit
def test_jobs_filtered_header_separates_matches_from_service_total(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs_presentation import render_jobs_result

    now = time.time()
    render_jobs_result(
        {
            "jobs": [
                {
                    "id": "running-a",
                    "source": "code",
                    "trigger": "watcher",
                    "phase": "running",
                    "started_at": now - 40,
                    "progress": {"step": "embed", "completed": 1, "total": 4},
                    "initiator": {"project_root": r"C:\projects\proj-a"},
                },
                {
                    "id": "running-b",
                    "source": "vault",
                    "trigger": "watcher",
                    "phase": "running",
                    "started_at": now - 20,
                    "progress": {"step": "embed + upsert documents"},
                    "initiator": {"project_root": r"C:\projects\proj-b"},
                },
            ],
            "total": 58,
            "returned": 2,
            "summary": {"running": 2, "phases": {"running": 2, "done": 56}},
            "filters": {"limit": 20, "phase": "running"},
        },
        job_id=None,
        port=8766,
    )

    output = capsys.readouterr().out
    lines = _plain_lines(output)
    expected_header_lines = (
        "Jobs",
        "Address: http://127.0.0.1:8766",
        "Displayed: 2 matching jobs",
        "Total: 58 jobs",
        "Displayed jobs: 2 active, 0 waiting, 0 finished, 0 failed",
        "Order: latest job appears last",
        "Legend: * active, ~ waiting, ! failed, - finished",
        "Scripting: use --json (this summary always contains the word 'active')",
        "Filter: state active or waiting",
    )
    missing_header_lines = [line for line in expected_header_lines if line not in lines]
    assert not missing_header_lines, (
        f"missing filtered jobs header lines: {missing_header_lines}"
    )
    assert [lines.index(line) for line in expected_header_lines] == sorted(
        lines.index(line) for line in expected_header_lines
    )
    assert "Showing:" not in output
    rows = _jobs_feed_rows(output)
    assert len(rows) == 2
    assert {row["id"] for row in rows} == {"running-a", "running-b"}
    assert all(row["marker"] == "*" and row["state"] == "active" for row in rows)
