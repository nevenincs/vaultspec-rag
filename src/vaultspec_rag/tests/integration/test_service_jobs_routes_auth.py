"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from ._service_jobs_route_helpers import (
    _routes_app as _routes_app_fixture,
)
from ._service_jobs_support import _clean_jobs as _clean_jobs_fixture

__all__ = ["_clean_jobs_fixture", "_routes_app_fixture"]

if TYPE_CHECKING:
    import httpx
    from starlette.testclient import TestClient


@pytest.mark.unit
def test_jobs_route_401_without_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = cast("httpx.Response", client.get("/jobs"))  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    assert response.status_code == 401
    payload: dict[str, Any] = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


@pytest.mark.unit
def test_jobs_route_401_with_wrong_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", headers={"Authorization": "Bearer wrong"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 401


@pytest.mark.unit
def test_jobs_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/jobs", headers={"Authorization": f"Bearer {token}"}),  # pyright: ignore[reportUnknownMemberType]  # starlette TestClient stub incomplete
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    payload: dict[str, Any] = response.json()
    assert set(payload) == {"jobs", "total", "returned", "summary", "filters"}
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["source"] == "vault"
    assert payload["jobs"][0]["phase"] == "done"
    assert payload["summary"]["running"] == 0
    assert payload["summary"]["initiators"]["tool"] == 1
    assert payload["summary"]["users"]


@pytest.mark.unit
def test_jobs_route_200_with_query_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast("httpx.Response", client.get("/jobs", params={"token": token}))  # pyright: ignore[reportUnknownMemberType]
    assert response.status_code == 200
    assert len(response.json()["jobs"]) == 1
