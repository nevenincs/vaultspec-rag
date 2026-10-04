"""Focused real-behavior coverage for the managed service jobs surface."""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ... import jobs as _jobs
from ...indexer._run_ledger_models import RunAuthority
from ...job_control import RunControlToken
from ...job_dispatch import (
    _admit_attempt_mode,
    _AttemptDispatch,
    _run_indexing_attempt,
)
from ...job_manager.manager import JobManager
from ...job_manager.models import JobAttemptContext
from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ...server import ServerRouteRuntime, create_http_app
from ...server._routes import InvalidJobRequestError, validated_index_request
from ...service import ServiceRegistry
from ...service_quiesce import ServiceQuiesceController

if TYPE_CHECKING:
    from collections.abc import Coroutine
    from pathlib import Path


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "authority"),
    [
        (JobMode.INCREMENTAL, RunAuthority.PUBLICATION),
        (JobMode.INCREMENTAL, RunAuthority.REBUILD),
        (JobMode.REBUILD, RunAuthority.REBUILD),
    ],
)
async def test_generic_service_admission_preserves_closed_authority(
    tmp_path: Path,
    mode: JobMode,
    authority: RunAuthority,
) -> None:
    """The generic HTTP adapter must retain the exact admitted enum member."""
    (tmp_path / ".vault").mkdir()
    spec, _initiator, _admission = await validated_index_request(
        {
            "operation": "index",
            "source": "vault",
            "project_root": str(tmp_path),
            "mode": mode.value,
            "authority": authority.value,
        },
    )

    assert spec.mode is mode
    assert spec.authority is authority


@pytest.mark.unit
@pytest.mark.parametrize(
    ("case", "mode", "raw_authority"),
    [
        ("missing", JobMode.INCREMENTAL, None),
        ("empty", JobMode.INCREMENTAL, ""),
        ("non-text", JobMode.INCREMENTAL, 1),
        ("unknown", JobMode.INCREMENTAL, "migration"),
        ("publication-rebuild", JobMode.REBUILD, "publication"),
        ("audit-incremental", JobMode.INCREMENTAL, "audit_verification"),
    ],
)
async def test_generic_service_admission_rejects_invalid_authority(
    tmp_path: Path,
    case: str,
    mode: JobMode,
    raw_authority: object,
) -> None:
    """Missing, open-vocabulary, and forbidden authority shapes fail closed."""
    del case
    (tmp_path / ".vault").mkdir()
    payload: dict[str, object] = {
        "operation": "index",
        "source": "vault",
        "project_root": str(tmp_path),
        "mode": mode.value,
    }
    if raw_authority is not None:
        payload["authority"] = raw_authority

    with pytest.raises(InvalidJobRequestError) as raised:
        await validated_index_request(payload)

    assert raised.value.code == "invalid_job_spec"


def _attempt_contract(
    *,
    tmp_path: Path,
    mode: JobMode,
    persisted_authority: RunAuthority,
    context_authority: RunAuthority,
) -> tuple[JobAttemptContext, _AttemptDispatch, ServiceRegistry]:
    """Build one real manager-owned attempt and its persisted dispatch contract."""
    manager = JobManager(
        quiesce_controller=ServiceQuiesceController(),
        max_nonterminal=2,
        state_path=None,
    )
    created = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.DOCUMENT,
            project_root=str(tmp_path),
            mode=mode,
            authority=persisted_authority,
        ),
        JobInitiator("test", "authority-dispatch-guard", str(tmp_path)),
    )
    assert created.job is not None
    task = asyncio.current_task()
    assert task is not None
    context = JobAttemptContext(
        manager,
        created.job.id,
        1,
        task,
        RunControlToken(),
        context_authority,
    )
    registry = ServiceRegistry()
    dispatch = _AttemptDispatch(
        source=JobSource.DOCUMENT,
        job_id=created.job.id,
        root=tmp_path,
        mode=mode,
        authority=persisted_authority,
        registry=registry,
    )
    return context, dispatch, registry


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "persisted_authority", "context_authority", "message"),
    [
        (
            JobMode.REBUILD,
            RunAuthority.PUBLICATION,
            RunAuthority.PUBLICATION,
            "publication authority cannot run a full index attempt",
        ),
        (
            JobMode.INCREMENTAL,
            RunAuthority.AUDIT_VERIFICATION,
            RunAuthority.AUDIT_VERIFICATION,
            "audit-verification authority cannot run a publication index attempt",
        ),
        (
            JobMode.INCREMENTAL,
            RunAuthority.REBUILD,
            RunAuthority.PUBLICATION,
            "attempt authority does not match its persisted dispatch authority",
        ),
    ],
)
async def test_attempt_dispatch_refuses_unsupported_authority_before_execution(
    tmp_path: Path,
    mode: JobMode,
    persisted_authority: RunAuthority,
    context_authority: RunAuthority,
    message: str,
) -> None:
    """The indexer boundary must reject widening, audit, and stale authority."""
    context, dispatch, registry = _attempt_contract(
        tmp_path=tmp_path,
        mode=mode,
        persisted_authority=persisted_authority,
        context_authority=context_authority,
    )
    try:
        with pytest.raises(RuntimeError, match=message):
            _admit_attempt_mode(context, dispatch)
    finally:
        registry.close_all()


