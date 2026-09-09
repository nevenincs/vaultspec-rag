"""Unit tests for admin-tool URL routing in _http_search (no mocks)."""

from __future__ import annotations

import asyncio
import json
import os
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.requests import Request

from .._search_state import FreshnessWaitPolicy
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..server._main import create_http_app
from ..server._routes_search import (
    SearchRequest,
    SearchRouteError,
    _admit_requested_freshness,
    _capture_publication_targets,
    _execute_search_route,
    _execute_search_until_disconnect,
    _normalise_search_request,
)
from ..server._runtime import ServerRouteRuntime
from ..service import ServiceRegistry
from ..serviceclient._transport import _logs_route_path

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestLogsRoutePath:
    """get_logs must target /logs/json (JSON body), not plaintext /logs."""

    def test_routes_to_json_endpoint(self) -> None:
        assert _logs_route_path({}) == "/logs/json"

    def test_appends_lines_query(self) -> None:
        path = _logs_route_path({"lines": 50})
        assert path == "/logs/json?lines=50"
        assert path != "/logs" and not path.startswith("/logs?")

    def test_appends_filter_query(self) -> None:
        path = _logs_route_path(
            {"lines": 50, "job_id": "abc123", "contains": "Qdrant ready"}
        )
        assert path.startswith("/logs/json?")
        assert "lines=50" in path
        assert "job_id=abc123" in path
        assert "contains=Qdrant+ready" in path


def _payload(root: Path, **extra: object) -> dict[str, object]:
    (root / ".vault").mkdir(exist_ok=True)
    return {
        "project_root": str(root),
        "query": "readiness",
        "type": "code",
        **extra,
    }


def _normalised(root: Path, **extra: object) -> SearchRequest:
    result = _normalise_search_request(_payload(root, **extra), "request-1")
    assert isinstance(result, SearchRequest)
    return result


def _error_body(result: SearchRequest | SearchRouteError) -> dict[str, object]:
    assert isinstance(result, SearchRouteError)
    return cast("dict[str, object]", json.loads(bytes(result.response.body)))


def test_search_freshness_policy_defaults_to_immediate(tmp_path: Path) -> None:
    request = _normalised(tmp_path)

    assert request.freshness_policy is FreshnessWaitPolicy.IMMEDIATE
    assert request.freshness_wait_seconds == 0


@pytest.mark.parametrize(
    ("extra", "expected"),
    [
        (
            {"freshness_policy": None},
            "freshness_policy must be 'immediate' or 'bounded'",
        ),
        (
            {"freshness_policy": "eventual"},
            "freshness_policy must be 'immediate' or 'bounded'",
        ),
        (
            {"freshness_wait_seconds": 1},
            "freshness_wait_seconds requires freshness_policy 'bounded'",
        ),
        (
            {"freshness_policy": "bounded"},
            "freshness_wait_seconds must be a finite number between 0 and 30",
        ),
        (
            {"freshness_policy": "bounded", "freshness_wait_seconds": "1"},
            "freshness_wait_seconds must be a finite number between 0 and 30",
        ),
        (
            {"freshness_policy": "bounded", "freshness_wait_seconds": -0.1},
            "freshness_wait_seconds must be a finite number between 0 and 30",
        ),
        (
            {"freshness_policy": "bounded", "freshness_wait_seconds": float("inf")},
            "freshness_wait_seconds must be a finite number between 0 and 30",
        ),
    ],
)
def test_search_freshness_policy_rejects_malformed_inputs(
    tmp_path: Path,
    extra: dict[str, object],
    expected: str,
) -> None:
    body = _error_body(_normalise_search_request(_payload(tmp_path, **extra), "bad"))

    assert body == {"ok": False, "error": "bad_request", "message": expected}


def test_bounded_policy_rejects_bool_with_exact_envelope(tmp_path: Path) -> None:
    # Removing the bool guard produced SearchRequest(True -> 1.0), failing
    # _error_body's SearchRouteError assertion; restoration passed this test.
    result = _normalise_search_request(
        _payload(
            tmp_path,
            freshness_policy="bounded",
            freshness_wait_seconds=True,
        ),
        "bool-bound",
    )

    assert _error_body(result) == {
        "ok": False,
        "error": "bad_request",
        "message": "freshness_wait_seconds must be a finite number between 0 and 30",
    }


def test_search_freshness_bound_uses_configured_maximum(tmp_path: Path) -> None:
    variable = EnvVar.SEARCH_FRESHNESS_WAIT_MAX_SECONDS.value
    previous = os.environ.get(variable)
    os.environ[variable] = "2.5"
    reset_config()
    try:
        body = _error_body(
            _normalise_search_request(
                _payload(
                    tmp_path,
                    freshness_policy="bounded",
                    freshness_wait_seconds=2.5001,
                ),
                "too-long",
            )
        )
        assert body == {
            "ok": False,
            "error": "bad_request",
            "message": (
                "freshness_wait_seconds must be a finite number between 0 and 2.5"
            ),
        }
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        reset_config()


