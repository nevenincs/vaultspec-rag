"""Focused real-behavior coverage for the jobs registry."""

from __future__ import annotations

from pathlib import Path  # noqa: TC003
from typing import cast

import pytest

import vaultspec_rag.mcp._tools as tools

from ._helpers import _make_root
from ._jobs_registry_support import wait_for_terminal_job


@pytest.mark.subprocess_gpu
@pytest.mark.usefixtures("live_service")
async def test_reindex_vault_records_finished_tool_job(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)

    response = await tools.reindex_vault(project_root=str(root))
    assert isinstance(response, dict)
    assert response["ok"] is True
    assert "job_id" in response

    job_id: str = cast("str", response["job_id"])
    job = await wait_for_terminal_job(job_id)
    assert job["source"] == "vault"
    assert job["trigger"] == "tool"
    assert job["phase"] == "done"
    assert isinstance(job["finished_at"], float)
    assert isinstance(job["result"], str)


@pytest.mark.subprocess_gpu
@pytest.mark.usefixtures("live_service")
async def test_reindex_codebase_records_finished_tool_job(
    tmp_path: Path,
) -> None:
    root = _make_root(tmp_path)

    response = await tools.reindex_codebase(project_root=str(root))
    assert isinstance(response, dict)
    assert response["ok"] is True
    assert "job_id" in response

    job_id: str = cast("str", response["job_id"])
    job = await wait_for_terminal_job(job_id)
    assert job["source"] == "code"
    assert job["trigger"] == "tool"
    assert job["phase"] == "done"
    assert isinstance(job["finished_at"], float)
    assert isinstance(job["result"], str)
