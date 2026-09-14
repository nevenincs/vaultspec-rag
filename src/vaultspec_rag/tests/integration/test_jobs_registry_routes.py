"""Focused real-behavior coverage for the jobs registry."""

from __future__ import annotations

import asyncio
from pathlib import Path  # noqa: TC003
from typing import cast

import pytest

import vaultspec_rag.mcp._tools as tools

from ...indexer._run_ledger_models import RunAuthority
from ...serviceclient._transport import _try_http_reindex
from ._helpers import _make_root
from ._jobs_registry_support import wait_for_terminal_job


async def _seed_publication(port: int, root: Path, source: str) -> None:
    """Establish rebuild authority before exercising an MCP refresh."""
    response = await asyncio.to_thread(
        _try_http_reindex,
        source,
        True,
        port,
        str(root),
        authority=RunAuthority.REBUILD,
        initiator_kind="mcp",
    )
    assert response is not None
    assert response["ok"] is True, response
    job = await wait_for_terminal_job(cast("str", response["job_id"]))
    assert job["phase"] == "done", job


@pytest.mark.subprocess_gpu
async def test_reindex_vault_records_finished_tool_job(
    tmp_path: Path,
    live_service: tuple[int, Path],
) -> None:
    root = _make_root(tmp_path)
    await _seed_publication(live_service[0], root, "vault")

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
async def test_reindex_codebase_records_finished_tool_job(
    tmp_path: Path,
    live_service: tuple[int, Path],
) -> None:
    root = _make_root(tmp_path)
    await _seed_publication(live_service[0], root, "code")

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
