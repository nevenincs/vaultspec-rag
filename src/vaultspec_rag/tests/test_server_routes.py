"""Route-exposure tests for the storage-schema contract and the health rollup.

Asserts the three runtime surfaces advertise the storage-schema contract: the
full descriptor on the readiness report, and the bare ``schema_version`` echo on
``/health`` and on the service-state snapshot. Also covers the ``/health`` jobs
rollup and the generation bound on its degradation verdict. Real computation, no
mocks; the descriptor is torch-free so these stay in the unit gate.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Any, cast

import pytest

from .. import store_schema
from .._job_errors import STALL_THRESHOLD_SECONDS
from .._readiness import compute_readiness
from ..config._settings import reset_config
from ..config._types import EnvVar
from ..job_models import JobSource
from ..server import health_handler
from ._job_records import activity_record

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    import httpx

pytestmark = [pytest.mark.unit]

# A disk-full error text classifies to a stable, asserted ``error_kind``, so the
# reason string these tests match on never depends on the classifier's default.
_DISK_FULL = "[Errno 28] No space left on device"

# The epoch clock's tick is coarse enough on some hosts that two stamps taken
# back to back compare equal. Every ordering these tests depend on is separated
# by more than one tick so "before" never degenerates into "at the same time".
_CLOCK_TICK_GAP_SECONDS = 0.1


@pytest.fixture
def isolated_jobs(tmp_path: Path) -> Iterator[None]:
    """Point job state at a per-test status dir and clear it on both sides.

    The narrowing keeps persisted job snapshots out of the session-wide status
    dir every test shares. Restoring the env is deliberately absent: the autouse
    machine-singleton re-arm in the package conftest resets the canonical paths
    and both config caches at every test boundary, so repeating that here would
    only duplicate a guarantee that already holds.
    """
    import os

    from ..jobs import reset

    os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
    reset_config()
    reset()
    try:
        yield
    finally:
        reset()


@pytest.fixture
def restored_generation() -> Iterator[None]:
    """Restore the process-wide start stamps a test moves."""
    import vaultspec_rag.server as mod

    prior_monotonic = mod._start_time
    prior_wall = mod._start_wall_time
    try:
        yield
    finally:
        mod._start_time = prior_monotonic
        mod._start_wall_time = prior_wall


def _begin_generation() -> None:
    """Stamp both start witnesses as if a daemon generation began right now."""
    import vaultspec_rag.server as mod

    mod._start_time = time.monotonic()
    mod._start_wall_time = time.time()


class TestReadinessDescriptor:
    """/readiness carries the bounded storage-schema descriptor."""

    def test_readiness_to_dict_carries_schema_descriptor(self) -> None:
        report = compute_readiness().to_dict()
        assert "schema" in report
        assert report["schema"] == store_schema.describe_storage_schema()

    def test_descriptor_version_matches_constant(self) -> None:
        report = compute_readiness().to_dict()
        schema = cast("dict[str, Any]", report["schema"])
        assert schema["version"] == store_schema.STORAGE_SCHEMA_VERSION

    def test_report_is_json_serialisable_with_schema(self) -> None:
        import json

        json.dumps(compute_readiness().to_dict())


class TestHealthSchemaVersion:
    """/health echoes the bare schema_version for a cheap pre-read gate."""

    def test_health_echoes_schema_version(self) -> None:
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        app = Starlette(routes=[Route("/health", health_handler)])
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        resp: httpx.Response = client.get("/health")
        data: dict[str, Any] = cast("dict[str, Any]", resp.json())
        assert data["schema_version"] == store_schema.STORAGE_SCHEMA_VERSION


@pytest.mark.usefixtures("isolated_jobs")
class TestHealthJobsRollup:
    """/health carries the bounded jobs-health rollup."""

    def test_health_reports_running_stalled_and_last_failure(
        self,
        tmp_path: Path,
    ) -> None:
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from ..job_models import (
            JobInitiator,
            JobMode,
            JobOperation,
            JobSource,
            JobSpec,
        )
        from ..jobs import get_job_manager, record_finish, record_start

        failed_id = record_start(JobSource.CODE, "tool")
        record_finish(failed_id, error=_DISK_FULL)
        running_id = record_start(JobSource.VAULT, "tool")
        paused = get_job_manager().create(
            JobSpec(
                operation=JobOperation.INDEX,
                source=JobSource.VAULT,
                project_root=str(tmp_path),
                mode=JobMode.INCREMENTAL,
            ),
            JobInitiator(
                kind="cli",
                command="health_test",
                project_root=str(tmp_path),
            ),
            start_paused=True,
        )
        assert paused.job is not None

        app = Starlette(routes=[Route("/health", health_handler)])
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        data: dict[str, Any] = cast("dict[str, Any]", client.get("/health").json())
        jobs = cast("dict[str, Any]", data["jobs"])
        assert jobs["running"] == 1
        assert jobs["paused"] == 1
        assert jobs["active"] == 2
        assert jobs["transitional"] == 0
        assert jobs["stalled"] == 0
        last_failed = cast("dict[str, Any]", jobs["last_failed"])
        assert last_failed["id"] == failed_id
        assert last_failed["error_kind"] == "disk_full"
        del running_id


@pytest.mark.usefixtures("isolated_jobs", "restored_generation")
class TestHealthFailureGenerationBound:
    """A job failure degrades health only for the process that suffered it.

    Job records are durable, so the newest failure on file routinely belongs to
    an earlier daemon. These tests fix the boundary: the failure stays visible
    in the payload, and only a failure from the running generation is allowed to
    speak for the running process.
    """

    def test_failure_before_this_generation_is_reported_but_not_degrading(
        self,
    ) -> None:
        """A failure the running process did not suffer produces no reason.

        The empty reason list is the whole assertion: the health handler flips
        ``ready`` only when a reason is present, so no reason is no flip.
        """
        from ..jobs import record_finish, record_start
        from ..server._lifespan import _jobs_health

        failed_id = record_start(JobSource.CODE, "tool")
        record_finish(failed_id, error=_DISK_FULL)
        time.sleep(_CLOCK_TICK_GAP_SECONDS)
        _begin_generation()

        jobs_health, degraded_reasons = _jobs_health()

        assert degraded_reasons == []
        last_failed = cast("dict[str, Any]", jobs_health["last_failed"])
        assert last_failed["id"] == failed_id
        assert last_failed["error_kind"] == "disk_full"
        assert isinstance(last_failed["finished_at"], float)

    def test_failure_inside_this_generation_degrades(self) -> None:
        from ..jobs import record_finish, record_start
        from ..server._lifespan import _jobs_health

        _begin_generation()
        time.sleep(_CLOCK_TICK_GAP_SECONDS)
        failed_id = record_start(JobSource.CODE, "tool")
        record_finish(failed_id, error=_DISK_FULL)

        jobs_health, degraded_reasons = _jobs_health()

        assert degraded_reasons == ["the latest indexing job failed: disk_full"]
        assert cast("dict[str, Any]", jobs_health["last_failed"])["id"] == failed_id

    def test_stalled_job_degrades_regardless_of_generation(self) -> None:
        """Stall is a live condition, so the generation bound must not reach it.

        The job here stopped reporting progress before the generation started -
        exactly the shape the failure bound suppresses - and must still degrade.
        """
        from ..jobs import record_progress, record_start
        from ..server._lifespan import _jobs_health

        running_id = record_start(JobSource.CODE, "watcher")
        record_progress(running_id, "embed", 3, 20)
        with activity_record(running_id) as record:
            progress = cast("dict[str, Any]", record["progress"])
            progress["last_updated"] -= STALL_THRESHOLD_SECONDS + 60.0
        time.sleep(_CLOCK_TICK_GAP_SECONDS)
        _begin_generation()

        jobs_health, degraded_reasons = _jobs_health()

        assert jobs_health["stalled"] == 1
        assert degraded_reasons == ["1 indexing job(s) are stalled"]

    @pytest.mark.parametrize("stamp", [None, "2026-07-24T15:15:52Z"])
    def test_failure_without_a_usable_timestamp_degrades(self, stamp: object) -> None:
        """An unplaceable failure degrades rather than being assumed historical.

        The generation starts after the failure, so a usable stamp would put it
        out of generation and silence it (the first test in this class). Losing
        the stamp must reverse that: the reason is the only signal that the live
        service is broken, and an over-report is visible and self-clearing.
        """
        from ..jobs import record_finish, record_start
        from ..server._lifespan import _jobs_health

        failed_id = record_start(JobSource.CODE, "tool")
        record_finish(failed_id, error=_DISK_FULL)
        with activity_record(failed_id) as record:
            record["finished_at"] = stamp
        time.sleep(_CLOCK_TICK_GAP_SECONDS)
        _begin_generation()

        jobs_health, degraded_reasons = _jobs_health()

        assert degraded_reasons == ["the latest indexing job failed: disk_full"]
        assert (
            cast("dict[str, Any]", jobs_health["last_failed"])["finished_at"] == stamp
        )

    def test_stale_failure_leaves_the_health_verdict_unchanged(self) -> None:
        """The served verdict with a stale failure on file matches having none.

        Comparing two real responses from one process keeps the assertion honest
        without a loaded model: whatever the rest of the environment contributes
        cancels out, so any difference is the stale failure's doing.
        """
        from starlette.applications import Starlette
        from starlette.routing import Route
        from starlette.testclient import TestClient

        from ..jobs import record_finish, record_start

        app = Starlette(routes=[Route("/health", health_handler)])
        client: httpx.Client = cast("httpx.Client", TestClient(app))
        _begin_generation()
        baseline: dict[str, Any] = cast("dict[str, Any]", client.get("/health").json())

        failed_id = record_start(JobSource.CODE, "tool")
        record_finish(failed_id, error=_DISK_FULL)
        time.sleep(_CLOCK_TICK_GAP_SECONDS)
        _begin_generation()

        data: dict[str, Any] = cast("dict[str, Any]", client.get("/health").json())

        assert data["degraded_reasons"] == baseline["degraded_reasons"]
        assert data["status"] == baseline["status"]
        assert cast("dict[str, Any]", baseline["jobs"])["last_failed"] is None
        assert cast("dict[str, Any]", data["jobs"])["last_failed"]["id"] == failed_id


class TestServiceStateSchemaVersion:
    """get_service_state echoes the bare schema_version."""

    def test_service_state_echoes_schema_version(self, tmp_path: Path) -> None:
        # Isolate the managed-singleton paths to a temp dir so the snapshot
        # never touches the operator's real status or qdrant storage dir.
        import os

        import vaultspec_rag as vr

        prior = {
            EnvVar.STATUS_DIR: os.environ.get(EnvVar.STATUS_DIR),
            EnvVar.QDRANT_STORAGE_DIR: os.environ.get(EnvVar.QDRANT_STORAGE_DIR),
        }
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
        os.environ[EnvVar.QDRANT_STORAGE_DIR] = str(
            tmp_path / "qdrant-server" / "storage"
        )
        reset_config()
        try:
            state = vr.get_service_state(tmp_path)
            assert state["schema_version"] == store_schema.STORAGE_SCHEMA_VERSION
        finally:
            for key, value in prior.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            reset_config()
