"""Daemon-funnel integration coverage for encode-seam donor vector reuse.

Drives the exact production path the resident service runs for a rebuild
job - admission, ``JobManager`` dispatch, ``bind_index_job``'s code attempt
runner, ``CodebaseIndexer.full_index(clean=True)`` - against a real
supervised qdrant server with the real production embedding model, and
asserts the reuse telemetry is visible on the SERVED job record (the
canonical manager view ``/jobs`` returns for every manager-owned job).

The served-record assertion is deliberately at the job-record layer, not
the in-process ``IndexResult``: seam-level unit coverage stayed green while
the daemon's job records showed no reuse block at all, because the
telemetry rode only the legacy activity record that the canonical snapshot
shadows. These tests bind to the view an operator (and a measurement run)
actually reads.
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING, cast

import pytest

from ... import jobs
from ...concurrency import reset_limiters
from ...config import get_config, reset_config
from ...job_models import JobState
from ...registry import get_registry, reset_registry
from ...server._routes import _service_job_snapshot
from ._helpers import provisioned_qdrant_binary, serve_qdrant

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Generator
    from pathlib import Path

    from pytest import TempPathFactory

    from ...job_manager import JobManager
    from ...qdrant_runtime import QdrantSupervisor
    from ...service import ServiceRegistry

pytestmark = [pytest.mark.integration]

_JOB_WAIT_SECONDS = 240.0


def _write_code_files(root: Path, count: int) -> list[Path]:
    """Create a small real Python corpus with deterministic content."""
    source_dir = root / "src"
    source_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for ordinal in range(count):
        path = source_dir / f"reuse_{ordinal:03d}.py"
        path.write_text(
            f"def reuse_{ordinal:03d}() -> str:\n"
            f'    """Donor reuse corpus function {ordinal:03d}."""\n'
            f'    return "reuse-{ordinal:03d}"\n',
            encoding="utf-8",
        )
        paths.append(path)
    return paths


@pytest.fixture(scope="module")
def real_qdrant_binary() -> Path:
    """Provision (or reuse) the pinned real Qdrant binary."""
    return provisioned_qdrant_binary()


@pytest.fixture(scope="module")
def qdrant_server(
    real_qdrant_binary: Path,
    tmp_path_factory: TempPathFactory,
) -> Generator[QdrantSupervisor]:
    """One real qdrant server on ephemeral ports with temp storage."""
    yield from serve_qdrant(real_qdrant_binary, tmp_path_factory.mktemp("reuse-qdrant"))


def _server_mode_config(status_dir: Path, qdrant_url: str) -> dict[str, object]:
    return {
        "status_dir": str(status_dir),
        "qdrant_storage_dir": str(status_dir / "qdrant-server" / "storage"),
        "qdrant_url": qdrant_url,
        "qdrant_server": True,
        "local_only": False,
        "sparse_enabled": False,
        "reranker_enabled": False,
        "index_job_concurrency": 1,
        "job_shutdown_timeout_seconds": _JOB_WAIT_SECONDS,
    }


@pytest.fixture(scope="module")
def reuse_registry(
    qdrant_server: QdrantSupervisor,
    tmp_path_factory: TempPathFactory,
) -> Generator[tuple[ServiceRegistry, dict[str, object]]]:
    """Server-mode production registry with isolated machine-global state."""
    status_dir = tmp_path_factory.mktemp("reuse-status")
    overrides = _server_mode_config(status_dir, qdrant_server.url)
    env = pytest.MonkeyPatch()
    env.setenv("VAULTSPEC_RAG_STATUS_DIR", str(status_dir))
    env.setenv(
        "VAULTSPEC_RAG_QDRANT_STORAGE_DIR",
        str(status_dir / "qdrant-server" / "storage"),
    )
    env.delenv("VAULTSPEC_RAG_INDEX_REUSE", raising=False)
    reset_registry()
    jobs.reset()
    reset_limiters()
    reset_config()
    get_config(overrides)
    registry = get_registry()
    registry.load_model()
    yield registry, overrides
    reset_registry()
    jobs.reset()
    reset_limiters()
    env.undo()
    reset_config()


@pytest.fixture
async def reuse_job_manager(
    reuse_registry: tuple[ServiceRegistry, dict[str, object]],
) -> AsyncGenerator[JobManager]:
    """Fresh manager state per test over the module-cached model."""
    registry, overrides = reuse_registry
    get_config(dict(overrides))
    jobs.reset()
    reset_limiters()
    manager = jobs.get_job_manager()
    yield manager
    survivors = manager.active()
    assert not survivors, "managed reuse attempts must drain before teardown"
    from pathlib import Path as _Path

    for root in registry.health()["projects"]:
        registry.close_project(_Path(root))
    jobs.reset()
    reset_limiters()


async def _run_rebuild_job(manager: JobManager, root: Path) -> str:
    """Run one production rebuild job to completion and return its id."""
    job_id = jobs.start_reindex_codebase(root, clean=True)
    joined = await manager.wait_for_attempt(
        job_id,
        timeout_seconds=_JOB_WAIT_SECONDS,
    )
    assert joined.code == "attempt_released", joined.code
    snapshot = manager.get(job_id)
    assert snapshot is not None
    assert snapshot.state is JobState.SUCCEEDED, snapshot.result
    return job_id


def _served_record(job_id: str) -> dict[str, object]:
    """Return the job record exactly as the service's /jobs view serves it."""
    for record in _service_job_snapshot():
        if record.get("id") == job_id:
            return record
    raise AssertionError(f"job {job_id} is missing from the served snapshot")


