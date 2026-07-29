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
from typing import TYPE_CHECKING, Any, ClassVar

import pytest
import uvicorn
from starlette.applications import Starlette
from starlette.routing import Route
from typer.testing import CliRunner

import vaultspec_rag.mcp._admin_client as admin
import vaultspec_rag.server as _m

from ... import jobs as _jobs
from ... import jobs as _managed_jobs
from ...cli import app
from ...config._settings import reset_config
from ...config._types import EnvVar
from ...server._lifespan import health_handler
from ...server._routes import ROUTES
from .._http_stubs import QuietHandler
from .._ports import free_loopback_port

__all__ = [
    "_assert_cli_job_attribution",
    "_assert_mcp_job_snapshot",
    "_canonical_resilience_server",
    "_clean_jobs",
    "_cli_jobs_payload",
    "_jobs_feed_rows",
    "_jobs_http_server",
    "_label_values",
    "_plain_lines",
    "_wait_for_terminal_jobs",
]

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
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
                "resources": {"current": {"rss_mib": 10.0}},
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
                "resources": {"finished": {"rss_mib": 11.0}},
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
                "resources": {"finished": {"rss_mib": 12.0}},
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


@pytest.fixture(name="_clean_jobs")
def _clean_jobs() -> Iterator[None]:
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
    """Assert the complete real MCP job envelope and caller identity.

    Exact on purpose: the envelope is a contract, and a subset check would stop
    catching an unintended key forever. The tool answers from the same route as
    the HTTP listing, so the machine-wide readings the listing carries are part
    of what it returns.
    """
    assert set(result) == {
        "jobs",
        "total",
        "returned",
        "summary",
        "filters",
        "gpu",
        "pressure",
        "device_load",
    }
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
    assert isinstance(entry["resources"]["started"]["rss_mib"], float)


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
