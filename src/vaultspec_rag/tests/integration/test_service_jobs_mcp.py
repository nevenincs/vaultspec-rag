"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, cast

import pytest

import vaultspec_rag.mcp._admin_client as admin
import vaultspec_rag.mcp._tools as tools

from ._service_jobs_support import (
    _assert_cli_job_attribution,
    _assert_mcp_job_snapshot,
    _wait_for_terminal_jobs,
)

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_returns_snapshot_shape(
    live_service: tuple[int, Path],
    tmp_path: Path,
) -> None:
    # Trigger a real job so the daemon has one in its registry.
    # We use an empty tmp_path so the reindex is near-instant.
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vaultspec").mkdir(parents=True, exist_ok=True)
    mcp_job = await tools.reindex_vault(project_root=str(tmp_path))

    result = await _wait_for_terminal_jobs(cast("str", mcp_job["job_id"]))
    _assert_mcp_job_snapshot(
        result,
        job_id=mcp_job["job_id"],
        project_root=tmp_path,
    )
    await _assert_cli_job_attribution(
        port=live_service[0],
        project_root=tmp_path,
        mcp_job_id=mcp_job["job_id"],
    )


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_terminal_job_wait_honours_subsecond_deadline(
    live_service: tuple[int, Path],  # noqa: ARG001
) -> None:
    """Real filtered admin polling cannot overrun its caller's short budget."""
    started = time.monotonic()
    with pytest.raises(
        AssertionError,
        match=r"did not reach a terminal phase within 0\.05s",
    ) as caught:
        await _wait_for_terminal_jobs("nonexistent-job", timeout=0.05)
    assert time.monotonic() - started < 1.0
    assert "last_job=None" in str(caught.value)
    assert "last_response=" in str(caught.value)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_is_newest_first(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    (first_root / ".vault").mkdir(parents=True, exist_ok=True)
    (first_root / ".vaultspec").mkdir(parents=True, exist_ok=True)
    (second_root / ".vault").mkdir(parents=True, exist_ok=True)
    (second_root / ".vaultspec").mkdir(parents=True, exist_ok=True)
    job1 = await tools.reindex_vault(project_root=str(first_root))
    job2 = await tools.reindex_vault(project_root=str(second_root))
    await _wait_for_terminal_jobs(cast("str", job1["job_id"]))
    await _wait_for_terminal_jobs(cast("str", job2["job_id"]))

    jobs = (await admin.get_jobs())["jobs"]
    # The list is newest-first, so job2 should appear before job1
    ids = [entry["id"] for entry in jobs]
    assert ids.index(job2["job_id"]) < ids.index(job1["job_id"])


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_honours_limit(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    # Distinct roots exercise the view limit without collapsing equivalent
    # active work through the canonical deduplication contract.
    for number in range(3):
        project_root = tmp_path / f"project-{number}"
        (project_root / ".vault").mkdir(parents=True, exist_ok=True)
        (project_root / ".vaultspec").mkdir(parents=True, exist_ok=True)
        await tools.reindex_vault(project_root=str(project_root))

    jobs = (await admin.get_jobs(limit=2))["jobs"]
    assert len(jobs) == 2


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_filters_by_source(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vaultspec").mkdir(parents=True, exist_ok=True)
    await tools.reindex_vault(project_root=str(tmp_path))
    await tools.reindex_codebase(project_root=str(tmp_path))

    jobs = (await admin.get_jobs(source="code"))["jobs"]

    assert jobs
    assert all(entry["source"] == "code" for entry in jobs)


@pytest.mark.integration
@pytest.mark.subprocess_gpu
async def test_get_jobs_non_positive_limit_is_empty(
    live_service: tuple[int, Path],  # noqa: ARG001
    tmp_path: Path,
) -> None:
    (tmp_path / ".vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / ".vaultspec").mkdir(parents=True, exist_ok=True)
    await tools.reindex_vault(project_root=str(tmp_path))
    assert (await admin.get_jobs(limit=0))["jobs"] == []
