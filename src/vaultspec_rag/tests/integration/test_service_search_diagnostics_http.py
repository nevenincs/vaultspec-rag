"""Search diagnostics over the direct HTTP route.

The route answers callers that never go through the client, so its own
contract - the type it accepts, the state it reports for an empty index,
and its refusal of a root outside a project - is asserted here.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.testclient import TestClient

from ..._search_state import SearchWaitCause, WaitObservation
from ...server import ServerRouteRuntime, create_http_app
from ...server import _routes_search as search_routes
from ...server import _state as server_state
from ...server._search_activity import (
    SearchActivityAdmissionError,
    SearchActivityLedger,
    SearchActivityStart,
    SearchActivityTicket,
)
from ...server._search_availability import SearchResponseClassification
from ...service import ServiceRegistry
from ...serviceclient._transport import _do_http_call
from .._search_readiness_scenarios import (
    SEARCH_READINESS_SCENARIOS,
    SearchReadinessScenario,
)
from ._service_search_diagnostics_support import (
    assert_empty_search_phase_timing,
    assert_request_id,
    raw_search,
    wait_for_search_log_line,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from ...server._routes_search import SearchAvailabilityRequestFacts


def _injected_domain_response(
    scenario: SearchReadinessScenario,
) -> dict[str, object]:
    response: dict[str, object] = {
        "request_id": scenario.request_id,
        "readiness": scenario.readiness(),
    }
    if scenario.failure is None:
        response["results"] = scenario.result_payloads()
        if len(scenario.source_facts) > 1:
            response.update({"ok": True, "partial": True, "domains": {}})
        return response
    response.update(
        {
            "ok": False,
            "error": scenario.failure.code,
            "message": scenario.failure.message,
            "retryable": scenario.failure.retryable,
            "remediation": scenario.failure.remediation,
        }
    )
    return response


@contextmanager
def _inject_classified_domain_outcome(
    scenario: SearchReadinessScenario,
) -> Generator[None]:
    """Inject classification before production completion and HTTP shaping."""
    response = _injected_domain_response(scenario)
    classification = SearchResponseClassification(
        response=response,
        status_code=503 if scenario.failure is not None else 200,
        matching_jobs=(),
        matching_jobs_truncated=False,
        rebuilding=scenario.failure is not None
        and scenario.failure.code == "rebuild_required",
        availability_cause=None,
        source_fact=scenario.source_facts[0],
    )
    original = search_routes._run_search_with_availability
    mutable_routes = cast("Any", search_routes)

    async def injected(
        run: Callable[[], dict[str, object]],
        facts: SearchAvailabilityRequestFacts,
    ) -> tuple[dict[str, object], SearchResponseClassification | None]:
        del run, facts
        return response, classification

    mutable_routes._run_search_with_availability = injected
    try:
        yield
    finally:
        mutable_routes._run_search_with_availability = original


def _production_route_response(
    tmp_path: Path, scenario: SearchReadinessScenario
) -> tuple[int, dict[str, object], dict[str, str]]:
    root = tmp_path / scenario.name
    (root / ".vault").mkdir(parents=True)
    app = create_http_app(
        ServerRouteRuntime(token="matrix-token", registry=ServiceRegistry(), port=8765),
        lifespan=None,
    )
    with (
        _inject_classified_domain_outcome(scenario),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/search",
            headers={"Authorization": "Bearer matrix-token"},
            json={
                "query": "canonical matrix",
                "type": "vault",
                "project_root": str(root),
            },
        )
    return response.status_code, response.json(), dict(response.headers)


class _QueueFullLedger(SearchActivityLedger):
    """Raise the production capacity exception before request execution."""

    def start(self, admission: SearchActivityStart) -> SearchActivityTicket:
        del admission
        raise SearchActivityAdmissionError(
            request_id="scenario-capacity",
            reason="queue_full",
            wait=WaitObservation(SearchWaitCause.SEARCH_ADMISSION, 0.0, 0.0, 0.0),
            deadline=None,
        )

    def finish(self, *_args: object, **_kwargs: object) -> bool:  # type: ignore[override]
        return False


@contextmanager
def _inject_queue_full_activity() -> Generator[None]:
    original = server_state._search_activity_ledger
    server_state._search_activity_ledger = _QueueFullLedger()
    try:
        yield
    finally:
        server_state._search_activity_ledger = original


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario",
    [
        scenario
        for scenario in SEARCH_READINESS_SCENARIOS.values()
        if scenario.name != "capacity_limited"
    ],
    ids=lambda item: item.name,
)
def test_readiness_matrix_uses_production_http_response_shaping(
    tmp_path: Path, scenario: SearchReadinessScenario
) -> None:
    status, body, headers = _production_route_response(tmp_path, scenario)

    # Mutation proof (rebuild_required): temporarily changing production's
    # rebuild status mapping from 409 to 200 made this exact assertion report
    # 200 != 409 (RED exit 1); in the same uninterrupted sequence, immediate
    # restoration made the identical node return 409 (GREEN exit 0).
    assert status == scenario.status_code
    assert body["request_id"] == scenario.request_id
    readiness = cast("dict[str, object]", body["readiness"])
    expected_readiness = scenario.readiness()
    assert readiness["aggregate"] == expected_readiness["aggregate"]
    sources = cast("list[dict[str, object]]", readiness["sources"])
    expected_sources = cast("list[dict[str, object]]", expected_readiness["sources"])
    assert [source["source"] for source in sources] == [
        fact.source for fact in scenario.source_facts
    ]
    for source, expected in zip(sources, expected_sources, strict=True):
        actual_without_waits = {
            key: value for key, value in source.items() if key != "waits"
        }
        expected_without_waits = {
            key: value for key, value in expected.items() if key != "waits"
        }
        assert actual_without_waits == expected_without_waits
        actual_waits = cast("list[dict[str, object]]", source["waits"])
        expected_waits = cast("list[dict[str, object]]", expected["waits"])
        assert actual_waits[: len(expected_waits)] == expected_waits
        assert actual_waits[-1]["cause"] == "search_admission"
    assert "retry-after" not in headers
    if scenario.failure is None:
        assert body["results"] == scenario.result_payloads()
    else:
        assert "results" not in body
        assert body["error"] == scenario.failure.code
        assert body["remediation"] == scenario.failure.remediation


@pytest.mark.unit
def test_matrix_capacity_without_reset_deadline_is_503_without_retry_after(
    tmp_path: Path,
) -> None:
    scenario = SEARCH_READINESS_SCENARIOS["capacity_limited"]
    root = tmp_path / "capacity"
    (root / ".vault").mkdir(parents=True)
    app = create_http_app(
        ServerRouteRuntime(token="matrix-token", registry=ServiceRegistry(), port=8765),
        lifespan=None,
    )
    with (
        _inject_queue_full_activity(),
        TestClient(app, raise_server_exceptions=False) as client,
    ):
        response = client.post(
            "/search",
            headers={"Authorization": "Bearer matrix-token"},
            json={"query": "capacity", "type": "vault", "project_root": str(root)},
        )
    body = cast("dict[str, object]", response.json())

    assert response.status_code == scenario.status_code == 503
    assert scenario.failure is not None
    assert body["error"] == "capacity_limited"
    assert "results" not in body
    assert body["request_id"] == scenario.request_id
    assert body["retryable"] is scenario.failure.retryable
    assert body["remediation"]
    assert cast("list[dict[str, object]]", body["waits"])[0]["cause"] == (
        "search_admission"
    )
    assert "retry-after" not in response.headers


@pytest.mark.subprocess_gpu
def test_direct_http_search_type_contract(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "search-type-contract-project"
    (root / ".vault").mkdir(parents=True)
    health = _do_http_call(port, "/health", None, timeout=5)
    assert isinstance(health, dict), health
    token = health.get("service_token")
    assert isinstance(token, str) and token, health

    # Compatibility aliases ("all", "codebase", ...) are accepted only at the
    # CLI/MCP boundary, which normalizes them before the wire; the /search
    # route itself requires the canonical vocabulary (allow_aliases=False),
    # so both an alias and a malformed (non-string) type are rejected the
    # same way here.
    for invalid_type in ("all", "codebase", ["code"]):
        status, _headers, body = raw_search(
            port,
            token,
            {
                "query": "",
                "type": invalid_type,
                "project_root": str(tmp_path / "missing-project"),
            },
            timeout=5,
        )
        assert status == 400, body
        assert body["ok"] is False, body
        assert body["error"] == "unknown_source_type", body
        assert body["error_kind"] == "unknown_source_type", body
        assert body["aliases_allowed"] is False, body
        message = str(body["message"])
        assert "'vault'" in message, body
        assert "'code'" in message, body
        assert "'document'" in message, body
        assert "'combined'" in message, body

    canonical_status, _canonical_headers, canonical_body = raw_search(
        port,
        token,
        {
            "query": "nothing should match this empty code workspace",
            "type": "code",
            "top_k": 3,
            "project_root": str(root),
        },
        timeout=120,
    )
    assert canonical_status == 200, canonical_body
    index_state = cast("dict[str, object]", canonical_body["index_state"])
    assert index_state["source"] == "code", canonical_body
    request_id = assert_request_id(canonical_body)
    canonical_log = wait_for_search_log_line(port, request_id)
    assert "source=code" in canonical_log
    assert "search_type=code" in canonical_log


@pytest.mark.subprocess_gpu
def test_direct_http_code_search_reports_code_index_state(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "empty-code-project"
    (root / ".vault").mkdir(parents=True)

    result = _do_http_call(
        port,
        "/search",
        {
            "query": "nothing should match this empty code workspace",
            "type": "code",
            "top_k": 3,
            "project_root": str(root),
        },
        timeout=120,
    )

    assert isinstance(result, dict)
    assert_request_id(result)
    assert result["results"] == []
    assert_empty_search_phase_timing(result)
    index_state = cast("dict[str, object]", result["index_state"])
    assert isinstance(index_state, dict)
    assert index_state["source"] == "code"
    assert index_state["indexed_count"] == 0
    assert set(index_state) == {
        "source",
        "indexed_count",
        "indexed_target_root",
        "requested_target_root",
        "target_matches",
        "status",
        "index_integrity",
    }
    empty = cast("dict[str, object]", result["empty"])
    assert isinstance(empty, dict)
    assert empty["reason"] == "index_missing"
    remediation = cast("list[object]", empty["remediation"])
    assert isinstance(remediation, list)
    assert any("index --type code" in str(item) for item in remediation)


@pytest.mark.subprocess_gpu
def test_direct_http_search_invalid_root_is_bad_request(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "not-a-vaultspec-project"
    root.mkdir()

    result = _do_http_call(
        port,
        "/search",
        {
            "query": "anything",
            "type": "vault",
            "top_k": 3,
            "project_root": str(root),
        },
        timeout=120,
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["error"] == "bad_request"
    assert "no .vault" in str(result["message"])
