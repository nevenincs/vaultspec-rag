"""Unit coverage for service search diagnostic payloads."""

from __future__ import annotations

from typing import cast


def test_search_index_state_uses_selected_source_preflight_count() -> None:
    from ..server._routes import _search_index_state

    state = _search_index_state(
        indexed_count=37,
        requested_root="C:/work/project",
        search_type="codebase",
    )

    assert state == {
        "source": "code",
        "indexed_count": 37,
        "indexed_target_root": "C:/work/project",
        "requested_target_root": "C:/work/project",
        "target_matches": True,
        "status": "available",
    }


def test_empty_search_diagnostics_use_supported_jobs_filter() -> None:
    from ..server._routes import _empty_search_diagnostics

    diagnostics = _empty_search_diagnostics(
        {
            "source": "code",
            "indexed_count": 0,
        },
        port=8766,
    )

    remediation = cast("list[object]", diagnostics["remediation"])
    assert isinstance(remediation, list)
    assert "vaultspec-rag server jobs --state active --port 8766" in remediation
    assert all("--running" not in str(item) for item in remediation)
