"""CPU-only route guard for the jobs quiesce-state projection."""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, cast

import pytest
from starlette.testclient import TestClient

from ..server import ServerRouteRuntime, create_http_app
from ..service_quiesce import QUIESCE_ENVELOPE_FIELDS

if TYPE_CHECKING:
    from collections.abc import Generator

    from ..service import ServiceRegistry

pytestmark = [pytest.mark.unit]

_TOKEN = "jobs-quiesce-projection-token"
_HEADERS = {"Authorization": f"Bearer {_TOKEN}"}
#: The canonical controller vocabulary, derived rather than restated.
#: Three copies of this literal used to sit in three test modules, which
#: is the duplication the controller module warns about: a field added to
#: the snapshot turned into three unrelated failures that each looked
#: like a projection bug. The literal names are pinned once, in the
#: controller's own contract test.
_ENVELOPE_KEYS = QUIESCE_ENVELOPE_FIELDS


@contextmanager
def _jobs_client(registry: ServiceRegistry) -> Generator[TestClient]:
    """Serve the production jobs handler in-process with its real token gate."""
    app = create_http_app(
        ServerRouteRuntime(token=_TOKEN, registry=registry, port=8765),
        lifespan=None,
    )
    with TestClient(app) as client:
        yield client


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
    assert cast("dict[str, object]", payload)["quiesce"] == expected


def test_jobs_route_refreshes_the_exact_quiesce_envelope() -> None:
    """Jobs observations follow running, quiesced, and resumed lifecycle truth.

    Mutation: remove the ``quiesce_snapshot().as_envelope()`` response entry.
    The route assertion fails because the canonical lifecycle block is absent.
    """
    from ..service import ServiceRegistry

    registry = ServiceRegistry()
    assert registry.quiesce_snapshot().state.value == "running"

    with _jobs_client(registry) as client:
        _assert_current_projection(client, registry)

        paused = registry.quiesce_resources(timeout_seconds=0)
        assert paused.achieved
        _assert_current_projection(client, registry)

        resumed = registry.resume_resources()
        assert resumed.achieved
        _assert_current_projection(client, registry)
