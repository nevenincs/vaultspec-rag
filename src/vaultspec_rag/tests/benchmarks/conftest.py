"""Benchmark fixtures - real GPU components for performance tests."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

import pytest

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from pytest import TempPathFactory

    from ...embeddings import EmbeddingModel
    from ...indexer import VaultIndexer
    from ...search import VaultSearcher
    from ...store import VaultStore
    from ..conftest import RagComponentsWithManifest

from ..conftest import _index_corpus
from ..corpus import build_synthetic_vault


@pytest.fixture(scope="session")
def _bench_components(  # pyright: ignore[reportUnusedFunction]
    embedding_model: EmbeddingModel,
    tmp_path_factory: TempPathFactory,
) -> Generator[RagComponentsWithManifest]:
    """Session-scoped RAG components for benchmarks (48-doc corpus)."""
    root: Path = tmp_path_factory.mktemp("bench-vault")
    manifest = build_synthetic_vault(root, n_docs=48, seed=300)
    components = _index_corpus(root, embedding_model)
    yield cast(
        "RagComponentsWithManifest",
        components.__class__(  # type: ignore[call-arg]
            **components,  # type: ignore[misc]
            manifest=manifest,
        ),
    )
    components["store"].close()


@pytest.fixture(scope="session")
def model(_bench_components: RagComponentsWithManifest) -> EmbeddingModel:
    """Real EmbeddingModel on CUDA."""
    return _bench_components["model"]


@pytest.fixture(scope="session")
def store(_bench_components: RagComponentsWithManifest) -> VaultStore:
    """Real VaultStore backed by Qdrant."""
    return _bench_components["store"]


@pytest.fixture(scope="session")
def indexer(_bench_components: RagComponentsWithManifest) -> VaultIndexer:
    """Real VaultIndexer."""
    return _bench_components["indexer"]


@pytest.fixture(scope="session")
def searcher(_bench_components: RagComponentsWithManifest) -> VaultSearcher:
    """Real VaultSearcher."""
    from ... import VaultSearcher

    comp = _bench_components
    return VaultSearcher(comp["root"], comp["model"], comp["store"])


@pytest.fixture(scope="session")
def root(_bench_components: RagComponentsWithManifest) -> Path:
    """Synthetic project root path."""
    return _bench_components["root"]
