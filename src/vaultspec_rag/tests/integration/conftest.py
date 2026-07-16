"""RAG integration test fixtures.

Uses the session-scoped ``rag_components`` from the parent conftest.
Only defines ``rag_components_with_code`` for tests that need codebase
indexing on top of vault indexing.
"""

from __future__ import annotations

import os
import time
from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ..conftest import RagComponentsWithManifest

from ..._machine_lock import (
    machine_lock_live_holder,
    machine_lock_path,
    release_machine_lock,
)
from ...config import EnvVar, get_config, reset_config
from ...progress import NullProgressReporter
from .._model_setup import (
    configured_service_model_ids,
    ensure_model_snapshots,
    model_setup_timeout_seconds,
    models_are_cached,
)
from ..conftest import _index_corpus
from ..corpus import build_synthetic_vault


def _service_output(log_path: Path) -> str:
    """Return the complete retained service log, or an empty string."""
    if not log_path.is_file():
        return ""
    return log_path.read_text(encoding="utf-8", errors="replace")


def _service_diagnostics(log_path: Path) -> str:
    """Return the bounded retained service-log tail."""
    output = _service_output(log_path)
    if not output:
        return "service log was not created"
    return "\n".join(output.splitlines()[-80:])


def _remaining_startup_budget(
    *,
    started: float,
    budget: float,
    stages: list[str],
    stage: str,
) -> float:
    """Return the remaining whole-startup budget or fail with stage context."""
    elapsed = time.monotonic() - started
    remaining = budget - elapsed
    if remaining <= 0:
        detail = "\n".join(stages) or "<no completed startup stages>"
        raise AssertionError(
            f"Service startup exceeded {budget:.3f}s before {stage}; "
            f"elapsed={elapsed:.3f}s\nStartup stages:\n{detail}"
        )
    return remaining


def _verify_offline_service_startup(log_path: Path, stages: list[str]) -> str:
    """Prove local-only constructors ran without the configured HF endpoint."""
    output = _service_output(log_path)
    expected_markers = ["EmbeddingModel cache-only mode: True"]
    if bool(get_config().reranker_enabled):
        expected_markers.append("(cache-only=True)")
    missing_markers = [marker for marker in expected_markers if marker not in output]
    hf_endpoint = (
        os.environ.get(EnvVar.HF_ENDPOINT.value) or "https://huggingface.co"
    ).rstrip("/")
    if missing_markers or hf_endpoint in output:
        raise AssertionError(
            "Service did not prove cache-only startup without Hugging Face "
            f"metadata access; missing_markers={missing_markers!r}, "
            f"endpoint_seen={hf_endpoint in output}, endpoint={hf_endpoint!r}\n"
            f"Startup stages:\n{'\n'.join(stages)}\nService output:\n"
            f"{_service_diagnostics(log_path)}"
        )
    return (
        f"offline verification endpoint={hf_endpoint!r} metadata_requests=0 "
        f"markers={expected_markers!r}"
    )


@pytest.fixture
def isolated_lock(tmp_path: Path) -> Generator[Path]:
    """Provide and safely remove a test-owned machine-singleton lock path."""
    key = EnvVar.QDRANT_STORAGE_DIR.value
    previous = os.environ.get(key)
    os.environ[key] = str(tmp_path / "qdrant-server" / "storage")
    reset_config()
    try:
        yield machine_lock_path()
    finally:
        try:
            release_machine_lock()
            path = machine_lock_path()
            live_holder = machine_lock_live_holder()
            if live_holder != 0:
                msg = (
                    "refusing to unlink test-owned machine lock while its real "
                    f"holder {live_holder} is still alive"
                )
                raise AssertionError(msg)
            path.unlink(missing_ok=True)
        finally:
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous
            reset_config()


@pytest.fixture(scope="session")
def rag_components_with_code(
    embedding_model: EmbeddingModel,
    tmp_path_factory: TempPathFactory,
) -> Generator[RagComponentsWithManifest]:
    """RAG components with vault + codebase indexed.

    Creates a synthetic vault and indexes both vault docs and any
    source files present under the synthetic project root.
    """
    root: Path = tmp_path_factory.mktemp("integ-code-vault")
    manifest = build_synthetic_vault(root, n_docs=24, seed=200)
    components = _index_corpus(root, embedding_model)

    code_indexer = components["code_indexer"]
    code_indexer.full_index(reporter=NullProgressReporter())

    yield cast(
        "RagComponentsWithManifest",
        components.__class__(  # type: ignore[call-arg]
            **components,  # type: ignore[misc]
            manifest=manifest,
        ),
    )

    components["store"].close()


