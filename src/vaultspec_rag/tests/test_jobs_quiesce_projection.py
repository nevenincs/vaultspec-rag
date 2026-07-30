"""CPU-only route guard for the jobs quiesce-state projection."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import vaultspec_rag.server as server

from ..registry import get_registry
from ..server._routes import jobs_route

if TYPE_CHECKING:
    from collections.abc import Generator

    from ..service import ServiceRegistry

pytestmark = [pytest.mark.unit]

_TOKEN = "jobs-quiesce-projection-token"
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


@contextmanager
def _jobs_client() -> Generator[TestClient]:
    """Serve the production jobs handler in-process with its real token gate."""
    prior_token = server._SERVICE_TOKEN
    server._SERVICE_TOKEN = _TOKEN
    app = Starlette(routes=[Route("/jobs", jobs_route)])
    try:
        with TestClient(app) as client:
            yield client
    finally:
        server._SERVICE_TOKEN = prior_token


def _assert_current_projection(
    client: TestClient,
    registry: ServiceRegistry,
) -> None:
    """The route must render the registry's full current envelope unchanged."""
    response = client.get("/jobs", headers=_HEADERS)
    payload: object = response.json()
    assert response.status_code == 200
    assert isinstance(payload, dict)
    expected = registry.quiesce_snapshot().as_envelope()

    assert set(expected) == _ENVELOPE_KEYS
    assert payload["quiesce"] == expected


def test_jobs_route_refreshes_the_exact_quiesce_envelope() -> None:
    """Jobs observations follow running, quiesced, and resumed lifecycle truth.

    Mutation: remove the ``quiesce_snapshot().as_envelope()`` response entry.
    The route assertion fails because the canonical lifecycle block is absent.
    """
    registry = get_registry()
    assert server._registry is registry
    assert registry.quiesce_snapshot().state.value == "running"

    with _jobs_client() as client:
        _assert_current_projection(client, registry)

        paused = registry.quiesce_resources(timeout_seconds=0)
        assert paused.achieved
        _assert_current_projection(client, registry)

        resumed = registry.resume_resources()
        assert resumed.achieved
        _assert_current_projection(client, registry)
