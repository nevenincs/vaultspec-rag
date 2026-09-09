"""HTTP proofs for canonical watcher-controller projections."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from .. import jobs
from ..job_models import JobSource
from ..server import ServerRouteRuntime, _watcher, create_http_app
from ..server._watcher import _WatcherScheduler
from ..service import ServiceRegistry
from ..watcher_controller import (
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    WatcherController,
)
from ..watcher_retry import WatcherSource

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(name="route_client")
def fixture_route_client(tmp_path: Path) -> Iterator[tuple[TestClient, str, Path]]:
    prior_scheduler = _watcher._watcher_scheduler
    prior_task = _watcher._watcher_scheduler_task
    jobs.reset()
    root = (tmp_path / "project").resolve()
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=lambda: 20.0)
    _watcher._watcher_scheduler = scheduler
    _watcher._watcher_scheduler_task = None
    app = create_http_app(
        ServerRouteRuntime(
            token="watcher-projection-token",
            registry=ServiceRegistry(),
            port=8765,
        ),
        lifespan=None,
    )
    with TestClient(app) as client:
        yield client, "watcher-projection-token", root
    jobs.reset()
    _watcher._watcher_scheduler = prior_scheduler
    _watcher._watcher_scheduler_task = prior_task


def _register_controller(
    root: Path,
    *,
    source: WatcherSource,
    state: ControllerState,
    job_id: str | None = None,
) -> None:
    scheduler = _watcher._watcher_scheduler
    assert scheduler is not None
    controller = WatcherController(
        ControllerSnapshot(
            canonical_root=str(root),
            source=source,
            state=state,
            reason=ControllerReason.QUIET_TREE_DEADLINE,
            scope=ControllerScope(generation=1),
            observed_at=10.0,
            next_decision_at=25.0,
            freshness_deadline=40.0,
            job_id=job_id,
        ),
        monotonic=lambda: 20.0,
        wall_clock=lambda: 20.0,
    )
    scheduler.register(controller, reevaluate=lambda: None, admit=lambda _item: None)


def test_watcher_route_filters_and_bounds_canonical_envelopes(
    route_client: tuple[TestClient, str, Path],
) -> None:
    client, token, root = route_client
    _register_controller(root, source=WatcherSource.CODE, state=ControllerState.READY)
    _register_controller(
        root, source=WatcherSource.VAULT, state=ControllerState.COLLECTING
    )

    response = client.get(
        "/watcher",
        params={"root": str(root), "source": "code", "state": "ready", "limit": 1},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["controllers_total"] == 1
    assert body["controllers_returned"] == 1
    assert body["controllers_truncated"] is False
    assert body["controllers"][0]["root"] == str(root)
    assert body["controllers"][0]["source"] == "code"
    assert body["controllers"][0]["state"] == "ready"
    assert body["controllers"][0]["reason"] == "quiet_tree_deadline"

    bounded = client.get(
        "/watcher?limit=0",
        headers={"Authorization": f"Bearer {token}"},
    ).json()
    assert bounded["controllers"] == []
    assert bounded["controllers_total"] == 2
    assert bounded["controllers_truncated"] is True


def test_job_routes_attach_same_controller_envelope_by_job_id(
    route_client: tuple[TestClient, str, Path],
) -> None:
    client, token, root = route_client
    job_id = jobs.record_start(JobSource.CODE, "watcher", project_root=root)
    _register_controller(
        root,
        source=WatcherSource.CODE,
        state=ControllerState.RUNNING,
        job_id=job_id,
    )
    headers = {"Authorization": f"Bearer {token}"}

    detail = client.get(f"/jobs/{job_id}", headers=headers)
    listing = client.get("/jobs", headers=headers)

    assert detail.status_code == 200
    detail_controller = detail.json()["job"]["controller"]
    listed = next(item for item in listing.json()["jobs"] if item["id"] == job_id)
    assert listed["controller"] == detail_controller
    assert detail_controller["job_id"] == job_id
    assert detail_controller["state"] == "running"
