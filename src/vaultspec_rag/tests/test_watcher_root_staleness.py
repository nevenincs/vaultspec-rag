"""A deleted watched root is retired once, refused clearly, and never re-armed.

Roots are routinely short-lived worktrees. When one is deleted while watched,
every controller, intake and search against it must stop treating it as a
project that only needs indexing: the controllers move to a terminal state
with one warning, stopping the watcher succeeds, searches answer ``410
root_missing`` instead of a retryable ``503``, and an operator can see and
prune the stale roots.

The lifecycle exercised here is the production one: the real scheduler, the
real stop and drain, the real HTTP routes over an in-process ASGI transport.
Only intake coroutines are owned by the tests, because the lifecycle treats
intake as an opaque task and a task the test releases turns the drain window
into a gate rather than a race against a real indexing run. No GPU, no store.

MUTATION PROOF, each run as one uninterrupted break, run, restore, run:

- Removing the missing-root sweep from ``_WatcherScheduler._run_cycle`` fails
  ``test_scheduler_retires_a_deleted_root_with_one_warning`` on its
  reevaluation-count assertion.
- Treating every failure as new in ``WatcherFailureLog.report`` fails
  ``test_identical_watcher_failures_are_logged_once_then_summarised`` on its
  single-ERROR assertion (50 errors logged instead of 1).
- Restoring ``logger.exception`` for a missing root in
  ``_wait_for_intake_release`` fails
  ``test_stopping_a_watcher_of_a_deleted_root_succeeds_without_error`` on its
  no-ERROR assertion.
- Removing the missing-root refusal from ``_ensure_watcher_soon`` fails
  ``test_requests_for_a_deleted_root_never_rearm_its_watcher`` on its
  no-deferred-start assertion.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import TYPE_CHECKING, cast

import httpx
import pytest

from .. import server
from .._job_errors import (
    FULL_REINDEX_REQUIRED_PHRASE,
    JobErrorKind,
    classify_error_text,
)
from .._publication_state import acquire_publication_snapshot
from .._root_identity import canonical_root_key
from .._root_presence import (
    clear_stale_watcher_root,
    record_stale_watcher_root,
    stale_watcher_roots,
)
from .._source_types import PublicSourceType
from ..config._settings import get_config
from ..indexer._publication_proof import ProofMissingError
from ..operator_state._service import DegradationReason
from ..server import WatcherStartOutcome
from ..server import _watcher as watcher_lifecycle
from ..server._lifespan import _stale_watcher_root_degradations
from ..server._routes_search import _search_response_status
from ..server._watcher import _WatcherScheduler
from ..service import ServiceRegistry
from ..watcher_controller import (
    ControllerReason,
    ControllerScope,
    ControllerSnapshot,
    ControllerState,
    WatcherController,
)
from ..watcher_retry import WatcherRetryStateError, WatcherSource
from ._config_fixtures import reset_config

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, AsyncIterator, Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_TOKEN = "test-token-root-staleness"
_DRAIN_TIMEOUT_SECONDS = 10.0


class _Clock:
    def __init__(self, now: float) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


def _controller(root: Path, source: WatcherSource, clock: _Clock) -> WatcherController:
    return WatcherController(
        ControllerSnapshot(
            canonical_root=canonical_root_key(root),
            source=source,
            state=ControllerState.IDLE,
            reason=ControllerReason.CONVERGED,
            scope=ControllerScope(generation=0),
            observed_at=clock.now,
        ),
        monotonic=clock,
        wall_clock=clock,
    )


@pytest.fixture(autouse=True)
def _forget_stale_roots() -> Iterator[None]:
    """Leave the service-wide stale-root record as each test found it."""
    yield
    for record in stale_watcher_roots():
        clear_stale_watcher_root(record.root)


@pytest.fixture
def watching_service() -> Iterator[None]:
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
async def client() -> AsyncIterator[httpx.AsyncClient]:
    """Drive the real routes on this test's own event loop."""
    from ..server import ServerRouteRuntime, create_http_app

    registry = ServiceRegistry()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=create_http_app(
                ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
                lifespan=None,
            ),
            raise_app_exceptions=False,
        ),
        base_url="http://127.0.0.1",
        headers={"Authorization": f"Bearer {_TOKEN}"},
    ) as http_client:
        yield http_client
    registry.close_all()


@contextlib.asynccontextmanager
async def _owned_intake(
    root: Path, *, fail: bool = False
) -> AsyncGenerator[asyncio.Event]:
    """Publish a watcher for *root* whose intake exits when released."""
    release = asyncio.Event()

    async def _intake() -> None:
        await release.wait()
        if fail:
            raise FileNotFoundError(f"watched root vanished: {root}")

    intake = asyncio.create_task(_intake())
    with server._watcher_lock:
        server._watcher_tasks[root] = intake
        server._watcher_stops[root] = asyncio.Event()
    try:
        yield release
    finally:
        server._stop_watcher(root)
        release.set()
        assert await server._wait_for_watcher_cleanup(
            root, timeout_seconds=_DRAIN_TIMEOUT_SECONDS
        )
        assert root not in server._watcher_tasks


