"""Compute-free production-route resource and search-evidence coverage."""

from __future__ import annotations

import socket
import uuid
from typing import cast

import pytest
from starlette.testclient import TestClient

from ..runtime_observations import runtime_observations
from ..server._main import create_http_app
from ..server._routes_search import (
    SearchActivityFinalization,
    _finish_search_activity,
    _record_provisional_activity,
)
from ..server._runtime import ServerRouteRuntime
from ..server._search_activity import (
    SearchActivityCompletion,
    SearchActivityFilters,
    SearchActivityLedger,
    SearchActivityRequest,
    SearchActivityStart,
)
from ..server._search_evidence import (
    MAX_LEDGER_EVIDENCE_BYTES,
    MAX_REQUEST_EVIDENCE_BYTES,
    MAX_RESPONSE_EVIDENCE_BYTES,
    capture_json_evidence,
)
from ..server._state import search_activity_ledger
from ..service import ServiceRegistry

pytestmark = pytest.mark.unit


def test_runtime_route_observes_real_ram_disk_models_and_tcp_peer() -> None:
    """Removing route token gating failed the 401 assertion (exit 1), then
    restoration passed this test (exit 0).
    """
    with socket.socket() as listener, socket.socket() as peer:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        peer.connect(("127.0.0.1", port))
        accepted, _ = listener.accept()
        with accepted:
            app = create_http_app(
                ServerRouteRuntime(
                    token="resource-test", registry=ServiceRegistry(), port=port
                ),
                lifespan=None,
            )
            with TestClient(app, base_url="http://127.0.0.1") as client:
                result = client.get(
                    "/runtime-observations",
                    headers={"Authorization": "Bearer resource-test"},
                )
                assert result.status_code == 200
                observed = result.json()
                assert observed["ram"]["process_rss_bytes"] > 0
                assert observed["ram"]["total_bytes"] > 0
                assert observed["disk"]["total_bytes"] >= observed["disk"]["free_bytes"]
                assert observed["models"]["embedding"]["loaded_name"] is None
                assert observed["models"]["embedding"]["configured_name"]
                assert observed["clients"]["kind"] == "observed_tcp_connections"
                assert observed["clients"]["items"] == [
                    {
                        "host": "127.0.0.1",
                        "port": peer.getsockname()[1],
                        "status": "ESTABLISHED",
                    }
                ]
                assert observed["cpu"]["process_percent_basis"] == "one_cpu_core"
                assert observed["quiesce"]["state"] == "running"
                assert isinstance(observed["pools"], dict)
                assert "system_utilization_percent" in observed["cpu"]
                assert client.get("/runtime-observations").status_code == 401


def test_runtime_missing_measurements_remain_null() -> None:
    """Injecting GPU memory zero failed the absent-reading assertion (exit 1),
    then restoration passed this test (exit 0).
    """
    result = runtime_observations(port=12345)
    ram = cast("dict[str, object]", result["ram"])
    gpu = cast("dict[str, object]", result["gpu"])
    if ram["available"] is True:
        assert cast("int", ram["process_rss_bytes"]) > 0
        assert cast("int", ram["total_bytes"]) > 0
    if gpu["available"] is False:
        assert gpu["memory_used_mib"] is None
        assert gpu["memory_total_mib"] is None
        assert gpu["reason"] == "accelerator_measurement_unavailable"
    else:
        assert cast("float", gpu["memory_used_mib"]) >= 0
        assert cast("float", gpu["memory_total_mib"]) > 0


