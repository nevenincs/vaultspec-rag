from __future__ import annotations

import shutil
import subprocess
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    import pathlib
from vaultspec.config import reset_config

from vaultspec_rag.config import VaultSpecConfigWrapper as VaultSpecConfig
from vaultspec_rag.config import get_config
from vaultspec_rag.tests.constants import (
    GPU_FAST_CORPUS_STEMS,
    PROJECT_ROOT,
    QDRANT_SUFFIX_FAST,
    QDRANT_SUFFIX_FULL,
    TEST_PROJECT,
)

# GPU-only: sentence-transformers + Qwen3-Embedding-0.6B + SPLADE v3. Requires CUDA.


def _fast_index(indexer, model, store, root, stems):
    """Index only the given subset of document stems."""
    from vaultspec.vaultcore import scan_vault

    from vaultspec_rag import IndexResult, prepare_document

    start = time.time()

    paths = [p for p in scan_vault(root) if p.stem in stems]
    docs = []
    for p in paths:
        doc = prepare_document(p, root)
        if doc is not None:
            docs.append(doc)

    if not docs:
        return IndexResult(
            total=0,
            added=0,
            updated=0,
            removed=0,
            duration_ms=0,
            device=model.device,
        )

    texts = [f"{d.title}\n\n{d.content}" for d in docs]
    vectors = model.encode_documents(texts)
    sparse_vecs = model.encode_documents_sparse(texts)

    for doc, vec, svec in zip(docs, vectors, sparse_vecs, strict=True):
        doc.vector = vec.tolist()
        doc.sparse_indices = list(svec.indices)
        doc.sparse_values = list(svec.values)

    store.ensure_table()
    store.upsert_documents(docs)

    # Save metadata for incremental indexing
    indexer._save_meta(docs)

    duration_ms = int((time.time() - start) * 1000)
    return IndexResult(
        total=len(docs),
        added=len(docs),
        updated=0,
        removed=0,
        duration_ms=duration_ms,
        device=model.device,
    )


def _build_rag_components(
    root: pathlib.Path, *, fast: bool, qdrant_suffix: str = ""
) -> dict:
    """Build RAG components for testing.

    When ``fast=True``, indexes a 13-doc subset covering all doc_types
    and key features.  When ``fast=False``, indexes the full corpus.

    ``qdrant_suffix`` isolates the qdrant directory so that the fast and
    full fixtures don't share the same storage path.
    """

    from vaultspec_rag import EmbeddingModel, VaultIndexer, VaultStore

    qdrant_name = f".qdrant{qdrant_suffix}"
    qdrant_dir = root / qdrant_name

    # Clean up any previous test data
    if qdrant_dir.exists():
        shutil.rmtree(qdrant_dir)

    model = EmbeddingModel()
    store = VaultStore(root)
    # Override db_path to use the suffixed directory for test isolation
    if qdrant_suffix:
        store._client.close()
        store.db_path = qdrant_dir
        store.db_path.mkdir(parents=True, exist_ok=True)
        from qdrant_client import QdrantClient as _QdrantClient

        store._client = _QdrantClient(path=str(qdrant_dir))

    indexer = VaultIndexer(root, model, store)

    if fast:
        result = _fast_index(indexer, model, store, root, GPU_FAST_CORPUS_STEMS)
    else:
        result = indexer.full_index()

    return {
        "model": model,
        "store": store,
        "indexer": indexer,
        "index_result": result,
        "root": root,
        "db_dir": qdrant_dir,
    }


@pytest.fixture(scope="session")
def rag_components():
    """Set up real RAG components once for the entire test session.

    Indexes a 13-doc subset covering all 5 doc_types and key features.
    Uses .qdrant-fast/ to avoid colliding with the full-corpus fixture.
    """
    components = _build_rag_components(
        TEST_PROJECT, fast=True, qdrant_suffix=QDRANT_SUFFIX_FAST
    )

    yield components

    db_dir = components["db_dir"]
    if db_dir.exists():
        shutil.rmtree(db_dir)


@pytest.fixture(scope="session")
def rag_components_full():
    """Set up real RAG components with the FULL 213-doc corpus.

    Only used by tests marked @pytest.mark.quality that need full-corpus
    coverage (quality precision tests, document count assertions, etc.).
    Uses .qdrant-full/ to avoid colliding with the fast fixture.
    """
    components = _build_rag_components(
        TEST_PROJECT, fast=False, qdrant_suffix=QDRANT_SUFFIX_FULL
    )

    yield components

    db_dir = components["db_dir"]
    if db_dir.exists():
        shutil.rmtree(db_dir)


@pytest.fixture
def require_gpu_corpus(rag_components):
    """Assert RAG corpus is available.

    Kept for backward compatibility with test files that reference it.
    """
    assert rag_components["model"] is not None


def _cleanup_test_project(root: pathlib.Path) -> None:
    """Remove transient artifacts, preserving .vault/ and README."""
    for item in root.iterdir():
        if item.name in (".vault", "README.md", ".gitignore"):
            continue
        if item.is_dir():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


@pytest.fixture(scope="session", autouse=True)
def _vault_snapshot_reset():
    """Reset test-project/.vault/ to git HEAD after the full test session."""
    yield
    subprocess.run(
        ["git", "checkout", "--", "test-project/.vault/"],
        cwd=PROJECT_ROOT,
        check=False,
    )


@pytest.fixture
def vaultspec_config():
    """Provide a fresh VaultSpecConfig from current environment.

    Resets the singleton before and after to ensure test isolation.
    """
    reset_config()
    cfg = get_config()
    yield cfg
    reset_config()


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


@pytest.fixture
def clean_config():
    """Reset the config singleton before and after the test."""
    reset_config()
    yield
    reset_config()
