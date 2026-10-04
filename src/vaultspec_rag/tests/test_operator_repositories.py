"""Repository inventory through real files, Git worktrees and production routes."""

from __future__ import annotations

import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, cast

import pytest
from starlette.testclient import TestClient

from ..config._types import EnvVar
from ..server._main import create_http_app
from ..server._routes_operator import repository_inventory
from ..server._runtime import ServerRouteRuntime, get_app_runtime
from ..service import ServiceRegistry
from ..storage_manifest import load_manifest, record_root
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from starlette.applications import Starlette

pytestmark = [pytest.mark.unit]
_TOKEN = "repository-tests"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}


@pytest.fixture
def client(isolated_status_dir: Path) -> Iterator[TestClient]:
    del isolated_status_dir
    with managed_env(**{EnvVar.WATCH_ENABLED.value: "false"}):
        registry = ServiceRegistry()
        app = create_http_app(ServerRouteRuntime(_TOKEN, registry, 8765), None)
        with TestClient(app, base_url="http://127.0.0.1") as http:
            yield http
        registry.close_all()


def test_enrollment_persists_and_repeated_request_preserves_index_stamp(
    client: TestClient, tmp_path: Path
) -> None:
    root = tmp_path / "project"
    root.mkdir()
    response = client.post(
        "/repositories/enroll", json={"root": str(root)}, headers=_HEADERS
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "enrolled"
    assert payload["watcher_status"] == "disabled"
    entry = load_manifest()[payload["prefix"]]
    assert entry.root == str(root.resolve())
    record_root(root, backend=entry.backend, last_indexed="2026-10-01T09:00:00Z")
    repeated = client.post(
        "/repositories/enroll",
        json={"root": str(root), "watch": False},
        headers=_HEADERS,
    )
    assert repeated.status_code == 200
    assert repeated.json()["status"] == "already_enrolled"
    assert load_manifest()[entry.prefix].last_indexed == "2026-10-01T09:00:00Z"
    inventory = client.get("/repositories", headers=_HEADERS).json()
    assert inventory["total"] == 1
    assert inventory["repositories"][0]["enrolled"] is True
    assert inventory["repositories"][0]["resident"] is None


@pytest.mark.parametrize(
    "payload",
    [{}, {"root": ""}, {"root": 42}, []],
    ids=["missing-root", "empty-root", "numeric-root", "array-body"],
)
def test_enrollment_validation_precedes_manifest_write(
    client: TestClient, payload: object
) -> None:
    # Proof: accepting fallback roots/objects returned 200; restoration passed.
    response = client.post("/repositories/enroll", json=payload, headers=_HEADERS)
    assert response.status_code == 400
    assert response.json()["error"] == "bad_request"
    assert load_manifest() == {}


def test_enrollment_requires_boolean_watch(client: TestClient, tmp_path: Path) -> None:
    # Proof: bypassing the boolean guard returned 200; restoration passed.
    response = client.post(
        "/repositories/enroll",
        json={"root": str(tmp_path), "watch": "yes"},
        headers=_HEADERS,
    )
    assert response.status_code == 400
    assert response.json()["message"] == "watch must be a boolean."
    assert load_manifest() == {}


def test_enrollment_rejects_missing_root_and_malformed_json(
    client: TestClient, tmp_path: Path
) -> None:
    # Proof: bypassing the directory check returned 200; restoring it passed.
    missing = client.post(
        "/repositories/enroll",
        json={"root": str(tmp_path / "absent")},
        headers=_HEADERS,
    )
    assert missing.status_code == 400
    assert missing.json()["message"] == "root must name an existing directory."
    malformed = client.post("/repositories/enroll", content="{", headers=_HEADERS)
    assert malformed.status_code == 400
    assert load_manifest() == {}


def test_repository_routes_authenticate_before_inventory_or_enrollment(
    client: TestClient, tmp_path: Path
) -> None:
    # Proof: bypassing the token check returned 200; restoring it passed.
    assert client.get("/repositories").status_code == 401
    assert (
        client.post("/repositories/enroll", json={"root": str(tmp_path)}).status_code
        == 401
    )
    assert load_manifest() == {}


def test_stopping_registry_refuses_enrollment_before_persistence(
    client: TestClient, tmp_path: Path
) -> None:
    # Proof: bypassing the shutdown check returned 200; restoration passed.
    get_app_runtime(cast("Starlette", client.app)).registry.close_all()
    response = client.post(
        "/repositories/enroll", json={"root": str(tmp_path)}, headers=_HEADERS
    )
    assert response.status_code == 503
    assert response.json()["error"] == "service_stopping"
    assert load_manifest() == {}


@pytest.mark.parametrize("payload", [{}, {"root": ""}, {"root": 42}, []])
def test_eviction_validates_before_registry_access(
    client: TestClient, payload: object
) -> None:
    # Proof: fallback roots/objects returned 200; validation restored passed.
    response = client.post("/projects/evict", json=payload, headers=_HEADERS)
    assert response.status_code == 400
    assert response.json()["error"] == "bad_request"


def _wait_for_eviction_stack() -> None:
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        for frame in sys._current_frames().values():
            while frame is not None:
                if (
                    frame.f_code.co_name == "try_evict"
                    and frame.f_globals["__name__"] == "vaultspec_rag._service_eviction"
                ):
                    return
                frame = frame.f_back
        time.sleep(0.01)
    pytest.fail("The real eviction did not reach its registry lock.")


def test_eviction_lock_wait_keeps_other_routes_responsive(
    client: TestClient, tmp_path: Path
) -> None:
    registry = get_app_runtime(cast("Starlette", client.app)).registry
    held = threading.Event()
    release = threading.Event()

    def hold_root() -> None:
        with registry._root_store_guard(tmp_path.resolve()):
            held.set()
            release.wait(timeout=5)

    owner = threading.Thread(target=hold_root)
    owner.start()
    assert held.wait(timeout=2)
    with ThreadPoolExecutor(max_workers=1) as requests:
        eviction = requests.submit(
            client.post,
            "/projects/evict",
            json={"root": str(tmp_path)},
            headers=_HEADERS,
        )
        timer: threading.Timer | None = None
        try:
            _wait_for_eviction_stack()
            timer = threading.Timer(2, release.set)
            timer.start()
            response = client.get("/repositories", headers=_HEADERS)
            assert response.status_code == 200
            # Proof: inline eviction failed here; worker dispatch restored passed.
            assert release.is_set() is False, "Eviction blocked the daemon event loop."
        finally:
            if timer is not None:
                timer.cancel()
            release.set()
            owner.join(timeout=2)
        assert eviction.result(timeout=2).json()["reason"] == "not_found"
    assert not owner.is_alive()


def test_inventory_limit_filter_and_missing_measurements(
    client: TestClient, tmp_path: Path
) -> None:
    roots = [tmp_path / name for name in ("a", "b", "c")]
    for root in roots:
        root.mkdir()
        record_root(root, backend="server")
    payload = client.get("/repositories?limit=2", headers=_HEADERS).json()
    assert payload["returned"] == 2
    assert payload["total"] == 3
    assert payload["truncated"] is True
    assert payload["seats"]["projects"]["used"] == 0
    assert "search" in payload["seats"]
    filtered = client.get(
        "/repositories", params={"root": str(roots[1])}, headers=_HEADERS
    ).json()
    assert [row["root"] for row in filtered["repositories"]] == [
        str(roots[1].resolve())
    ]
    assert client.get("/repositories?root=", headers=_HEADERS).status_code == 400
    # Proof: removing the clamp returned 9000; restoring it passed.
    assert (
        client.get("/repositories?limit=9000", headers=_HEADERS).json()["limit"] == 1000
    )


def _git(*arguments: str, root: Path) -> None:
    subprocess.run(
        ["git", "-C", str(root), *arguments],
        check=True,
        capture_output=True,
        timeout=10,
    )


def test_real_git_worktrees_are_grouped_without_implicitly_enrolling(
    client: TestClient, tmp_path: Path
) -> None:
    primary = tmp_path / "repo"
    primary.mkdir()
    _git("init", root=primary)
    _git(
        "-c",
        "user.name=Inventory Test",
        "-c",
        "user.email=inventory@example.invalid",
        "commit",
        "--allow-empty",
        "-m",
        "Initial",
        root=primary,
    )
    linked = tmp_path / "linked"
    _git("worktree", "add", "-b", "linked", str(linked), root=primary)
    record_root(linked, backend="server")
    response = client.get(
        "/repositories", params={"root": str(primary)}, headers=_HEADERS
    )
    assert response.status_code == 200
    rows = {row["root"]: row for row in response.json()["repositories"]}
    assert set(rows) == {str(primary.resolve()), str(linked.resolve())}
    assert rows[str(primary.resolve())]["enrolled"] is False
    assert rows[str(primary.resolve())]["is_worktree"] is False
    assert rows[str(linked.resolve())]["is_worktree"] is True
    assert rows[str(linked.resolve())]["repository_root"] == str(primary.resolve())
    assert len(load_manifest()) == 1


def test_inventory_reports_vanished_enrolled_root(
    isolated_status_dir: Path, tmp_path: Path
) -> None:
    del isolated_status_dir
    root = tmp_path / "removed-worktree"
    root.mkdir()
    record_root(root, backend="server")
    root.rmdir()
    registry = ServiceRegistry()
    payload = repository_inventory(registry, root=None, limit=200)
    rows = cast("list[dict[str, object]]", payload["repositories"])
    assert rows[0]["status"] == "orphaned"
    assert rows[0]["last_indexed"] is None
    registry.close_all()
