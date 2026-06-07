"""Tests for the Tier-2b jobs surface (#142, plan P04).

Three layers, no mocks/skips/monkeypatch:

- MCP: seed the real in-flight registry via ``_jobs.record_start`` /
  ``record_finish`` and assert the ``get_jobs`` tool returns the snapshot
  shape (and honours ``limit``); the registry is reset in teardown.
- CLI: drive ``server service jobs`` through the real Typer app against a
  dead ``--port`` so ``_try_mcp_admin`` genuinely fails to connect, asserting
  the exit-3 + JSON envelope contract.
- Starlette: exercise the real ``GET /jobs`` route through
  ``starlette.testclient.TestClient`` (the real ASGI client, NOT a mock) built
  from ``_routes.ROUTES`` with a known ``_SERVICE_TOKEN`` - 401 without token,
  200 JSON with token.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient
from typer.testing import CliRunner

import vaultspec_rag.mcp_server as _m

from ... import mcp_server
from ...cli import app
from ...mcp_server import _jobs
from ...mcp_server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Iterator

runner = CliRunner()

# A port with nothing listening: _try_mcp_admin gets connection-refused
# and returns None -> the command reports service-not-running (exit 3).
_DEAD_PORT = "59235"


@pytest.fixture
def _clean_jobs() -> Iterator[None]:
    """Reset the in-flight registry before and after each test."""
    _jobs.reset()
    yield
    _jobs.reset()


# --------------------------------------------------------------------------- #
# MCP: get_jobs returns the registry snapshot shape                           #
# --------------------------------------------------------------------------- #


async def test_get_jobs_returns_snapshot_shape(_clean_jobs: None) -> None:
    job_id = _jobs.record_start("vault", "tool")
    _jobs.record_finish(job_id, result="+1 /0 -0 (5ms)")

    result = await mcp_server.get_jobs()
    assert set(result) == {"jobs"}
    jobs = result["jobs"]
    assert isinstance(jobs, list)
    assert len(jobs) == 1
    entry = jobs[0]
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
    assert entry["id"] == job_id
    assert entry["source"] == "vault"
    assert entry["trigger"] == "tool"
    assert entry["phase"] == "done"
    assert entry["result"] == "+1 /0 -0 (5ms)"


async def test_get_jobs_is_newest_first(_clean_jobs: None) -> None:
    first = _jobs.record_start("vault", "tool")
    second = _jobs.record_start("code", "watcher")

    jobs = (await mcp_server.get_jobs())["jobs"]
    assert [entry["id"] for entry in jobs] == [second, first]


async def test_get_jobs_honours_limit(_clean_jobs: None) -> None:
    newest_ids = [_jobs.record_start("vault", "tool") for _ in range(5)]

    jobs = (await mcp_server.get_jobs(limit=2))["jobs"]
    assert len(jobs) == 2
    # Newest-first: the two most recent records.
    assert [entry["id"] for entry in jobs] == [newest_ids[-1], newest_ids[-2]]


async def test_get_jobs_non_positive_limit_is_empty(_clean_jobs: None) -> None:
    _jobs.record_start("vault", "tool")
    assert (await mcp_server.get_jobs(limit=0))["jobs"] == []


# --------------------------------------------------------------------------- #
# CLI: service-not-running -> exit 3 + JSON envelope                          #
# --------------------------------------------------------------------------- #


def test_jobs_not_running_json() -> None:
    result = runner.invoke(
        app,
        ["server", "service", "jobs", "--port", _DEAD_PORT, "--json"],
    )
    assert result.exit_code == 3
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["command"] == "service.jobs"
    assert payload["error"] == "service_not_running"


def test_jobs_not_running_prose() -> None:
    result = runner.invoke(app, ["server", "service", "jobs", "--port", _DEAD_PORT])
    assert result.exit_code == 3
    assert "not running" in result.stdout.lower()


def test_jobs_subcommand_registered() -> None:
    result = runner.invoke(app, ["server", "service", "jobs", "--help"])
    assert result.exit_code == 0


def test_jobs_cli_mcp_parity() -> None:
    assert callable(mcp_server.get_jobs)
    help_result = runner.invoke(app, ["server", "service", "--help"])
    assert help_result.exit_code == 0
    assert "jobs" in help_result.stdout


# --------------------------------------------------------------------------- #
# Starlette: real ASGI TestClient against /jobs gating                        #
# --------------------------------------------------------------------------- #


@pytest.fixture
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
    response = client.get("/jobs")
    assert response.status_code == 401
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


def test_jobs_route_401_with_wrong_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = client.get("/jobs", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_jobs_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = client.get("/jobs", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert set(payload) == {"jobs"}
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["source"] == "vault"
    assert payload["jobs"][0]["phase"] == "done"


def test_jobs_route_200_with_query_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = client.get("/jobs", params={"token": token})
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1


def test_jobs_route_respects_limit_param(
    _routes_app: tuple[TestClient, str],
) -> None:
    # Seed a second record so a limit=1 actually trims.
    _jobs.record_start("code", "watcher")
    client, token = _routes_app
    response = client.get("/jobs", params={"token": token, "limit": "1"})
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1
