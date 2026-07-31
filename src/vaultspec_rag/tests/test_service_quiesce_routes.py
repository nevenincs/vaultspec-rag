"""Loopback route coverage for acknowledged service quiesce."""

from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, NamedTuple, cast

import pytest
from starlette.testclient import TestClient

from ..job_manager.manager import JobManager
from ..job_manager.models import JobAttemptContext, JobExecutionResult
from ..job_models import (
    JobInitiator,
    JobMode,
    JobOperation,
    JobSnapshot,
    JobSource,
    JobSpec,
    JobState,
)
from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState, QuiesceTransition
from ._job_roots import _TEST_PROJECT_ROOT
from ._quiesce_helpers import QUIESCE_THREAD_TIMEOUT, wait_for_quiesce_state

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_TOKEN = "quiesce-route-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}
_ENVELOPE_KEYS = {
    "state",
    "admission_epoch",
    "admissions_open",
    "active_compute_tickets",
    "drain_complete",
    "vram_released",
    "safe_to_borrow_gpu",
    "pause_requested_at",
    "drain_acknowledged_at",
    "quiesced_at",
    "warming_started_at",
    "failure_reason",
}


class QuiesceRoutes(NamedTuple):
    """One live loopback client bound to the registry its routes drive."""

    client: TestClient
    registry: ServiceRegistry


@contextmanager
def _running_service_loop() -> Generator[asyncio.AbstractEventLoop]:
    """Run the recovery manager on its real adopted service loop."""
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    def run_loop() -> None:
        asyncio.set_event_loop(loop)
        ready.set()
        loop.run_forever()
        loop.close()

    owner = threading.Thread(target=run_loop, name="resume-route-recovery-loop")
    owner.start()
    if not ready.wait(timeout=QUIESCE_THREAD_TIMEOUT):
        raise AssertionError("the adopted recovery service loop did not start")
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        owner.join(timeout=QUIESCE_THREAD_TIMEOUT)
        assert not owner.is_alive(), "the adopted recovery service loop did not stop"


def _attach_durable_quiesced_job(
    registry: ServiceRegistry,
    state_path: Path,
) -> tuple[JobManager, str]:
    """Attach a real durable paused job to the registry route authority."""
    manager = JobManager(
        max_nonterminal=1,
        state_path=state_path,
        quiesce_controller=registry._quiesce_controller,
    )
    registry._job_manager = manager
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.CODE,
            _TEST_PROJECT_ROOT,
            JobMode.REBUILD,
        ),
        JobInitiator("test", "resume-route-recovery", _TEST_PROJECT_ROOT),
    )
    assert created.job is not None
    job_id = created.job.id
    assert (
        manager.defer_unstarted_for_quiesce(job_id).code
        == "quiesce_deferred_before_start"
    )
    assert registry.quiesce_resources(timeout_seconds=0).achieved
    return manager, job_id


def _assert_unpublished_resume_failure(payload: dict[str, object]) -> None:
    """Assert the canonical route evidence for durable recovery failure."""
    assert set(payload) == {
        "ok",
        "status",
        "quiesce",
        "error",
        "message",
        "retryable",
    }
    assert payload["ok"] is False
    assert payload["status"] == "resume_recovery_failed"
    assert payload["error"] == payload["status"]
    assert payload["retryable"] is True
    assert "job_resume_persistence_unpublished" in str(payload["message"])
    raw_quiesce = payload["quiesce"]
    assert isinstance(raw_quiesce, dict)
    # isinstance narrows an unparameterised builtin only to an unknown-keyed
    # mapping, so the key type has to be stated before any lookup reads.
    quiesce = cast("dict[str, object]", raw_quiesce)
    assert quiesce["state"] == "warming"
    assert quiesce["admissions_open"] is False
    assert quiesce["safe_to_borrow_gpu"] is False
    assert quiesce["failure_reason"] == "job_resume_persistence_unpublished"


def _assert_achieved_resume(payload: dict[str, object]) -> None:
    """Assert that a service-owned success carries no failure fields."""
    assert set(payload) == {"ok", "status", "quiesce"}
    assert payload["ok"] is True
    assert payload["status"] == "running"
    raw_quiesce = payload["quiesce"]
    assert isinstance(raw_quiesce, dict)
    quiesce = cast("dict[str, object]", raw_quiesce)
    assert quiesce["state"] == "running"
    assert quiesce["admissions_open"] is True
    assert quiesce["safe_to_borrow_gpu"] is False
    assert quiesce["failure_reason"] is None


