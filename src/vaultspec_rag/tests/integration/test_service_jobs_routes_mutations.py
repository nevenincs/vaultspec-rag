"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from starlette.applications import Starlette

import vaultspec_rag.server as _m

from ... import jobs as _jobs
from ...server._routes import ROUTES

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path

    from ...job_manager.manager import JobManager


def _make_vault_roots(tmp_path: Path) -> tuple[Path, Path]:
    """Create the large-registry and target workspace roots under *tmp_path*."""
    large_root, target_root = tmp_path / "large-registry-entry", tmp_path / "target"
    for root in (large_root, target_root):
        (root / ".vault").mkdir(parents=True)
    return large_root, target_root


def _seed_persistence_backpressure(manager: JobManager, root: Path) -> None:
    """Create one real large terminal record before the ASGI overlap probe."""
    from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec

    entry = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.VAULT,
            project_root=str(root),
            mode=JobMode.INCREMENTAL,
        ),
        JobInitiator(
            kind="test",
            command="seed_real_persistence_backpressure",
            project_root=str(root),
        ),
    )
    assert entry.job is not None
    failed = manager.fail_unstarted(
        entry.job.id,
        result=("real-persistence-backpressure:" + ("x" * (32 * 1024 * 1024))),
    )
    assert failed.code == "job_failed_before_dispatch"


async def _assert_mutation_overlaps_auth_probe(
    client: httpx.AsyncClient,
    request: Coroutine[Any, Any, httpx.Response],
) -> httpx.Response:
    """Require a real durable mutation to yield to an ASGI auth request."""
    mutation = asyncio.create_task(request)
    await asyncio.sleep(0)
    probe = await client.get("/jobs")
    overlapped = not mutation.done()
    response = await mutation
    assert probe.status_code == 401
    assert overlapped, (
        "the durable mutation completed before an independent ASGI "
        "auth response could run"
    )
    return response


@pytest.mark.unit
async def test_job_mutations_keep_real_asgi_loop_responsive(
    tmp_path: Path,
) -> None:
    """Real durable CRUD writes must overlap an immediate ASGI auth response."""
    from ...config._settings import reset_config
    from ...config._types import EnvVar
    from ...jobs import get_job_manager, reset

    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_token = _m._SERVICE_TOKEN
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    reset_config()
    reset()
    _jobs.reset()
    token = "test-token-responsive-job-writes"
    _m._SERVICE_TOKEN = token
    headers = {"Authorization": f"Bearer {token}"}
    large_root, target_root = _make_vault_roots(tmp_path)

    try:
        manager = get_job_manager()
        _seed_persistence_backpressure(manager, large_root)

        app_under_test = Starlette(routes=ROUTES)
        transport = httpx.ASGITransport(app=app_under_test)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            created = await _assert_mutation_overlaps_auth_probe(
                client,
                client.post(
                    "/jobs",
                    headers=headers,
                    json={
                        "operation": "index",
                        "source": "vault",
                        "project_root": str(target_root),
                        "mode": "incremental",
                        "start_paused": True,
                    },
                ),
            )
            assert created.status_code == 202, created.text
            job = cast("dict[str, object]", created.json()["job"])
            job_id = str(job["id"])

            cancelled = await _assert_mutation_overlaps_auth_probe(
                client,
                client.put(
                    f"/jobs/{job_id}/desired-state",
                    headers=headers,
                    json={
                        "state": "cancelled",
                        "expected_revision": job["revision"],
                    },
                ),
            )
            assert cancelled.status_code == 200, cancelled.text

            manager.begin_shutdown()
            retried = await _assert_mutation_overlaps_auth_probe(
                client, client.post(f"/jobs/{job_id}/retry", headers=headers)
            )
            assert retried.status_code == 202, retried.text

            deleted = await _assert_mutation_overlaps_auth_probe(
                client, client.delete(f"/jobs/{job_id}", headers=headers)
            )
            assert deleted.status_code == 200, deleted.text
    finally:
        reset()
        _jobs.reset()
        _m._SERVICE_TOKEN = prior_token
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        reset_config()
