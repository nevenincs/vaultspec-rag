"""CPU-only guards for the canonical quiesce state projections."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import vaultspec_rag.server as server

from ..registry import get_registry
from ..server._lifespan import health_handler
from ..server._routes import get_service_state_route

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..service import ServiceRegistry

pytestmark = [pytest.mark.unit]

_TOKEN = "quiesce-state-projection-token"
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
def _projection_client() -> Generator[TestClient]:
    """Serve both production projections through a local in-process app."""
    prior_token = server._SERVICE_TOKEN
    server._SERVICE_TOKEN = _TOKEN
    app = Starlette(
        routes=[
            Route("/health", health_handler),
            Route("/service-state", get_service_state_route),
        ],
    )
    try:
        with TestClient(app) as client:
            yield client
    finally:
        server._SERVICE_TOKEN = prior_token


def _assert_current_projection(
    client: TestClient,
    root: Path,
    registry: ServiceRegistry,
) -> None:
    """Both endpoints must render the registry's current full envelope exactly."""
    health: object = client.get("/health").json()
    state: object = client.get(
        "/service-state",
        params={"project_root": str(root)},
        headers=_HEADERS,
    ).json()
    assert isinstance(health, dict)
    assert isinstance(state, dict)
    expected = registry.quiesce_snapshot().as_envelope()

    assert set(expected) == _ENVELOPE_KEYS
    assert cast("dict[str, object]", health)["quiesce"] == expected
    assert cast("dict[str, object]", state)["quiesce"] == expected


def test_health_and_service_state_refresh_the_exact_quiesce_envelope(
    tmp_path: Path,
) -> None:
    """Neither public state projection may cache or reshape lifecycle truth.

    Mutation: remove either ``quiesce_snapshot().as_envelope()`` projection.
    The corresponding equality assertion fails; return a partial envelope and
    the exact twelve-key assertion fails.
    """
    registry = get_registry()
    assert server._registry is registry
    assert registry.quiesce_snapshot().state.value == "running"
    (tmp_path / ".vault").mkdir()

    with _projection_client() as client:
        _assert_current_projection(client, tmp_path, registry)

        paused = registry.quiesce_resources(timeout_seconds=0)
        assert paused.achieved
        _assert_current_projection(client, tmp_path, registry)

        resumed = registry.resume_resources()
        assert resumed.achieved
        _assert_current_projection(client, tmp_path, registry)