def _records(caplog: pytest.LogCaptureFixture, level: int) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno == level]


async def test_scheduler_retires_a_deleted_root_with_one_warning(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = tmp_path / "worktree"
    root.mkdir()
    clock = _Clock(10.0)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    reevaluations: list[WatcherSource] = []
    controllers = [
        _controller(root, source, clock)
        for source in (WatcherSource.CODE, WatcherSource.VAULT)
    ]
    for controller in controllers:
        scheduler.register(
            controller,
            reevaluate=lambda source=controller.snapshot.source: reevaluations.append(
                source
            ),
            admit=lambda _selection: None,
        )
    await scheduler._run_cycle()
    assert len(reevaluations) == 2

    root.rmdir()
    caplog.set_level(logging.INFO, logger="vaultspec_rag.server")
    for _ in range(3):
        await scheduler._run_cycle()
    # The intake that owns the root re-registers it: still missing, still one
    # warning, because the root has not transitioned again.
    replacement = _controller(root, WatcherSource.CODE, clock)
    scheduler.register(
        replacement, reevaluate=lambda: None, admit=lambda _selection: None
    )
    await scheduler._run_cycle()

    assert len(reevaluations) == 2, "a missing root must not be reevaluated"
    for controller in (*controllers, replacement):
        assert controller.snapshot.state is ControllerState.STALE
        assert controller.snapshot.reason is ControllerReason.ROOT_MISSING
        assert controller.snapshot.remediation
    assert scheduler.empty
    warnings = _records(caplog, logging.WARNING)
    assert len(warnings) == 1, [record.getMessage() for record in warnings]
    assert "service.watcher event=root_missing" in warnings[0].getMessage()
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]
    transitions = [
        record
        for record in caplog.records
        if "service.watcher.controller event=transition" in record.getMessage()
        and "state=stale reason=root_missing" in record.getMessage()
    ]
    assert len(transitions) == 3
    stale = stale_watcher_roots()
    assert [record.root for record in stale] == [canonical_root_key(root)]
    assert stale[0].sources == ("code", "vault")


