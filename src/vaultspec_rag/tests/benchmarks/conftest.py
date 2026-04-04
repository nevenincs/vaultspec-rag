"""Benchmark fixtures — real GPU components for performance tests."""

from __future__ import annotations

import pytest

from ..conftest import _index_corpus
from ..corpus import build_synthetic_vault


@pytest.fixture(scope="session")
def _bench_components(embedding_model, tmp_path_factory):
    """Session-scoped RAG components for benchmarks (48-doc corpus)."""
    root = tmp_path_factory.mktemp("bench-vault")
    manifest = build_synthetic_vault(root, n_docs=48, seed=300)
    components = _index_corpus(root, embedding_model)
    yield {**components, "manifest": manifest}
    components["store"].close()


@pytest.fixture(scope="session")
def model(_bench_components):
    """Real EmbeddingModel on CUDA."""
    return _bench_components["model"]


@pytest.fixture(scope="session")
def store(_bench_components):
    """Real VaultStore backed by Qdrant."""
    return _bench_components["store"]


@pytest.fixture(scope="session")
def indexer(_bench_components):
    """Real VaultIndexer."""
    return _bench_components["indexer"]


@pytest.fixture(scope="session")
def searcher(_bench_components):
    """Real VaultSearcher."""
    from vaultspec_rag import VaultSearcher

    comp = _bench_components
    return VaultSearcher(comp["root"], comp["model"], comp["store"])


@pytest.fixture(scope="session")
def root(_bench_components):
    """Synthetic project root path."""
    return _bench_components["root"]