def test_positive_bounded_policy_is_normalized(tmp_path: Path) -> None:
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=2,
    )

    assert request.freshness_policy is FreshnessWaitPolicy.BOUNDED
    assert request.freshness_wait_seconds == 2.0


@pytest.mark.asyncio
async def test_immediate_policy_never_requires_a_readiness_registry(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()

    admission = await _admit_requested_freshness(_normalised(tmp_path), registry)

    assert admission.outcome == "immediate"


@pytest.mark.asyncio
async def test_in_flight_wait_keeps_its_admitted_publication_target(
    tmp_path: Path,
) -> None:
    # Disabling generation matching made stale "first" satisfy "second" and
    # failed len(_observers) == 1 with 0; restoration passed this test.
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    first = readiness.notify_controller(tmp_path, "code", generation="first")
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=1,
    )

    waiting = asyncio.create_task(_admit_requested_freshness(request, registry))
    for _ in range(10):
        if readiness._observers:
            break
        await asyncio.sleep(0)
    assert len(readiness._observers) == 1
    readiness.notify_controller(tmp_path, "code", generation="second")
    readiness.publish_next(tmp_path, "code", generation="first")

    assert (await waiting).outcome == "satisfied"
    newly_admitted = _capture_publication_targets(request, readiness)
    assert newly_admitted is not None
    assert first.controller_revision == 1
    assert newly_admitted[0].revision == 2
    assert newly_admitted[0].generation == "second"
    second_wait = asyncio.create_task(_admit_requested_freshness(request, registry))
    for _ in range(10):
        if readiness._observers:
            break
        await asyncio.sleep(0)
    assert len(readiness._observers) == 1
    assert not second_wait.done()

    readiness.publish_next(tmp_path, "code", generation="second")

    assert (await second_wait).outcome == "satisfied"


@pytest.mark.asyncio
async def test_bounded_request_returns_typed_unverifiable_before_retrieval(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=0,
    )

    result = await _execute_search_route(request, None, registry)

    assert result.status_code == 503
    assert result.result["ok"] is False
    assert result.result["error"] == "index_unverifiable"
    assert "results" not in result.result


@pytest.mark.asyncio
async def test_bounded_request_returns_typed_timeout_before_retrieval(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    readiness.publish_next(tmp_path, "code", generation="served")
    readiness.notify_controller(tmp_path, "code", generation="desired")
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=0,
    )

    result = await _execute_search_route(request, None, registry)

    assert result.status_code == 503
    assert result.result["ok"] is False
    assert result.result["error"] == "freshness_wait_timeout"
    assert result.result["retryable"] is True
    assert result.result["request_id"] == request.request_id
    assert result.result["remediation"] == "vaultspec-rag server status --verbose"
    assert "results" not in result.result
    readiness_block = cast("dict[str, object]", result.result["readiness"])
    sources = cast("list[dict[str, object]]", readiness_block["sources"])
    assert len(sources) == 1
    source = sources[0]
    assert source["source"] == "code"
    assert source["availability"] == "usable"
    assert source["freshness"] == "updating"
    assert source["absence_authority"] == "non_authoritative"
    assert source["reason_code"] == "freshness_wait_timeout"
    assert source["generation"] == {
        "served_generation": "served",
        "desired_generation": "desired",
        "served_revision": 1,
        "desired_revision": 2,
    }
    assert source["waits"] == [
        {
            "cause": "controller_deferral",
            "waited_seconds": 0.0,
            "configured_bound_seconds": 0.0,
            "remaining_bound_seconds": 0.0,
        }
    ]
    assert source["evidence"] == ["target_revision:2"]
    assert readiness_block["aggregate"] == {
        "availability": "usable",
        "freshness": "updating",
        "absence_authority": "non_authoritative",
        "source_count": 1,
        "usable_source_count": 1,
        "degraded_sources": ["code"],
    }


@pytest.mark.asyncio
async def test_timeout_without_prior_publication_is_unavailable_and_unverifiable(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    registry.readiness_registry.notify_controller(
        tmp_path, "code", generation="desired"
    )
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=0,
    )

    result = await _execute_search_route(request, None, registry)

    readiness = cast("dict[str, object]", result.result["readiness"])
    source = cast("list[dict[str, object]]", readiness["sources"])[0]
    assert result.status_code == 503
    assert result.result["error"] == "freshness_wait_timeout"
    assert source["availability"] == "unavailable"
    assert source["freshness"] == "unverifiable"
    assert source["absence_authority"] == "non_authoritative"
    assert source["generation"] == {
        "desired_generation": "desired",
        "desired_revision": 1,
    }


@pytest.mark.asyncio
async def test_cancellation_propagates_and_unregisters_without_response(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    readiness.notify_controller(tmp_path, "code", generation="desired")
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=30,
    )
    executing = asyncio.create_task(_execute_search_route(request, None, registry))
    for _ in range(10):
        if readiness._observers:
            break
        await asyncio.sleep(0)
    assert len(readiness._observers) == 1

    executing.cancel()
    with pytest.raises(asyncio.CancelledError):
        await executing

    assert readiness._observers == {}


