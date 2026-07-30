"""CPU-only search-admission coverage for service resource quiesce."""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING

import pytest
from starlette.applications import Starlette
from starlette.routing import Route
from starlette.testclient import TestClient

import vaultspec_rag.server as server

from ..server._routes_search import search_route
from ..server._state import search_activity_ledger
from ..service import ServiceRegistry
from ..service_quiesce import (
    QuiesceAdmissionClosedError,
    QuiesceState,
    QuiesceTransitionCode,
)

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


_QUIESCE_SEARCH_MESSAGE = (
    "Search is temporarily unavailable while service compute admission is closed; "
    "retry after the service returns to running."
)


class _QuiesceSearchEnvelopeHandler(BaseHTTPRequestHandler):
    """Serve the canonical quiesce rejection through a real HTTP socket."""

    def do_POST(self) -> None:
        assert self.path == "/search"
        response = {
            "ok": False,
            "error": "quiesce_admission_closed",
            "message": _QUIESCE_SEARCH_MESSAGE,
            "retryable": True,
            "request_id": "loopback-quiesce-admission",
            "quiesce": {
                "state": "quiesced",
                "admission_epoch": 4,
                "safe_to_borrow_gpu": True,
            },
        }
        payload = json.dumps(response).encode("utf-8")
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, format: str, *args: object) -> None:
        """Keep the focused transport proof's loopback request silent."""


def test_quiesced_search_returns_the_retryable_envelope_for_every_source(
    tmp_path: Path,
) -> None:
    """Closed admission rejects before any source can construct compute work.

    Replacing the route's ``QuiesceAdmissionClosedError`` handling with a
    raised runtime error makes the named 503 assertion fail, proving this is
    not a generic server-error response.
    """
    from time import time_ns

    root = tmp_path / "vault"
    (root / ".vault").mkdir(parents=True)
    registry = ServiceRegistry()
    assert registry.quiesce_resources(timeout_seconds=0).achieved
    previous_registry = server._registry
    previous_token = server._SERVICE_TOKEN
    server._registry = registry
    server._SERVICE_TOKEN = "closed-admission-token"
    app = Starlette(routes=[Route("/search", search_route, methods=["POST"])])
    marker = f"quiesce-admission-{time_ns()}"
    try:
        with TestClient(app, raise_server_exceptions=False) as client:
            responses = {
                source: client.post(
                    "/search",
                    headers={"Authorization": "Bearer closed-admission-token"},
                    json={
                        "query": f"{marker}-{source}",
                        "type": source,
                        "project_root": str(root),
                    },
                )
                for source in ("vault", "code", "document", "combined")
            }
    finally:
        server._registry = previous_registry
        server._SERVICE_TOKEN = previous_token

    snapshot = registry.quiesce_snapshot()
    for source, response in responses.items():
        assert response.status_code == 503, source
        payload: dict[str, object] = response.json()
        request_id = payload.get("request_id")
        assert isinstance(request_id, str), source
        assert payload == {
            "ok": False,
            "error": "quiesce_admission_closed",
            "message": _QUIESCE_SEARCH_MESSAGE,
            "retryable": True,
            "request_id": request_id,
            "quiesce": {
                "state": "quiesced",
                "admission_epoch": snapshot.admission_epoch,
                "safe_to_borrow_gpu": True,
            },
        }

    activity = search_activity_ledger().snapshot(include_query=True)
    recent = activity["recent"]
    for source in ("vault", "code", "document", "combined"):
        records = [
            record for record in recent if record.get("query") == f"{marker}-{source}"
        ]
        assert len(records) == 1
        record = records[0]
        assert record["status_code"] == 503
        assert record["outcome"] == "unavailable"
        assert record["error_code"] == "quiesce_admission_closed"
        assert record["error_message"] == _QUIESCE_SEARCH_MESSAGE
    assert registry.snapshot() == []
    assert registry.health() == {
        "model_loaded": False,
        "reranker_loaded": False,
        "cuda": False,
        "project_count": 0,
        "projects": [],
        "nonconforming": [],
    }
    assert registry.quiesce_snapshot() == snapshot
    assert snapshot.active_compute_tickets == 0
    assert snapshot.vram_released
    assert snapshot.safe_to_borrow_gpu


def test_search_transport_preserves_the_exact_quiesce_envelope() -> None:
    """The client returns the service's rejection unchanged, without fallback."""
    from ..serviceclient._transport import _try_http_search

    httpd = ThreadingHTTPServer(("127.0.0.1", 0), _QuiesceSearchEnvelopeHandler)
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.start()
    try:
        response = _try_http_search(
            query="closed admission must not fall back",
            search_type="vault",
            top_k=1,
            port=httpd.server_address[1],
            project_root="C:/loopback-vault",
        )
    finally:
        httpd.shutdown()
        server_thread.join(timeout=5)
        httpd.server_close()

    assert not server_thread.is_alive()
    assert response == {
        "ok": False,
        "error": "quiesce_admission_closed",
        "message": _QUIESCE_SEARCH_MESSAGE,
        "retryable": True,
        "request_id": "loopback-quiesce-admission",
        "quiesce": {
            "state": "quiesced",
            "admission_epoch": 4,
            "safe_to_borrow_gpu": True,
        },
    }


def test_admission_ticket_must_drain_before_registry_becomes_quiesced() -> None:
    """A pre-pause compute ticket keeps the shared search boundary fail-closed."""
    registry = ServiceRegistry()
    ticket = registry._quiesce_controller.acquire_ticket()
    try:
        timed_out = registry.quiesce_resources(timeout_seconds=0)

        assert timed_out.code is QuiesceTransitionCode.DRAIN_TIMED_OUT
        assert registry.quiesce_snapshot().state is QuiesceState.PAUSING
        assert registry.quiesce_snapshot().active_compute_tickets == 1
        assert registry.snapshot() == []
        assert registry.health()["cuda"] is False
    finally:
        assert ticket.release()

    quiesced = registry.quiesce_resources(timeout_seconds=0)

    assert quiesced.achieved
    assert registry.quiesce_snapshot().state is QuiesceState.QUIESCED
    assert registry.quiesce_snapshot().active_compute_tickets == 0


def test_quiesced_search_lease_rejects_before_project_or_compute_construction(
    tmp_path: Path,
) -> None:
    """Closed search admission cannot construct a store, model, or reranker."""
    registry = ServiceRegistry()

    assert registry.quiesce_resources(timeout_seconds=0).achieved

    with pytest.raises(QuiesceAdmissionClosedError), registry.search_lease(tmp_path):
        pass

    assert registry.snapshot() == []
    assert registry.health()["model_loaded"] is False
    assert registry.health()["reranker_loaded"] is False
    assert registry.health()["cuda"] is False
