"""Real lifespan storage-task scheduling without starting storage or GPU work."""

from __future__ import annotations

import asyncio
import inspect
from typing import TYPE_CHECKING

import pytest

from .. import jobs
from .._machine_lock import release_machine_lock_lease
from ..config._settings import get_config
from ..config._types import EnvVar
from ..server import ServerRouteRuntime
from ..server._lifecycle import _DiscoveryPublisher
from ..server._lifespan import (
    _claim_machine_singleton,
    _start_components,
    _start_storage_tasks,
)
from ..service import ServiceRegistry
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Collection

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_singleton_dirs")]


def _task_names(tasks: Collection[asyncio.Task[None]]) -> set[str]:
    names: set[str] = set()
    for task in tasks:
        coroutine = task.get_coro()
        assert inspect.iscoroutine(coroutine)
        names.add(coroutine.cr_code.co_name)
    return names


@pytest.mark.parametrize(
    ("autoprune", "reconcile"),
    [
        pytest.param(False, True, id="reconcile-only"),
        pytest.param(True, False, id="prune-only"),
        pytest.param(True, True, id="both"),
        pytest.param(False, False, id="neither"),
    ],
)
@pytest.mark.parametrize(
    ("server_mode", "local_only", "storage_tasks"),
    [
        pytest.param(True, False, True, id="server"),
        pytest.param(True, True, False, id="local-only"),
        pytest.param(False, False, False, id="server-disabled"),
    ],
)
async def test_lifespan_schedules_independently_enabled_storage_maintenance(
    autoprune: bool,
    reconcile: bool,
    server_mode: bool,
    local_only: bool,
    storage_tasks: bool,
) -> None:
    # Mutation: gating task creation on stage flags must fail for a server
    # starting with both disabled; enable checks belong to each real tick.
    with managed_env(
        **{
            EnvVar.QDRANT_SERVER.value: "1" if server_mode else "0",
            EnvVar.LOCAL_ONLY.value: "1" if local_only else "0",
            EnvVar.STORAGE_AUTOPRUNE.value: "1" if autoprune else "0",
            EnvVar.STORAGE_RECONCILE.value: "1" if reconcile else "0",
        }
    ):
        tasks = _start_storage_tasks(get_config())
        try:
            names = _task_names(tasks)
            assert ("_maintenance_loop" in names) is storage_tasks, (
                "server lifespan must retain runtime maintenance scheduling"
            )
            assert ("_survey_warmup_task" in names) is storage_tasks
            assert len(tasks) == len(names)
        finally:
            # Cancel before yielding so neither the warmer nor a maintenance
            # cycle opens a backend. These are the production coroutines.
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert all(task.cancelled() for task in tasks)


async def test_component_startup_includes_storage_tasks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Only model loading is replaced at the external accelerator seam. The
    # startup entry, registry, discovery publisher, jobs and tasks are real.
    # Mutation: omitting the production scheduler call must fail this assertion.
    registry = ServiceRegistry()

    def model_loaded() -> None:
        pass

    monkeypatch.setattr(registry, "load_model", model_loaded)
    with managed_env(
        **{
            EnvVar.QDRANT_SERVER.value: "1",
            EnvVar.LOCAL_ONLY.value: "0",
            EnvVar.QDRANT_URL.value: "http://127.0.0.1:notaport",
            EnvVar.RERANKER_ENABLED.value: "0",
            EnvVar.STORAGE_AUTOPRUNE.value: "0",
            EnvVar.STORAGE_RECONCILE.value: "1",
        }
    ):
        lease = _claim_machine_singleton()
        publisher = _DiscoveryPublisher(
            ServerRouteRuntime(
                token="storage-task-startup-token", registry=registry, port=8766
            ),
            lease,
        )
        tasks: list[asyncio.Task[None]] = []
        try:
            tasks = await _start_components(publisher, registry)
            names = _task_names(tasks)
            assert "_maintenance_loop" in names, (
                "component startup must return its storage maintenance task"
            )
            assert "_survey_warmup_task" in names
            assert "_heartbeat_loop" in names
            assert "_borrower_lease_recovery_loop" in names
        finally:
            publisher.quiesce()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            try:
                registry.readiness_registry.close()
                publisher.cleanup()
            finally:
                release_machine_lock_lease(lease)
        assert all(task.done() for task in tasks)


async def test_running_maintenance_honors_disabled_then_enabled_stages() -> None:
    jobs.reset()
    with managed_env(
        **{
            EnvVar.QDRANT_SERVER.value: "1",
            EnvVar.LOCAL_ONLY.value: "0",
            EnvVar.QDRANT_URL.value: "http://127.0.0.1:notaport",
            EnvVar.STORAGE_AUTOPRUNE.value: "0",
            EnvVar.STORAGE_RECONCILE.value: "0",
            EnvVar.STORAGE_AUTOPRUNE_INTERVAL_MINUTES.value: "0.001",
        }
    ):
        tasks = _start_storage_tasks(get_config())
        maintenance_tasks = [
            task for task in tasks if "_maintenance_loop" in _task_names([task])
        ]
        try:
            assert len(maintenance_tasks) == 1, (
                "disabled server stages must retain a maintenance loop for re-enable"
            )
            for task in tasks:
                if task not in maintenance_tasks:
                    task.cancel()
            # The real loop has a one-second minimum sleep. Its disabled tick
            # must return before creating a job or constructing the backend.
            await asyncio.sleep(1.2)
            assert not jobs.snapshot(), "disabled stages must perform no maintenance"
            with managed_env(**{EnvVar.STORAGE_RECONCILE.value: "1"}):
                async with asyncio.timeout(5.0):
                    while not any(
                        record.get("phase") == "error" for record in jobs.snapshot()
                    ):
                        await asyncio.sleep(0.02)
            # The enabled real tick reaches construction, where the malformed
            # isolated endpoint fails before opening any network connection.
            [record] = jobs.snapshot()
            assert "notaport" in str(record["result"])
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        assert all(task.done() for task in tasks)
