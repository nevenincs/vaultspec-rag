"""Real admission boundary for independently bounded document workloads."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

from ..._job_errors import JobError, JobErrorKind
from ...config import get_config
from ...index_profiles import get_index_support_profile
from ...job_control import RunControlToken
from ...job_dispatch import _run_document_attempt
from ...job_manager import JobAttemptContext, JobManager
from ...job_models import JobInitiator, JobMode, JobOperation, JobSource, JobSpec
from ...service import ServiceRegistry

pytestmark = [pytest.mark.integration, pytest.mark.timeout(120)]


def _write_document_route(root: Path, extractor: Path) -> None:
    executable = str(extractor.resolve()).replace("\\", "/")
    python = str(Path(sys.executable).resolve()).replace("\\", "/")
    (root / ".vaultragpreprocess.toml").write_text(
        "version = 2\n\n"
        "[[rule]]\n"
        'pattern = "*.blob"\n'
        f"command = '\"{python}\" \"{executable}\" {{path}}'\n"
        'target = "document"\n'
        'extractor_version = "1"\n'
        'on_error = "fail"\n',
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_over_budget_document_is_refused_before_gpu_or_extractor(
    clean_config: None,
    tmp_path: Path,
) -> None:
    """Admission rejects an oversized queue before model/extractor work."""
    del clean_config
    limits = get_index_support_profile("embedded-local").document
    get_config(
        {
            "index_support_profile": "embedded-local",
            "index_queue_max_bytes": limits.queue_bytes + 1,
        }
    )
    sentinel = tmp_path / "extractor-ran.flag"
    extractor = tmp_path / "extractor.py"
    extractor.write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('ran', encoding='utf-8')\n",
        encoding="utf-8",
    )
    _write_document_route(tmp_path, extractor)
    source = tmp_path / "oversized.blob"
    source.write_bytes(b"bounded admission input")

    manager = JobManager(max_nonterminal=1, state_path=None)
    created = manager.create(
        JobSpec(
            JobOperation.INDEX,
            JobSource.DOCUMENT,
            str(tmp_path),
            JobMode.INCREMENTAL,
        ),
        JobInitiator("integration", "document resource admission", str(tmp_path)),
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
    )
    registry = ServiceRegistry()
    try:
        with pytest.raises(JobError) as caught:
            _run_document_attempt(
                context,
                manager=manager,
                job_id=created.job.id,
                root=tmp_path,
                clean=False,
                registry=registry,
            )
        assert caught.value.error_kind is JobErrorKind.CORPUS_LIMIT_EXCEEDED
        assert "document queue_bytes" in str(caught.value)
        assert registry.health()["model_loaded"] is False
        assert registry.health()["project_count"] == 0
        assert not sentinel.exists()
        assert not (tmp_path / get_config().data_dir).exists()
    finally:
        registry.close_all()