@pytest.fixture
def live_service(
    tmp_path: Path,
) -> Generator[tuple[int, Path]]:
    """Provide a cache-prepared, offline real service with bounded startup."""
    from ...cli import (
        _read_service_status,
        _spawn_service,
        _terminate_pid,
        _write_service_status,
    )
    from ._helpers import (
        _get_ephemeral_port,
        _poll_health,
        _service_env,
        _wait_for_exit,
    )

    startup_started = time.monotonic()
    startup_budget = model_setup_timeout_seconds()
    stages: list[str] = []

    def remaining_budget(stage: str) -> float:
        return _remaining_startup_budget(
            started=startup_started,
            budget=startup_budget,
            stages=stages,
            stage=stage,
        )

    online_acquisition_env = {
        EnvVar.HF_HUB_OFFLINE.value: None,
        EnvVar.TRANSFORMERS_OFFLINE.value: None,
    }
    with _service_env(tmp_path, env_overrides=online_acquisition_env):
        model_ids = configured_service_model_ids()
        warm_cache = models_are_cached(model_ids)
        stage_started = time.monotonic()
        ensure_model_snapshots(
            model_ids,
            timeout_seconds=remaining_budget("model acquisition"),
        )
        elapsed = time.monotonic() - stage_started
        stages.append(
            "model acquisition "
            f"state={'warm' if warm_cache else 'repaired'} "
            f"elapsed={elapsed:.3f}s "
            f"remaining={remaining_budget('service spawn'):.3f}s "
            f"models={list(model_ids)!r} "
            f"offline_env_cleared={list(online_acquisition_env)!r}"
        )

    offline_env = {
        EnvVar.HF_HUB_OFFLINE.value: "1",
        EnvVar.TRANSFORMERS_OFFLINE.value: "1",
    }
    with _service_env(tmp_path, env_overrides=offline_env):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        stage_started = time.monotonic()
        pid = _spawn_service(
            port,
            log_path,
            watch=False,
        )
        try:
            _write_service_status(pid, port)
            stages.append(
                "service spawn "
                f"elapsed={time.monotonic() - stage_started:.3f}s "
                f"remaining={remaining_budget('health readiness'):.3f}s "
                f"pid={pid} port={port} offline_env={offline_env!r}"
            )
            try:
                stage_started = time.monotonic()
                _poll_health(
                    port,
                    timeout=remaining_budget("health readiness"),
                )
                stages.append(
                    "health readiness "
                    f"elapsed={time.monotonic() - stage_started:.3f}s "
                    f"total={time.monotonic() - startup_started:.3f}s"
                )
                stages.append(_verify_offline_service_startup(log_path, stages))
            except TimeoutError as exc:
                message = (
                    f"{exc}\nStartup deadline={startup_budget:.3f}s\n"
                    f"Startup stages:\n{'\n'.join(stages)}\n"
                    f"Service output:\n{_service_diagnostics(log_path)}"
                )
                raise AssertionError(message) from exc
            yield port, tmp_path
        finally:
            status = _read_service_status()
            raw_qdrant_pid = status.get("qdrant_pid") if status else None
            qdrant_pid = (
                raw_qdrant_pid
                if isinstance(raw_qdrant_pid, int)
                and not isinstance(raw_qdrant_pid, bool)
                else None
            )
            _terminate_pid(pid)
            if not _wait_for_exit(pid, timeout=15.0):
                raise AssertionError(
                    f"Test-owned service process {pid} did not exit.\n"
                    f"Service output:\n{_service_diagnostics(log_path)}"
                )
            if qdrant_pid is not None and not _wait_for_exit(qdrant_pid, timeout=15.0):
                _terminate_pid(qdrant_pid)
                _wait_for_exit(qdrant_pid, timeout=15.0)
                raise AssertionError(
                    f"Test-owned Qdrant process {qdrant_pid} did not exit with its "
                    f"service {pid}.\nService output:\n"
                    f"{_service_diagnostics(log_path)}"
                )
