"""Integration tests for service search diagnostics."""

from __future__ import annotations

import socket
import time
from typing import TYPE_CHECKING, cast

import pytest

from ...cli._http_search import _do_http_call, _timeout_diagnostics, _try_http_search

if TYPE_CHECKING:
    from pathlib import Path


def _assert_search_phase_timing(result: dict[str, object]) -> dict[str, object]:
    timing = cast("dict[str, object]", result["timing"])
    for key in (
        "search_seconds",
        "model_load_seconds",
        "project_lease_seconds",
        "embedding_seconds",
        "qdrant_seconds",
        "rerank_seconds",
        "postprocess_seconds",
        "queue_wait_seconds",
    ):
        assert isinstance(timing[key], float)
    phases = cast("dict[str, object]", timing["phases"])
    for key in (
        "model_load_seconds",
        "project_lease_seconds",
        "embedding_seconds",
        "gpu_queue_wait_seconds",
        "queue_wait_seconds",
        "qdrant_seconds",
    ):
        assert isinstance(phases[key], float)
    assert timing["timing_scope"] == "server_route"
    return timing


def _assert_request_id(result: dict[str, object]) -> str:
    request_id = result["request_id"]
    assert isinstance(request_id, str)
    assert len(request_id) == 32
    return request_id


@pytest.mark.subprocess_gpu
def test_empty_service_search_reports_missing_index(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "empty-project"
    (root / ".vault").mkdir(parents=True)

    result = _try_http_search(
        "nothing should match this empty workspace",
        "vault",
        3,
        port,
        str(root),
        timeout=120,
    )

    assert isinstance(result, dict)
    _assert_request_id(result)
    assert result["results"] == []
    _assert_search_phase_timing(result)
    index_state = cast("dict[str, object]", result["index_state"])
    assert isinstance(index_state, dict)
    assert index_state["source"] == "vault"
    assert index_state["indexed_count"] == 0
    assert index_state["requested_target_root"] == str(root)
    assert index_state["target_matches"] is True
    empty = cast("dict[str, object]", result["empty"])
    assert isinstance(empty, dict)
    assert empty["reason"] == "index_missing"
    remediation = empty["remediation"]
    assert isinstance(remediation, list)
    assert any("index --type vault" in str(item) for item in remediation)


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
    _assert_request_id(result)
    assert result["results"] == []
    _assert_search_phase_timing(result)
    index_state = cast("dict[str, object]", result["index_state"])
    assert isinstance(index_state, dict)
    assert index_state["source"] == "code"
    assert index_state["indexed_count"] == 0
    empty = cast("dict[str, object]", result["empty"])
    assert isinstance(empty, dict)
    assert empty["reason"] == "index_missing"
    remediation = empty["remediation"]
    assert isinstance(remediation, list)
    assert any("index --type code" in str(item) for item in remediation)


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
    request_id = _assert_request_id(result)
    logs: dict[str, object] | None = None
    for _ in range(10):
        logs = _do_http_call(
            port,
            f"/logs/json?contains={request_id}",
            None,
            timeout=5,
        )
        if isinstance(logs, dict) and logs.get("lines"):
            break
        time.sleep(0.1)

    assert isinstance(logs, dict)
    lines = logs["lines"]
    assert isinstance(lines, list)
    assert any(
        request_id in str(line)
        and "service.search" in str(line)
        and "event=completed" in str(line)
        for line in lines
    )


@pytest.mark.subprocess_gpu
def test_service_search_short_timeout_reports_operational_diagnostics(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    port, _status_dir = live_service
    root = tmp_path / "timeout-project"
    (root / ".vault").mkdir(parents=True)

    result = _try_http_search(
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
    remediation = result["remediation"]
    assert health["status"] == "ready"
    assert jobs["available"] is True
    backpressure = cast("dict[str, object]", diagnostics["backpressure"])
    assert backpressure["active_indexing_conflict"] is False
    assert isinstance(remediation, list)
    assert f"vaultspec-rag server status --port {port}" in remediation
    assert any("server jobs --running" in str(item) for item in remediation)


def _unused_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def test_timeout_diagnostics_survive_unavailable_probe_port() -> None:
    result = _timeout_diagnostics(_unused_local_port(), 0.01)

    assert result["ok"] is False
    assert result["error"] == "http_search_timeout"
    diagnostics = cast("dict[str, object]", result["diagnostics"])
    health = cast("dict[str, object]", diagnostics["health"])
    jobs = cast("dict[str, object]", diagnostics["jobs"])
    backpressure = cast("dict[str, object]", diagnostics["backpressure"])
    assert health["available"] is False
    assert jobs["available"] is False
    assert backpressure["active_indexing_conflict"] is None


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