@pytest.mark.timeout(600)
async def test_rebuild_job_record_carries_donor_reuse_telemetry(
    tmp_path: Path,
    reuse_job_manager: JobManager,
) -> None:
    """A daemon-path rebuild with an eligible donor reports hits on its record.

    Red with the wiring defect present: the reuse block reached only the
    legacy activity record, which the canonical manager snapshot shadows in
    the served view, so ``record["reuse"]`` read as absent/None for every
    manager-owned job regardless of what the run resolved.
    """
    donor_root = tmp_path / "donor"
    _write_code_files(donor_root, 3)
    donor_id = await _run_rebuild_job(reuse_job_manager, donor_root)

    # The donor's own record must already distinguish "no donors existed"
    # (donor_absent) from "reuse never resolved" (null) on the served view.
    donor_reuse = _served_record(donor_id).get("reuse")
    assert isinstance(donor_reuse, dict), (
        "served job record dropped the reuse block for a manager-owned job"
    )
    assert cast("dict[str, object]", donor_reuse)["donor_absent"] is True

    target_root = tmp_path / "target"
    shutil.copytree(donor_root, target_root)
    target_id = await _run_rebuild_job(reuse_job_manager, target_root)

    target_reuse = _served_record(target_id).get("reuse")
    assert isinstance(target_reuse, dict), (
        "served job record dropped the reuse block for a manager-owned job"
    )
    reuse = cast("dict[str, object]", target_reuse)
    assert reuse["donor_absent"] is False
    assert cast("int", reuse["reuse_hits"]) > 0
    assert cast("float", reuse["hit_rate"]) > 0.0
    assert cast("float", reuse["gpu_seconds_saved"]) > 0.0
    donor_collections = cast("list[str]", reuse["donor_collections"])
    assert donor_collections, "eligible donor collections must be recorded"


@pytest.mark.timeout(600)
async def test_flag_off_rebuild_job_record_has_no_reuse_block(
    tmp_path: Path,
    reuse_job_manager: JobManager,
    reuse_registry: tuple[ServiceRegistry, dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the knob off, the served record's reuse block stays null."""
    _, overrides = reuse_registry
    root = tmp_path / "flag-off"
    _write_code_files(root, 2)
    monkeypatch.setenv("VAULTSPEC_RAG_INDEX_REUSE", "0")
    get_config(dict(overrides))
    try:
        job_id = await _run_rebuild_job(reuse_job_manager, root)
        assert _served_record(job_id).get("reuse") is None
    finally:
        monkeypatch.delenv("VAULTSPEC_RAG_INDEX_REUSE", raising=False)
        get_config(dict(overrides))
