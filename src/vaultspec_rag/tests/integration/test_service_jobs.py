"""Tests for the managed jobs surface.

Three layers, no mocks/skips/monkeypatch:

- MCP: seed the real in-flight registry via ``_jobs.record_start`` /
  ``record_finish`` and assert the ``get_jobs`` tool returns the snapshot
  shape (and honours ``limit``); the registry is reset in teardown.
- CLI: drive ``server jobs`` through the real Typer app against a
  dead ``--port`` so ``_try_http_admin`` genuinely fails to connect, asserting
  the exit-3 + JSON envelope contract.
- Starlette: exercise the real ``GET /jobs`` route through
  ``starlette.testclient.TestClient`` (the real ASGI client, NOT a mock) built
  from ``_routes.ROUTES`` with a known ``_SERVICE_TOKEN`` - 401 without token,
  200 JSON with token.
"""

from __future__ import annotations

import asyncio
import contextlib
import http.server
import json
import os
import re
import threading
import time
import urllib.parse
from typing import TYPE_CHECKING, Any, ClassVar, cast

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient
from typer.testing import CliRunner

if TYPE_CHECKING:
    import httpx

import vaultspec_rag.mcp._admin_client as admin
import vaultspec_rag.mcp._tools as tools
import vaultspec_rag.server as _m

from ... import jobs as _managed_jobs
from ..._job_errors import JobError, JobErrorKind, remediation
from ...cli import app
from ...config import EnvVar, reset_config
from ...job_control import RunControlToken
from ...job_models import (
    DesiredJobState,
    IndexResilienceSnapshot,
    JobInitiator,
    JobMode,
    JobOperation,
    JobSource,
    JobSpec,
    JobState,
)
from ...server import _jobs
from ...server._lifespan import health_handler
from ...server._routes import ROUTES
from .._http_stubs import QuietHandler
from .._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Coroutine, Generator, Iterator
    from pathlib import Path

runner = CliRunner()

# A port with nothing listening: _try_http_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59235"
_JOB_COMPLETION_TIMEOUT_SECONDS = 120.0
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
_JOB_ROW_RE = re.compile(
    r"^(?P<marker>[*!~ -]) (?P<time>\d\d:\d\d:\d\d|time not reported) "
    r"(?P<state>\S+) (?P<operation>.+?) \(job (?P<id>[^)]+)\) - "
    r"(?P<detail>.*)$"
)


def _plain_lines(output: str) -> list[str]:
    clean = _ANSI_RE.sub("", output)
    return [line.strip() for line in clean.splitlines() if line.strip()]


def _jobs_feed_rows(output: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw_line in _ANSI_RE.sub("", output).splitlines():
        match = _JOB_ROW_RE.fullmatch(raw_line)
        if match is not None:
            rows.append(match.groupdict())
    return rows


def _label_values(output: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in _plain_lines(output):
        if ": " in line:
            label, value = line.split(": ", 1)
            values[label] = value
    return values


class _JobsHTTPHandler(QuietHandler):
    payloads: ClassVar[list[dict[str, object]]] = []
    paths: ClassVar[list[str]] = []
    request_count = 0

    def do_GET(self) -> None:
        type(self).paths.append(self.path)
        payload_index = min(self.request_count, len(self.payloads) - 1)
        payload = self.payloads[payload_index]
        type(self).request_count += 1
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))


@contextlib.contextmanager
def _jobs_http_server(
    payloads: list[dict[str, object]],
) -> Generator[tuple[http.server.HTTPServer, int]]:
    _JobsHTTPHandler.payloads = payloads
    _JobsHTTPHandler.paths = []
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


