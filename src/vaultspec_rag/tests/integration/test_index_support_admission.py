"""Production-boundary coverage for code support measurement and admission."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest
from starlette.applications import Starlette

import vaultspec_rag.server as server_package

from ..._job_errors import JobError, JobErrorKind
from ..._store_models import CodeChunk
from ...config import EnvVar, reset_config
from ...index_profiles import SupportMeasurement, SupportProfileLimits
from ...indexer import CodebaseIndexer
from ...indexer._streaming import CodeFileSegment
from ...jobs import get_job_manager, reset
from ...server._routes import ROUTES

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]


def test_code_discovery_measures_only_admitted_source_dimensions(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src" / "feature.py"
    source.parent.mkdir(parents=True)
    source.write_text("def feature() -> int:\n    return 42\n", encoding="utf-8")
    excluded = tmp_path / "data" / "payload.bin"
    excluded.parent.mkdir(parents=True)
    excluded.write_bytes(b"\x00\x01\x02\x03")

    indexer = CodebaseIndexer(
        tmp_path,
        cast("Any", None),
        cast("Any", None),
    )
    full = indexer.preflight_content()
    scoped = indexer.preflight_changed_paths((source, excluded))

    expected = SupportMeasurement(source_files=1, source_bytes=source.stat().st_size)
    assert full.scan.measurement == expected
    assert scoped.measurement == expected
    assert full.scan.files == (source,)


def test_code_segment_measurement_rejects_before_overweight_segment_yields(
    tmp_path: Path,
) -> None:
    indexer = CodebaseIndexer(
        tmp_path,
        cast("Any", None),
        cast("Any", None),
    )
    indexer._support_measurement = SupportMeasurement(1, 64)
    indexer._support_limits = SupportProfileLimits(
        source_files=2,
        source_bytes=128,
        generated_chunks=1,
        weighted_bytes=32,
    )
    indexer._support_profile_name = "test-boundary"
    chunk = CodeChunk(
        id="feature-0",
        path="src/feature.py",
        language="python",
        content="def feature() -> int:\n    return 42\n",
        line_start=1,
        line_end=2,
    )
    segment = CodeFileSegment(
        path=chunk.path,
        ordinal=0,
        chunks=(chunk,),
        estimated_bytes=33,
        is_file_end=True,
    )

    with pytest.raises(JobError) as raised:
        next(iter(indexer._measure_code_segments((segment,))))

    assert raised.value.error_kind is JobErrorKind.CORPUS_LIMIT_EXCEEDED
    assert indexer.support_measurement == SupportMeasurement(1, 64, 1, 33)


@pytest.mark.asyncio
async def test_code_profile_refusal_is_structured_before_job_creation(
    tmp_path: Path,
) -> None:
    root = tmp_path / "project"
    (root / ".vault").mkdir(parents=True)
    source = root / "src" / "feature.py"
    source.parent.mkdir(parents=True)
    source.write_text("feature = 42\n", encoding="utf-8")
    prior_env = {
        variable: os.environ.get(variable.value)
        for variable in (
            EnvVar.STATUS_DIR,
            EnvVar.INDEX_SUPPORT_PROFILE,
            EnvVar.LOCAL_ONLY,
            EnvVar.QDRANT_SERVER,
        )
    }
    prior_token = server_package._SERVICE_TOKEN
    token = "test-code-support-admission"
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
    os.environ[EnvVar.INDEX_SUPPORT_PROFILE.value] = "managed-service"
    os.environ[EnvVar.LOCAL_ONLY.value] = "1"
    os.environ[EnvVar.QDRANT_SERVER.value] = "1"
    reset_config()
    reset()
    server_package._SERVICE_TOKEN = token

    try:
        transport = httpx.ASGITransport(app=Starlette(routes=ROUTES))
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
        ) as client:
            response = await client.post(
                "/jobs",
                headers={"Authorization": f"Bearer {token}"},
                json={
                    "operation": "index",
                    "source": "code",
                    "project_root": str(root),
                    "mode": "incremental",
                },
            )

        payload = cast("dict[str, object]", response.json())
        assert response.status_code == 422
        assert payload["code"] == JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET.value
        assert payload["error"] == JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET.value
        assert get_job_manager().list_jobs() == []
    finally:
        reset()
        server_package._SERVICE_TOKEN = prior_token
        for variable, value in prior_env.items():
            if value is None:
                os.environ.pop(variable.value, None)
            else:
                os.environ[variable.value] = value
        reset_config()
