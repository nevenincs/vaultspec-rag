import asyncio

import pytest

from vaultspec_rag.mcp._admin_tools import evict_project, list_projects

pytestmark = [pytest.mark.subprocess_gpu]


def test_list_projects_empty_registry(live_service) -> None:
    """With no slots, returns empty projects and config-matched caps."""
    from vaultspec_rag.config import get_config

    # live_service starts fresh, so registry is empty
    result = asyncio.run(list_projects())
    assert result["projects"] == []
    cfg = get_config()
    assert result["max_projects"] == cfg.service_max_projects
    assert result["idle_ttl_seconds"] == float(cfg.service_idle_ttl_seconds)


def test_evict_project_unknown_returns_not_found(live_service, tmp_path) -> None:
    result = asyncio.run(evict_project(str(tmp_path / "never-seen")))
    assert result == {"evicted": False, "reason": "not_found"}
