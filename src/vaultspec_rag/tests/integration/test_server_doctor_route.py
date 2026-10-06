"""Starlette coverage for the ``GET /readiness`` loopback route.

Exercises the real ASGI route through ``starlette.testclient.TestClient`` (NOT
a mock) built from ``_routes.ROUTES`` with a known ``_SERVICE_TOKEN``: 401
without the token, 200 with it, and a body identical to the bounded snapshot
``get_readiness`` returns. The ``server doctor`` CLI verb reads the same
function and asks it to check the models in depth, which a polled route does
not, so the two surfaces differ in the model row's depth and in nothing else.
No mocks/skips.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from starlette.testclient import TestClient

from ...api import get_readiness
from ...server import ServerRouteRuntime, create_http_app
from ...service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

pytestmark = [pytest.mark.integration]


@pytest.fixture
def _routes_app() -> Iterator[tuple[TestClient, str]]:  # pyright: ignore[reportUnusedFunction]
    """A real ASGI TestClient over ROUTES with a known service token."""
    client = TestClient(
        create_http_app(
            ServerRouteRuntime(
                token="test-token-readiness",
                registry=ServiceRegistry(),
                port=8765,
            ),
            lifespan=None,
        ),
        base_url="http://127.0.0.1",
    )
    try:
        yield client, "test-token-readiness"
    finally:
        client.close()


def test_readiness_route_401_without_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _ = _routes_app
    response = cast("httpx.Response", client.get("/readiness"))
    assert response.status_code == 401


def test_readiness_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/readiness", headers={"Authorization": f"Bearer {token}"}),
    )
    assert response.status_code == 200
    # Route and CLI verb read the same reporter, so the snapshot is identical.
    assert response.json() == get_readiness()
