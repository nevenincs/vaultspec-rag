from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypedDict

import pytest

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Generator
    from pathlib import Path

    from pytest import TempPathFactory

    from .. import CodebaseIndexer, EmbeddingModel, VaultIndexer, VaultStore
    from ..indexer import IndexResult

from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]
    reset_config,
)

from ..config import VaultSpecConfigWrapper as VaultSpecConfig
from ..config import get_config
from ..config import reset_config as reset_rag_config
from ..progress import NullProgressReporter
from .corpus import CorpusManifest, build_synthetic_vault

# GPU-only: sentence-transformers + Qwen3-Embedding-0.6B + SPLADE v3. Requires CUDA.


class RagComponents(TypedDict):
    """Typed bundle returned by :func:`_index_corpus` and yielded by RAG fixtures."""

    model: EmbeddingModel
    store: VaultStore
    indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    index_result: IndexResult
    root: Path


class RagComponentsWithManifest(TypedDict):
    """RAG components bundle that also carries the :class:`CorpusManifest`."""

    model: EmbeddingModel
    store: VaultStore
    indexer: VaultIndexer
    code_indexer: CodebaseIndexer
    index_result: IndexResult
    root: Path
    manifest: CorpusManifest


def _index_corpus(
    root: pathlib.Path,
    model: EmbeddingModel,
) -> RagComponents:
    """Build RAG components and index a synthetic vault at *root*.

    Uses config overrides to place Qdrant data inside the synthetic
    project's data dir - no suffix hacks needed.
    """
    from .. import CodebaseIndexer, VaultIndexer, VaultStore

    store = VaultStore(root)
    indexer = VaultIndexer(root, model, store)
    code_indexer = CodebaseIndexer(root, model, store)
    result = indexer.full_index(reporter=NullProgressReporter())

    return RagComponents(
        model=model,
        store=store,
        indexer=indexer,
        code_indexer=code_indexer,
        index_result=result,
        root=root,
    )


@pytest.fixture(scope="session")
def embedding_model() -> EmbeddingModel:
    """Shared EmbeddingModel instance for the entire test session.

    Avoids loading ~900MB of GPU models per fixture.
    """
    from .. import EmbeddingModel

    return EmbeddingModel()


@pytest.fixture(scope="session")
def synthetic_vault(tmp_path_factory: TempPathFactory) -> CorpusManifest:
    """Session-scoped synthetic vault with 24 well-formed docs."""
    root = tmp_path_factory.mktemp("vault")
    return build_synthetic_vault(root, n_docs=24, seed=42)


@pytest.fixture(scope="session")
def rag_components(
    embedding_model: EmbeddingModel,
    synthetic_vault: CorpusManifest,
) -> Generator[RagComponentsWithManifest]:
    """Real RAG components backed by the synthetic vault.

    Indexes all 24 docs with real GPU embeddings.
    """
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()

    components = _index_corpus(synthetic_vault.root, embedding_model)

    yield RagComponentsWithManifest(
        model=components["model"],
        store=components["store"],
        indexer=components["indexer"],
        code_indexer=components["code_indexer"],
        index_result=components["index_result"],
        root=components["root"],
        manifest=synthetic_vault,
    )

    components["store"].close()


@pytest.fixture(scope="session")
def rag_components_full(
    embedding_model: EmbeddingModel,
    tmp_path_factory: TempPathFactory,
) -> Generator[RagComponentsWithManifest]:
    """Real RAG components with a larger synthetic corpus (48 docs).

    Used by tests marked @pytest.mark.quality that need broader coverage.
    """
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()

    root = tmp_path_factory.mktemp("vault-full")
    manifest = build_synthetic_vault(root, n_docs=48, seed=99)
    components = _index_corpus(root, embedding_model)

    yield RagComponentsWithManifest(
        model=components["model"],
        store=components["store"],
        indexer=components["indexer"],
        code_indexer=components["code_indexer"],
        index_result=components["index_result"],
        root=components["root"],
        manifest=manifest,
    )

    components["store"].close()


@pytest.fixture
def malformed_vault(tmp_path: pathlib.Path) -> CorpusManifest:
    """Function-scoped vault including malformed documents."""
    return build_synthetic_vault(
        tmp_path,
        n_docs=12,
        include_malformed=True,
        seed=77,
    )


@pytest.fixture
def vaultspec_config() -> Generator[VaultSpecConfig]:
    """Provide a fresh VaultSpecConfig from current environment.

    Resets the singleton before and after to ensure test isolation.
    """
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()
    cfg = get_config()
    yield cfg
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()


@pytest.fixture
def config_override() -> Generator[Callable[[dict[str, Any]], VaultSpecConfig]]:
    """Factory fixture: call with overrides dict to get a custom config.

    Example::

        def test_custom_port(config_override):
            cfg = config_override({"mcp_port": 9999})
            assert cfg.mcp_port == 9999
    """
    created: list[VaultSpecConfig] = []

    def _make(overrides: dict[str, Any]) -> VaultSpecConfig:
        cfg = VaultSpecConfig.from_environment(overrides=overrides)
        created.append(cfg)
        return cfg

    yield _make
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()


@pytest.fixture
def clean_config() -> Generator[None]:
    """Reset the config singleton before and after the test."""
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()
    yield
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()
