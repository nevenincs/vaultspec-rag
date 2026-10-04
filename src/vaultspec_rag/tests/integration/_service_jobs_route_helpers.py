"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from starlette.testclient import TestClient

from ... import jobs as _jobs
from ...job_models import JobSource
from ...server import ServerRouteRuntime, create_http_app
from ...service import ServiceRegistry

__all__ = [
    "_assert_route_control_conflicts",
    "_assert_route_exact_id_contract",
    "_assert_route_paused_filter",
    "_cancel_route_job",
    "_retry_delete_route_job",
    "_routes_app",
    "_seed_paused_route_job",
]

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx

    from ...job_models import JobSnapshot


@pytest.fixture(name="_routes_app")
def _routes_app(
    _clean_jobs: None,
    tmp_path: Path,
) -> Iterator[tuple[TestClient, str]]:
    """Build a real Starlette app from the read-only ROUTES.

    Sets a known ``_SERVICE_TOKEN`` on the package namespace (the route's
    ``require_token`` reads it through the alias) and seeds one finished
    record. Restores the token on teardown so the suite stays isolated.
    """
    import os

    from ...config._types import EnvVar
    from .._config_fixtures import reset_config

    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "route-status")
    reset_config()
    _jobs.reset()
    job_id = _jobs.record_start(JobSource.VAULT, "tool")
    _jobs.record_finish(job_id, result="+1 /0 -0 (5ms)")

    app_under_test = create_http_app(
        ServerRouteRuntime(
            token="test-token-jobs",
            registry=ServiceRegistry(),
            port=8765,
        ),
        lifespan=None,
    )
    client = TestClient(app_under_test, base_url="http://127.0.0.1")
    try:
        yield client, "test-token-jobs"
    finally:
        _jobs.reset()
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        reset_config()


def _seed_paused_route_job(project_root: Path) -> JobSnapshot:
    """Admit one job and pause it before dispatch, as the routes then see it.

    Jobs are created only through ``/reindex``, which dispatches at once; the
    control routes under test need work that holds still, so the job is
    admitted through the manager the route uses and paused before it runs.
    """
    from ...indexer._run_ledger_models import RunAuthority
    from ...job_models import (
        DesiredJobState,
        JobInitiator,
        JobMode,
        JobOperation,
        JobSpec,
    )

    manager = _jobs.get_job_manager()
    created = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.VAULT,
            project_root=str(project_root),
            mode=JobMode.INCREMENTAL,
            authority=RunAuthority.PUBLICATION,
        ),
        JobInitiator("cli", "test_create", str(project_root)),
    )
    assert created.code == "job_created", created
    assert created.job is not None
    paused = manager.set_desired_state(created.job.id, DesiredJobState.PAUSED)
    assert paused.code == "job_paused", paused
    assert paused.job is not None
    return paused.job


def _assert_route_exact_id_contract(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
) -> None:
    """Assert detail and every mutating route require the exact ID."""
    detail = cast(
        "httpx.Response",
        client.get(f"/jobs/{job_id}", headers=headers),
    )
    assert detail.status_code == 200
    assert detail.json()["job"]["state"] == "paused"
    prefix = job_id[:8]
    prefix_detail = cast(
        "httpx.Response",
        client.get(f"/jobs/{prefix}", headers=headers),
    )
    assert prefix_detail.status_code == 404
    prefix_desired = cast(
        "httpx.Response",
        client.put(
            f"/jobs/{prefix}/desired-state",
            headers=headers,
            json={"state": "paused"},
        ),
    )
    assert prefix_desired.status_code == 404
    prefix_retry = cast(
        "httpx.Response",
        client.post(f"/jobs/{prefix}/retry", headers=headers),
    )
    assert prefix_retry.status_code == 404
    prefix_delete = cast(
        "httpx.Response",
        client.delete(f"/jobs/{prefix}", headers=headers),
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
        client.get(
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


def _assert_route_control_conflicts(
    client: TestClient,
    headers: dict[str, str],
    job_id: str,
) -> None:
    """Assert force, stale revision, and active deletion conflicts."""
    stale_force = cast(
        "httpx.Response",
        client.put(
            f"/jobs/{job_id}/desired-state",
            headers=headers,
            json={"state": "running", "mode": "force"},
        ),
    )
    assert stale_force.status_code == 409, stale_force.text
    assert stale_force.json()["code"] == "force_termination_unavailable"
    stale_revision = cast(
        "httpx.Response",
        client.put(
            f"/jobs/{job_id}/desired-state",
            headers=headers,
            json={"state": "cancelled", "expected_revision": 999},
        ),
    )
    assert stale_revision.status_code == 409
    assert stale_revision.json()["code"] == "revision_conflict"
    active_delete = cast(
        "httpx.Response",
        client.delete(f"/jobs/{job_id}", headers=headers),
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
        client.put(
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
        client.put(
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
        client.post(f"/jobs/{job_id}/retry", headers=headers),
    )
    assert retried.status_code == 202
    assert retried.json()["job"]["parent_job_id"] == job_id
    assert retried.headers["location"].startswith("/jobs/")
    deleted = cast(
        "httpx.Response",
        client.delete(f"/jobs/{job_id}", headers=headers),
    )
    assert deleted.status_code == 200
    assert deleted.json()["code"] == "job_deleted"
    missing = cast(
        "httpx.Response",
        client.get(f"/jobs/{job_id}", headers=headers),
    )
    assert missing.status_code == 404
