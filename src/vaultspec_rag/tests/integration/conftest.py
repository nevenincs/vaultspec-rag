"""RAG integration test fixtures.

Uses the session-scoped ``rag_components`` from the parent conftest.
Only defines ``rag_components_with_code`` for tests that need codebase
indexing on top of vault indexing.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ..conftest import RagComponentsWithManifest

from ...progress import NullProgressReporter
from ..conftest import _index_corpus
from ..corpus import build_synthetic_vault


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
    """Provide a test-owned real service with bounded startup and shutdown."""
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

    def diagnostics(log_path: Path) -> str:
        if not log_path.is_file():
            return "service log was not created"
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-80:])

    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(
            port,
            log_path,
            watch=False,
        )
        _write_service_status(pid, port)
        try:
            try:
                _poll_health(port, timeout=90.0)
            except TimeoutError as exc:
                message = f"{exc}\nService output:\n{diagnostics(log_path)}"
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
                    f"Service output:\n{diagnostics(log_path)}"
                )
            if qdrant_pid is not None and not _wait_for_exit(qdrant_pid, timeout=15.0):
                _terminate_pid(qdrant_pid)
                _wait_for_exit(qdrant_pid, timeout=15.0)
                raise AssertionError(
                    f"Test-owned Qdrant process {qdrant_pid} did not exit with its "
                    f"service {pid}.\nService output:\n{diagnostics(log_path)}"
                )
