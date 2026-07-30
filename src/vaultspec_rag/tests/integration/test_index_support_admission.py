"""Production-boundary coverage for code support measurement and admission."""

from __future__ import annotations

import os
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, cast

import httpx
import pytest

from ..._job_errors import JobError, JobErrorKind
from ..._store_models import CodeChunk
from ...config._settings import reset_config
from ...config._types import EnvVar
from ...index_profiles import SupportMeasurement, SupportProfileLimits
from ...indexer import CodebaseIndexer
from ...indexer._streaming import CodeFileSegment
from ...jobs import get_job_manager, reset
from ...server import ServerRouteRuntime, create_http_app
from ...service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Generator
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
    indexer._support_budget._support_measurement = SupportMeasurement(1, 64)
    indexer._support_budget._support_limits = SupportProfileLimits(
        source_files=2,
        source_bytes=128,
        generated_chunks=1,
        weighted_bytes=32,
        extracted_bytes=128,
        queue_bytes=128,
        rss_bytes=128,
        cuda_bytes=128,
    )
    indexer._support_budget._support_profile_name = "test-boundary"
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
        next(iter(indexer._support_budget.measure_code_segments((segment,))))

    assert raised.value.error_kind is JobErrorKind.CORPUS_LIMIT_EXCEEDED
    assert indexer.support_measurement == SupportMeasurement(1, 64, 1, 33)


def test_code_runtime_measurement_keeps_extractor_host_and_device_bounds_separate(
    tmp_path: Path,
) -> None:
    indexer = CodebaseIndexer(
        tmp_path,
        cast("Any", None),
        cast("Any", None),
    )
    indexer._support_budget._support_measurement = SupportMeasurement(
        1, 64, queue_bytes=16
    )
    indexer._support_budget._support_limits = SupportProfileLimits(
        source_files=2,
        source_bytes=128,
        generated_chunks=2,
        weighted_bytes=128,
        extracted_bytes=20,
        queue_bytes=16,
        rss_bytes=32,
        cuda_bytes=24,
    )
    indexer._support_budget._support_profile_name = "test-boundary"

    indexer._support_budget.record_extracted_bytes(17)
    indexer._support_budget._record_resource_measurement(rss_bytes=31, cuda_bytes=23)
    assert indexer.support_measurement == SupportMeasurement(
        1,
        64,
        extracted_bytes=17,
        queue_bytes=16,
        rss_bytes=31,
        cuda_bytes=23,
    )

    with pytest.raises(JobError) as raised:
        indexer._support_budget._record_resource_measurement(
            rss_bytes=33, cuda_bytes=23
        )

    assert raised.value.error_kind is JobErrorKind.CORPUS_LIMIT_EXCEEDED
    assert "rss_bytes" in str(raised.value)


@contextmanager
def _refusing_admission_service(tmp_path: Path) -> Generator[Path]:
    """Yield a project root whose code admission is refused by the profile.

    ``managed-service`` accepts only the server backend, so selecting the
    local-only backend produces a genuine profile refusal from the real
    admission path - no doubles anywhere between the route and the check.
    """
    root = tmp_path / "project"
    (root / ".vault").mkdir(parents=True)
    source = root / "src" / "feature.py"
    source.parent.mkdir(parents=True)
    source.write_text("feature = 42\n", encoding="utf-8")
    variables = (
        EnvVar.STATUS_DIR,
        EnvVar.INDEX_SUPPORT_PROFILE,
        EnvVar.LOCAL_ONLY,
        EnvVar.QDRANT_SERVER,
    )
    prior_env = {variable: os.environ.get(variable.value) for variable in variables}
    os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path / "status")
    os.environ[EnvVar.INDEX_SUPPORT_PROFILE.value] = "managed-service"
    os.environ[EnvVar.LOCAL_ONLY.value] = "1"
    os.environ[EnvVar.QDRANT_SERVER.value] = "1"
    reset_config()
    reset()
    try:
        yield root
    finally:
        reset()
        for variable, value in prior_env.items():
            if value is None:
                os.environ.pop(variable.value, None)
            else:
                os.environ[variable.value] = value
        reset_config()


async def _post_index_job(token: str, root: Path, source: str) -> httpx.Response:
    transport = httpx.ASGITransport(
        app=create_http_app(
            ServerRouteRuntime(token=token, registry=ServiceRegistry()),
            lifespan=None,
        )
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post(
            "/jobs",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "operation": "index",
                "source": source,
                "project_root": str(root),
                "mode": "incremental",
            },
        )


@pytest.mark.asyncio
async def test_code_profile_refusal_is_structured_before_job_creation(
    tmp_path: Path,
) -> None:
    token = "test-code-support-admission"
    with _refusing_admission_service(tmp_path) as root:
        response = await _post_index_job(token, root, "code")

        payload = cast("dict[str, object]", response.json())
        assert response.status_code == 422
        assert payload["code"] == JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET.value
        assert payload["error"] == JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET.value
        assert get_job_manager().list_jobs() == []


@pytest.mark.asyncio
async def test_admission_refusal_states_its_kind_exactly_once(
    tmp_path: Path,
) -> None:
    """The machine kind travels as the code; the message must not repeat it.

    An admission failure's exception text carries its kind as a prefix so
    the typed identity survives the background-job text boundary. Every
    transport that also carries the kind as a separate field must strip it,
    or the operator reads the token twice in one line. Asserting on the
    exact leading token is deliberate: a looser "kind appears once anywhere"
    match would pass on a message that merely mentions its own kind in
    prose.
    """
    from ...cli import console
    from ...cli._index import _print_service_domain_outcomes
    from ...server._routes_reindex import _reindex_failure

    token = "test-admission-message-shape"
    with _refusing_admission_service(tmp_path) as root:
        response = await _post_index_job(token, root, "code")

    payload = cast("dict[str, object]", response.json())
    kind = str(payload["code"])
    message = str(payload["message"])
    assert kind == JobErrorKind.PROFILE_REQUIREMENTS_NOT_MET.value
    assert not message.startswith(f"{kind}:")

    # The whole chain an operator actually reads: the route's per-domain
    # failure record rendered by the CLI that requested a combined index.
    with console.capture() as captured:
        _print_service_domain_outcomes(
            {"code": _reindex_failure(error_kind=kind, detail=message)}
        )
    line = next(
        text
        for text in captured.get().splitlines()
        if text.startswith("Source code: failed:")
    )
    assert line.count(kind) == 1
