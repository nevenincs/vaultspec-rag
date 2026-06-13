"""Starlette coverage for the ``GET /readiness`` loopback route.

Exercises the real ASGI route through ``starlette.testclient.TestClient`` (NOT
a mock) built from ``_routes.ROUTES`` with a known ``_SERVICE_TOKEN``: 401
without the token, 200 with it, and a body identical to the snapshot the
``server doctor`` CLI verb renders - both adapters read ``get_readiness`` so
the bounded snapshot is the same in both surfaces. No mocks/skips.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import vaultspec_rag.server as _m

from ...api import get_readiness
from ...server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Iterator

    import httpx

pytestmark = [pytest.mark.integration]


@pytest.fixture
def _routes_app() -> Iterator[tuple[TestClient, str]]:
    """A real ASGI TestClient over ROUTES with a known service token."""
    prev_token = _m._SERVICE_TOKEN
    _m._SERVICE_TOKEN = "test-token-readiness"
    try:
        client = TestClient(Starlette(routes=ROUTES))
        yield client, "test-token-readiness"
    finally:
        _m._SERVICE_TOKEN = prev_token


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