@contextlib.contextmanager
def _canonical_resilience_server(
    tmp_path: Path,
) -> Generator[tuple[int, str]]:
    status_dir = tmp_path / "resilience-status"
    status_dir.mkdir()
    port = free_loopback_port()
    token = "canonical-resilience-token"
    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_watch_enabled = os.environ.get(EnvVar.WATCH_ENABLED)
    prior_token = _m._SERVICE_TOKEN
    server: uvicorn.Server | None = None
    thread: threading.Thread | None = None
    stopped = True
    try:
        os.environ[EnvVar.STATUS_DIR] = str(status_dir)
        os.environ[EnvVar.WATCH_ENABLED] = "false"
        reset_config()
        _managed_jobs.reset()
        _jobs.reset()
        _m._SERVICE_TOKEN = token
        (status_dir / "service.json").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "port": port,
                    "service_token": token,
                }
            ),
            encoding="utf-8",
        )
        server = uvicorn.Server(
            uvicorn.Config(
                Starlette(routes=[Route("/health", health_handler), *ROUTES]),
                host="127.0.0.1",
                port=port,
                log_config=None,
                access_log=False,
                lifespan="off",
            )
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        yield port, token
    finally:
        if server is not None:
            server.should_exit = True
        if thread is not None:
            thread.join(timeout=5.0)
            stopped = not thread.is_alive()
        _managed_jobs.reset()
        _jobs.reset()
        _m._SERVICE_TOKEN = prior_token
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        if prior_watch_enabled is None:
            os.environ.pop(EnvVar.WATCH_ENABLED, None)
        else:
            os.environ[EnvVar.WATCH_ENABLED] = prior_watch_enabled
        reset_config()
        assert stopped


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
                    "project_root": "C:\\projects\\proj-a",
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
                    "project_root": "C:\\projects\\proj-b",
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
                    "project_root": "C:\\projects\\proj-c",
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


async def _wait_for_terminal_jobs(
    job_id: str,
    *,
    timeout: float = _JOB_COMPLETION_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Wait for one real service job to reach a terminal phase."""
    import asyncio

    result: dict[str, Any] = {}
    last_job: dict[str, Any] | None = None
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        result = await admin.get_jobs(job_id=job_id, timeout=remaining)
        jobs = result.get("jobs", [])
        last_job = next(
            (job for job in jobs if job.get("id") == job_id),
            None,
        )
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if last_job is not None and last_job.get("phase") in (
            "done",
            "error",
            "failed",
        ):
            return result
        await asyncio.sleep(min(0.1, remaining))
    msg = (
        f"job {job_id} did not reach a terminal phase within {timeout:g}s; "
        f"last_job={last_job!r}; last_response={result!r}"
    )
    raise AssertionError(msg)


def _assert_mcp_job_snapshot(
    result: dict[str, Any],
    *,
    job_id: str,
    project_root: Path,
) -> None:
    """Assert the complete real MCP job envelope and caller identity."""
    assert set(result) == {"jobs", "total", "returned", "summary", "filters"}
    jobs: list[Any] = result["jobs"]
    assert isinstance(jobs, list)
    assert jobs
    entry = next(job for job in jobs if job["id"] == job_id)
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
    assert entry["initiator"]["project_root"] == str(project_root)
    assert entry["initiator"]["kind"] == "mcp"
    assert isinstance(entry["runtime"]["pid"], int)
    assert isinstance(entry["runtime"]["user"], str)
    assert isinstance(entry["resources"]["started"]["rss_mb"], float)


async def _assert_cli_job_attribution(
    *,
    port: int,
    project_root: Path,
    mcp_job_id: str,
) -> None:
    """Submit through the real CLI and assert its distinct caller identity."""
    cli_result = runner.invoke(
        app,
        [
            "--target",
            str(project_root),
            "index",
            "--type",
            "vault",
            "--port",
            str(port),
        ],
    )
    assert cli_result.exit_code == 0, cli_result.output
    cli_jobs = (await admin.get_jobs())["jobs"]
    cli_entry = next(job for job in cli_jobs if job["id"] != mcp_job_id)
    assert cli_entry["initiator"]["kind"] == "cli"
    assert cli_entry["initiator"]["project_root"] == str(project_root)


# --------------------------------------------------------------------------- #
# MCP: get_jobs returns the registry snapshot shape                           #
# --------------------------------------------------------------------------- #


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_returns_snapshot_shape(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    # Trigger a real job so the daemon has one in its registry.
    # We use an empty tmp_path so the reindex is near-instant.
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vaultspec").mkdir(parents=True, exist_ok=True)
    mcp_job = await tools.reindex_vault(project_root=str(tmp_path))

    result = await _wait_for_terminal_jobs(cast("str", mcp_job["job_id"]))
    _assert_mcp_job_snapshot(
        result,
        job_id=mcp_job["job_id"],
        project_root=tmp_path,
    )
    await _assert_cli_job_attribution(
        port=live_service[0],
        project_root=tmp_path,
        mcp_job_id=mcp_job["job_id"],
    )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_terminal_job_wait_honours_subsecond_deadline(
    live_service: tuple[int, Path],  # noqa: ARG001
) -> None:
    """Real filtered admin polling cannot overrun its caller's short budget."""
    started = time.monotonic()
    with pytest.raises(
        AssertionError,
        match=r"did not reach a terminal phase within 0\.05s",
    ) as caught:
        await _wait_for_terminal_jobs("nonexistent-job", timeout=0.05)
    assert time.monotonic() - started < 1.0
    assert "last_job=None" in str(caught.value)
    assert "last_response=" in str(caught.value)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_is_newest_first(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    (first_root / ".vault").mkdir(parents=True, exist_ok=True)
    (second_root / ".vault").mkdir(parents=True, exist_ok=True)
    job1 = await tools.reindex_vault(project_root=str(first_root))
    job2 = await tools.reindex_vault(project_root=str(second_root))
    await _wait_for_terminal_jobs(cast("str", job1["job_id"]))
    await _wait_for_terminal_jobs(cast("str", job2["job_id"]))

    jobs = (await admin.get_jobs())["jobs"]
    # The list is newest-first, so job2 should appear before job1
    ids = [entry["id"] for entry in jobs]
    assert ids.index(job2["job_id"]) < ids.index(job1["job_id"])


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_honours_limit(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    # Distinct roots exercise the view limit without collapsing equivalent
    # active work through the canonical deduplication contract.
    for number in range(3):
        project_root = tmp_path / f"project-{number}"
        (project_root / ".vault").mkdir(parents=True, exist_ok=True)
        await tools.reindex_vault(project_root=str(project_root))

    jobs = (await admin.get_jobs(limit=2))["jobs"]
    assert len(jobs) == 2


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_filters_by_source(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    await tools.reindex_vault(project_root=str(tmp_path))
    await tools.reindex_codebase(project_root=str(tmp_path))

    jobs = (await admin.get_jobs(source="code"))["jobs"]

    assert jobs
    assert all(entry["source"] == "code" for entry in jobs)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_non_positive_limit_is_empty(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    await tools.reindex_vault(project_root=str(tmp_path))
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
    assert f"Address: http://127.0.0.1:{_DEAD_PORT}" in result.stdout
    assert "not running" in result.stdout.lower()


def test_jobs_subcommand_registered() -> None:
    result = runner.invoke(app, ["server", "jobs", "--help"])
    assert result.exit_code == 0
    expected_flags = (
        "--state",
        "--index",
        "--query",
        "--failed",
        "--job-id",
        "--started-by",
        "--since",
        "--watch",
        "--interval",
        "--refresh-count",
    )
    missing = [flag for flag in expected_flags if flag not in result.stdout]
    assert not missing, f"missing flags in help: {missing}"
    assert "--phase" not in result.stdout
    assert "--source" not in result.stdout
    assert "--trigger" not in result.stdout
    assert "--running" not in result.stdout


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
        "Continuously refresh the human jobs view",
        "Stop --watch after this many refreshes",
        "active, waiting, finished, failed, or cancelled",
    )
    missing = [phrase for phrase in expected_phrases if phrase not in normalized]
    assert not missing, f"missing operator phrasing: {missing}"
    forbidden_phrases = (
        "job id, result, or progress",
        "--source",
        "--trigger",
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


def test_jobs_index_filter_is_operator_facing_cli_alias() -> None:
    with _jobs_http_server(
        [
            {
                "jobs": [],
                "filters": {"limit": 20, "source": "code"},
                "total": 0,
                "returned": 0,
            }
        ]
    ) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--index",
                "code",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert request.path == "/jobs"
    assert query["source"] == ["code"]
    assert "No jobs matched these filters." in result.output
    assert "--source" not in result.output


def test_jobs_started_by_filter_is_operator_facing_cli_alias() -> None:
    with _jobs_http_server(
        [
            {
                "jobs": [],
                "filters": {"limit": 20, "trigger": "watcher"},
                "total": 0,
                "returned": 0,
            }
        ]
    ) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--started-by",
                "automatic",
                "--port",
                str(port),
            ],
        )

    assert result.exit_code == 0, result.output
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert request.path == "/jobs"
    assert query["trigger"] == ["watcher"]
    assert "No jobs matched these filters." in result.output
    assert "--trigger" not in result.output


@pytest.mark.parametrize(
    ("state", "phase", "filter_line", "empty_message"),
    [
        (
            "active",
            "running",
            "Filter: state active",
            "There are no active jobs.",
        ),
        (
            "waiting",
            "running",
            "Filter: state waiting",
            "There are no waiting jobs.",
        ),
        (
            "finished",
            "done",
            "Filter: state finished",
            "No jobs matched these filters.",
        ),
    ],
)
def test_jobs_state_filter_sends_service_phase(
    state: str,
    phase: str,
    filter_line: str,
    empty_message: str,
) -> None:
    with _jobs_http_server([{"jobs": [], "filters": {"phase": phase}, "total": 0}]) as (
        _server,
        port,
    ):
        result = runner.invoke(
            app,
            ["server", "jobs", "--port", str(port), "--state", state],
        )

    assert result.exit_code == 0, result.stdout
    request = urllib.parse.urlparse(_JobsHTTPHandler.paths[0])
    query = urllib.parse.parse_qs(request.query)
    assert query["phase"] == [phase]
    assert filter_line in result.stdout
    assert empty_message in result.stdout


@pytest.mark.parametrize(
    ("argv", "message"),
    [
        (
            ["server", "jobs", "--state", "bananas"],
            'Invalid --state "bananas". Use active, waiting, finished, failed, '
            "or cancelled.",
        ),
        (
            ["server", "jobs", "--index", "database"],
            'Invalid --index "database". Use vault or code.',
        ),
        (
            ["server", "jobs", "--started-by", "robot"],
            'Invalid --started-by "robot". Use manual or automatic.',
        ),
    ],
)
def test_jobs_rejects_invalid_filter_values(argv: list[str], message: str) -> None:
    result = runner.invoke(
        app,
        [*argv, "--port", _DEAD_PORT],
    )

    assert result.exit_code == 2
    assert message in result.stdout
    assert "not running" not in result.stdout.lower()


def test_jobs_rejects_invalid_filter_values_as_json() -> None:
    result = runner.invoke(
        app,
        [
            "server",
            "jobs",
            "--state",
            "bananas",
            "--port",
            _DEAD_PORT,
            "--json",
        ],
    )

    assert result.exit_code == 2
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "service.jobs"
    assert payload["error"] == "invalid_filter"
    assert 'Invalid --state "bananas"' in payload["message"]


@pytest.mark.parametrize(
    "argv",
    [
        ["server", "jobs", "--phase", "finished"],
        ["server", "jobs", "--source", "code"],
        ["server", "jobs", "--trigger", "automatic"],
    ],
)
def test_jobs_removed_legacy_filter_flags_are_not_supported(
    argv: list[str],
) -> None:
    result = runner.invoke(app, [*argv, "--port", _DEAD_PORT])

    assert result.exit_code != 0
    assert "not running" not in result.stdout.lower()


@pytest.mark.parametrize(
    ("result", "expected_message", "expected_filter"),
    [
        (
            {"jobs": [], "filters": {"limit": 5, "phase": "running"}},
            "There are no active or waiting jobs.",
            "Filter: state active or waiting",
        ),
        (
            {"jobs": [], "filters": {"limit": 5, "failed": True}},
            "There are no failed jobs.",
            "Filter: failed only",
        ),
        (
            {"jobs": [], "filters": {"limit": 5, "source": "code"}},
            "No jobs matched these filters.",
            "Filter: index code",
        ),
        (
            {"jobs": [], "filters": {"limit": 5}},
            "No jobs have been reported by this service yet.",
            None,
        ),
    ],
)
def test_empty_jobs_output_is_actionable(
    result: dict[str, object],
    expected_message: str,
    expected_filter: str | None,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs import _render_jobs_result

    _render_jobs_result(result, job_id=None, port=8766)

    output = capsys.readouterr().out
    lines = _plain_lines(output)
    expected_present = [
        "Jobs",
        "Address: http://127.0.0.1:8766",
        "Displayed: 0 matching jobs" if expected_filter else "Displayed: 0 jobs",
        "Displayed jobs: 0 active, 0 waiting, 0 finished, 0 failed",
        "Order: latest job appears last",
        expected_message,
        "Next actions:",
        "vaultspec-rag server status --port 8766",
        "vaultspec-rag server logs --limit 20 --port 8766",
    ]
    if expected_filter is not None:
        expected_present.append(expected_filter)
    missing = [line for line in expected_present if line not in lines]
    assert not missing, f"missing actionable empty-jobs lines: {missing}"
    assert "No running jobs." not in output
    assert "No recent jobs." not in output


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


def test_jobs_filtered_header_separates_matches_from_service_total(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs import _render_jobs_result

    now = time.time()
    _render_jobs_result(
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
    assert compound == "embedding and writing sections 64 of 196"
    assert "upsert" not in compound


def test_jobs_missing_context_uses_reported_absence_language(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from ...cli._service_jobs import _render_jobs_result

    _render_jobs_result(
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
            "project_root": r"C:\projects\proj-a",
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

    assert "10 minutes" in running_output
    assert "10 minutes" not in failed_output


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
    tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    """Build a real Starlette app from the read-only ROUTES.

    Sets a known ``_SERVICE_TOKEN`` on the package namespace (the route's
    ``require_token`` reads it through the alias) and seeds one finished
    record. Restores the token on teardown so the suite stays isolated.
    """
    import os

    from ...config import EnvVar, reset_config

    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "route-status")
    reset_config()
    _jobs.reset()
    job_id = _jobs.record_start("vault", "tool")
    _jobs.record_finish(job_id, result="+1 /0 -0 (5ms)")

    prev_token = _m._SERVICE_TOKEN
    _m._SERVICE_TOKEN = "test-token-jobs"

    app_under_test = Starlette(routes=ROUTES)
    client = TestClient(app_under_test)
    try:
        yield client, "test-token-jobs"
    finally:
        _jobs.reset()
        _m._SERVICE_TOKEN = prev_token
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        reset_config()


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


def _create_route_job(
    client: TestClient,
    headers: dict[str, str],
    project_root: Path,
    *,
    idempotency_key: str | None = None,
    include_initiator: bool = False,
) -> httpx.Response:
    """Create one paused route job through the real ASGI client."""
    request_headers = dict(headers)
    if idempotency_key is not None:
        request_headers["Idempotency-Key"] = idempotency_key
    payload: dict[str, object] = {
        "operation": "index",
        "source": "vault",
        "project_root": str(project_root),
        "mode": "incremental",
        "start_paused": True,
    }
    if include_initiator:
        payload["initiator"] = {"kind": "cli", "command": "test_create"}
    return cast(
        "httpx.Response",
        client.post(  # pyright: ignore[reportUnknownMemberType]
            "/jobs",
            headers=request_headers,
            json=payload,
        ),
    )


def _assert_route_creation_contract(
    client: TestClient,
    headers: dict[str, str],
    project_root: Path,
) -> str:
    """Assert create, idempotent replay, key conflict, and active deduplication."""
    created = _create_route_job(
        client,
        headers,
        project_root,
        idempotency_key="route-lifecycle",
        include_initiator=True,
    )
    assert created.status_code == 202, created.text
    created_payload: dict[str, Any] = created.json()
    job = cast("dict[str, Any]", created_payload["job"])
    job_id = str(job["id"])
    assert created.headers["location"] == f"/jobs/{job_id}"
    assert job["state"] == "paused"
    assert job["desired_state"] == "paused"
    replay = _create_route_job(
        client,
        headers,
        project_root,
        idempotency_key="route-lifecycle",
        include_initiator=True,
    )
    assert replay.status_code == 200
    assert replay.json()["code"] == "idempotency_replayed"
    assert replay.json()["job"]["id"] == job_id
    assert replay.headers["location"] == f"/jobs/{job_id}"
    other_root = project_root / "other"
    (other_root / ".vault").mkdir(parents=True)
    key_conflict = _create_route_job(
        client,
        headers,
        other_root,
        idempotency_key="route-lifecycle",
    )
    assert key_conflict.status_code == 409
    assert key_conflict.json()["code"] == "idempotency_key_conflict"
    deduplicated = _create_route_job(
        client,
        headers,
        project_root,
        include_initiator=True,
    )
    assert deduplicated.status_code == 200
    assert deduplicated.json()["code"] == "active_job_exists"
    assert deduplicated.json()["job"]["id"] == job_id
    return job_id


def _assert_route_exact_id_contract(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
) -> None:
    """Assert detail and every mutating route require the exact ID."""
    detail = cast(
        "httpx.Response",
        client.get(f"/jobs/{job_id}", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert detail.status_code == 200
    assert detail.json()["job"]["state"] == "paused"
    prefix = job_id[:8]
    prefix_detail = cast(
        "httpx.Response",
        client.get(f"/jobs/{prefix}", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert prefix_detail.status_code == 404
    prefix_desired = cast(
        "httpx.Response",
        client.put(  # pyright: ignore[reportUnknownMemberType]
            f"/jobs/{prefix}/desired-state",
            headers=headers,
            json={"state": "paused"},
        ),
    )
    assert prefix_desired.status_code == 404
    prefix_retry = cast(
        "httpx.Response",
        client.post(f"/jobs/{prefix}/retry", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert prefix_retry.status_code == 404
    prefix_delete = cast(
        "httpx.Response",
        client.delete(f"/jobs/{prefix}", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert prefix_delete.status_code == 404


def _assert_route_paused_filter(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
) -> None:
    """Assert the canonical job appears in the controllable paused filter."""
    filtered = cast(
        "httpx.Response",
        client.get(  # pyright: ignore[reportUnknownMemberType]
            "/jobs",
            headers=headers,
            params={
                "state": "paused",
                "desired_state": "paused",
                "controllable": "true",
            },
        ),
    )
    assert filtered.status_code == 200
    assert [entry["id"] for entry in filtered.json()["jobs"]] == [job_id]


def test_jobs_route_canonical_control_retry_and_delete(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir()
    client, token = _routes_app
    headers = {"Authorization": f"Bearer {token}"}
    job_id = _assert_route_creation_contract(client, headers, tmp_path)
    _assert_route_exact_id_contract(client, headers, job_id)
    _assert_route_paused_filter(client, headers, job_id)


def _assert_route_control_conflicts(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
) -> None:
    """Assert force, stale revision, and active deletion conflicts."""
    stale_force = cast(
        "httpx.Response",
        client.put(  # pyright: ignore[reportUnknownMemberType]
            f"/jobs/{job_id}/desired-state",
            headers=headers,
            json={"state": "running", "mode": "force"},
        ),
    )
    assert stale_force.status_code == 409, stale_force.text
    assert stale_force.json()["code"] == "force_termination_unavailable"
    stale_revision = cast(
        "httpx.Response",
        client.put(  # pyright: ignore[reportUnknownMemberType]
            f"/jobs/{job_id}/desired-state",
            headers=headers,
            json={"state": "cancelled", "expected_revision": 999},
        ),
    )
    assert stale_revision.status_code == 409
    assert stale_revision.json()["code"] == "revision_conflict"
    active_delete = cast(
        "httpx.Response",
        client.delete(f"/jobs/{job_id}", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert active_delete.status_code == 409
    assert active_delete.json()["code"] == "job_not_terminal"


def _cancel_route_job(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
    revision: int,
) -> None:
    """Cancel a route job and assert stale replay is idempotent."""
    cancelled = cast(
        "httpx.Response",
        client.put(  # pyright: ignore[reportUnknownMemberType]
            f"/jobs/{job_id}/desired-state",
            headers=headers,
            json={"state": "cancelled", "expected_revision": revision},
        ),
    )
    assert cancelled.status_code == 200
    cancelled_job = cancelled.json()["job"]
    assert cancelled_job["state"] == "cancelled"
    replayed_cancel = cast(
        "httpx.Response",
        client.put(  # pyright: ignore[reportUnknownMemberType]
            f"/jobs/{job_id}/desired-state",
            headers=headers,
            json={"state": "cancelled", "expected_revision": revision},
        ),
    )
    assert replayed_cancel.status_code == 200
    assert replayed_cancel.json()["code"] == "already_satisfied"
    assert replayed_cancel.json()["job"]["id"] == job_id
    assert replayed_cancel.json()["job"]["revision"] == cancelled_job["revision"]
    assert replayed_cancel.json()["job"]["state"] == "cancelled"


def _retry_delete_route_job(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
) -> None:
    """Retry a terminal job, delete its parent, and assert absence."""
    from ...jobs import get_job_manager

    get_job_manager().begin_shutdown()
    retried = cast(
        "httpx.Response",
        client.post(f"/jobs/{job_id}/retry", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert retried.status_code == 202
    assert retried.json()["job"]["parent_job_id"] == job_id
    assert retried.headers["location"].startswith("/jobs/")
    deleted = cast(
        "httpx.Response",
        client.delete(f"/jobs/{job_id}", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert deleted.status_code == 200
    assert deleted.json()["code"] == "job_deleted"
    missing = cast(
        "httpx.Response",
        client.get(f"/jobs/{job_id}", headers=headers),  # pyright: ignore[reportUnknownMemberType]
    )
    assert missing.status_code == 404


def test_jobs_route_control_retry_and_terminal_delete(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir()
    client, token = _routes_app
    headers = {"Authorization": f"Bearer {token}"}
    created = _create_route_job(client, headers, tmp_path)
    assert created.status_code == 202
    job = created.json()["job"]
    job_id = str(job["id"])
    _assert_route_control_conflicts(client, headers, job_id)
    _cancel_route_job(client, headers, job_id, int(job["revision"]))
    _retry_delete_route_job(client, headers, job_id)


def test_jobs_route_enforces_nonterminal_capacity(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    import os

    from ...config import EnvVar, reset_config
    from ...jobs import reset

    client, token = _routes_app
    headers = {"Authorization": f"Bearer {token}"}
    roots = (tmp_path / "one", tmp_path / "two")
    for root in roots:
        (root / ".vault").mkdir(parents=True)
    prior = {
        EnvVar.STATUS_DIR: os.environ.get(EnvVar.STATUS_DIR),
        EnvVar.JOB_MAX_NONTERMINAL: os.environ.get(EnvVar.JOB_MAX_NONTERMINAL),
    }
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    os.environ[EnvVar.JOB_MAX_NONTERMINAL] = "1"
    reset_config()
    reset()
    try:
        first = cast(
            "httpx.Response",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/jobs",
                headers=headers,
                json={
                    "operation": "index",
                    "source": "vault",
                    "project_root": str(roots[0]),
                    "mode": "incremental",
                    "start_paused": True,
                },
            ),
        )
        assert first.status_code == 202
        second = cast(
            "httpx.Response",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/jobs",
                headers=headers,
                json={
                    "operation": "index",
                    "source": "vault",
                    "project_root": str(roots[1]),
                    "mode": "incremental",
                    "start_paused": True,
                },
            ),
        )
        assert second.status_code == 429
        assert second.json()["code"] == "job_capacity_exceeded"
    finally:
        reset()
        for key, value in prior.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        reset_config()


def test_reindex_route_rejects_unknown_type(
    _routes_app: tuple[TestClient, str],
    tmp_path: Path,
) -> None:
    client, token = _routes_app
    invalid_types: tuple[object, ...] = ("database", [])
    for invalid_type in invalid_types:
        response = cast(
            "httpx.Response",
            client.post(  # pyright: ignore[reportUnknownMemberType]
                "/reindex",
                headers={"Authorization": f"Bearer {token}"},
                json={"type": invalid_type, "project_root": str(tmp_path)},
            ),
        )
        assert response.status_code == 400
        assert response.json()["code"] == "invalid_job_spec"


async def test_job_mutations_keep_real_asgi_loop_responsive(
    tmp_path: Path,
) -> None:
    """Real durable CRUD writes must overlap an immediate ASGI auth response."""
    import asyncio
    import os

    import httpx

    from ...config import EnvVar, reset_config
    from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
    from ...jobs import get_job_manager, reset

    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_token = _m._SERVICE_TOKEN
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    reset_config()
    reset()
    _jobs.reset()
    token = "test-token-responsive-job-writes"
    _m._SERVICE_TOKEN = token
    headers = {"Authorization": f"Bearer {token}"}
    large_root = tmp_path / "large-registry-entry"
    target_root = tmp_path / "target"
    (large_root / ".vault").mkdir(parents=True)
    (target_root / ".vault").mkdir(parents=True)

    try:
        manager = get_job_manager()
        large_entry = manager.create(
            JobSpec(
                operation=JobOperation.INDEX,
                source=JobSource.VAULT,
                project_root=str(large_root),
                mode=JobMode.INCREMENTAL,
            ),
            JobInitiator(
                kind="test",
                command="seed_real_persistence_backpressure",
                project_root=str(large_root),
            ),
        )
        assert large_entry.job is not None
        failed = manager.fail_unstarted(
            large_entry.job.id,
            result=("real-persistence-backpressure:" + ("x" * (32 * 1024 * 1024))),
        )
        assert failed.code == "job_failed_before_dispatch"

        app_under_test = Starlette(routes=ROUTES)
        transport = httpx.ASGITransport(app=app_under_test)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:

            async def assert_overlaps_auth_probe(
                request: Coroutine[Any, Any, httpx.Response],
            ) -> httpx.Response:
                mutation = asyncio.create_task(request)
                await asyncio.sleep(0)
                probe = await client.get("/jobs")
                overlapped = not mutation.done()
                response = await mutation
                assert probe.status_code == 401
                assert overlapped, (
                    "the durable mutation completed before an independent ASGI "
                    "auth response could run"
                )
                return response

            created = await assert_overlaps_auth_probe(
                client.post(
                    "/jobs",
                    headers=headers,
                    json={
                        "operation": "index",
                        "source": "vault",
                        "project_root": str(target_root),
                        "mode": "incremental",
                        "start_paused": True,
                    },
                )
            )
            assert created.status_code == 202, created.text
            job = cast("dict[str, Any]", created.json()["job"])
            job_id = str(job["id"])

            cancelled = await assert_overlaps_auth_probe(
                client.put(
                    f"/jobs/{job_id}/desired-state",
                    headers=headers,
                    json={
                        "state": "cancelled",
                        "expected_revision": job["revision"],
                    },
                )
            )
            assert cancelled.status_code == 200, cancelled.text

            manager.begin_shutdown()
            retried = await assert_overlaps_auth_probe(
                client.post(f"/jobs/{job_id}/retry", headers=headers)
            )
            assert retried.status_code == 202, retried.text

            deleted = await assert_overlaps_auth_probe(
                client.delete(f"/jobs/{job_id}", headers=headers)
            )
            assert deleted.status_code == 200, deleted.text
    finally:
        reset()
        _jobs.reset()
        _m._SERVICE_TOKEN = prior_token
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        reset_config()


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
        client.get("/jobs", params={"token": token, "limit": "1"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
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
        client.get("/jobs", params={"token": token, "limit": "1"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
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
        client.get(  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
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
        client.get("/jobs", params={"token": token, "source": "codebase"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
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
        client.get(  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
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
        client.get("/jobs", params={"token": token, "query": "cli"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
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
        client.get("/jobs", params={"token": token, "since": "0.1"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
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
        client.get("/jobs", params={"token": token, "job_id": prefix}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    assert payload["returned"] >= 2
    assert all(str(job["id"]).startswith(prefix) for job in payload["jobs"])


async def _seed_terminal_resilience_job(
    project_root: Path,
    *,
    outcome_name: str,
    error_kind: JobErrorKind | None,
) -> dict[str, object]:
    manager = _managed_jobs.get_job_manager()
    created = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.CODE,
            project_root=str(project_root),
            mode=JobMode.REBUILD,
        ),
        JobInitiator("cli", "server jobs", str(project_root)),
        start_paused=outcome_name == "controlled",
    )
    assert created.job is not None
    job_id = created.job.id
    owner_task: asyncio.Task[object] | None = None
    if outcome_name == "controlled":
        terminal = manager.set_desired_state(job_id, DesiredJobState.CANCELLED)
        terminal_outcome = JobState.CANCELLED.value
    elif outcome_name == "interrupted":
        owner_task = asyncio.create_task(asyncio.Event().wait())
        started = manager.start_attempt(
            job_id,
            task=owner_task,
            control=RunControlToken(),
        )
        assert started.code == "attempt_started"
        terminal = manager.finish_attempt(
            job_id,
            attempt=1,
            task=owner_task,
            state=JobState.INTERRUPTED,
            result="the service stopped before the attempt completed",
            error_kind=JobState.INTERRUPTED.value,
        )
        terminal_outcome = JobState.INTERRUPTED.value
    else:
        assert error_kind is not None
        terminal = manager.fail_unstarted(
            job_id,
            result=str(JobError(error_kind, f"{outcome_name} safety boundary reached")),
        )
        terminal_outcome = error_kind.value
    try:
        assert terminal.job is not None
        resilience = IndexResilienceSnapshot(
            generation_id=f"generation-{outcome_name}",
            committed_units=41,
            replayed_units=3,
            checkpoint_compatible=True,
            last_durable_progress_at=1_722_000_000.0,
            no_progress_timeout_seconds=300.0,
            no_progress_remaining_seconds=17.5,
            circuit_state=(
                "open" if error_kind is JobErrorKind.WATCHER_CIRCUIT_OPEN else "closed"
            ),
            next_retry_at=1_722_000_060.0,
            peak_rss_mb=512.0,
            rss_ceiling_mb=2048.0,
            peak_cuda_allocated_mb=768.0,
            peak_cuda_reserved_mb=896.0,
            cuda_ceiling_mb=4096.0,
            support_profile="embedded-local",
            terminal_outcome=terminal_outcome,
        )
        assert manager.update_terminal_resilience(
            job_id,
            attempt=terminal.job.attempt.number,
            resilience=resilience,
        )
        snapshot = manager.get(job_id)
        assert snapshot is not None
        return snapshot.to_dict()
    finally:
        if owner_task is not None:
            owner_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await owner_task


def _resilience_http_views(
    port: int,
    token: str,
    job_id: str,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Fetch and validate the collection, detail, and health HTTP surfaces."""
    import httpx

    headers = {"Authorization": f"Bearer {token}"}
    with httpx.Client(base_url=f"http://127.0.0.1:{port}") as client:
        collection_response = client.get("/jobs", headers=headers)
        detail_response = client.get(f"/jobs/{job_id}", headers=headers)
        health_response = client.get("/health")
    assert collection_response.status_code == 200
    assert detail_response.status_code == 200
    assert health_response.status_code == 200
    collection_job = cast("dict[str, object]", collection_response.json()["jobs"][0])
    detail_job = cast("dict[str, object]", detail_response.json()["job"])
    health_jobs = cast("dict[str, object]", health_response.json()["jobs"])
    return collection_job, detail_job, health_jobs


def _assert_resilience_job_parity(
    canonical: dict[str, object],
    collection_job: dict[str, object],
    detail_job: dict[str, object],
    *,
    job_id: str,
    expected_state: JobState,
    expected_error_kind: str | None,
) -> str:
    """Assert canonical collection and detail payload parity."""
    assert collection_job["id"] == detail_job["id"] == job_id
    assert collection_job["state"] == detail_job["state"] == canonical["state"]
    assert detail_job["state"] == expected_state.value
    assert (
        collection_job["error_kind"] == detail_job["error_kind"] == expected_error_kind
    )
    assert collection_job["resilience"] == detail_job["resilience"]
    expected_terminal_outcome = (
        expected_error_kind
        if expected_error_kind is not None
        else JobState.CANCELLED.value
    )
    detail_resilience = cast("dict[str, object]", detail_job["resilience"])
    assert detail_resilience["terminal_outcome"] == expected_terminal_outcome
    return expected_terminal_outcome


# The resilience measures the job response rounds to operator precision; the
# health rollup projects them at full snapshot precision. Rounding both sides
# to the same precision before comparing makes the identity a comparison of
# state, not of serialization cadence, so a future fractional-memory scenario
# cannot reintroduce a rounds-vs-full-precision divergence.
_RESILIENCE_MEASURE_KEYS = (
    "no_progress_timeout_seconds",
    "no_progress_remaining_seconds",
    "peak_rss_mb",
    "rss_ceiling_mb",
    "peak_cuda_allocated_mb",
    "peak_cuda_reserved_mb",
    "cuda_ceiling_mb",
)


def _resilience_state(resilience: dict[str, object]) -> dict[str, object]:
    """Return the shared resilience state: measures rounded, remediation dropped.

    ``remediation`` is excluded because it is not resilience state - it is a
    derived presentation hint the broker-facing job response adds and the
    liveness-facing health rollup deliberately does not carry. It is verified
    separately as a correct derivation of the shared terminal outcome.
    """
    state = {
        key: (
            round(float(value), 1)
            if key in _RESILIENCE_MEASURE_KEYS
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            else value
        )
        for key, value in resilience.items()
        if key != "remediation"
    }
    return state


def _assert_resilience_health(
    health_jobs: dict[str, object],
    detail_job: dict[str, object],
    *,
    job_id: str,
    outcome_name: str,
    error_kind: JobErrorKind | None,
) -> None:
    """Assert health carries the same bounded resilience STATE and failure evidence.

    Health and the job response expose identical resilience STATE - the full
    canonical field set, including the terminal outcome. They differ only on the
    derived ``remediation`` hint, which the broker-facing job response carries
    and the liveness health rollup does not. So the identity is over the state,
    and the job response's remediation is verified separately as the correct
    derivation of the terminal outcome both surfaces share.
    """
    health_resilience = cast("dict[str, object]", health_jobs["resilience"]).copy()
    assert health_resilience.pop("job_id") == job_id
    assert health_resilience.pop("source") == "code"
    detail_resilience = cast("dict[str, object]", detail_job["resilience"])
    # Identical resilience state across the two surfaces (remediation excluded,
    # measures compared at one precision). Any divergence in generation,
    # checkpoint counts, circuit, ceilings, or terminal outcome still fails.
    assert _resilience_state(health_resilience) == _resilience_state(detail_resilience)
    # The broker response's remediation is the correct derivation of the
    # terminal outcome both surfaces carry - same state, same derivation.
    shared_terminal = health_resilience["terminal_outcome"]
    assert detail_resilience["remediation"] == remediation(
        shared_terminal if isinstance(shared_terminal, str) else None
    )
    if error_kind is None or outcome_name == "interrupted":
        assert health_jobs["last_failed"] is None
        return
    last_failed = cast("dict[str, object]", health_jobs["last_failed"])
    assert last_failed["id"] == job_id
    assert last_failed["error_kind"] == error_kind.value


def _assert_resilience_cli_json(
    port: int,
    job_id: str,
    detail_job: dict[str, object],
) -> None:
    """Assert the JSON CLI retains detail-route resilience fields."""
    cli_json = runner.invoke(
        app,
        [
            "server",
            "jobs",
            "--port",
            str(port),
            "--job-id",
            job_id,
            "--json",
        ],
    )
    assert cli_json.exit_code == 0, cli_json.output
    cli_job = cast("dict[str, object]", json.loads(cli_json.output)["data"]["jobs"][0])
    assert cli_job["error_kind"] == detail_job["error_kind"]
    assert cli_job["resilience"] == detail_job["resilience"]


def _assert_resilience_cli_human(
    port: int,
    job_id: str,
    outcome_name: str,
    expected_terminal_outcome: str,
) -> None:
    """Assert the human CLI renders every bounded resilience field."""
    cli_human = runner.invoke(
        app,
        ["server", "jobs", "--port", str(port), "--job-id", job_id],
    )
    assert cli_human.exit_code == 0, cli_human.output
    expected_lines = (
        "Index profile: embedded-local",
        f"Checkpoint generation: generation-{outcome_name}",
        "Checkpoint compatible: yes",
        "Checkpoint units: 41 committed, 3 resumed",
        "No-progress budget remaining: 17 seconds",
        "Retry circuit: " + ("open" if outcome_name == "circuit-open" else "closed"),
        "Next retry: 2024-07-26 13:21:00 UTC",
        "RSS high-water / ceiling: 512.0 MiB / 2.0 GiB",
        "CUDA allocated high-water: 768.0 MiB",
        "CUDA reserved high-water / ceiling: 896.0 MiB / 4.0 GiB",
        f"Index outcome: {expected_terminal_outcome}",
    )
    for line in expected_lines:
        assert line in cli_human.output


@pytest.mark.parametrize(
    ("outcome_name", "error_kind", "expected_state", "expected_error_kind"),
    [
        ("controlled", None, JobState.CANCELLED, None),
        ("interrupted", None, JobState.INTERRUPTED, "interrupted"),
        (
            "rss-limited",
            JobErrorKind.RSS_MEMORY_CEILING,
            JobState.FAILED,
            "rss_memory_ceiling",
        ),
        (
            "cuda-limited",
            JobErrorKind.CUDA_MEMORY_CEILING,
            JobState.FAILED,
            "cuda_memory_ceiling",
        ),
        (
            "timed-out",
            JobErrorKind.NO_PROGRESS_TIMEOUT,
            JobState.FAILED,
            "no_progress_timeout",
        ),
        (
            "circuit-open",
            JobErrorKind.WATCHER_CIRCUIT_OPEN,
            JobState.FAILED,
            "watcher_circuit_open",
        ),
    ],
)
async def test_canonical_resilience_snapshot_has_http_health_and_cli_parity(
    tmp_path: Path,
    outcome_name: str,
    error_kind: JobErrorKind | None,
    expected_state: JobState,
    expected_error_kind: str | None,
) -> None:
    project_root = tmp_path / outcome_name
    project_root.mkdir()
    with _canonical_resilience_server(tmp_path) as (port, token):
        canonical = await _seed_terminal_resilience_job(
            project_root,
            outcome_name=outcome_name,
            error_kind=error_kind,
        )
        job_id = cast("str", canonical["id"])
        collection_job, detail_job, health_jobs = _resilience_http_views(
            port,
            token,
            job_id,
        )
        expected_terminal_outcome = _assert_resilience_job_parity(
            canonical,
            collection_job,
            detail_job,
            job_id=job_id,
            expected_state=expected_state,
            expected_error_kind=expected_error_kind,
        )
        _assert_resilience_health(
            health_jobs,
            detail_job,
            job_id=job_id,
            outcome_name=outcome_name,
            error_kind=error_kind,
        )
        _assert_resilience_cli_json(port, job_id, detail_job)
        _assert_resilience_cli_human(
            port,
            job_id,
            outcome_name,
            expected_terminal_outcome,
        )
