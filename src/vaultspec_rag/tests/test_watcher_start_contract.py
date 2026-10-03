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
import json
import os
from typing import TYPE_CHECKING, cast

import httpx
import pytest

from .. import server
from ..config._settings import get_config
from ..server import WatcherStartOutcome
from ..server import _watcher as watcher_lifecycle
from ._config_fixtures import reset_config

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
            ),
            raise_app_exceptions=False,
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


@pytest.mark.usefixtures("watching_service")
@pytest.mark.parametrize("verb", ["start", "stop", "reconfigure"])
@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"{", id="invalid-json"),
        pytest.param(b"\xff", id="invalid-encoding"),
        pytest.param(b"null", id="null-body"),
        pytest.param(b"[]", id="array-body"),
        pytest.param(b"true", id="boolean-body"),
        pytest.param(b"42", id="number-body"),
        pytest.param(b'"project"', id="string-body"),
        pytest.param(b"{}", id="missing-root"),
        pytest.param(b'{"project_root":"project"}', id="wrong-root-key"),
        pytest.param(b'{"root":null}', id="null-root"),
        pytest.param(b'{"root":true}', id="boolean-root"),
        pytest.param(b'{"root":42}', id="number-root"),
        pytest.param(b'{"root":[]}', id="array-root"),
        pytest.param(b'{"root":{}}', id="object-root"),
        pytest.param(b'{"root":""}', id="empty-root"),
        pytest.param(b'{"root":"  "}', id="blank-root"),
        pytest.param(b'{"root":"a\\u0000b"}', id="invalid-path"),
    ],
)
async def test_watcher_route_rejects_invalid_root_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    watcher_client: httpx.AsyncClient,
    verb: str,
    body: bytes,
) -> None:
    """Bypassing root validation must fail the typed 400 assertion."""
    root = tmp_path.resolve()
    monkeypatch.chdir(root)
    async with _stop_still_draining(root):
        generation = watcher_lifecycle._watcher_stop_generations[root]
        response = await watcher_client.post(
            f"/watcher/{verb}",
            content=body,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400, "invalid watcher input must be HTTP 400"
        assert response.json()["error"] == "bad_request"
        assert response.json()["ok"] is False
        assert watcher_lifecycle._watcher_stop_generations[root] == generation, (
            "invalid input must not dispatch watcher lifecycle"
        )
        assert root not in watcher_lifecycle._watcher_restarts


@pytest.mark.usefixtures("watching_service")
@pytest.mark.parametrize("verb", ["start", "stop", "reconfigure"])
async def test_watcher_route_rejects_root_resolution_error_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    watcher_client: httpx.AsyncClient,
    verb: str,
) -> None:
    """Filesystem resolution faults remain client-input failures."""
    from .. import _root_identity as root_identity

    root = tmp_path.resolve()
    async with _stop_still_draining(root):
        generation = watcher_lifecycle._watcher_stop_generations[root]
        with monkeypatch.context() as paths:

            def unavailable_path(_path: object) -> Path:
                raise OSError("root path cannot be resolved")

            paths.setattr(root_identity, "Path", unavailable_path)
            response = await watcher_client.post(
                f"/watcher/{verb}", json={"root": str(root)}
            )
        assert response.status_code == 400
        assert response.json()["error"] == "bad_request"
        assert response.json()["message"] == "root path cannot be resolved"
        assert watcher_lifecycle._watcher_stop_generations[root] == generation, (
            "invalid input must not dispatch watcher lifecycle"
        )
        assert root not in watcher_lifecycle._watcher_restarts