def test_route_finalization_retains_detached_request_and_nested_response() -> None:
    """Adding a response on the redacted branch failed its exact omission
    assertion (exit 1), then restoration passed this test (exit 0).
    """
    ledger = search_activity_ledger()
    request_id = uuid.uuid4().hex
    filters = SearchActivityFilters(request_id=request_id)
    ticket = ledger.start(SearchActivityStart(request_id, "", "unknown", None, None))
    inputs: dict[str, object] = {
        "query": "related services",
        "type": "combined",
        "top_k": 4,
        "project_root": "/repo",
        "include_paths": ["src/**"],
        "language": "python",
        "token": "never retain this",
    }
    _record_provisional_activity(ticket, inputs)
    response: dict[str, object] = {
        "results": [
            {
                "id": "one",
                "path": "src/api.py",
                "score": 0.8,
                "snippet": "def related_service(): pass",
                "document_metadata": {"nested": [1, True]},
            }
        ],
        "readiness": {"sources": [{"source": "code", "freshness": "fresh"}]},
    }
    _finish_search_activity(
        ticket,
        SearchActivityFinalization(
            result=response, status_code=200, total_seconds=0.25
        ),
    )
    response["results"] = []
    app = create_http_app(
        ServerRouteRuntime(
            token="evidence-test", registry=ServiceRegistry(), port=8765
        ),
        lifespan=None,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        result = client.get(
            f"/search-activity?request_id={request_id}",
            headers={"Authorization": "Bearer evidence-test"},
        )
    record = result.json()["recent"][0]
    assert record["request_inputs"]["include_paths"] == ["src/**"]
    assert "token" not in record["request_inputs"]
    assert record["response"]["results"][0]["document_metadata"] == {
        "nested": [1, True]
    }
    assert record["response"]["readiness"]["sources"][0]["freshness"] == "fresh"
    assert record["result_count"] == 1
    assert record["evidence_truncated_paths"] == {"request_inputs": [], "response": []}
    record["response"]["results"] = []
    assert ledger.snapshot(include_query=True, filters=filters)["recent"][0]["response"]
    redacted = ledger.snapshot(include_query=False, filters=filters)["recent"][0]
    assert redacted["evidence_redacted"] is True
    assert "response" not in redacted
    assert "request_inputs" not in redacted


def test_json_evidence_bounds_unicode_nested_rows_and_paths() -> None:
    """Bypassing the capture budget failed the byte ceiling assertion (exit 1),
    then restoration passed this test (exit 0).
    """
    payload = {
        "results": [
            {"snippet": "🌳" * 9000, "metadata": {"value": "x" * 9000}}
            for _ in range(1000)
        ]
    }
    evidence = capture_json_evidence(payload, maximum_bytes=MAX_RESPONSE_EVIDENCE_BYTES)
    assert evidence.size_bytes <= MAX_RESPONSE_EVIDENCE_BYTES
    assert evidence.truncated_paths
    assert "$.results[0].snippet" in evidence.truncated_paths
    response = cast("dict[str, object]", evidence.materialize())
    assert len(cast("list[object]", response["results"])) < 1000


def test_rejected_search_keeps_its_actual_returned_validation_body() -> None:
    ledger = search_activity_ledger()
    app = create_http_app(
        ServerRouteRuntime(
            token="validation-test", registry=ServiceRegistry(), port=8765
        ),
        lifespan=None,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        returned = client.post(
            "/search",
            json={"query": "", "type": "code", "project_root": "/repo"},
            headers={"Authorization": "Bearer validation-test"},
        )
    record = ledger.snapshot(include_query=True)["recent"][0]
    assert returned.status_code == 400
    assert record["response"] == returned.json()
    assert record["status_code"] == returned.status_code
    assert record["outcome"] == "validation_rejected"


def test_whole_ledger_eviction_preserves_relational_rows_and_bounds_active_inputs() -> (
    None
):
    """Returning before ledger eviction failed its byte ceiling assertion
    (exit 1), then restoration passed this test (exit 0).
    """
    ledger = SearchActivityLedger(max_recent=100)
    inputs = {"query": "inspect", "include_paths": ["x" * 8000 for _ in range(128)]}
    response = {"results": [{"snippet": "s" * 8000} for _ in range(128)]}
    for index in range(50):
        ticket = ledger.start(
            SearchActivityStart(str(index), "inspect", "code", "/repo", 5)
        )
        ledger.update_request(
            ticket,
            request=SearchActivityRequest("inspect", "code", "/repo", 5, inputs=inputs),
        )
        assert ledger._evidence_bytes <= MAX_LEDGER_EVIDENCE_BYTES
        ledger.finish(
            ticket,
            completion=SearchActivityCompletion(
                outcome="success", status_code=200, result_count=128, response=response
            ),
        )
        assert ledger._evidence_bytes <= MAX_LEDGER_EVIDENCE_BYTES
    recent = ledger.snapshot(include_query=True)["recent"]
    assert len(recent) == 50
    assert recent[0]["response"] is not None
    assert recent[-1]["evidence_evicted"] is True
    assert recent[-1]["response"] is None
    assert recent[-1]["result_count"] == 128
    active = ledger.start(SearchActivityStart("active", "inspect", "code", "/repo", 5))
    ledger.update_request(
        active,
        request=SearchActivityRequest("inspect", "code", "/repo", 5, inputs=inputs),
    )
    retained = ledger._active[active.request_id]
    assert retained.request_inputs is not None
    assert retained.request_inputs.size_bytes <= MAX_REQUEST_EVIDENCE_BYTES
    assert ledger._evidence_bytes <= MAX_LEDGER_EVIDENCE_BYTES