@pytest.fixture
def quiesce_routes() -> Generator[QuiesceRoutes]:
    """Serve the real pause/resume routes over a real registry.

    Server exceptions are deliberately not re-raised into the test: uvicorn
    turns an escaping handler exception into a bare 500, and a lifecycle verb
    that lets one escape is precisely what these cases are asserting against.
    Re-raising here would hide that behind a test-only error.
    """
    registry = ServiceRegistry()
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield QuiesceRoutes(client, registry)


def test_pause_resume_routes_return_the_complete_controller_envelope(
    quiesce_routes: QuiesceRoutes,
) -> None:
    """A real registry exposes only achieved pause and resume lifecycle truth."""
    client = quiesce_routes.client
    unauthorized = client.post("/pause")
    assert unauthorized.status_code == 401

    paused = client.post("/pause", headers=_HEADERS)
    resumed = client.post("/resume", headers=_HEADERS)

    assert paused.status_code == 200
    assert resumed.status_code == 200
    pause_payload = paused.json()
    resume_payload = resumed.json()

    assert pause_payload["ok"] is True
    assert pause_payload["status"] == "quiesced"
    assert set(pause_payload["quiesce"]) == _ENVELOPE_KEYS
    assert pause_payload["quiesce"]["state"] == "quiesced"
    assert pause_payload["quiesce"]["safe_to_borrow_gpu"] is True
    assert pause_payload["quiesce"]["failure_reason"] is None
    assert "error" not in pause_payload
    assert "message" not in pause_payload
    assert "retryable" not in pause_payload

    assert resume_payload["ok"] is True
    assert resume_payload["status"] == "running"
    assert set(resume_payload["quiesce"]) == _ENVELOPE_KEYS
    assert resume_payload["quiesce"]["state"] == "running"
    assert resume_payload["quiesce"]["safe_to_borrow_gpu"] is False
    assert resume_payload["quiesce"]["failure_reason"] is None
    assert "error" not in resume_payload
    assert "message" not in resume_payload
    assert "retryable" not in resume_payload


def test_resume_releases_a_daemon_a_failed_pause_left_held(
    quiesce_routes: QuiesceRoutes,
) -> None:
    """The operator's own second command is what recovers a stranded pause."""
    client, registry = quiesce_routes
    stuck_ticket = registry.acquire_compute_ticket()
    try:
        timed_out = registry.quiesce_resources(timeout_seconds=0)
        assert timed_out.snapshot.state is QuiesceState.PAUSING
        assert timed_out.snapshot.failure_reason == "compute_ticket_drain_timed_out"

        resumed = client.post("/resume", headers=_HEADERS)
    finally:
        stuck_ticket.release()

    assert resumed.status_code == 200
    payload = resumed.json()
    assert payload["ok"] is True
    assert payload["status"] == "pause_aborted"
    assert payload["quiesce"]["state"] == "running"
    assert payload["quiesce"]["admissions_open"] is True
    assert payload["quiesce"]["failure_reason"] is None
    assert registry.quiesce_snapshot().state is QuiesceState.RUNNING


