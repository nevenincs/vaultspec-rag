"""CPU-only guards for the canonical quiesce state projections."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
from starlette.testclient import TestClient

from ..server import ServerRouteRuntime, create_http_app
from ..service_quiesce import QUIESCE_ENVELOPE_FIELDS

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from ..service import ServiceRegistry

pytestmark = [pytest.mark.unit]

_TOKEN = "quiesce-state-projection-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}
#: The canonical controller vocabulary, derived rather than restated.
#: Three copies of this literal used to sit in three test modules, which
#: is the duplication the controller module warns about: a field added to
#: the snapshot turned into three unrelated failures that each looked
#: like a projection bug. The literal names are pinned once, in the
#: controller's own contract test.
_ENVELOPE_KEYS = QUIESCE_ENVELOPE_FIELDS


@contextmanager
def _projection_client(registry: ServiceRegistry) -> Generator[TestClient]:
    """Serve both production projections through a local in-process app."""
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(app) as client:
        yield client


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
    from ..service import ServiceRegistry

    registry = ServiceRegistry()
    assert registry.quiesce_snapshot().state.value == "running"
    (tmp_path / ".vault").mkdir()

    with _projection_client(registry) as client:
        _assert_current_projection(client, tmp_path, registry)

        paused = registry.quiesce_resources(timeout_seconds=0)
        assert paused.achieved
        _assert_current_projection(client, tmp_path, registry)

        resumed = registry.resume_resources()
        assert resumed.achieved
        _assert_current_projection(client, tmp_path, registry)
