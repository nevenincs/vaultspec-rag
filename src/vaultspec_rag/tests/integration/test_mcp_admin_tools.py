import asyncio

import pytest

from vaultspec_rag.mcp._admin_tools import evict_project, list_projects

pytestmark = [pytest.mark.subprocess_gpu]


@pytest.mark.usefixtures("live_service")
def test_list_projects_empty_registry() -> None:
    """With no slots, returns empty projects and config-matched caps."""
    from vaultspec_rag.config import get_config

    # live_service starts fresh, so registry is empty
    result = asyncio.run(list_projects())
    assert result["projects"] == []
    cfg = get_config()
    assert result["max_projects"] == cfg.service_max_projects
    assert result["idle_ttl_seconds"] == float(cfg.service_idle_ttl_seconds)


@pytest.mark.usefixtures("live_service")
def test_evict_project_unknown_returns_not_found(tmp_path) -> None:
    target = str(tmp_path / "never-seen")
    result = asyncio.run(evict_project(target))
    assert result == {"root": target, "evicted": False, "reason": "not_found"}
