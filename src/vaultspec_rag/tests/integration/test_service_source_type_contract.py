"""Real HTTP route evidence for the canonical source vocabulary."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, cast

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import vaultspec_rag.server as server

from ..._source_types import PublicSourceType
from ...cli._search import _validate_search_type
from ...config import EnvVar, reset_config
from ...mcp._tools import _canonical_tool_source
from ...server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx

pytestmark = [pytest.mark.integration]


@pytest.fixture
def canonical_routes(tmp_path: Path) -> Iterator[tuple[TestClient, str]]:
    """Serve the production route table with isolated real service state."""
    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_token = server._SERVICE_TOKEN
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    server._SERVICE_TOKEN = "canonical-source-test-token"
    reset_config()
    try:
        with TestClient(Starlette(routes=ROUTES)) as client:
            yield client, "canonical-source-test-token"
    finally:
        server._SERVICE_TOKEN = prior_token
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        reset_config()


@pytest.mark.parametrize(
    ("path", "alias"),
    (
        ("/search", "docs"),
        ("/reindex", "codebase"),
        ("/clean", "all"),
    ),
)
def test_http_routes_reject_compatibility_source_aliases(
    canonical_routes: tuple[TestClient, str],
    tmp_path: Path,
    path: str,
    alias: str,
) -> None:
    client, token = canonical_routes
    response = cast(
        "httpx.Response",
        client.post(  # pyright: ignore[reportUnknownMemberType] - starlette TestClient stub gap
            path,
            headers={"Authorization": f"Bearer {token}"},
            json={
                "type": alias,
                "query": "canonical source contract",
                "project_root": str(tmp_path),
            },
        ),
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unknown_source_type"
    assert payload["error_kind"] == "unknown_source_type"
    assert payload["received"] == alias
    assert payload["aliases_allowed"] is False
    assert payload["allowed"] == ["vault", "code", "document", "combined"]


@pytest.mark.parametrize(
    ("alias", "expected"),
    (
        ("docs", PublicSourceType.VAULT),
        ("codebase", PublicSourceType.CODE),
        ("all", PublicSourceType.COMBINED),
    ),
)
def test_cli_and_mcp_boundaries_retain_compatibility_aliases(
    alias: str,
    expected: PublicSourceType,
) -> None:
    assert _validate_search_type(alias, json_mode=False) is expected
    assert _canonical_tool_source(alias) == expected.value
