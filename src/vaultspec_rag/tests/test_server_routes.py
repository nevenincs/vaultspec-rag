"""Route-exposure tests for the storage-schema contract.

Asserts the three runtime surfaces advertise the contract: the full descriptor
on the readiness report, and the bare ``schema_version`` echo on ``/health`` and
on the service-state snapshot. Real computation, no mocks; the descriptor is
torch-free so these stay in the unit gate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import pytest

from .. import store_schema
from .._readiness import compute_readiness
from ..config import EnvVar, reset_config
from ..server import health_handler

if TYPE_CHECKING:
    from pathlib import Path

    import httpx

pytestmark = [pytest.mark.unit]


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


class TestHealthJobsRollup:
    """/health carries the bounded jobs-health rollup."""

    def test_health_reports_running_stalled_and_last_failure(
        self,
        tmp_path: Path,
    ) -> None:
        import os

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
        from ..jobs import get_job_manager, record_finish, record_start, reset

        prior_status_dir = os.environ.get(EnvVar.STATUS_DIR)
        os.environ[EnvVar.STATUS_DIR] = str(tmp_path / "status")
        reset_config()
        reset()
        try:
            failed_id = record_start("code", "tool")
            record_finish(failed_id, error="[Errno 28] No space left on device")
            running_id = record_start("vault", "tool")
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
        finally:
            reset()
            if prior_status_dir is None:
                os.environ.pop(EnvVar.STATUS_DIR, None)
            else:
                os.environ[EnvVar.STATUS_DIR] = prior_status_dir
            reset_config()


class TestServiceStateSchemaVersion:
    """get_service_state echoes the bare schema_version."""

    def test_service_state_echoes_schema_version(self, tmp_path: Path) -> None:
        # Isolate the managed-singleton paths to a temp dir so the snapshot
        # never touches the operator's real status or qdrant storage dir
        # (managed-singleton-paths-isolate-storage-dir-in-tests).
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
