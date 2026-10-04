"""Real watcher policy, HTTP and scheduler proofs for equivalent root paths."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from httpx import ASGITransport, AsyncClient

from .. import server
from .._root_identity import canonical_root_key
from ..server import ServerRouteRuntime, create_http_app
from ..server import _watcher as watcher_service
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
from ..watcher_retry_policy import WatcherRetryPolicy

if TYPE_CHECKING:
    from ..watcher_admission import AdmissionSelection

pytestmark = pytest.mark.unit


def _policy_controller(root: Path, source: WatcherSource) -> WatcherController:
    policy = WatcherRetryPolicy.for_root(root, source, now=10.0)
    return WatcherController(
        ControllerSnapshot(
            canonical_root=policy.state.canonical_root,
            source=source,
            state=ControllerState.READY,
            reason=ControllerReason.QUIET_TREE_DEADLINE,
            scope=ControllerScope(generation=1),
            observed_at=10.0,
            next_decision_at=11.0,
            freshness_deadline=40.0,
        ),
        monotonic=lambda: 10.0,
        wall_clock=lambda: 10.0,
    )


def _alias(root: Path, spelling: str) -> str:
    if spelling == "relative":
        return root.name
    if spelling == "dot":
        return str(root / ".." / root.name)
    if spelling == "windows_case_slashes":
        if os.name != "nt":
            pytest.skip("Case and separator aliases follow Windows filesystem identity")
        return str(root).upper().replace("\\", "/")
    return str(root)


def test_policy_root_key_retains_persisted_platform_normalization(
    tmp_path: Path,
) -> None:
    root = tmp_path / "MixedCaseProject"
    root.mkdir()
    controller = _policy_controller(root, WatcherSource.CODE)
    assert controller.snapshot.canonical_root == os.path.normcase(str(root.resolve()))


@pytest.mark.parametrize("parameter", ["root", "project_root"])
@pytest.mark.parametrize(
    "spelling", ["absolute", "relative", "dot", "windows_case_slashes"]
)
async def test_http_root_aliases_select_all_real_policy_controllers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, spelling: str, parameter: str
) -> None:
    root = tmp_path / "MixedCaseProject"
    root.mkdir()
    monkeypatch.chdir(root.parent)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=lambda: 10.0)
    for source in WatcherSource:
        scheduler.register(
            _policy_controller(root, source),
            reevaluate=lambda: None,
            admit=lambda _selection: None,
        )
    scheduler.register(
        _policy_controller(tmp_path / "another", WatcherSource.CODE),
        reevaluate=lambda: None,
        admit=lambda _selection: None,
    )
    monkeypatch.setattr(watcher_service, "_watcher_scheduler", scheduler)
    task = asyncio.create_task(asyncio.sleep(0))
    monkeypatch.setattr(server, "_watcher_tasks", {root: task})
    app = create_http_app(
        ServerRouteRuntime(token="root-token", registry=ServiceRegistry(), port=8765),
        lifespan=None,
    )
    alias = _alias(root, spelling)
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get(
            "/watcher",
            params={parameter: alias},
            headers={"Authorization": "Bearer root-token"},
        )
    await task
    assert response.status_code == 200
    state = response.json()
    assert state["controllers_total"] == 3
    assert {item["root"] for item in state["controllers"]} == {canonical_root_key(root)}
    assert state["filters"]["root"] == alias
    if parameter == "project_root":
        assert state["running"] is True


async def test_unregister_alias_removes_all_sources_and_joins_active_callback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "MixedCaseProject"
    root.mkdir()
    monkeypatch.chdir(root.parent)
    entered = asyncio.Event()
    release = asyncio.Event()

    async def reevaluate() -> None:
        entered.set()
        await release.wait()

    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=lambda: 10.0)
    for source in WatcherSource:
        scheduler.register(
            _policy_controller(root, source),
            reevaluate=reevaluate,
            admit=lambda _selection: None,
        )
    scheduler.register(
        _policy_controller(tmp_path / "another", WatcherSource.CODE),
        reevaluate=lambda: None,
        admit=lambda _selection: None,
    )
    cycle = asyncio.create_task(scheduler._run_cycle())
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    alias = Path(
        _alias(root, "windows_case_slashes" if os.name == "nt" else "relative")
    )
    joined: asyncio.Task[bool] | None = None
    try:
        scheduler.unregister_root(alias)
        assert len(scheduler.snapshots()) == 1
        assert scheduler.snapshots()[0].canonical_root == canonical_root_key(
            tmp_path / "another"
        )
        joined = asyncio.create_task(scheduler.wait_root_released(alias, deadline=11.0))
        await asyncio.sleep(0)
        assert not joined.done(), (
            "Root join returned while its canonical callback was active"
        )
    finally:
        release.set()
        await cycle
        if joined is not None:
            await joined
    assert joined is not None
    assert joined.result() is True


async def test_alias_join_respects_active_callback_deadline(tmp_path: Path) -> None:
    root = tmp_path / "MixedCaseProject"
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=lambda: 10.0)
    controller = _policy_controller(root, WatcherSource.CODE)
    scheduler.register(
        controller, reevaluate=lambda: None, admit=lambda _selection: None
    )
    entered = asyncio.Event()
    release = asyncio.Event()

    async def admit(_selection: AdmissionSelection) -> None:
        entered.set()
        await release.wait()

    key = (controller.snapshot.canonical_root, controller.snapshot.source)
    active = asyncio.create_task(scheduler._invoke(key, admit, None))
    await asyncio.wait_for(entered.wait(), timeout=1.0)
    try:
        assert await scheduler.wait_root_released(root / ".", deadline=10.0) is False
    finally:
        release.set()
        await active


@pytest.mark.parametrize("parameter", ["root", "project_root", "both"])
async def test_invalid_root_query_is_an_actionable_bad_request(parameter: str) -> None:
    app = create_http_app(
        ServerRouteRuntime(token="root-token", registry=ServiceRegistry(), port=8765),
        lifespan=None,
    )
    parameters = (
        {"root": ".", "project_root": "a\0b"}
        if parameter == "both"
        else {parameter: "a\0b"}
    )
    async with AsyncClient(
        transport=ASGITransport(app), base_url="http://127.0.0.1"
    ) as client:
        response = await client.get(
            "/watcher",
            params=parameters,
            headers={"Authorization": "Bearer root-token"},
        )
    assert response.status_code == 400
    assert response.json()["error"] == "bad_request"
