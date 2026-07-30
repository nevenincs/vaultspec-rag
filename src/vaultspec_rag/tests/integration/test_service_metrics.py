"""Tests for the Tier-3 metrics surface (#142).

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

from typing import TYPE_CHECKING, cast

import httpx
import pytest
from starlette.testclient import TestClient

import vaultspec_rag.mcp._tools as tools

from ... import server
from ...server import ServerRouteRuntime, create_http_app
from ...service import ServiceRegistry
from ._helpers import _make_root
from .conftest import _attach_live_service, _live_service_context

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from pytest import TempPathFactory


@pytest.fixture
def _clean_metrics(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    """Zero the metrics holder before and after each test."""
    server.reset_metrics()
    yield
    server.reset_metrics()


@pytest.fixture
def _clean_watchers(  # pyright: ignore[reportUnusedFunction]
) -> Iterator[None]:
    """Stop any watcher the search/reindex paths started as a side effect."""
    yield
    server._stop_all_watchers()


# --------------------------------------------------------------------------- #
# Unit: incr / observe / render_prometheus text format                        #
# --------------------------------------------------------------------------- #


@pytest.mark.unit
def test_incr_accumulates_in_render(_clean_metrics: None) -> None:
    server.incr("search_total")
    server.incr("search_total")
    server.incr("reindex_total")

    text = server.render_prometheus()
    assert "vaultspec_rag_search_total 2" in text
    assert "vaultspec_rag_reindex_total 1" in text


@pytest.mark.unit
def test_render_emits_type_lines(_clean_metrics: None) -> None:
    text = server.render_prometheus()
    assert "# TYPE vaultspec_rag_search_total counter" in text
    assert "# TYPE vaultspec_rag_reindex_total counter" in text
    assert "# TYPE vaultspec_rag_search_last_duration_seconds gauge" in text
    assert "# TYPE vaultspec_rag_reindex_last_duration_seconds gauge" in text
    # Each metric value sits on its own line; text ends with a newline.
    assert text.endswith("\n")


@pytest.mark.unit
def test_observe_sets_gauge(_clean_metrics: None) -> None:
    server.observe("search_last_duration_seconds", 0.25)
    text = server.render_prometheus()
    assert "vaultspec_rag_search_last_duration_seconds 0.25" in text


@pytest.mark.unit
def test_incr_unknown_name_is_noop(_clean_metrics: None) -> None:
    server.incr("does_not_exist")
    text = server.render_prometheus()
    assert "does_not_exist" not in text


@pytest.mark.unit
def test_maintenance_reconcile_metrics_are_registered(_clean_metrics: None) -> None:
    # The scheduled geometry-reconcile pass emits these three keys; they must
    # be registered or ``incr``/``observe`` silently drop them (unknown names
    # are no-ops), leaving them permanently absent from ``/metrics``.
    server.incr("maintenance_reconciled_total", 3)
    server.incr("maintenance_reconciled_bytes_total", 4096)
    server.observe("store_drifted_collections", 2.0)

    text = server.render_prometheus()
    assert "vaultspec_rag_maintenance_reconciled_total 3" in text
    assert "vaultspec_rag_maintenance_reconciled_bytes_total 4096" in text
    assert "vaultspec_rag_store_drifted_collections 2.0" in text


@pytest.mark.unit
def test_reset_zeroes_counters(_clean_metrics: None) -> None:
    server.incr("search_total", 5)
    server.reset_metrics()
    text = server.render_prometheus()
    assert "vaultspec_rag_search_total 0" in text


# --------------------------------------------------------------------------- #
# Integration (GPU): real tool paths increment the inline counters            #
# --------------------------------------------------------------------------- #


import vaultspec_rag.mcp._admin_client as admin_tools  # noqa: E402


async def _reindex_vault_to_completion(root: Path) -> None:
    """Run a real vault reindex and wait for its job to leave the queue.

    The counter the caller then reads is only credited once the job has
    actually finished, so polling the job's phase is what makes the
    subsequent metric assertion deterministic rather than racy.
    """
    import asyncio

    response = await tools.reindex_vault(project_root=str(root))
    assert isinstance(response, dict)
    job_id: str = cast("str", response["job_id"])
    for _ in range(50):
        jobs_res = await admin_tools.get_jobs()
        jobs = [j for j in jobs_res.get("jobs", []) if j["id"] == job_id]
        if jobs and jobs[0]["phase"] in ("done", "error", "failed"):
            break
        await asyncio.sleep(0.1)


@pytest.fixture(scope="module")
def _metrics_daemon(  # pyright: ignore[reportUnusedFunction]
    tmp_path_factory: TempPathFactory,
) -> Iterator[tuple[int, Path, dict[str, str | None]]]:
    """Hold a daemon whose global counters nothing outside this module moves.

    ``/metrics`` exposes whole-process counters with no per-root breakdown, so
    the two GPU tests below can only be written as a delta over the daemon's
    entire workload. The session-wide daemon is shared with modules that start
    reindex jobs without waiting for them, and those land inside this module's
    measurement window - a single reindex was observed moving the shared
    counter by six. A test that measures a process-global number has to own the
    process, so this module pays one extra spawn rather than assert a total it
    does not control.
    """
    with _live_service_context(tmp_path_factory.mktemp("metrics-service")) as service:
        yield service


@pytest.fixture
def metrics_service(
    _metrics_daemon: tuple[int, Path, dict[str, str | None]],
) -> Iterator[tuple[int, Path]]:
    """Point this test's clients at the module's own counter-isolated daemon."""
    with _attach_live_service(_metrics_daemon) as service:
        yield service


def _counter_value(text: str, name: str) -> float:
    """Read one counter's current value out of a Prometheus exposition.

    Parsed by exact key rather than matched as a substring. A counter that has
    served earlier work in the same daemon renders a multi-digit value, and
    ``"..._total 1" in text`` is satisfied by ``11`` - so a substring assertion
    keeps passing however far the real count has drifted from the expected one.
    """
    prefixed = f"vaultspec_rag_{name}"
    for line in text.splitlines():
        key, _, raw = line.partition(" ")
        if key == prefixed:
            return float(raw)
    raise AssertionError(f"{prefixed} absent from metrics exposition:\n{text}")


async def _fetch_daemon_metrics(port: int, token: str) -> str:
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"http://127.0.0.1:{port}/metrics",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        )
        assert resp.status_code == 200
        return resp.text


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_search_vault_increments_counter(
    tmp_path: Path,
    metrics_service: tuple[int, Path],
) -> None:
    root = _make_root(tmp_path)
    port, _status_dir = metrics_service

    from ._helpers import _poll_health

    health = _poll_health(port)
    token = health["service_token"]

    baseline = await _fetch_daemon_metrics(port, token)
    reindexes = _counter_value(baseline, "reindex_total")
    searches = _counter_value(baseline, "search_total")

    await _reindex_vault_to_completion(root)

    before = await _fetch_daemon_metrics(port, token)
    # The reindex is credited inline, and it must move only its own counter:
    # a reindex that also bumped the search counter would make every later
    # search assertion pass for the wrong reason.
    assert _counter_value(before, "reindex_total") == reindexes + 1
    assert _counter_value(before, "search_total") == searches

    await tools.search_vault("body", top_k=3, project_root=str(root))

    after = await _fetch_daemon_metrics(port, token)
    assert _counter_value(after, "search_total") == searches + 1


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_reindex_vault_increments_counter(
    tmp_path: Path,
    metrics_service: tuple[int, Path],
) -> None:
    root = _make_root(tmp_path)
    port, _status_dir = metrics_service

    from ._helpers import _poll_health

    health = _poll_health(port)
    token = health["service_token"]

    before = await _fetch_daemon_metrics(port, token)
    reindexes = _counter_value(before, "reindex_total")

    await _reindex_vault_to_completion(root)

    after = await _fetch_daemon_metrics(port, token)
    assert _counter_value(after, "reindex_total") == reindexes + 1


# --------------------------------------------------------------------------- #
# Starlette: real ASGI TestClient against /metrics gating + format            #
# --------------------------------------------------------------------------- #


@pytest.fixture
def _routes_app(  # pyright: ignore[reportUnusedFunction]
    _clean_metrics: None,
) -> Iterator[tuple[TestClient, str]]:
    """Build a real production app with an isolated route runtime.

    The runtime carries the known token, and the seeded counters make the
    rendered body carry non-zero values.
    """
    server.incr("search_total", 3)
    server.incr("reindex_total")

    app_under_test = create_http_app(
        ServerRouteRuntime(
            token="test-token-metrics",
            registry=ServiceRegistry(),
        ),
        lifespan=None,
    )
    client = TestClient(app_under_test)
    try:
        yield client, "test-token-metrics"
    finally:
        client.close()


@pytest.mark.unit
def test_metrics_route_401_without_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = cast("httpx.Response", client.get("/metrics"))
    assert response.status_code == 401
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"] == "unauthorized"


@pytest.mark.unit
def test_metrics_route_401_with_wrong_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, _token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/metrics", headers={"Authorization": "Bearer wrong"}),
    )
    assert response.status_code == 401


@pytest.mark.unit
def test_metrics_route_200_with_bearer_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast(
        "httpx.Response",
        client.get("/metrics", headers={"Authorization": f"Bearer {token}"}),
    )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    body: str = response.text
    assert "vaultspec_rag_search_total 3" in body
    assert "vaultspec_rag_reindex_total 1" in body
    assert "# TYPE vaultspec_rag_search_total counter" in body


@pytest.mark.unit
def test_metrics_route_200_with_query_token(
    _routes_app: tuple[TestClient, str],
) -> None:
    client, token = _routes_app
    response = cast("httpx.Response", client.get("/metrics", params={"token": token}))
    assert response.status_code == 200
    assert "vaultspec_rag_search_total 3" in response.text
