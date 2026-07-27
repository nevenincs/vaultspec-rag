"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from vaultspec_rag import jobs as _jobs
from vaultspec_rag.job_models import JobSource

from .._job_records import activity_record
from ._service_jobs_route_helpers import (
    _routes_app as _routes_app_fixture,
)
from ._service_jobs_support import _clean_jobs as _clean_jobs_fixture

__all__ = ["_clean_jobs_fixture", "_routes_app_fixture"]

if TYPE_CHECKING:
    import httpx
    from starlette.testclient import TestClient

# The start stamp is pushed well outside the window the query asks for, so the
# record is only reachable through the progress stamp; the window itself is wide
# enough that no amount of host load can move a just-written stamp out of it.
_STARTED_BEFORE_WINDOW_SECONDS = 600.0
_SINCE_WINDOW_SECONDS = 60.0


@pytest.mark.unit
def test_jobs_route_respects_limit_param(
    _routes_app: tuple[TestClient, str],
) -> None:
    # Seed a second record so a limit=1 actually trims.
    _jobs.record_start(JobSource.CODE, "watcher")
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", params={"token": token, "limit": "1"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1


@pytest.mark.unit
def test_jobs_route_prioritises_running_before_limit(
    _routes_app: tuple[TestClient, str],
) -> None:
    running_id = _jobs.record_start(JobSource.CODE, "watcher")
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


@pytest.mark.unit
def test_jobs_route_prioritises_failed_before_completed_limit(
    _routes_app: tuple[TestClient, str],
) -> None:
    _jobs.record_finish(_jobs.record_start(JobSource.CODE, "tool"), result="newer done")
    failed_id = _jobs.record_start(JobSource.CODE, "tool")
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


@pytest.mark.unit
def test_jobs_route_filters_phase_source_trigger_and_query(
    _routes_app: tuple[TestClient, str],
) -> None:
    _jobs.record_start(JobSource.CODE, "watcher")
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


@pytest.mark.unit
def test_jobs_route_accepts_codebase_source_alias(
    _routes_app: tuple[TestClient, str],
) -> None:
    running_id = _jobs.record_start(JobSource.CODE, "watcher")
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


@pytest.mark.unit
def test_jobs_route_filters_failed_job_id_and_since(
    _routes_app: tuple[TestClient, str],
) -> None:
    failed_id = _jobs.record_start(JobSource.CODE, "tool")
    _jobs.record_finish(failed_id, error="boom")
    _jobs.record_finish(_jobs.record_start(JobSource.VAULT, "watcher"), result="old")
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


@pytest.mark.unit
def test_jobs_route_query_matches_runtime_and_initiator(
    _routes_app: tuple[TestClient, str],
) -> None:
    running_id = _jobs.record_start(
        JobSource.CODE,
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


@pytest.mark.unit
def test_jobs_route_since_uses_progress_update_time(
    _routes_app: tuple[TestClient, str],
) -> None:
    """A job started outside the window is returned on its progress stamp.

    Backdating the start stamp is what gives the assertion teeth: the record can
    only come back on the strength of the progress stamp, and it comes back by a
    minute rather than by milliseconds. Producing the same shape by waiting
    would run the whole assertion inside a sub-second race against the durable
    snapshot write ``record_progress`` performs after stamping.
    """
    running_id = _jobs.record_start(JobSource.CODE, "tool")
    with activity_record(running_id) as record:
        record["started_at"] = (
            cast("float", record["started_at"]) - _STARTED_BEFORE_WINDOW_SECONDS
        )
    _jobs.record_progress(running_id, "embed", completed=1, total=10)
    client, token = _routes_app

    response = cast(
        "httpx.Response",
        client.get(  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
            "/jobs",
            params={"token": token, "since": str(_SINCE_WINDOW_SECONDS)},
        ),
    )

    assert response.status_code == 200
    payload: dict[str, Any] = response.json()
    ids = [job["id"] for job in payload["jobs"]]
    assert running_id in ids


@pytest.mark.unit
def test_jobs_route_job_id_prefix_can_return_multiple_matches(
    _routes_app: tuple[TestClient, str],
) -> None:
    ids_by_prefix: dict[str, list[str]] = {}
    for _ in range(17):
        job_id = _jobs.record_start(JobSource.VAULT, "tool")
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