async def test_identical_watcher_failures_are_logged_once_then_summarised(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    clock = _Clock(10.0)
    scheduler = _WatcherScheduler(reevaluation_seconds=5.0, monotonic=clock)
    message = ["watcher retry state prepare failed for code.json"]

    def fail() -> None:
        raise WatcherRetryStateError(message[0])

    controller = _controller(tmp_path, WatcherSource.CODE, clock)
    scheduler.register(controller, reevaluate=fail, admit=lambda _selection: None)
    caplog.set_level(logging.INFO, logger="vaultspec_rag.server")

    for _ in range(50):
        await scheduler._run_cycle()
    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 1, "identical repeats must be suppressed"
    assert errors[0].exc_info is not None

    clock.now += 300.0
    await scheduler._run_cycle()
    errors = _records(caplog, logging.ERROR)
    assert len(errors) == 2
    assert "50 more times" in errors[1].getMessage()
    assert errors[1].exc_info is None

    message[0] = "watcher retry state lock failed for code.json.lock"
    await scheduler._run_cycle()
    assert len(_records(caplog, logging.ERROR)) == 3, "a new error is logged"

    for index in range(40):
        message[0] = f"distinct failure {index}"
        await scheduler._run_cycle()
    key = (controller.snapshot.canonical_root, controller.snapshot.source)
    remembered = scheduler._failures._seen[(key, "reevaluation")]
    assert len(remembered) <= 8, "memory is bounded"


@pytest.mark.usefixtures("watching_service")
async def test_stopping_a_watcher_of_a_deleted_root_succeeds_without_error(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = (tmp_path / "worktree").resolve()
    root.mkdir()
    caplog.set_level(logging.DEBUG, logger="vaultspec_rag.server")
    async with _owned_intake(root, fail=True) as release:
        root.rmdir()
        cleanup = server._stop_watcher(root)
        release.set()
        assert cleanup is not None
        assert await asyncio.wait_for(cleanup, _DRAIN_TIMEOUT_SECONDS) is True
    assert root not in watcher_lifecycle._watcher_drains
    assert not [record for record in caplog.records if record.levelno >= logging.ERROR]


@pytest.mark.usefixtures("watching_service")
async def test_requests_for_a_deleted_root_never_rearm_its_watcher(
    tmp_path: Path,
) -> None:
    root = (tmp_path / "deleted").resolve()
    registry = ServiceRegistry()
    try:
        server._ensure_watcher_soon(root, registry)
        assert root not in watcher_lifecycle._deferred_watcher_roots
        assert (
            server._ensure_watcher(root, registry) is WatcherStartOutcome.ROOT_MISSING
        )
        assert root not in watcher_lifecycle._watcher_starting_generations
        assert root not in server._watcher_tasks
    finally:
        server._stop_watcher(root)
        assert await server._wait_for_watcher_cleanup(
            root, timeout_seconds=_DRAIN_TIMEOUT_SECONDS
        )
        registry.close_all()


@pytest.mark.usefixtures("watching_service")
async def test_start_route_reports_a_missing_root(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = (tmp_path / "deleted").resolve()
    response = await client.post("/watcher/start", json={"root": str(root)})
    assert response.status_code == 200
    payload = response.json()
    assert payload["started"] is False
    assert payload["status"] == "root_missing"


async def test_search_against_a_deleted_root_is_gone_not_unavailable(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = (tmp_path / "deleted-worktree").resolve()
    get_config({"watch_enabled": True})
    try:
        response = await client.post(
            "/search",
            json={"query": "anything", "project_root": str(root)},
        )
    finally:
        reset_config()

    assert response.status_code == 410, response.text
    payload = cast("dict[str, object]", response.json())
    assert payload["error"] == "root_missing"
    assert payload["retryable"] is False
    assert "does not exist" in str(payload["message"])
    assert "server updates prune" in str(payload["remediation"])
    assert root not in watcher_lifecycle._deferred_watcher_roots
    assert root not in server._watcher_tasks
    assert _search_response_status(payload) == 410


async def test_reindex_against_a_deleted_root_is_refused_as_missing(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    root = (tmp_path / "deleted-worktree").resolve()
    response = await client.post(
        "/reindex",
        json={"project_root": str(root), "type": "vault", "authority": "publication"},
    )
    assert response.status_code == 410, response.text
    assert response.json()["error"] == "root_missing"


def test_missing_proof_of_a_deleted_root_does_not_ask_for_a_rebuild(
    tmp_path: Path,
) -> None:
    root = tmp_path / "deleted-worktree"
    with pytest.raises(ProofMissingError) as missing:
        acquire_publication_snapshot(root, PublicSourceType.VAULT)

    message = str(missing.value)
    assert "project root does not exist" in message
    assert FULL_REINDEX_REQUIRED_PHRASE not in message
    assert classify_error_text(message) is not JobErrorKind.FULL_REINDEX_REQUIRED


def test_health_reports_stale_roots_until_pruned_or_recovered(tmp_path: Path) -> None:
    gone = tmp_path / "gone"
    back = tmp_path / "back"
    assert _stale_watcher_root_degradations() == []

    assert record_stale_watcher_root(gone, ("code",))
    assert record_stale_watcher_root(back, ("vault",))
    assert not record_stale_watcher_root(gone, ("vault",)), "one transition only"
    degradations = _stale_watcher_root_degradations()
    assert [item.reason for item in degradations] == [
        DegradationReason.STALE_WATCHER_ROOTS
    ]
    assert str(gone) in degradations[0].detail
    assert "2 watched project root(s)" in degradations[0].detail

    back.mkdir()
    degradations = _stale_watcher_root_degradations()
    assert str(back) not in degradations[0].detail, "a recovered root clears"

    assert clear_stale_watcher_root(gone)
    assert _stale_watcher_root_degradations() == []


@pytest.mark.usefixtures("watching_service")
async def test_prune_route_stops_watchers_of_missing_roots(
    tmp_path: Path,
    client: httpx.AsyncClient,
) -> None:
    watched = (tmp_path / "watched").resolve()
    watched.mkdir()
    retired = (tmp_path / "retired").resolve()
    record_stale_watcher_root(retired, ("code",))

    async with _owned_intake(watched):
        watched.rmdir()
        listed = (await client.get("/watcher")).json()
        assert [entry["root"] for entry in listed["stale_roots"]] == [str(retired)]
        assert listed["stale_roots_total"] == 1

        preview = await client.post("/watcher/prune", json={"dry_run": True})
        assert preview.status_code == 200
        previewed = preview.json()
        assert previewed["status"] == "would_prune"
        assert previewed["count"] == 2
        assert {entry["root"] for entry in previewed["roots"]} == {
            str(watched),
            str(retired),
        }
        assert watched in server._watcher_tasks, "a dry run changes nothing"
        assert len(stale_watcher_roots()) == 1

        pruned = (await client.post("/watcher/prune", json={})).json()
        assert pruned["ok"] is True
        assert pruned["status"] == "pruned"
        assert pruned["count"] == 2
        assert watched not in server._watcher_tasks
        assert stale_watcher_roots() == ()

    again = await client.post("/watcher/prune", json={})
    assert again.status_code == 200
    assert again.json() == {
        "ok": True,
        "dry_run": False,
        "status": "nothing_to_prune",
        "count": 0,
        "roots": [],
    }
    assert (await client.get("/watcher")).json()["stale_roots"] == []


async def test_prune_route_rejects_a_non_boolean_dry_run(
    client: httpx.AsyncClient,
) -> None:
    response = await client.post("/watcher/prune", json={"dry_run": "yes"})
    assert response.status_code == 400
    assert response.json()["error"] == "bad_request"
