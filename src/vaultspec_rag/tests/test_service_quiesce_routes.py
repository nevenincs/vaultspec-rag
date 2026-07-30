"""Loopback route coverage for acknowledged service quiesce."""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, NamedTuple

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import vaultspec_rag.server as server

from ..server._routes import pause_service_route, resume_service_route
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState, QuiesceTransition
from ._quiesce_helpers import QUIESCE_THREAD_TIMEOUT, wait_for_quiesce_state

if TYPE_CHECKING:
    from collections.abc import Generator

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


@pytest.fixture
def quiesce_routes() -> Generator[QuiesceRoutes]:
    """Serve the real pause/resume routes over a real registry.

    Server exceptions are deliberately not re-raised into the test: uvicorn
    turns an escaping handler exception into a bare 500, and a lifecycle verb
    that lets one escape is precisely what these cases are asserting against.
    Re-raising here would hide that behind a test-only error.
    """
    previous_registry = server._registry
    previous_token = server._SERVICE_TOKEN
    registry = ServiceRegistry()
    server._registry = registry
    server._SERVICE_TOKEN = _TOKEN
    app = Starlette(
        routes=[
            Route("/pause", pause_service_route, methods=["POST"]),
            Route("/resume", resume_service_route, methods=["POST"]),
        ],
    )
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            yield QuiesceRoutes(client, registry)
    finally:
        server._registry = previous_registry
        server._SERVICE_TOKEN = previous_token


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

    assert resume_payload["ok"] is True
    assert resume_payload["status"] == "running"
    assert set(resume_payload["quiesce"]) == _ENVELOPE_KEYS
    assert resume_payload["quiesce"]["state"] == "running"
    assert resume_payload["quiesce"]["safe_to_borrow_gpu"] is False
    assert resume_payload["quiesce"]["failure_reason"] is None
    assert "error" not in resume_payload


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
    assert "resume" in payload["message"]
    assert payload["quiesce"]["state"] == "pausing"
    assert not owner.is_alive()
    assert owner_outcomes[0].achieved
