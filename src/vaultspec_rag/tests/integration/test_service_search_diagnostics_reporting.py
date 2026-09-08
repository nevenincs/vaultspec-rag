"""What one search reports back to an operator.

These scenarios each drive a single search against a quiet service and
assert the report it produces: that an unindexed root is named as missing
rather than answered as empty, that the request id on the response is the
one that turns up in the structured log, and that a client transport timeout
does not manufacture service readiness diagnostics.
"""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, cast

import pytest

from ...serviceclient._search_transport import try_http_search
from ...serviceclient._transport import _do_http_call
from .._search_readiness_scenarios import (
    SEARCH_READINESS_SCENARIOS,
    SearchReadinessScenario,
    canonical_service_envelope,
)
from ..test_cli_search import _invoke_readiness_search, _search_envelope_service
from ._service_search_diagnostics_support import (
    assert_empty_search_phase_timing,
    assert_request_id,
    wait_for_search_log_line,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario", SEARCH_READINESS_SCENARIOS.values(), ids=lambda item: item.name
)
def test_cli_json_preserves_shared_readiness_scenario(
    tmp_path: Path, scenario: SearchReadinessScenario
) -> None:
    payload = canonical_service_envelope(scenario)
    with _search_envelope_service(payload, status=scenario.status_code) as (
        port,
        requests,
    ):
        result = _invoke_readiness_search(tmp_path, port, "--json")

    assert result.exit_code == (0 if scenario.failure is None else 1)
    expected = dict(payload)
    expected.update({"query": "readiness", "search_type": "code", "via": "service"})
    emitted = json.loads(result.output)
    if scenario.failure is None:
        # Mutation proof (current): temporarily removing readiness while the
        # CLI copied the service payload failed this exact JSON parity assertion
        # (RED exit 1); immediate restoration passed the identical node (GREEN 0).
        assert emitted == {"ok": True, "command": "search", "data": expected}
    else:
        failure_expected = dict(payload)
        failure_expected["command"] = "search"
        assert emitted == failure_expected
        assert "results" not in emitted
    assert requests == [
        {
            "query": "readiness",
            "type": "code",
            "top_k": 10,
            "project_root": str(tmp_path.resolve()),
            "freshness_policy": "immediate",
        }
    ]


@pytest.mark.unit
@pytest.mark.parametrize(
    "scenario", SEARCH_READINESS_SCENARIOS.values(), ids=lambda item: item.name
)
def test_cli_human_renders_shared_readiness_scenario(
    tmp_path: Path, scenario: SearchReadinessScenario
) -> None:
    payload = canonical_service_envelope(scenario)
    with _search_envelope_service(payload, status=scenario.status_code) as (
        port,
        _requests,
    ):
        result = _invoke_readiness_search(tmp_path, port)

    assert result.exit_code == (0 if scenario.failure is None else 1)
    aggregate = scenario.aggregate
    assert (
        f"Readiness: {aggregate.availability.value} / {aggregate.freshness.value} / "
        f"{aggregate.absence_authority.value}"
    ) in result.output
    for fact in scenario.source_facts:
        assert f"{fact.source}: {fact.availability.value}, {fact.freshness.value}" in (
            result.output
        )
        assert len(fact.reason_code or "") <= 256
        assert all(len(item) <= 256 for item in fact.evidence)
        for wait in fact.waits:
            assert f"Wait {fact.source} {wait.cause.value}:" in result.output
    if scenario.failure is not None:
        assert f"Code: {scenario.failure.code}" in result.output
        assert scenario.failure.remediation in result.output
        assert result.output.count(scenario.failure.remediation) == 1
    elif scenario.name == "authoritative_empty":
        assert "No source code results found" in result.output
    elif scenario.name in {"updating", "mixed_combined"}:
        assert scenario.results[0].text in result.output


@pytest.mark.subprocess_gpu
def test_empty_service_search_reports_missing_index(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "empty-project"
    (root / ".vault").mkdir(parents=True)

    result = try_http_search(
        "nothing should match this empty workspace",
        "vault",
        3,
        port,
        str(root),
        timeout=120,
    )

    assert isinstance(result, dict)
    assert_request_id(result)
    assert result["results"] == []
    assert_empty_search_phase_timing(result)
    index_state = cast("dict[str, object]", result["index_state"])
    assert isinstance(index_state, dict)
    assert index_state["source"] == "vault"
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
    assert index_state["requested_target_root"] == str(root)
    assert index_state["target_matches"] is True
    empty = cast("dict[str, object]", result["empty"])
    assert isinstance(empty, dict)
    assert empty["reason"] == "index_missing"
    remediation = cast("list[object]", empty["remediation"])
    assert isinstance(remediation, list)
    assert any("index --type vault" in str(item) for item in remediation)


@pytest.mark.subprocess_gpu
def test_search_request_id_is_log_correlatable(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "request-id-project"
    (root / ".vault").mkdir(parents=True)

    result = _do_http_call(
        port,
        "/search",
        {
            "query": "correlate this search request",
            "type": "code",
            "top_k": 1,
            "project_root": str(root),
        },
        timeout=120,
    )

    assert isinstance(result, dict)
    request_id = assert_request_id(result)
    completed_log = wait_for_search_log_line(port, request_id)
    assert "service.search event=completed status_code=200" in completed_log
    assert f"request_id={request_id}" in completed_log
    assert "source=code" in completed_log
    assert "search_type=code" in completed_log
    assert f"root={root}" in completed_log
    assert "results=0" in completed_log
    assert re.search(r"\btotal_seconds=\d+\.\d{3}\b", completed_log)


@pytest.mark.subprocess_gpu
def test_service_search_short_timeout_remains_transport_only(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "timeout-project"
    (root / ".vault").mkdir(parents=True)

    result = try_http_search(
        "this request intentionally has an unrealistically short timeout",
        "vault",
        3,
        port,
        str(root),
        timeout=0.000001,
    )

    assert isinstance(result, dict)
    assert result["ok"] is False
    assert result["error"] == "http_call_failed"
    assert isinstance(result["message"], str)
    assert set(result) == {"ok", "error", "message"}
