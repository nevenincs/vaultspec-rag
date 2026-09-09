"""Cross-surface conformance proofs for canonical controller facts."""

from __future__ import annotations

import ast
import inspect
from typing import TYPE_CHECKING

import pytest
from starlette.testclient import TestClient

from .. import jobs
from ..api import controller_snapshot_envelope, get_service_state
from ..job_models import JobSource
from ..mcp import _admin_client
from ..server import ServerRouteRuntime, _watcher, create_http_app
from ..server._watcher import _WatcherScheduler
from ..service import ServiceRegistry
from ..serviceclient import _transport
from ..watcher_controller import (
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    WatcherController,
)
from ..watcher_retry import WatcherSource

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.fixture(name="controller_surfaces")
def fixture_controller_surfaces(
    tmp_path: Path,
) -> Iterator[tuple[TestClient, ServiceRegistry, Path, dict[str, object], str]]:
    previous_scheduler = _watcher._watcher_scheduler
    previous_task = _watcher._watcher_scheduler_task
    jobs.reset()
    root = (tmp_path / "project").resolve()
    job_id = jobs.record_start(JobSource.CODE, "watcher", project_root=root)
    snapshot = ControllerSnapshot(
        canonical_root=str(root),
        source=WatcherSource.CODE,
        state=ControllerState.REFUSED,
        reason=ControllerReason.FULL_REINDEX_REQUIRED,
        scope=ControllerScope(generation=7),
        observed_at=10.0,
        next_decision_at=None,
        freshness_deadline=40.0,
        job_id=job_id,
    )
    expected = controller_snapshot_envelope(snapshot)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=lambda: 20.0)
    scheduler.register(
        WatcherController(snapshot, monotonic=lambda: 20.0, wall_clock=lambda: 20.0),
        reevaluate=lambda: None,
        admit=lambda _selection: None,
    )
    _watcher._watcher_scheduler = scheduler
    _watcher._watcher_scheduler_task = None
    registry = ServiceRegistry()
    app = create_http_app(
        ServerRouteRuntime(token="surface-token", registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(app) as client:
        yield client, registry, root, expected, job_id
    jobs.reset()
    _watcher._watcher_scheduler = previous_scheduler
    _watcher._watcher_scheduler_task = previous_task


def test_service_watcher_and_job_surfaces_publish_identical_controller_values(
    controller_surfaces: tuple[
        TestClient, ServiceRegistry, Path, dict[str, object], str
    ],
) -> None:
    client, registry, root, expected, job_id = controller_surfaces
    headers = {"Authorization": "Bearer surface-token"}

    service_controller = get_service_state(root, registry=registry)["watcher"][
        "controllers"
    ][0]
    watcher = client.get(
        "/watcher",
        params={"root": str(root), "source": "code", "state": "refused", "limit": 1},
        headers=headers,
    ).json()
    detail = client.get(f"/jobs/{job_id}", headers=headers).json()["job"]
    listing = client.get("/jobs", headers=headers).json()["jobs"]
    listed = next(item for item in listing if item["id"] == job_id)

    assert service_controller == expected
    assert watcher["controllers"] == [expected]
    assert detail["controller"] == expected
    assert listed["controller"] == expected
    assert watcher["controllers_total"] == 1
    assert watcher["controllers_truncated"] is False
    assert expected["reason"] == "full_reindex_required"
    assert expected["remediation"] == (
        "Inspect the refusal reason and request an explicit rebuild."
    )


@pytest.mark.parametrize(
    "adapter",
    [
        _admin_client.get_watcher_state,
        _transport._resolve_admin_call,
    ],
)
def test_client_adapters_do_not_recompute_controller_authority(
    adapter: Callable[..., object],
) -> None:
    """Guard thin client seams against acquiring controller arithmetic."""
    source = inspect.getsource(adapter)
    tree = ast.parse(source)
    forbidden_names = {
        "ControllerReason",
        "ControllerState",
        "datetime",
        "monotonic",
        "time",
        "timedelta",
    }
    loaded_names = {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load)
    }
    assert loaded_names.isdisjoint(forbidden_names)
    assert "oldest_age_seconds" not in source
    assert "next_decision_at" not in source
    assert "freshness_deadline" not in source