@pytest.mark.asyncio
async def test_asgi_disconnect_cancels_without_response_and_cleans_waiter(
    tmp_path: Path,
) -> None:
    # Bypassing the disconnect race returned a timeout and failed with DID NOT
    # RAISE CancelledError; restoration passed this test.
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    readiness.notify_controller(tmp_path, "code", generation="desired")
    token = "disconnect-readiness-token"
    app = create_http_app(
        ServerRouteRuntime(token=token, registry=registry, port=8765),
        lifespan=None,
    )
    payload = json.dumps(
        _payload(
            tmp_path,
            freshness_policy="bounded",
            freshness_wait_seconds=30,
        )
    ).encode()
    inbound: asyncio.Queue[dict[str, object]] = asyncio.Queue()
    inbound.put_nowait({"type": "http.request", "body": payload, "more_body": False})
    sent: list[dict[str, object]] = []

    async def receive() -> dict[str, object]:
        return await inbound.get()

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/search",
        "raw_path": b"/search",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8765),
        "state": {},
    }
    serving = asyncio.create_task(
        app(
            cast("Any", scope),
            cast("Any", receive),
            cast("Any", send),
        )
    )
    for _ in range(20):
        if readiness._observers:
            break
        await asyncio.sleep(0)
    assert len(readiness._observers) == 1

    inbound.put_nowait({"type": "http.disconnect"})
    with pytest.raises(asyncio.CancelledError):
        await serving

    assert sent == []
    assert readiness._observers == {}


def _receive_only_request(
    receive: Any,
) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/search",
            "headers": [],
            "query_string": b"",
        },
        receive=receive,
    )


@pytest.mark.asyncio
async def test_outer_handler_cancellation_cleans_both_owned_tasks(
    tmp_path: Path,
) -> None:
    # Removing execution-task cancellation from the wrapper finally left one
    # readiness observer and failed the exact empty-registry assertion; restored passed.
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    readiness.notify_controller(tmp_path, "code", generation="desired")
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=30,
    )
    receiver_finished = asyncio.Event()

    async def receive() -> dict[str, object]:
        try:
            await asyncio.Event().wait()
        finally:
            receiver_finished.set()
        raise AssertionError("cancelled receiver resumed")

    handling = asyncio.create_task(
        _execute_search_until_disconnect(
            _receive_only_request(receive), request, None, registry
        )
    )
    for _ in range(20):
        if readiness._observers:
            break
        await asyncio.sleep(0)
    assert len(readiness._observers) == 1

    handling.cancel()
    with pytest.raises(asyncio.CancelledError):
        await handling

    assert readiness._observers == {}
    assert receiver_finished.is_set()


@pytest.mark.asyncio
async def test_simultaneous_disconnect_wins_over_execution_completion(
    tmp_path: Path,
) -> None:
    # Prioritizing a simultaneously completed execution returned a 503 and
    # failed with DID NOT RAISE CancelledError; restoration passed this test.
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=0,
    )

    async def receive() -> dict[str, object]:
        return {"type": "http.disconnect"}

    with pytest.raises(asyncio.CancelledError):
        await _execute_search_until_disconnect(
            _receive_only_request(receive), request, None, registry
        )


@pytest.mark.asyncio
async def test_normal_completion_cleans_pending_disconnect_listener(
    tmp_path: Path,
) -> None:
    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=0,
    )
    receiver_finished = asyncio.Event()

    async def receive() -> dict[str, object]:
        try:
            await asyncio.Event().wait()
        finally:
            receiver_finished.set()
        raise AssertionError("cancelled receiver resumed")

    result = await _execute_search_until_disconnect(
        _receive_only_request(receive), request, None, registry
    )

    assert result.result["error"] == "index_unverifiable"
    assert receiver_finished.is_set()


@pytest.mark.asyncio
async def test_receive_failure_escapes_and_cleans_execution_waiter(
    tmp_path: Path,
) -> None:
    # Replacing ``await disconnected`` with unconditional CancelledError masked
    # ReceiveTransportError; the exact exception assertion failed. Restoration passed.
    class ReceiveTransportError(RuntimeError):
        pass

    registry = ServiceRegistry()
    registry.start_readiness(asyncio.get_running_loop())
    readiness = registry.readiness_registry
    readiness.notify_controller(tmp_path, "code", generation="desired")
    request = _normalised(
        tmp_path,
        freshness_policy="bounded",
        freshness_wait_seconds=30,
    )

    async def receive() -> dict[str, object]:
        raise ReceiveTransportError("receive transport failed")

    with pytest.raises(ReceiveTransportError, match=r"^receive transport failed$"):
        await _execute_search_until_disconnect(
            _receive_only_request(receive), request, None, registry
        )

    assert readiness._observers == {}