@pytest.mark.unit
@pytest.mark.parametrize(
    ("mode", "authority", "expected_clean"),
    [
        (JobMode.INCREMENTAL, RunAuthority.PUBLICATION, False),
        (JobMode.INCREMENTAL, RunAuthority.REBUILD, False),
        (JobMode.REBUILD, RunAuthority.REBUILD, True),
    ],
)
async def test_admitted_authority_preserves_requested_dispatch_mode(
    tmp_path: Path,
    mode: JobMode,
    authority: RunAuthority,
    expected_clean: bool,
) -> None:
    """Persisted mode remains the cost selector after authority admission."""
    context, dispatch, registry = _attempt_contract(
        tmp_path=tmp_path,
        mode=mode,
        persisted_authority=authority,
        context_authority=authority,
    )
    try:
        assert _admit_attempt_mode(context, dispatch) is expected_clean
    finally:
        registry.close_all()


@pytest.mark.unit
async def test_attempt_runner_checks_authority_before_admission(
    tmp_path: Path,
) -> None:
    """The concrete runner checks authority before cancellation or preflight."""
    context, dispatch, registry = _attempt_contract(
        tmp_path=tmp_path,
        mode=JobMode.REBUILD,
        persisted_authority=RunAuthority.PUBLICATION,
        context_authority=RunAuthority.PUBLICATION,
    )
    context.control.request_cancel()
    try:
        with pytest.raises(
            RuntimeError,
            match="publication authority cannot run a full index attempt",
        ):
            _run_indexing_attempt(context, dispatch=dispatch)
    finally:
        registry.close_all()


def _make_vault_roots(tmp_path: Path) -> tuple[Path, Path]:
    """Create the large-registry and target workspace roots under *tmp_path*."""
    large_root, target_root = tmp_path / "large-registry-entry", tmp_path / "target"
    for root in (large_root, target_root):
        (root / ".vault").mkdir(parents=True)
    return large_root, target_root


def _seed_persistence_backpressure(manager: JobManager, root: Path) -> None:
    """Create one real large terminal record before the ASGI overlap probe."""
    from ...indexer._run_ledger_models import RunAuthority
    from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec

    entry = manager.create(
        JobSpec(
            operation=JobOperation.INDEX,
            source=JobSource.VAULT,
            project_root=str(root),
            mode=JobMode.INCREMENTAL,
            authority=RunAuthority.PUBLICATION,
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


async def _assert_reindex_refuses_unauthorised_modes(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    root: Path,
) -> None:
    """Require missing and mismatched authority to fail before any admission."""
    for clean, authority in (
        (False, None),
        (True, "publication"),
        (False, "audit_verification"),
    ):
        payload: dict[str, object] = {
            "type": "vault",
            "clean": clean,
            "project_root": str(root),
        }
        if authority is not None:
            payload["authority"] = authority
        refused = await client.post("/reindex", headers=headers, json=payload)
        assert refused.status_code == 400, refused.text
        assert refused.json()["code"] == "invalid_job_spec"


@pytest.mark.unit
async def test_job_mutations_keep_real_asgi_loop_responsive(
    tmp_path: Path,
) -> None:
    """Real durable job writes must overlap an immediate ASGI auth response."""
    from ...config._types import EnvVar
    from ...jobs import get_job_manager, reset
    from .._config_fixtures import reset_config

    prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
    prior_watch_enabled = os.environ.get(EnvVar.WATCH_ENABLED)
    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    os.environ[EnvVar.WATCH_ENABLED] = "false"
    reset_config()
    reset()
    _jobs.reset()
    token = "test-token-responsive-job-writes"
    headers = {"Authorization": f"Bearer {token}"}
    large_root, target_root = _make_vault_roots(tmp_path)

    try:
        manager = get_job_manager()
        _seed_persistence_backpressure(manager, large_root)
        # Admission still persists while dispatch is stopped, so the created
        # job stays queued and no index attempt runs under this probe.
        manager.begin_shutdown()

        app_under_test = create_http_app(
            ServerRouteRuntime(token=token, registry=ServiceRegistry(), port=8765),
            lifespan=None,
        )
        transport = httpx.ASGITransport(app=app_under_test)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1",
        ) as client:
            await _assert_reindex_refuses_unauthorised_modes(
                client, headers, target_root
            )

            created = await _assert_mutation_overlaps_auth_probe(
                client,
                client.post(
                    "/reindex",
                    headers=headers,
                    json={
                        "type": "vault",
                        "clean": False,
                        "project_root": str(target_root),
                        "authority": "publication",
                    },
                ),
            )
            assert created.status_code == 200, created.text
            outcome = cast("dict[str, object]", created.json()["outcome"])
            job = cast("dict[str, object]", outcome["job"])
            spec = cast("dict[str, object]", job["spec"])
            assert spec["authority"] == "publication"
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
        if prior_status_dir is None:
            os.environ.pop(EnvVar.STATUS_DIR, None)
        else:
            os.environ[EnvVar.STATUS_DIR] = prior_status_dir
        if prior_watch_enabled is None:
            os.environ.pop(EnvVar.WATCH_ENABLED, None)
        else:
            os.environ[EnvVar.WATCH_ENABLED] = prior_watch_enabled
        reset_config()
