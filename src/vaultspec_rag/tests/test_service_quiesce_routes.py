"""Loopback route coverage for acknowledged service quiesce."""

from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import vaultspec_rag.server as server

from ..server._routes import pause_service_route, resume_service_route
from ..service import ServiceRegistry

pytestmark = [pytest.mark.unit]


def test_pause_resume_routes_return_the_complete_controller_envelope() -> None:
    """A real registry exposes only achieved pause and resume lifecycle truth."""
    previous_registry = server._registry
    previous_token = server._SERVICE_TOKEN
    registry = ServiceRegistry()
    server._registry = registry
    server._SERVICE_TOKEN = "quiesce-route-token"
    app = Starlette(
        routes=[
            Route("/pause", pause_service_route, methods=["POST"]),
            Route("/resume", resume_service_route, methods=["POST"]),
        ],
    )
    try:
        with TestClient(app) as client:
            unauthorized = client.post("/pause")
            assert unauthorized.status_code == 401

            headers = {"Authorization": "Bearer quiesce-route-token"}
            paused = client.post("/pause", headers=headers)
            resumed = client.post("/resume", headers=headers)
    finally:
        server._registry = previous_registry
        server._SERVICE_TOKEN = previous_token

    pause_payload = paused.json()
    resume_payload = resumed.json()
    expected_keys = {
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

    assert paused.status_code == 200
    assert pause_payload["ok"] is True
    assert pause_payload["status"] == "quiesced"
    assert set(pause_payload["quiesce"]) == expected_keys
    assert pause_payload["quiesce"]["state"] == "quiesced"
    assert pause_payload["quiesce"]["safe_to_borrow_gpu"] is True
    assert pause_payload["quiesce"]["failure_reason"] is None

    assert resumed.status_code == 200
    assert resume_payload["ok"] is True
    assert resume_payload["status"] == "running"
    assert set(resume_payload["quiesce"]) == expected_keys
    assert resume_payload["quiesce"]["state"] == "running"
    assert resume_payload["quiesce"]["safe_to_borrow_gpu"] is False
    assert resume_payload["quiesce"]["failure_reason"] is None
