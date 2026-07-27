from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, TypedDict

import pytest

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Generator, Mapping

    from pytest import TempPathFactory
    from sentence_transformers import CrossEncoder

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
from ..config import EnvVar, get_config
from ..config import VaultSpecConfigWrapper as VaultSpecConfig
from ..config import reset_config as reset_rag_config
from ..progress import NullProgressReporter
from ._model_setup import ensure_model_snapshots, model_setup_timeout_seconds
from .corpus import CorpusManifest, build_synthetic_vault

# GPU-only: sentence-transformers + Qwen3-Embedding-0.6B + SPLADE v3. Requires CUDA.


def _force_machine_singleton_test_paths(paths: Mapping[str, str]) -> None:
    """Restore the session-owned singleton paths and clear both config caches."""

    for var, value in paths.items():
        os.environ[var] = value
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()


@pytest.fixture(scope="session", autouse=True)
def isolated_machine_singleton_dirs(
    host_provisioned_qdrant_source: tuple[Path, Path] | None,
) -> Generator[Mapping[str, str]]:
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

    from ..config import EnvVar
    from .integration._helpers import _mirror_managed_qdrant_binary

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
        if host_provisioned_qdrant_source is not None:
            _mirror_managed_qdrant_binary(
                base / "status",
                host_provisioned_qdrant_source,
            )
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


def _apply_env(values: Mapping[str, str | None]) -> None:
    """Set or unset *values* and clear both configuration caches."""
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    reset_config()  # pyright: ignore[reportMissingTypeStubs]
    reset_rag_config()


@contextmanager
def managed_env(**overrides: str | None) -> Generator[None]:
    """Apply environment *overrides* for the duration of the block.

    A ``None`` value removes the variable. Both configuration caches are
    cleared on entry and again on exit, because the managed directories and the
    Qdrant URL are all read through a cached config object: an override that
    does not clear the cache silently has no effect, and one that does not
    clear it on the way out leaks into whatever reads config next.

    The autouse re-arm below already restores the two session singleton paths at
    every test boundary; this restores whatever keys the caller actually named,
    which is what makes it usable for the other overrides (a Qdrant URL, an
    admin timeout) and for a block narrower than one test.
    """
    prior: dict[str, str | None] = {key: os.environ.get(key) for key in overrides}
    try:
        _apply_env(overrides)
        yield
    finally:
        _apply_env(prior)


@pytest.fixture
def isolated_status_dir(tmp_path: Path) -> Generator[Path]:
    """Redirect the managed service dir at a fresh temp dir for one test.

    The status dir resolves the recorded service, its auth token, the managed
    log tree, and the storage manifest, so a test that reads or writes any of
    those has to relocate it or it shares state with the operator's real
    service. Yields the relocated directory, created and empty.
    """
    status_dir = tmp_path / "managed"
    status_dir.mkdir(parents=True, exist_ok=True)
    with managed_env(**{EnvVar.STATUS_DIR.value: str(status_dir)}):
        yield status_dir


@pytest.fixture
def isolated_singleton_dirs(tmp_path: Path) -> Generator[Path]:
    """Redirect both machine-singleton dirs so lock and service stay in tmp.

    The machine lock and the Qdrant identity sidecar are anchored to the Qdrant
    storage dir, not the status dir, so a test driving service start or stop
    must relocate both or it contends for the real machine singleton. Yields
    the relocated status dir.
    """
    status_dir = tmp_path / "status"
    status_dir.mkdir(parents=True, exist_ok=True)
    with managed_env(
        **{
            EnvVar.STATUS_DIR.value: str(status_dir),
            EnvVar.QDRANT_STORAGE_DIR.value: str(tmp_path / "qdrant" / "storage"),
        }
    ):
        yield status_dir


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
    reranker: CrossEncoder


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
def shared_reranker() -> Generator[CrossEncoder]:
    """One CrossEncoder for the whole session, shared the way the service shares it.

    The service loads exactly one reranker on its registry and injects it into
    every searcher it constructs; a searcher built without one lazily loads a
    private ~2.3 GB copy on first rerank instead. Dozens of per-test copies
    outlive their tests until garbage collection and push the device into
    shared-system-memory fallback, degrading every later forward pass. Loading
    through the registry keeps this fixture on the production construction
    path; missing snapshots are acquired by the killable setup worker first,
    and the offline overrides make the load itself run cache-only, exactly as
    the ``embedding_model`` fixture does.
    """
    from ..service import ServiceRegistry

    cfg = get_config()
    ensure_model_snapshots(
        (str(cfg.reranker_model),),
        timeout_seconds=model_setup_timeout_seconds(),
    )
    registry = ServiceRegistry()
    with managed_env(
        **{
            EnvVar.HF_HUB_OFFLINE.value: "1",
            EnvVar.TRANSFORMERS_OFFLINE.value: "1",
        }
    ):
        reranker = registry.get_reranker()
    yield reranker
    registry.close_all()


@pytest.fixture(scope="session")
def synthetic_vault(tmp_path_factory: TempPathFactory) -> CorpusManifest:
    """Session-scoped synthetic vault with 24 well-formed docs."""
    root = tmp_path_factory.mktemp("vault")
    return build_synthetic_vault(root, n_docs=24, seed=42)


@pytest.fixture(scope="session")
def rag_components(
    embedding_model: EmbeddingModel,
    shared_reranker: CrossEncoder,
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
        reranker=shared_reranker,
    )

    components["store"].close()


@pytest.fixture(scope="session")
def rag_components_full(
    embedding_model: EmbeddingModel,
    shared_reranker: CrossEncoder,
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
        reranker=shared_reranker,
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
