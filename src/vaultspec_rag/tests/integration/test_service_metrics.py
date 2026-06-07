"""Tests for the Tier-3 metrics surface (#142, plan P05).

Three layers, no mocks/skips/monkeypatch:

- Unit: drive ``incr`` / ``observe`` / ``render_prometheus`` directly and
  assert the Prometheus text exposition format (TYPE lines, prefixed metric
  names, counter values). The holder is reset in teardown.
- Integration (GPU): run a real ``search_vault`` / ``reindex_vault`` against
  the global registry with a real GPU-backed slot (reusing the session-scoped
  ``embedding_model`` fixture and the global-registry pattern from
  ``test_watcher_control.py``) and assert the inline counters increment.
- Starlette: exercise the real ``GET /metrics`` route through
  ``starlette.testclient.TestClient`` (the real ASGI client, NOT a mock) built
  from ``_routes.ROUTES`` with a known ``_SERVICE_TOKEN`` - 401 without token,
  200 Prometheus text with token.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

import vaultspec_rag.mcp_server as _m

from ... import mcp_server
from ...mcp_server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ...embeddings import EmbeddingModel


@pytest.fixture
def _clean_metrics() -> Iterator[None]:
    """Zero the metrics holder before and after each test."""
    mcp_server.reset_metrics()
    yield
    mcp_server.reset_metrics()


@pytest.fixture
def _clean_watchers() -> Iterator[None]:
    """Stop any watcher the search/reindex paths started as a side effect."""
    yield
    mcp_server._stop_all_watchers()


def _make_root(tmp_path: Path) -> Path:
    adr_dir = tmp_path / ".vault" / "adr"
    adr_dir.mkdir(parents=True)
    (adr_dir / "x.md").write_text(
        "---\ntags: ['#adr', '#t']\n---\n# x\n\nbody\n",
        encoding="utf-8",
    )
    return tmp_path


# --------------------------------------------------------------------------- #
# Unit: incr / observe / render_prometheus text format                        #
# --------------------------------------------------------------------------- #


def test_incr_accumulates_in_render(_clean_metrics: None) -> None:
    mcp_server.incr("search_total")
    mcp_server.incr("search_total")
    mcp_server.incr("reindex_total")

    text = mcp_server.render_prometheus()
    assert "vaultspec_rag_search_total 2" in text
    assert "vaultspec_rag_reindex_total 1" in text


def test_render_emits_type_lines(_clean_metrics: None) -> None:
    text = mcp_server.render_prometheus()
    assert "# TYPE vaultspec_rag_search_total counter" in text
    assert "# TYPE vaultspec_rag_reindex_total counter" in text
    assert "# TYPE vaultspec_rag_search_last_duration_seconds gauge" in text
    assert "# TYPE vaultspec_rag_reindex_last_duration_seconds gauge" in text
    # Each metric value sits on its own line; text ends with a newline.
    assert text.endswith("\n")


def test_observe_sets_gauge(_clean_metrics: None) -> None:
    mcp_server.observe("search_last_duration_seconds", 0.25)
    text = mcp_server.render_prometheus()
    assert "vaultspec_rag_search_last_duration_seconds 0.25" in text


def test_incr_unknown_name_is_noop(_clean_metrics: None) -> None:
    mcp_server.incr("does_not_exist")
    text = mcp_server.render_prometheus()
    assert "does_not_exist" not in text


def test_reset_zeroes_counters(_clean_metrics: None) -> None:
    mcp_server.incr("search_total", 5)
    mcp_server.reset_metrics()
    text = mcp_server.render_prometheus()
    assert "vaultspec_rag_search_total 0" in text


# --------------------------------------------------------------------------- #
# Integration (GPU): real tool paths increment the inline counters            #
# --------------------------------------------------------------------------- #


@pytest.mark.integration
async def test_search_vault_increments_counter(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    _clean_metrics: None,
    _clean_watchers: None,
) -> None:
    import asyncio

    from ...mcp_server import _jobs

    root = _make_root(tmp_path)
    mcp_server._registry._model = embedding_model

    response = await mcp_server.reindex_vault(project_root=str(root))
    assert isinstance(response, dict)
    job_id = response["job_id"]
    for _ in range(50):
        jobs = [j for j in _jobs.snapshot() if j["id"] == job_id]
        if jobs and jobs[0]["phase"] in ("done", "error", "failed"):
            break
        await asyncio.sleep(0.1)

    before = mcp_server.render_prometheus()
    assert "vaultspec_rag_search_total 0" in before
    # The reindex above bumped the reindex counter inline.
    assert "vaultspec_rag_reindex_total 1" in before

    await mcp_server.search_vault("body", top_k=3, project_root=str(root))

    after = mcp_server.render_prometheus()
    assert "vaultspec_rag_search_total 1" in after


@pytest.mark.integration
async def test_reindex_vault_increments_counter(
    tmp_path: Path,
    embedding_model: EmbeddingModel,
    _clean_metrics: None,
    _clean_watchers: None,
) -> None:
    import asyncio

    from ...mcp_server import _jobs

    root = _make_root(tmp_path)
    mcp_server._registry._model = embedding_model

    response = await mcp_server.reindex_vault(project_root=str(root))
    assert isinstance(response, dict)
    job_id = response["job_id"]
    for _ in range(50):
        jobs = [j for j in _jobs.snapshot() if j["id"] == job_id]
        if jobs and jobs[0]["phase"] in ("done", "error", "failed"):
            break
        await asyncio.sleep(0.1)

    text = mcp_server.render_prometheus()
    assert "vaultspec_rag_reindex_total 1" in text


# --------------------------------------------------------------------------- #
# Starlette: real ASGI TestClient against /metrics gating + format            #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _routes_app(_clean_metrics: None) -> Iterator[tuple[TestClient, str]]:
    """Build a real Starlette app from the read-only ROUTES.

    Sets a known ``_SERVICE_TOKEN`` on the package namespace (the route's
    ``require_token`` reads it through the alias) and seeds a couple of
    counter increments so the rendered body carries non-zero values.
    Restores the token on teardown so the suite stays isolated.
    """
    mcp_server.incr("search_total", 3)
    mcp_server.incr("reindex_total")

    prev_token = _m._SERVICE_TOKEN
    _m._SERVICE_TOKEN = "test-token-metrics"

    app_under_test = Starlette(routes=ROUTES)
    client = TestClient(app_under_test)
    try:
        yield client, "test-token-metrics"
    finally:
        _m._SERVICE_TOKEN = prev_token


def test_metrics_route_401_without_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = client.get("/metrics")
    assert response.status_code == 401
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


def test_metrics_route_401_with_wrong_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = client.get("/metrics", headers={"Authorization": "Bearer wrong"})
    assert response.status_code == 401


def test_metrics_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = client.get("/metrics", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body = response.text
    assert "vaultspec_rag_search_total 3" in body
    assert "vaultspec_rag_reindex_total 1" in body
    assert "# TYPE vaultspec_rag_search_total counter" in body


def test_metrics_route_200_with_query_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = client.get("/metrics", params={"token": token})
    assert response.status_code == 200
    assert "vaultspec_rag_search_total 3" in response.text
