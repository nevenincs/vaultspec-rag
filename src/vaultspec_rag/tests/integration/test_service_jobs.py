"""Tests for the Tier-2b jobs surface (#142, plan P04).

Three layers, no mocks/skips/monkeypatch:

- MCP: seed the real in-flight registry via ``_jobs.record_start`` /
  ``record_finish`` and assert the ``get_jobs`` tool returns the snapshot
  shape (and honours ``limit``); the registry is reset in teardown.
- CLI: drive ``server jobs`` through the real Typer app against a
  dead ``--port`` so ``_try_mcp_admin`` genuinely fails to connect, asserting
  the exit-3 + JSON envelope contract.
- Starlette: exercise the real ``GET /jobs`` route through
  ``starlette.testclient.TestClient`` (the real ASGI client, NOT a mock) built
  from ``_routes.ROUTES`` with a known ``_SERVICE_TOKEN`` - 401 without token,
  200 JSON with token.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
import time
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from typer.testing import CliRunner

if TYPE_CHECKING:
    import httpx

import vaultspec_rag.mcp._admin_tools as admin
import vaultspec_rag.mcp._tools as tools
import vaultspec_rag.server as _m

from ...cli import app
from ...server import _jobs
from ...server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59235"


class _JobsHTTPHandler(http.server.BaseHTTPRequestHandler):
    payloads: ClassVar[list[dict[str, object]]] = []
    request_count = 0

    def do_GET(self) -> None:
        payload_index = min(self.request_count, len(self.payloads) - 1)
        payload = self.payloads[payload_index]
        type(self).request_count += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        _ = format, args


@contextlib.contextmanager
def _jobs_http_server(
    payloads: list[dict[str, object]],
) -> Iterator[tuple[http.server.HTTPServer, int]]:
    _JobsHTTPHandler.payloads = payloads
    _JobsHTTPHandler.request_count = 0
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


def _cli_jobs_payload(now: float) -> dict[str, object]:
    return {
        "jobs": [
            {
                "id": "runjob12",
                "source": "code",
                "trigger": "watcher",
                "phase": "running",
                "started_at": now - 10,
                "finished_at": None,
                "result": None,
                "progress": {"step": "embed", "completed": 2, "total": 5},
                "runtime_seconds": 10.0,
                "last_progress_age_seconds": 1.0,
                "initiator": {
                    "kind": "watcher",
                    "command": "watcher_code_index",
                    "project_root": "proj-a",
                },
                "runtime": {"pid": 123, "user": "operator"},
                "resources": {"current": {"rss_mb": 10.0}},
            },
            {
                "id": "failjob1",
                "source": "vault",
                "trigger": "tool",
                "phase": "error",
                "started_at": now - 120,
                "finished_at": now - 100,
                "result": "boom",
                "progress": None,
                "runtime_seconds": 20.0,
                "last_progress_age_seconds": 100.0,
                "initiator": {
                    "kind": "cli",
                    "command": "reindex_vault",
                    "project_root": "proj-b",
                },
                "runtime": {"pid": 124, "user": "operator"},
                "resources": {"finished": {"rss_mb": 11.0}},
            },
            {
                "id": "donejob1",
                "source": "code",
                "trigger": "tool",
                "phase": "done",
                "started_at": now - 320,
                "finished_at": now - 300,
                "result": "+3 /1 -0 (22231ms)",
                "progress": None,
                "runtime_seconds": 20.0,
                "last_progress_age_seconds": 300.0,
                "initiator": {
                    "kind": "cli",
                    "command": "reindex_codebase",
                    "project_root": "proj-c",
                },
                "runtime": {"pid": 125, "user": "operator"},
                "resources": {"finished": {"rss_mb": 12.0}},
            },
        ],
        "total": 3,
        "returned": 3,
        "summary": {
            "running": 1,
            "phases": {"running": 1, "error": 1, "done": 1},
        },
        "filters": {"limit": 5},
    }


@pytest.fixture
def _clean_jobs(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    """Reset the in-flight registry before and after each test."""
    _jobs.reset()
    yield
    _jobs.reset()


# --------------------------------------------------------------------------- #
# MCP: get_jobs returns the registry snapshot shape                           #
# --------------------------------------------------------------------------- #


@pytest.mark.subprocess_gpu
async def test_get_jobs_returns_snapshot_shape(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    # Trigger a real job so the daemon has one in its registry.
    # We use an empty tmp_path so the reindex is near-instant.
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    await tools.reindex_vault(clean=True, project_root=str(tmp_path))

    # Poll until it's done so the snapshot is stable.
    import asyncio

    result: dict[str, Any] = {}
    for _ in range(50):
        result = await admin.get_jobs()
        done = result.get("jobs") and result["jobs"][0]["phase"] in (
            "done",
            "error",
            "failed",
        )
        if done:
            break
        await asyncio.sleep(0.1)

    assert set(result) == {"jobs", "total", "returned", "summary", "filters"}
    jobs: list[Any] = result["jobs"]
    assert isinstance(jobs, list)
    assert len(jobs) >= 1
    entry: dict[str, Any] = jobs[0]
    assert {
        "id",
        "source",
        "trigger",
        "phase",
        "started_at",
        "finished_at",
        "result",
        "progress",
        "initiator",
        "runtime",
        "resources",
        "runtime_seconds",
        "last_progress_age_seconds",
    } <= set(entry)
    assert entry["source"] == "vault"
    assert entry["trigger"] == "tool"
    assert entry["phase"] in ("done", "error", "failed")
    assert entry["initiator"]["project_root"] == str(tmp_path)
    assert entry["initiator"]["kind"] == "mcp"
    assert isinstance(entry["runtime"]["pid"], int)
    assert isinstance(entry["runtime"]["user"], str)
    assert isinstance(entry["resources"]["started"]["rss_mb"], float)


@pytest.mark.subprocess_gpu
async def test_get_jobs_is_newest_first(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    # Trigger two jobs
    job1 = await tools.reindex_vault(clean=True, project_root=str(tmp_path))
    job2 = await tools.reindex_codebase(clean=True, project_root=str(tmp_path))

    jobs = (await admin.get_jobs())["jobs"]
    # The list is newest-first, so job2 should appear before job1
    ids = [entry["id"] for entry in jobs]
    assert ids.index(job2["job_id"]) < ids.index(job1["job_id"])


@pytest.mark.subprocess_gpu
async def test_get_jobs_honours_limit(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    # Trigger multiple jobs
    for _ in range(3):
        await tools.reindex_vault(clean=True, project_root=str(tmp_path))

    jobs = (await admin.get_jobs(limit=2))["jobs"]
    assert len(jobs) == 2


@pytest.mark.subprocess_gpu
async def test_get_jobs_filters_by_source(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    await tools.reindex_vault(clean=True, project_root=str(tmp_path))
    await tools.reindex_codebase(clean=True, project_root=str(tmp_path))

    jobs = (await admin.get_jobs(source="code"))["jobs"]

    assert jobs
    assert all(entry["source"] == "code" for entry in jobs)


@pytest.mark.subprocess_gpu
async def test_get_jobs_non_positive_limit_is_empty(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    await tools.reindex_vault(clean=True, project_root=str(tmp_path))
    assert (await admin.get_jobs(limit=0))["jobs"] == []


# --------------------------------------------------------------------------- #
# CLI: service-not-running -> exit 3 + JSON envelope                          #
# --------------------------------------------------------------------------- #


def test_jobs_not_running_json() -> None:
    result = runner.invoke(
        app,
        ["server", "jobs", "--port", _DEAD_PORT, "--json"],
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "service.jobs"
    assert payload["error"] == "service_not_running"


def test_jobs_not_running_prose() -> None:
    result = runner.invoke(app, ["server", "jobs", "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert "not running" in result.stdout.lower()


def test_jobs_subcommand_registered() -> None:
    result = runner.invoke(app, ["server", "jobs", "--help"])
    assert result.exit_code == 0
    expected_flags = (
        "--state",
        "--running",
        "--query",
        "--failed",
        "--job-id",
        "--since",
        "--watch",
        "--interval",
    )
    missing = [flag for flag in expected_flags if flag not in result.stdout]
    assert not missing, f"missing flags in help: {missing}"
    assert "--phase" not in result.stdout


def test_jobs_help_uses_operator_language() -> None:
    result = runner.invoke(app, ["server", "jobs", "--help"])
    assert result.exit_code == 0
    normalized = " ".join(result.stdout.split())
    expected_phrases = (
        "Filter by job state",
        "job id, outcome, or progress",
        "automatic updates",
        "manual requests",
        "index update activity",
        "Show only failed jobs",
        "Show only active or waiting jobs",
        "running, finished, or failed",
    )
    missing = [phrase for phrase in expected_phrases if phrase not in normalized]
    assert not missing, f"missing operator phrasing: {missing}"
    forbidden_phrases = (
        "job id, result, or progress",
        "'watcher'",
        "index/reindex",
        "failed/error",
        "running, done, or failed",
    )
    leaked = [phrase for phrase in forbidden_phrases if phrase in normalized]
    assert not leaked, f"internal phrasing leaked into help: {leaked}"


def test_jobs_filter_summary_uses_operator_language() -> None:
    from ...cli._service_jobs import _filters_label

    rendered = _filters_label(
        {
            "filters": {
                "phase": "running",
                "trigger": "watcher",
                "source": "code",
                "failed": True,
            }
        }
    )

    assert rendered == (
        " Filtered by state active or waiting; index code; "
        "started by automatic updates; failed only."
    )
    assert "phase=" not in rendered
    assert "state=" not in rendered
    assert "trigger=" not in rendered
    assert "started by=" not in rendered
    assert "watcher" not in rendered


def test_jobs_filter_summary_humanizes_finished_state() -> None:
    from ...cli._service_jobs import _filters_label

    rendered = _filters_label({"filters": {"phase": "done", "limit": 5}})

    assert rendered == " Filtered by state finished."
    assert "state=done" not in rendered
    assert "state=" not in rendered


def test_jobs_trigger_filter_accepts_user_language() -> None:
    from ...cli._service_jobs import _jobs_args

    args = _jobs_args(
        limit=5,
        phase=None,
        source=None,
        trigger="automatic",
        query=None,
        failed=False,
        job_id=None,
        since=None,
    )

    assert args["trigger"] == "watcher"


def test_jobs_phase_filter_accepts_user_language() -> None:
    from ...cli._service_jobs import _jobs_args

    args = _jobs_args(
        limit=5,
        phase="finished",
        source=None,
        trigger=None,
        query=None,
        failed=False,
        job_id=None,
        since=None,
    )

    assert args["phase"] == "done"


def test_jobs_state_option_replaces_phase_in_help_but_phase_still_parses() -> None:
    with _jobs_http_server(
        [{"jobs": [], "filters": {"phase": "done"}, "total": 0}]
    ) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            ["server", "jobs", "--port", str(port), "--phase", "finished"],
        )

    assert result.exit_code == 0, result.stdout
    assert "No matching jobs." in result.stdout


def test_jobs_state_and_phase_conflict_is_actionable() -> None:
    result = runner.invoke(
        app,
        [
            "server",
            "jobs",
            "--port",
            _DEAD_PORT,
            "--state",
            "running",
            "--phase",
            "finished",
        ],
    )

    assert result.exit_code == 2
    assert "--state and --phase received different values" in result.stdout


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"jobs": [], "filters": {"limit": 5, "phase": "running"}}, "No running jobs."),
        ({"jobs": [], "filters": {"limit": 5, "failed": True}}, "No failed jobs."),
        ({"jobs": [], "filters": {"limit": 5, "source": "code"}}, "No matching jobs."),
        ({"jobs": [], "filters": {"limit": 5}}, "No recent jobs."),
    ],
)
def test_empty_jobs_output_matches_active_filter(
    result: dict[str, object],
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs import _render_jobs_result

    _render_jobs_result(result, job_id=None, port=8766)

    assert capsys.readouterr().out.strip() == expected


def test_jobs_human_output_is_line_oriented_operator_feed() -> None:
    now = time.time()
    with _jobs_http_server([_cli_jobs_payload(now)]) as (_server, port):
        result = runner.invoke(
            app,
            ["server", "jobs", "--limit", "5", "--port", str(port)],
        )

    assert result.exit_code == 0, result.output
    output = result.output
    expected_lines = (
        f"Jobs on service port {port}",
        "Shown: 3 of 3",
        "States: 1 active, 0 waiting, 1 finished, 1 failed",
        "Order: latest shown last",
        "for proj-a (job runjob12)",
        "for proj-b (job failjob1)",
        "for proj-c (job donejob1)",
        "* ",
        "! ",
        "FAILED",
        "finished code index refresh",
        "code index update",
        "added 3, updated 1, removed 0, finished in 22s",
        "embedding chunks 2 of 5; running for 10s",
    )
    missing = [text for text in expected_lines if text not in output]
    assert not missing, f"missing feed content: {missing}"
    forbidden_fragments = (
        "3/3 shown:",
        "Latest shown last.",
        "Filtered by",
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
    assert output.index("donejob1") < output.index("failjob1")
    assert output.index("failjob1") < output.index("runjob12")


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
    assert "Filter: failed only" in result.output
    assert "Filtered by failed only" not in result.output
    assert "not enough disk space; free disk space and retry" in result.output
    assert "[Errno 28]" not in result.output
    assert "No space left on device" not in result.output


def test_jobs_header_counts_waiting_jobs(capsys: pytest.CaptureFixture[str]) -> None:
    from ...cli._service_jobs import _render_jobs_result

    now = time.time()
    _render_jobs_result(
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
                        "project_root": r"proj-waiting",
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
    assert "Shown: 1 of 1" in output
    assert "States: 0 active, 1 waiting, 0 finished, 0 failed" in output
    assert "1 running" not in output
    assert "~ " in output
    assert "* " not in output
    assert "waiting code index update" in output
    assert "waiting to write the index for 20s" in output
    assert "running code index update" not in output
    assert "running for 20s" not in output


def test_jobs_waiting_progress_uses_user_language() -> None:
    from ...cli._service_jobs import _human_progress

    waiting = _human_progress(
        {"phase": "running", "progress": {"step": "queued", "completed": 0}}
    )
    compound = _human_progress(
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
    assert compound == "embedding and writing chunks 64 of 196"
    assert "upsert" not in compound


def test_jobs_humanizes_cancelled_automatic_update(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs import _render_jobs_result

    now = time.time()
    _render_jobs_result(
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
                        "project_root": r"example",
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
    assert "automatic update cancelled" in output
    assert "watcher" not in output


def test_job_detail_uses_plain_runtime_and_resource_language(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs import _render_job_detail

    _render_job_detail(
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
                "project_root": r"proj-a",
            },
            "runtime": {
                "pid": 123,
                "user": "operator",
                "executable": r".venv\Scripts\python.exe",
                "virtual_env": r".venv",
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
    assert "Started by: automatic updates" in output
    assert "Request: automatic code index update" in output
    assert "Process: 123" in output
    assert "User: operator" in output
    assert "Python: .venv/Scripts/python.exe" in output
    assert "Python environment: .venv" in output
    assert r".venv\Scripts\python.exe" not in output
    assert "Memory: memory 10.0 MB, GPU used 20.0 MB, GPU reserved 30.0 MB" in output
    for forbidden in (
        "Initiator:",
        "Command:",
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


def test_job_detail_only_reports_progress_freshness_while_running(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs import _render_job_detail

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
            "project_root": r"proj-a",
        },
    }

    _render_job_detail({**base_job, "phase": "running"})
    running_output = capsys.readouterr().out

    _render_job_detail(
        {
            **base_job,
            "id": "failed1",
            "phase": "error",
            "result": "[Errno 28] No space left on device",
        }
    )
    failed_output = capsys.readouterr().out

    assert "10m" in running_output
    assert "10m" not in failed_output


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
    assert "Watching; press Ctrl+C to stop." in result.output
    assert result.output.count("Jobs on service port") == 2


def test_jobs_watch_is_human_only() -> None:
    result = runner.invoke(
        app,
        ["server", "jobs", "--port", _DEAD_PORT, "--watch", "--json"],
    )
    assert result.exit_code == 2
    envelope = json.loads(result.output)
    assert envelope["error"] == "invalid_watch"


def test_jobs_cli_mcp_parity() -> None:
    assert callable(admin.get_jobs)
    help_result = runner.invoke(app, ["server", "--help"])
    assert help_result.exit_code == 0
    assert "jobs" in help_result.stdout


# --------------------------------------------------------------------------- #
# Starlette: real ASGI TestClient against /jobs gating                        #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _routes_app(  # pyright: ignore[reportUnusedFunction]
    _clean_jobs: None,
) -> Iterator[tuple[TestClient, str]]:
    """Build a real Starlette app from the read-only ROUTES.

    Sets a known ``_SERVICE_TOKEN`` on the package namespace (the route's
    ``require_token`` reads it through the alias) and seeds one finished
    record. Restores the token on teardown so the suite stays isolated.
    """
    job_id = _jobs.record_start("vault", "tool")
    _jobs.record_finish(job_id, result="+1 /0 -0 (5ms)")

    prev_token = _m._SERVICE_TOKEN
    _m._SERVICE_TOKEN = "test-token-jobs"

    app_under_test = Starlette(routes=ROUTES)
    client = TestClient(app_under_test)
    try:
        yield client, "test-token-jobs"
    finally:
        _m._SERVICE_TOKEN = prev_token


def test_jobs_route_401_without_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = cast("httpx.Response", client.get("/jobs"))  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    assert response.status_code == 401
    payload: dict[str, Any] = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


def test_jobs_route_401_with_wrong_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", headers={"Authorization": "Bearer wrong"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 401


def test_jobs_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", headers={"Authorization": f"Bearer {token}"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload: dict[str, Any] = response.json()
    assert set(payload) == {"jobs", "total", "returned", "summary", "filters"}
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["source"] == "vault"
    assert payload["jobs"][0]["phase"] == "done"
    assert payload["summary"]["running"] == 0
    assert payload["summary"]["initiators"]["tool"] == 1
    assert payload["summary"]["users"]


def test_jobs_route_200_with_query_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast("httpx.Response", client.get("/jobs", params={"token": token}))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1


def test_jobs_route_respects_limit_param(
    _routes_app: tuple[TestClient, str],
) -> None:
    # Seed a second record so a limit=1 actually trims.
    _jobs.record_start("code", "watcher")
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "limit": "1"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1


def test_jobs_route_prioritises_running_before_limit(
    _routes_app: tuple[TestClient, str],
) -> None:
    running_id = _jobs.record_start("code", "watcher")
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "limit": "1"}),
    )
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["jobs"][0]["id"] == running_id
    assert payload["jobs"][0]["phase"] == "running"
    assert "current" in payload["jobs"][0]["resources"]


def test_jobs_route_prioritises_failed_before_completed_limit(
    _routes_app: tuple[TestClient, str],
) -> None:
    _jobs.record_finish(_jobs.record_start("code", "tool"), result="newer done")
    failed_id = _jobs.record_start("code", "tool")
    _jobs.record_finish(failed_id, error="boom")
    client, token = _routes_app

    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "limit": "1"}),
    )

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["jobs"][0]["id"] == failed_id
    assert payload["jobs"][0]["phase"] == "error"


def test_jobs_route_filters_phase_source_trigger_and_query(
    _routes_app: tuple[TestClient, str],
) -> None:
    _jobs.record_start("code", "watcher")
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get(
            "/jobs",
            params={
                "token": token,
                "phase": "running",
                "source": "code",
                "trigger": "watcher",
                "query": "code",
            },
        ),
    )
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["returned"] == 1
    assert payload["jobs"][0]["source"] == "code"
    assert payload["jobs"][0]["trigger"] == "watcher"
    assert payload["jobs"][0]["phase"] == "running"


def test_jobs_route_accepts_codebase_source_alias(
    _routes_app: tuple[TestClient, str],
) -> None:
    running_id = _jobs.record_start("code", "watcher")
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "source": "codebase"}),
    )
    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    ids = [job["id"] for job in payload["jobs"]]
    assert running_id in ids
    assert payload["filters"]["source"] == "code"


def test_jobs_route_filters_failed_job_id_and_since(
    _routes_app: tuple[TestClient, str],
) -> None:
    failed_id = _jobs.record_start("code", "tool")
    _jobs.record_finish(failed_id, error="boom")
    _jobs.record_finish(_jobs.record_start("vault", "watcher"), result="old")
    client, token = _routes_app

    response = cast(
        "httpx.Response",
        client.get(
            "/jobs",
            params={
                "token": token,
                "failed": "true",
                "job_id": failed_id[:8],
                "since": "60",
            },
        ),
    )

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["returned"] == 1
    job = payload["jobs"][0]
    assert job["id"] == failed_id
    assert job["phase"] == "error"
    assert isinstance(job["runtime_seconds"], float)
    assert payload["filters"]["failed"] is True
    assert payload["filters"]["job_id"] == failed_id[:8]
    assert payload["filters"]["since"] == 60.0


def test_jobs_route_query_matches_runtime_and_initiator(
    _routes_app: tuple[TestClient, str],
) -> None:
    running_id = _jobs.record_start(
        "code",
        "tool",
        command="reindex_codebase",
        initiator_kind="cli",
    )
    client, token = _routes_app

    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "query": "cli"}),
    )

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    ids = [job["id"] for job in payload["jobs"]]
    assert running_id in ids


def test_jobs_route_since_uses_progress_update_time(
    _routes_app: tuple[TestClient, str],
) -> None:
    running_id = _jobs.record_start("code", "tool")
    time.sleep(0.2)
    _jobs.record_progress(running_id, "embed", completed=1, total=10)
    client, token = _routes_app

    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "since": "0.1"}),
    )

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    ids = [job["id"] for job in payload["jobs"]]
    assert running_id in ids


def test_jobs_route_job_id_prefix_can_return_multiple_matches(
    _routes_app: tuple[TestClient, str],
) -> None:
    ids_by_prefix: dict[str, list[str]] = {}
    for _ in range(17):
        job_id = _jobs.record_start("vault", "tool")
        ids_by_prefix.setdefault(job_id[:1], []).append(job_id)
    prefix = next(prefix for prefix, ids in ids_by_prefix.items() if len(ids) > 1)
    client, token = _routes_app

    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "job_id": prefix}),
    )

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["returned"] >= 2
    assert all(str(job["id"]).startswith(prefix) for job in payload["jobs"])