def test_resume_reports_unpublished_recovery_then_recovers_one_same_id_attempt(
    quiesce_routes: QuiesceRoutes,
    tmp_path: Path,
) -> None:
    """The authenticated route retains a failed recovery until one repair runs it.

    Making the failed-envelope ``retryable`` value false makes the named
    assertion fail, proving the route reports a recoverable service outcome.
    """
    client, registry = quiesce_routes
    state_path = tmp_path / "managed" / "jobs.json"
    manager, job_id = _attach_durable_quiesced_job(registry, state_path)
    attempts: list[int] = []
    runner_finished = threading.Event()

    def runner(context: JobAttemptContext) -> JobExecutionResult:
        attempts.append(context.attempt)
        return JobExecutionResult(summary="resume route recovery completed")

    def on_finished(
        snapshot: JobSnapshot,
        duration_seconds: float,
        result: JobExecutionResult | None,
        error: BaseException | None,
    ) -> None:
        del snapshot, duration_seconds, result, error
        runner_finished.set()

    assert (
        manager.bind_dispatch(job_id, runner, on_finished=on_finished).code
        == "dispatch_bound"
    )
    state_path.unlink()
    state_path.parent.rmdir()
    state_path.parent.write_text("not a directory", encoding="utf-8")

    failed = client.post("/resume", headers=_HEADERS)

    assert failed.status_code == 200
    failed_payload: dict[str, object] = failed.json()
    _assert_unpublished_resume_failure(failed_payload)
    retained = manager.get(job_id)
    assert retained is not None
    assert retained.id == job_id
    assert retained.state is JobState.PAUSED
    assert retained.attempt.number == 1
    initial_generation = manager._next_quiesced_dispatch_generation

    state_path.parent.unlink()
    state_path.parent.mkdir()
    with _running_service_loop() as service_loop:
        manager.adopt_service_loop(service_loop)
        recovered = client.post("/resume", headers=_HEADERS)
        assert runner_finished.wait(timeout=QUIESCE_THREAD_TIMEOUT), (
            "the repaired authenticated resume did not execute its bound runner"
        )

    assert recovered.status_code == 200
    recovered_payload: dict[str, object] = recovered.json()
    _assert_achieved_resume(recovered_payload)
    completed = manager.get(job_id)
    assert completed is not None
    assert completed.id == job_id
    assert completed.state is JobState.SUCCEEDED
    assert completed.attempt.number == 2
    assert attempts == [2]
    assert manager._next_quiesced_dispatch_generation == initial_generation + 1
    assert manager._pending_quiesced_dispatches == {}


def test_a_joined_pause_that_outwaits_its_owner_answers_with_an_envelope(
    quiesce_routes: QuiesceRoutes,
) -> None:
    """Two concurrent pauses are answered, never dropped as a bare 500.

    The second caller joins the owner's single-flight transition and spends
    its whole budget waiting for a release the owner is still holding.  A
    broker pausing speculatively has to read that as a refused lifecycle
    request, so it has to arrive as one envelope rather than a gateway fault.
    """
    client, registry = quiesce_routes
    owner_outcomes: list[QuiesceTransition] = []
    assert registry.gpu_lock.acquire(timeout=QUIESCE_THREAD_TIMEOUT)

    def owner_pause() -> None:
        owner_outcomes.append(
            registry.quiesce_resources(timeout_seconds=QUIESCE_THREAD_TIMEOUT),
        )

    owner = threading.Thread(target=owner_pause, name="pause-owner")
    owner.start()
    try:
        wait_for_quiesce_state(registry, QuiesceState.PAUSING)
        joined = client.post("/pause", headers=_HEADERS)
    finally:
        registry.gpu_lock.release()
        owner.join(timeout=QUIESCE_THREAD_TIMEOUT)

    assert joined.status_code == 200
    payload = joined.json()
    assert payload["ok"] is False
    assert payload["status"] == "quiesce_transition_wait_timed_out"
    assert payload["error"] == "quiesce_transition_wait_timed_out"
    assert payload["retryable"] is True
    assert "pause" in payload["message"]
    assert set(payload["quiesce"]) == _ENVELOPE_KEYS
    assert not owner.is_alive()
    assert owner_outcomes[0].achieved


def test_a_resume_opposing_an_owned_pause_answers_with_an_envelope(
    quiesce_routes: QuiesceRoutes,
) -> None:
    """A request against the live transition's direction is refused, not dropped."""
    client, registry = quiesce_routes
    stuck_ticket = registry.acquire_compute_ticket()
    owner_outcomes: list[QuiesceTransition] = []

    def owner_pause() -> None:
        owner_outcomes.append(
            registry.quiesce_resources(timeout_seconds=QUIESCE_THREAD_TIMEOUT),
        )

    owner = threading.Thread(target=owner_pause, name="pause-conflict-owner")
    owner.start()
    try:
        wait_for_quiesce_state(registry, QuiesceState.PAUSING)
        opposed = client.post("/resume", headers=_HEADERS)
    finally:
        stuck_ticket.release()
        owner.join(timeout=QUIESCE_THREAD_TIMEOUT)

    assert opposed.status_code == 200
    payload = opposed.json()
    assert payload["ok"] is False
    assert payload["status"] == "quiesce_transition_conflict"
    assert payload["error"] == "quiesce_transition_conflict"
    assert payload["retryable"] is True
    assert "resume" in payload["message"]
    assert payload["quiesce"]["state"] == "pausing"
    assert not owner.is_alive()
    assert owner_outcomes[0].achieved
