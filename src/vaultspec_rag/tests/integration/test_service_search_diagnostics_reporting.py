"""What one search reports back to an operator.

These scenarios each drive a single search against a quiet service and
assert the report it produces: that an unindexed root is named as missing
rather than answered as empty, that the request id on the response is the
one that turns up in the structured log, and that a timeout still carries
health, jobs, and backpressure diagnostics an operator can act on -
including when the probe port answers nothing at all.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

import pytest

from ...serviceclient._search_transport import _timeout_diagnostics, try_http_search
from ...serviceclient._transport import _do_http_call
from .._ports import free_loopback_port
from ._service_search_diagnostics_support import (
    assert_empty_search_phase_timing,
    assert_request_id,
    wait_for_search_log_line,
)

if TYPE_CHECKING:
    from pathlib import Path


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
def test_service_search_short_timeout_reports_operational_diagnostics(
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
    assert result["error"] == "http_search_timeout"
    assert result["timeout_seconds"] == 0.000001
    diagnostics = cast("dict[str, object]", result["diagnostics"])
    health = cast("dict[str, object]", diagnostics["health"])
    jobs = cast("dict[str, object]", diagnostics["jobs"])
    remediation = cast("list[object]", result["remediation"])
    assert health["status"] == "ready"
    assert jobs["available"] is True
    backpressure = cast("dict[str, object]", diagnostics["backpressure"])
    assert backpressure["active_indexing_conflict"] is False
    assert isinstance(remediation, list)
    assert f"vaultspec-rag server status --port {port}" in remediation
    assert any("server jobs --state active" in str(item) for item in remediation)


@pytest.mark.unit
def test_timeout_diagnostics_survive_unavailable_probe_port() -> None:
    result = _timeout_diagnostics(free_loopback_port(), 0.01)

    assert result["ok"] is False
    assert result["error"] == "http_search_timeout"
    diagnostics = cast("dict[str, object]", result["diagnostics"])
    health = cast("dict[str, object]", diagnostics["health"])
    jobs = cast("dict[str, object]", diagnostics["jobs"])
    backpressure = cast("dict[str, object]", diagnostics["backpressure"])
    assert health["available"] is False
    assert jobs["available"] is False
    assert backpressure["active_indexing_conflict"] is None
