"""RAG integration test fixtures.

Uses the session-scoped ``rag_components`` from the parent conftest.
Only defines ``rag_components_with_code`` for tests that need codebase
indexing on top of vault indexing.
"""

from __future__ import annotations

import pytest

from ...progress import NullProgressReporter
from ..conftest import _index_corpus
from ..corpus import build_synthetic_vault


@pytest.fixture(scope="session")
def rag_components_with_code(embedding_model, tmp_path_factory):
    """RAG components with vault + codebase indexed.

    Creates a synthetic vault and indexes both vault docs and any
    source files present under the synthetic project root.
    """
    root = tmp_path_factory.mktemp("integ-code-vault")
    manifest = build_synthetic_vault(root, n_docs=24, seed=200)
    components = _index_corpus(root, embedding_model)

    code_indexer = components["code_indexer"]
    code_indexer.full_index(reporter=NullProgressReporter())

    yield {**components, "manifest": manifest}

    components["store"].close()


@pytest.fixture
def live_service(request, tmp_path):
    """Provides a running real background service and its temp status directory."""
    from ...cli import _spawn_service, _terminate_pid, _write_service_status
    from ._helpers import _get_ephemeral_port, _poll_health, _service_env

    with _service_env(tmp_path):
        port = _get_ephemeral_port()
        log_path = tmp_path / "service.log"
        pid = _spawn_service(port, log_path)
        request.addfinalizer(lambda: _terminate_pid(pid))
        _write_service_status(pid, port)
        _poll_health(port)
        yield port, tmp_path
