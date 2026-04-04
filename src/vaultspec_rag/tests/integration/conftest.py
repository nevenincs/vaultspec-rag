"""RAG integration test fixtures."""

from __future__ import annotations

import pytest

from ..conftest import _index_corpus
from ..corpus import build_synthetic_vault


@pytest.fixture(scope="session")
def rag_components(embedding_model, tmp_path_factory):
    """Real RAG components backed by a synthetic vault (24 docs).

    Each integration test session gets its own tmp_path-based corpus.
    """
    root = tmp_path_factory.mktemp("integ-vault")
    manifest = build_synthetic_vault(root, n_docs=24, seed=100)
    components = _index_corpus(root, embedding_model)

    yield {**components, "manifest": manifest}

    components["store"].close()


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
    code_indexer.full_index()

    yield {**components, "manifest": manifest}

    components["store"].close()
