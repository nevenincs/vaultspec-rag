from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import pathlib

    from vaultspec_rag import EmbeddingModel
from vaultspec_core.config import reset_config

from vaultspec_rag.config import VaultSpecConfigWrapper as VaultSpecConfig
from vaultspec_rag.config import get_config
from vaultspec_rag.config import reset_config as reset_rag_config
from vaultspec_rag.progress import NullProgressReporter

from .corpus import CorpusManifest, build_synthetic_vault

# GPU-only: sentence-transformers + Qwen3-Embedding-0.6B + SPLADE v3. Requires CUDA.


def _index_corpus(
    root: pathlib.Path,
    model: EmbeddingModel,
) -> dict:
    """Build RAG components and index a synthetic vault at *root*.

    Uses config overrides to place Qdrant data inside the synthetic
    project's data dir — no suffix hacks needed.
    """
    from vaultspec_rag import CodebaseIndexer, VaultIndexer, VaultStore

    store = VaultStore(root)
    indexer = VaultIndexer(root, model, store)
    code_indexer = CodebaseIndexer(root, model, store)
    result = indexer.full_index(reporter=NullProgressReporter())

    return {
        "model": model,
        "store": store,
        "indexer": indexer,
        "code_indexer": code_indexer,
        "index_result": result,
        "root": root,
    }


@pytest.fixture(scope="session")
def embedding_model():
    """Shared EmbeddingModel instance for the entire test session.

    Avoids loading ~900MB of GPU models per fixture.
    """
    from vaultspec_rag import EmbeddingModel

    return EmbeddingModel()


@pytest.fixture(scope="session")
def synthetic_vault(tmp_path_factory) -> CorpusManifest:
    """Session-scoped synthetic vault with 24 well-formed docs."""
    root = tmp_path_factory.mktemp("vault")
    return build_synthetic_vault(root, n_docs=24, seed=42)


@pytest.fixture(scope="session")
def rag_components(embedding_model, synthetic_vault):
    """Real RAG components backed by the synthetic vault.

    Indexes all 24 docs with real GPU embeddings.
    """
    reset_config()
    reset_rag_config()

    components = _index_corpus(synthetic_vault.root, embedding_model)

    yield {**components, "manifest": synthetic_vault}

    components["store"].close()


@pytest.fixture(scope="session")
def rag_components_full(embedding_model, tmp_path_factory):
    """Real RAG components with a larger synthetic corpus (48 docs).

    Used by tests marked @pytest.mark.quality that need broader coverage.
    """
    reset_config()
    reset_rag_config()

    root = tmp_path_factory.mktemp("vault-full")
    manifest = build_synthetic_vault(root, n_docs=48, seed=99)
    components = _index_corpus(root, embedding_model)

    yield {**components, "manifest": manifest}

    components["store"].close()


@pytest.fixture
def malformed_vault(tmp_path) -> CorpusManifest:
    """Function-scoped vault including malformed documents."""
    return build_synthetic_vault(
        tmp_path,
        n_docs=12,
        include_malformed=True,
        seed=77,
    )


@pytest.fixture
def vaultspec_config():
    """Provide a fresh VaultSpecConfig from current environment.

    Resets the singleton before and after to ensure test isolation.
    """
    reset_config()
    reset_rag_config()
    cfg = get_config()
    yield cfg
    reset_config()
    reset_rag_config()


@pytest.fixture
def config_override():
    """Factory fixture: call with overrides dict to get a custom config.

    Example::

        def test_custom_port(config_override):
            cfg = config_override({"mcp_port": 9999})
            assert cfg.mcp_port == 9999
    """
    created: list[VaultSpecConfig] = []

    def _make(overrides: dict) -> VaultSpecConfig:
        cfg = VaultSpecConfig.from_environment(overrides=overrides)
        created.append(cfg)
        return cfg

    yield _make
    reset_config()
    reset_rag_config()


@pytest.fixture
def clean_config():
    """Reset the config singleton before and after the test."""
    reset_config()
    reset_rag_config()
    yield
    reset_config()
    reset_rag_config()
