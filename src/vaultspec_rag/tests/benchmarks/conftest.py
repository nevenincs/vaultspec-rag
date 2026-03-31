"""Benchmark fixtures — real GPU components for performance tests."""

from __future__ import annotations

import shutil

import pytest

from ..conftest import _build_rag_components
from ..constants import QDRANT_SUFFIX_FULL, TEST_PROJECT


@pytest.fixture(scope="session")
def _bench_components(embedding_model):
    """Session-scoped RAG components for benchmarks (full corpus)."""
    components = _build_rag_components(
        TEST_PROJECT,
        fast=False,
        qdrant_suffix=f"{QDRANT_SUFFIX_FULL}-bench",
        model=embedding_model,
    )
    yield components
    components["store"].close()
    db_dir = components["db_dir"]
    if db_dir.exists():
        shutil.rmtree(db_dir)


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
    """Test project root path."""
    return _bench_components["root"]
