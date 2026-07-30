"""A start request reports the state the root is in, not the one it intends.

Starting automatic updates for a root whose previous watcher is still draining
records the request and honours it later. The honest answer at that moment is
"queued", not "started": the drain runs for as long as the job-shutdown bound
allows, and a caller told the watcher was back would leave that project
unindexed for the whole window without knowing it.

The drain here is the production one - ``_stop_watcher`` moves the root into it
and ``_drain_watcher`` joins it. Only the intake coroutine belongs to the test:
the lifecycle owns intake as an opaque ``asyncio.Task`` and never looks inside
it, so a task the test releases turns the drain window into a gate it opens
instead of a race against a real indexing run. No GPU, no store, no model.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, cast

import httpx
import pytest

from .. import server
from ..config._settings import get_config, reset_config
from ..server import WatcherStartOutcome
from ..server import _watcher as watcher_lifecycle

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_TOKEN = "test-token-watcher-start"

#: Bounds both the production drain and the test's join on it. Every wait in
#: this module is gated on an event the test sets, so the bound is only there
#: to fail a wedged drain instead of hanging the suite.
_DRAIN_TIMEOUT_SECONDS = 10.0


@pytest.fixture
def watching_service() -> Iterator[None]:
    """Enable watching and keep the drain bound short for the test."""
    get_config(
        {
            "watch_enabled": True,
            "job_shutdown_timeout_seconds": _DRAIN_TIMEOUT_SECONDS,
        }
    )
    try:
        yield
    finally:
        reset_config()


@pytest.fixture
async def watcher_client() -> AsyncIterator[httpx.AsyncClient]:
    """Drive the real watcher routes on this test's own event loop.

    The routes must run on the loop the drain lives on, so the ASGI transport
    is used in-process rather than a thread-portal test client.
    """
    from ..server import ServerRouteRuntime, create_http_app
    from ..service import ServiceRegistry

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_http_app(
                ServerRouteRuntime(
                    token=_TOKEN,
                    registry=ServiceRegistry(),
                    port=8765,
                ),
                lifespan=None,
            )
        ),
        base_url="http://service",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as client:
        yield client


@contextlib.asynccontextmanager
async def _stop_still_draining(root: Path) -> AsyncGenerator[None]:
    """Hold *root* in the state an unfinished stop leaves behind."""
    release = asyncio.Event()

    async def _intake() -> None:
        await release.wait()

    intake = asyncio.create_task(_intake())
    with server._watcher_lock:
        server._watcher_tasks[root] = intake
        server._watcher_stops[root] = asyncio.Event()
    server._stop_watcher(root)
    assert root in watcher_lifecycle._watcher_drains
    assert root not in server._watcher_tasks
    try:
        yield
    finally:
        # Drop whatever restart the body queued, then let the old intake go so
        # the production drain converges and clears the root.
        server._stop_watcher(root)
        release.set()
        assert await server._wait_for_watcher_cleanup(
            root,
            timeout_seconds=_DRAIN_TIMEOUT_SECONDS,
        )
        assert root not in watcher_lifecycle._watcher_drains
        assert root not in server._watcher_tasks


async def _post(
    client: httpx.AsyncClient,
    path: str,
    body: dict[str, object],
) -> dict[str, object]:
    response = await client.post(path, json=body)
    assert response.status_code == 200
    return cast("dict[str, object]", response.json())


@pytest.mark.usefixtures("watching_service")
async def test_start_behind_a_draining_stop_is_not_reported_as_running(
    tmp_path: Path,
) -> None:
    """The reported bug: start answers True while nothing is watching.

    Mutation this catches: returning ``ALREADY_RUNNING`` (or any running
    outcome) from ``_ensure_watcher``'s ``_watcher_drains`` branch. The
    ``watching`` sample is the ground truth the outcome is checked against -
    no watcher task exists for the root at the moment the answer is given.
    """
    root = tmp_path.resolve()
    async with _stop_still_draining(root):
        outcome = server._ensure_watcher(root)
        watching = root in server._watcher_tasks

    assert watching is False
    assert outcome is WatcherStartOutcome.QUEUED_BEHIND_DRAIN
    assert outcome.running is False
    assert outcome.pending is True


@pytest.mark.usefixtures("watching_service")
async def test_start_route_behind_a_draining_stop_reports_the_queue(
    tmp_path: Path,
    watcher_client: httpx.AsyncClient,
) -> None:
    """The HTTP contract: ``started`` means watching, never "will watch"."""
    root = tmp_path.resolve()
    async with _stop_still_draining(root):
        payload = await _post(watcher_client, "/watcher/start", {"root": str(root)})
        watching = root in server._watcher_tasks

    assert watching is False
    assert payload["started"] is False
    assert payload["status"] == "queued_behind_drain"
    assert payload["watch_enabled"] is True


@pytest.mark.usefixtures("watching_service")
async def test_reconfigure_route_behind_a_draining_stop_reports_the_queue(
    tmp_path: Path,
    watcher_client: httpx.AsyncClient,
) -> None:
    """Reconfigure stops first, so it queues behind any drain already open."""
    root = tmp_path.resolve()
    async with _stop_still_draining(root):
        payload = await _post(
            watcher_client,
            "/watcher/reconfigure",
            {"root": str(root), "debounce_ms": 250, "cooldown_s": 3.0},
        )
        watching = root in server._watcher_tasks

    assert watching is False
    assert payload["restarted"] is False
    assert payload["status"] == "queued_behind_drain"
    assert payload["debounce_ms"] == 250


async def test_start_route_with_watching_disabled_reports_disabled(
    tmp_path: Path,
    watcher_client: httpx.AsyncClient,
) -> None:
    """Watching off is a state that will never be reached, not a success."""
    get_config({"watch_enabled": False})
    try:
        root = tmp_path.resolve()
        payload = await _post(watcher_client, "/watcher/start", {"root": str(root)})
    finally:
        reset_config()

    assert payload["started"] is False
    assert payload["status"] == "disabled"
    assert payload["watch_enabled"] is False
    assert root not in server._watcher_tasks
