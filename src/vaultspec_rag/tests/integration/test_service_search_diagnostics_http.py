"""Search diagnostics over the direct HTTP route.

The route answers callers that never go through the client, so its own
contract - the type it accepts, the state it reports for an empty index,
and its refusal of a root outside a project - is asserted here.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ...serviceclient._transport import _do_http_call
from ._service_search_diagnostics_support import (
    assert_empty_search_phase_timing,
    assert_request_id,
    raw_search,
    wait_for_search_log_line,
)

if TYPE_CHECKING:
    from pathlib import Path


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
