"""Integration tests for service search diagnostics."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

from ...cli._http_search import _do_http_call, _try_http_search

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

    result = _try_http_search(
        "nothing should match this empty workspace",
        "vault",
        3,
        port,
        str(root),
        timeout=120,
    )

    assert isinstance(result, dict)
    assert result["results"] == []
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
    assert result["results"] == []
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
