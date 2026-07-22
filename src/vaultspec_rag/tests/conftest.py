from __future__ import annotations

from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypedDict

import pytest

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Generator, Mapping

    from pytest import TempPathFactory

    from .. import CodebaseIndexer, EmbeddingModel, VaultIndexer, VaultStore
    from ..indexer import IndexResult

from vaultspec_core.config import (  # pyright: ignore[reportMissingTypeStubs]
    reset_config,
)

from .._test_isolation import (
    PYTEST_MANAGED_SINGLETON_ACTIVE_ENV,
    PYTEST_MANAGED_SINGLETON_ROOT_ENV,
    register_pytest_singleton_root,
)
from ..config import VaultSpecConfigWrapper as VaultSpecConfig
from ..config import get_config
from ..config import reset_config as reset_rag_config
from ..progress import NullProgressReporter
from ._model_setup import ensure_model_snapshots, model_setup_timeout_seconds
from .corpus import CorpusManifest, build_synthetic_vault

# GPU-only: sentence-transformers + Qwen3-Embedding-0.6B + SPLADE v3. Requires CUDA.


def _force_machine_singleton_test_paths(paths: Mapping[str, str]) -> None:
    """Restore the session-owned singleton paths and clear both config caches."""
    import os

    for var, value in paths.items():
        os.environ[var] = value
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()


@pytest.fixture(scope="session", autouse=True)
def isolated_machine_singleton_dirs() -> Generator[Mapping[str, str]]:
    """Point the machine-singleton dirs at a session temp tree for every test.

    The status dir and the qdrant storage dir resolve the machine-global
    managed service, its lock, and its manifest. A test that forgets to
    isolate them reaches the operator's real resident service - a pytest
    run once terminated the shared production daemon mid-index exactly
    this way, killing two in-flight jobs. Isolation is therefore
    structural: ambient values are saved for session teardown but never
    trusted during the run, and individual tests may still narrow further
    with their own isolated overrides.
    """
    import os

    from ..config import EnvVar
    from .integration._helpers import (
        _mirror_managed_qdrant_binary,
        _resolve_host_provisioned_qdrant,
    )

    host_qdrant = _resolve_host_provisioned_qdrant()
    raw_root = os.environ.get(PYTEST_MANAGED_SINGLETON_ROOT_ENV)
    if not raw_root:
        raise RuntimeError(
            "repository pytest bootstrap did not publish singleton containment"
        )
    session_root = register_pytest_singleton_root(raw_root)
    status_dir = os.environ.get(EnvVar.STATUS_DIR.value)
    qdrant_storage_dir = os.environ.get(EnvVar.QDRANT_STORAGE_DIR.value)
    if not status_dir or not qdrant_storage_dir:
        raise RuntimeError(
            "repository pytest bootstrap did not publish singleton paths"
        )
    base = Path(status_dir).expanduser().resolve().parent
    session_paths = MappingProxyType(
        {
            PYTEST_MANAGED_SINGLETON_ACTIVE_ENV: "1",
            PYTEST_MANAGED_SINGLETON_ROOT_ENV: str(session_root),
            EnvVar.STATUS_DIR.value: status_dir,
            EnvVar.QDRANT_STORAGE_DIR.value: qdrant_storage_dir,
        }
    )
    prior = {var: os.environ.get(var) for var in session_paths}
    try:
        register_pytest_singleton_root(session_root)
        _force_machine_singleton_test_paths(session_paths)
        if host_qdrant is not None:
            _mirror_managed_qdrant_binary(base / "status", host_qdrant)
        yield session_paths
    finally:
        for var, value in prior.items():
            if value is None:
                os.environ.pop(var, None)
            else:
                os.environ[var] = value
        reset_config()  # pyright: ignore[reportMissingTypeStubs]
        reset_rag_config()


@pytest.fixture(autouse=True)
def rearm_machine_singleton_isolation(
    isolated_machine_singleton_dirs: Mapping[str, str],
) -> Generator[None]:
    """Re-arm machine-dir isolation at both boundaries of every test.

    Tests may temporarily install narrower isolated paths. Regardless of whether
    a test removes a variable, redirects it to a non-empty value, or rebuilds a
    cached config from that value, the next boundary restores the canonical
    session paths and clears both configuration singletons.
    """
    _force_machine_singleton_test_paths(isolated_machine_singleton_dirs)
    try:
        yield
    finally:
        _force_machine_singleton_test_paths(isolated_machine_singleton_dirs)


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

    Avoids loading ~900MB of GPU models per fixture. Missing snapshots are
    downloaded by a killable subprocess under an explicit cold-session
    deadline; construction then runs cache-only so external metadata retries
    cannot leave pytest suspended in fixture setup.
    """
    from .. import EmbeddingModel

    cfg = get_config()
    ensure_model_snapshots(
        (str(cfg.embedding_model), str(cfg.sparse_model)),
        timeout_seconds=model_setup_timeout_seconds(),
    )
    return EmbeddingModel(local_files_only=True)


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
