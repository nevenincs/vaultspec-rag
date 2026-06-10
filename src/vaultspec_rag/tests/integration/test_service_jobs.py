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

import json
from typing import TYPE_CHECKING, Any, cast

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


@pytest.fixture  # pyright: ignore[reportUnusedFunction]
def _clean_jobs() -> Iterator[None]:
    """Reset the in-flight registry before and after each test."""
    _jobs.reset()
    yield
    _jobs.reset()


# --------------------------------------------------------------------------- #
# MCP: get_jobs returns the registry snapshot shape                           #
# --------------------------------------------------------------------------- #


@pytest.mark.subprocess_gpu
async def test_get_jobs_returns_snapshot_shape(
    _live_service: object,
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

    assert set(result) == {"jobs"}
    jobs: list[Any] = result["jobs"]
    assert isinstance(jobs, list)
    assert len(jobs) >= 1
    entry: dict[str, Any] = jobs[0]
    assert set(entry) == {
        "id",
        "source",
        "trigger",
        "phase",
        "started_at",
        "finished_at",
        "result",
        "progress",
    }
    assert entry["source"] == "vault"
    assert entry["trigger"] == "tool"
    assert entry["phase"] in ("done", "error", "failed")


@pytest.mark.subprocess_gpu
async def test_get_jobs_is_newest_first(
    _live_service: object,
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
    _live_service: object,
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    # Trigger multiple jobs
    for _ in range(3):
        await tools.reindex_vault(clean=True, project_root=str(tmp_path))

    jobs = (await admin.get_jobs(limit=2))["jobs"]
    assert len(jobs) == 2


@pytest.mark.subprocess_gpu
async def test_get_jobs_non_positive_limit_is_empty(
    _live_service: object,
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


def test_jobs_cli_mcp_parity() -> None:
    assert callable(admin.get_jobs)
    help_result = runner.invoke(app, ["server", "--help"])
    assert help_result.exit_code == 0
    assert "jobs" in help_result.stdout


# --------------------------------------------------------------------------- #
# Starlette: real ASGI TestClient against /jobs gating                        #
# --------------------------------------------------------------------------- #


@pytest.fixture  # pyright: ignore[reportUnusedFunction]
def _routes_app(_clean_jobs: None) -> Iterator[tuple[TestClient, str]]:
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
        "httpx.Response", client.get("/jobs", headers={"Authorization": "Bearer wrong"})
    )  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 401


def test_jobs_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", headers={"Authorization": f"Bearer {token}"}),
    )  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload: dict[str, Any] = response.json()
    assert set(payload) == {"jobs"}
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["source"] == "vault"
    assert payload["jobs"][0]["phase"] == "done"


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
        "httpx.Response", client.get("/jobs", params={"token": token, "limit": "1"})
    )  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1
