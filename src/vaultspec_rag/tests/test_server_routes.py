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
