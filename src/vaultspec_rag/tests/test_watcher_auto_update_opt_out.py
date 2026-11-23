"""An operator's per-root update stop holds until the explicit start verb.

Search, reindex and enrolment all start a root's watcher implicitly through
one function. These tests drive that function and the real HTTP routes over
an in-process ASGI transport, with the opt-out store in a temp status dir.
No GPU, no store, no project slot is opened: every path asserted here refuses
before the cold warm.

MUTATION PROOF, each run as one uninterrupted break, run, restore, run:

- Removing the opt-out check from ``_ensure_watcher_soon`` fails
  ``test_implicit_enrolment_never_restarts_a_stopped_root`` on its
  no-deferred-start assertion.
- Removing the opt-out refusal from ``reconfigure_watcher_route`` fails
  ``test_timing_change_does_not_start_a_stopped_root`` on its
  ``disabled_by_operator`` status assertion.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from .. import server, watcher_intent
from ..config._types import EnvVar
from ..server import _watcher as watcher_lifecycle
from ..service import ServiceRegistry
from ..watcher_intent import (
    AutoUpdateState,
    auto_update_state,
    auto_update_store_path,
    disable_auto_update,
    load_auto_update_store,
)
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit, pytest.mark.usefixtures("isolated_status_dir")]

_TOKEN = "test-token-auto-update-opt-out"
_PORT = 8765
_DRAIN_TIMEOUT_SECONDS = 10.0


@pytest.fixture
def watching_service(isolated_status_dir: Path) -> Iterator[None]:
    del isolated_status_dir
    with managed_env(**{EnvVar.WATCH_ENABLED.value: "true"}):
        yield


@pytest.fixture
def pull_only_service(isolated_status_dir: Path) -> Iterator[None]:
    del isolated_status_dir
    with managed_env(**{EnvVar.WATCH_ENABLED.value: "false"}):
        yield


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from ..server import ServerRouteRuntime, create_http_app

    registry = ServiceRegistry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_http_app(
                ServerRouteRuntime(token=_TOKEN, registry=registry, port=_PORT),
                lifespan=None,
            ),
            raise_app_exceptions=False,
        ),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as http_client:
        yield http_client
    registry.close_all()


def _project(tmp_path: Path) -> Path:
    root = (tmp_path / "project").resolve()
    root.mkdir()
    return root


async def _assert_no_implicit_start(root: Path) -> None:
    registry = ServiceRegistry()
    try:
        server._ensure_watcher_soon(root, registry)
        assert root not in watcher_lifecycle._deferred_watcher_roots
        assert root not in server._watcher_tasks
    finally:
        server._stop_watcher(root)
        assert await server._wait_for_watcher_cleanup(
            root, timeout_seconds=_DRAIN_TIMEOUT_SECONDS
        )
        registry.close_all()


@pytest.mark.usefixtures("watching_service")
async def test_implicit_enrolment_never_restarts_a_stopped_root(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = _project(tmp_path)
    response = await client.post("/watcher/stop", json={"root": str(root)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["stopped"] is False
    assert payload["status"] == "already_stopped"
    assert payload["auto_update"] == "disabled"
    assert payload["start_command"].startswith("vaultspec-rag server updates start ")
    assert payload["start_command"].endswith(f" --port {_PORT}")
    await _assert_no_implicit_start(root)
    # A restart reloads the copy from disk; the stop is still in force.
    watcher_intent._snapshot = None
    await _assert_no_implicit_start(root)


@pytest.mark.usefixtures("pull_only_service")
async def test_only_the_start_verb_clears_the_stop(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = _project(tmp_path)
    assert (await client.post("/watcher/stop", json={"root": str(root)})).is_success
    response = await client.post("/watcher/start", json={"root": str(root)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["auto_update"] == "enabled"
    # watch_enabled=false still wins over a cleared stop.
    assert payload["started"] is False
    assert payload["status"] == "disabled"
    assert auto_update_state(root) is AutoUpdateState.ENABLED


@pytest.mark.usefixtures("watching_service")
async def test_timing_change_does_not_start_a_stopped_root(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = _project(tmp_path)
    disable_auto_update(root, initiator="cli")
    response = await client.post(
        "/watcher/reconfigure", json={"root": str(root), "debounce_ms": 500}
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "disabled_by_operator"
    assert payload["restarted"] is False
    assert payload["auto_update"] == "disabled"
    assert "server updates start" in payload["start_command"]
    assert root not in watcher_lifecycle._watcher_starting_generations
    assert root not in server._watcher_tasks


@pytest.mark.usefixtures("watching_service")
async def test_unreadable_store_starts_nothing_and_refuses_both_verbs(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = _project(tmp_path)
    path = auto_update_store_path()
    path.write_bytes(b"{not json")
    assert load_auto_update_store() is AutoUpdateState.UNVERIFIABLE
    await _assert_no_implicit_start(root)
    for verb in ("stop", "start"):
        response = await client.post(f"/watcher/{verb}", json={"root": str(root)})
        assert response.status_code == 409
        payload = response.json()
        assert payload["ok"] is False
        assert payload["error"] == "auto_update_store_unverifiable"
        assert payload["store"] == str(path)
    assert path.read_bytes() == b"{not json"
    state = (await client.get("/watcher", params={"project_root": str(root)})).json()
    assert state["auto_update"] == "unverifiable"
    assert state["auto_update_store"]["status"] == "unverifiable"
    assert state["auto_update_store"]["path"] == str(path)


@pytest.mark.usefixtures("pull_only_service")
async def test_state_lists_stopped_roots_filtered_by_root_and_bounded(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    first = (tmp_path / "first").resolve()
    second = (tmp_path / "second").resolve()
    for root in (first, second):
        root.mkdir()
        disable_auto_update(root, initiator="cli")
    everything = (await client.get("/watcher", params={"limit": 1})).json()
    assert everything["auto_update_disabled_total"] == 2
    assert len(everything["auto_update_disabled"]) == 1
    assert everything["auto_update_store"]["status"] == "ok"
    one = (await client.get("/watcher", params={"project_root": str(second)})).json()
    assert [entry["root"] for entry in one["auto_update_disabled"]] == [str(second)]
    assert one["auto_update"] == "disabled"


@pytest.mark.usefixtures("pull_only_service")
async def test_prune_and_root_deletion_keep_the_stop(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = _project(tmp_path)
    assert (await client.post("/watcher/stop", json={"root": str(root)})).is_success
    root.rmdir()
    assert (await client.post("/watcher/prune", json={})).is_success
    root.mkdir()
    assert auto_update_state(root) is AutoUpdateState.DISABLED


@pytest.mark.usefixtures("watching_service")
async def test_enrolment_honours_the_stop_and_never_sets_one(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    stopped = _project(tmp_path)
    disable_auto_update(stopped, initiator="cli")
    response = await client.post("/repositories/enroll", json={"root": str(stopped)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["watcher_status"] == "disabled_by_operator"
    assert payload["auto_update"] == "disabled"
    assert "server updates start" in payload["start_command"]
    assert stopped not in watcher_lifecycle._deferred_watcher_roots

    unwatched = (tmp_path / "unwatched").resolve()
    unwatched.mkdir()
    response = await client.post(
        "/repositories/enroll", json={"root": str(unwatched), "watch": False}
    )
    assert response.json()["watcher_status"] == "disabled"
    assert auto_update_state(unwatched) is AutoUpdateState.ENABLED