@pytest.mark.usefixtures("watching_service")
@pytest.mark.parametrize("verb", ["start", "stop", "reconfigure"])
@pytest.mark.parametrize("spelling", ["absolute", "relative", "dot", "case-slashes"])
async def test_watcher_route_valid_alias_dispatches_canonical_lifecycle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    watcher_client: httpx.AsyncClient,
    verb: str,
    spelling: str,
) -> None:
    """Validation retains the actual watcher owner's canonical root and outcome."""
    root = tmp_path / "MixedCaseRoot"
    root.mkdir()
    root = root.resolve()
    monkeypatch.chdir(root.parent)
    aliases = {
        "absolute": str(root),
        "relative": root.name,
        "dot": str(root / ".." / root.name),
        "case-slashes": str(root).upper().replace("\\", "/"),
    }
    if spelling == "case-slashes" and os.name != "nt":
        pytest.skip("Case and separator aliases follow Windows filesystem identity")
    async with _stop_still_draining(root):
        generation = watcher_lifecycle._watcher_stop_generations[root]
        payload = await _post(
            watcher_client,
            f"/watcher/{verb}",
            {"root": aliases[spelling], "debounce_ms": 250, "cooldown_s": 3},
        )
        from .._root_identity import canonical_root_key

        assert canonical_root_key(str(payload["root"])) == canonical_root_key(root)
        if verb == "stop":
            assert payload["stopped"] is False
            assert root not in watcher_lifecycle._watcher_restarts
        else:
            assert payload["status"] == "queued_behind_drain"
            restart = watcher_lifecycle._watcher_restarts[root]
            if verb == "reconfigure":
                assert payload["restarted"] is False
                assert payload["debounce_ms"] == restart.debounce_ms == 250
                assert payload["cooldown_s"] == restart.cooldown_s == 3.0
            else:
                assert payload["started"] is False
        assert watcher_lifecycle._watcher_stop_generations[root] == generation + (
            0 if verb == "start" else 1
        )


@pytest.mark.usefixtures("watching_service")
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("debounce_ms", -1),
        ("debounce_ms", True),
        ("debounce_ms", 1.5),
        ("debounce_ms", "invalid"),
        ("debounce_ms", {}),
        ("debounce_ms", 10**400),
        ("cooldown_s", -1),
        ("cooldown_s", True),
        ("cooldown_s", "invalid"),
        ("cooldown_s", []),
        ("cooldown_s", float("nan")),
        ("cooldown_s", float("inf")),
        ("cooldown_s", 10**400),
    ],
)
async def test_reconfigure_rejects_invalid_timing_before_stopping(
    tmp_path: Path,
    watcher_client: httpx.AsyncClient,
    key: str,
    value: object,
) -> None:
    """A bad override must not stop or replace a root before reporting rejection."""
    root = tmp_path.resolve()
    async with _stop_still_draining(root):
        generation = watcher_lifecycle._watcher_stop_generations[root]
        response = await watcher_client.post(
            "/watcher/reconfigure",
            content=json.dumps({"root": str(root), key: value}),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400, "invalid timing must be HTTP 400"
        assert response.json()["error"] == "bad_request"
        assert watcher_lifecycle._watcher_stop_generations[root] == generation, (
            "invalid timing must not stop the watcher"
        )
        assert root not in watcher_lifecycle._watcher_restarts


@pytest.mark.usefixtures("watching_service")
async def test_valid_stop_dispatches_active_watcher_cleanup(
    tmp_path: Path, watcher_client: httpx.AsyncClient
) -> None:
    """A validated stop actually disables intake and starts canonical cleanup."""
    root = tmp_path.resolve()
    release = asyncio.Event()

    async def intake() -> None:
        await release.wait()

    task = asyncio.create_task(intake())
    stopped = asyncio.Event()
    with server._watcher_lock:
        server._watcher_tasks[root] = task
        server._watcher_stops[root] = stopped
    try:
        payload = await _post(watcher_client, "/watcher/stop", {"root": str(root)})
        assert payload["stopped"] is True
        assert root not in server._watcher_tasks
        assert stopped.is_set()
        assert watcher_lifecycle._watcher_drains[root].intake_task is task
    finally:
        server._stop_watcher(root)
        release.set()
        assert await server._wait_for_watcher_cleanup(
            root, timeout_seconds=_DRAIN_TIMEOUT_SECONDS
        )


@pytest.mark.parametrize("verb", ["start", "stop", "reconfigure"])
async def test_watcher_authentication_precedes_body_validation(
    watcher_client: httpx.AsyncClient, verb: str
) -> None:
    response = await watcher_client.post(
        f"/watcher/{verb}", content=b"{", headers={"Authorization": "Bearer wrong"}
    )
    assert response.status_code == 401


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
    from ..service import ServiceRegistry

    async with _stop_still_draining(root):
        outcome = server._ensure_watcher(root, ServiceRegistry())
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
