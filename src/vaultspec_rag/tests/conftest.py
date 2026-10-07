from __future__ import annotations

import os
import socket
import typing
from contextlib import contextmanager
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, TypedDict

import pytest

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Generator, Mapping

    from pytest import TempPathFactory
    from sentence_transformers import CrossEncoder

    from .. import CodebaseIndexer, EmbeddingModel, VaultIndexer
    from ..indexer import IndexResult
    from ..store_runtime import VaultStore
    from ._jobs_tui_harness import _JobService

from vaultspec_core.config import (
    reset_config,
)

from ..config._settings import VaultSpecConfigWrapper as VaultSpecConfig
from ..config._settings import get_config
from ..config._types import EnvVar
from ..operator_state._installation import ComputeCapability, InstallRole
from ..progress import NullProgressReporter
from ._committed_pins import pin_table_drift
from ._config_fixtures import reset_config as reset_rag_config
from ._model_setup import ensure_model_snapshots, model_setup_timeout_seconds
from ._operator_directory_guard import canonical_path
from ._singleton_root_fixtures import (
    PYTEST_SESSION_ACTIVE_ENV,
    PYTEST_SESSION_ROOT_ENV,
)
from .corpus import CorpusManifest, build_synthetic_vault

# GPU-only: Sentence Transformers with Qwen3 dense and ModernBERT SPARSEUP sparse.
# Requires CUDA.


def _force_machine_singleton_test_paths(paths: Mapping[str, str]) -> None:
    """Restore the session-owned singleton paths and clear both config caches."""

    for var, value in paths.items():
        os.environ[var] = value
    reset_config()
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

    from ..config._types import EnvVar
    from .integration._helpers import _mirror_managed_qdrant_binary

    raw_root = os.environ.get(PYTEST_SESSION_ROOT_ENV)
    if not raw_root:
        raise RuntimeError(
            "repository pytest bootstrap did not publish singleton containment"
        )
    session_root = canonical_path(raw_root)
    status_dir = os.environ.get(EnvVar.STATUS_DIR.value)
    qdrant_storage_dir = os.environ.get(EnvVar.QDRANT_STORAGE_DIR.value)
    if not status_dir or not qdrant_storage_dir:
        raise RuntimeError(
            "repository pytest bootstrap did not publish singleton paths"
        )
    base = Path(status_dir).expanduser().resolve().parent
    session_paths = MappingProxyType(
        {
            PYTEST_SESSION_ACTIVE_ENV: "1",
            PYTEST_SESSION_ROOT_ENV: str(session_root),
            EnvVar.STATUS_DIR.value: status_dir,
            EnvVar.QDRANT_STORAGE_DIR.value: qdrant_storage_dir,
        }
    )
    prior = {var: os.environ.get(var) for var in session_paths}
    try:
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
        reset_config()
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


@pytest.fixture(autouse=True)
def committed_pins_outlive_every_test() -> Generator[None]:
    """Fail the test that leaves a Qdrant pin table changed.

    One declared seam lets a test hold the shipped code to a stand-in release
    by writing its digests into the committed pin tables for a block. A
    digest left behind would make every later test trust bytes no release
    holds, and pass. So after each test both tables are compared with the
    values the source file commits, and the test that changed them is the one
    that fails.
    """
    yield
    drift = pin_table_drift()
    assert not drift, (
        "this test left the committed Qdrant pin tables changed: " + "; ".join(drift)
    )


def _apply_env(values: Mapping[str, str | None]) -> None:
    """Set or unset *values* and clear both configuration caches."""
    for key, value in values.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value
    reset_config()
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


@pytest.fixture
def second_loopback_address() -> str:
    """A loopback address other than 127.0.0.1, or a skip where none exists.

    The monitor admits one peer address, so its refusals are proven from a
    real second one. Linux and Windows route all of 127.0.0.0/8. macOS
    configures 127.0.0.1 alone, and there no such peer can be made without
    root: binding fails and connecting is answered with silence.
    """
    address = "127.0.0.2"
    with socket.socket() as probe:
        try:
            probe.bind((address, 0))
        except OSError:
            pytest.skip(
                f"this host has no {address}; add it with "
                f"`sudo ifconfig lo0 alias {address}` to run this proof"
            )
    return address


def pin_install_role(monkeypatch: pytest.MonkeyPatch, role: InstallRole) -> None:
    """Substitute the one reading of this installation's role.

    The role comes from which distributions the running interpreter holds, and
    the suite can neither add nor remove the inference stack in the shared
    interpreter, so each lane could otherwise reach only one side of every
    role-dependent branch. Only the reading is replaced; every consumer of it -
    install's torch and provisioning steps, the release-mismatch advice - runs
    unchanged.
    """
    from ..operator_state import _compute

    monkeypatch.setattr(_compute, "installed_role", lambda: (role, True))


def pin_daemon_capability(
    monkeypatch: pytest.MonkeyPatch, capability: ComputeCapability
) -> None:
    """Substitute what the interpreter that would run the daemon can do.

    Whether an environment can run the service is asked of a child of that
    interpreter, which imports torch and wakes the driver. The answer is a
    fact about the machine: a workstation with a GPU says it is ready and an
    accelerator-free runner says it is a client, so a test of what a command
    does for a host that can serve, or for one that cannot yet, would assert
    whichever the machine happened to be - and pay seconds per test to find
    out. Only the child's answer is replaced. The judgement made of it, and
    everything each command does with that judgement, run unchanged; the
    child itself is exercised against this machine's real environment in the
    environment-probe and service-environment tests.
    """
    from ..operator_state import _environment_probe
    from ..operator_state._compute import ProbeDepth
    from ..operator_state._environment_probe import InterpreterFacts
    from ..operator_state._models import ComputeReport

    def answer(
        interpreter: str,
        depth: ProbeDepth = ProbeDepth.METADATA,
        *,
        timeout: float | None = None,
    ) -> InterpreterFacts:
        del depth, timeout
        return InterpreterFacts(
            interpreter=interpreter,
            role=InstallRole.HOST,
            mcp_adapter=True,
            executable=interpreter,
            prefix="",
            compute=ComputeReport(capability=capability),
        )

    monkeypatch.setattr(_environment_probe, "probe_interpreter", answer)


@pytest.fixture
def inference_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make this installation read as an inference host that can serve.

    The accelerator-free lane runs without the ``gpu`` extra, so a test of a
    host-only path pins the role or it would silently exercise the client
    branch there instead. The capability is pinned with it, because the model
    and Qdrant steps are gated on both: a host whose accelerator is not
    usable is a different state, staged by ``pin_daemon_capability`` alone.
    """
    pin_install_role(monkeypatch, InstallRole.HOST)
    pin_daemon_capability(monkeypatch, ComputeCapability.READY)


@pytest.fixture
def client_installation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make this installation read as a client, whatever this env holds."""
    pin_install_role(monkeypatch, InstallRole.CLIENT)


def pin_hardware_anchors(monkeypatch: pytest.MonkeyPatch, directory: Path) -> None:
    """Resolve the machine's hardware anchors inside *directory*.

    The anchors cannot be moved through the environment, by design: one
    resolved through anything a process can change would exclude nothing. So
    a fresh interpreter a test starts consults the machine's own, and where a
    live service owns the GPU its start is refused before it does anything
    the test set out to observe. Such a child calls this itself, as the suite
    does for its own process.
    """
    from .. import _gpu_admission, _gpu_owner

    monkeypatch.setattr(
        _gpu_owner, "gpu_owner_anchor_path", lambda: directory / "gpu-owner.lock"
    )
    monkeypatch.setattr(
        _gpu_admission,
        "load_window_lock_path",
        lambda: directory / "gpu-load-window.lock",
    )


@pytest.fixture(autouse=True)
def gpu_owner_anchor(
    request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[Path]:
    """Point every machine-hardware anchor a test reaches at a private file.

    The machine's own anchors may be held by a live service, and a test must
    never contend for them: a test driving a start, a loan or a model load past
    the ownership check would otherwise be refused by the real owner or, on a
    free machine, take the real anchor itself - and an owner holds its anchor
    until the process exits, so one such test silences every GPU test that runs
    after it in that worker, and holds the anchor the developer's own service
    needs. Which makes this unconditional rather than opt-in: a test cannot
    declare in advance that nothing it drives will ask.

    Only where the anchors live is replaced; claiming, lending and refusing run
    unchanged, and there is no such redirection outside the suite. A test that
    asserts where the real ones resolve opts out with ``real_hardware_anchor``.
    """
    from .. import _gpu_owner
    from .._anchor_claim import release_anchor_claim

    anchor = tmp_path / "gpu-owner.lock"
    if "real_hardware_anchor" not in request.keywords:
        pin_hardware_anchors(monkeypatch, tmp_path)
    yield anchor
    with _gpu_owner._guard:
        descriptor = _gpu_owner._held.pop(str(anchor), None)
    if descriptor is not None:
        release_anchor_claim(descriptor, pid_record=True)


@pytest.fixture(autouse=True)
def no_claim_on_a_machine_anchor() -> Generator[None]:
    """Fail a test that left this process owning one of the machine's anchors.

    An ownership claim outlives the test that took it, so the damage shows up
    as an unrelated test being refused the GPU, in another worker, in a run
    that may be on someone else's machine. This names the test that took it
    instead, and lets the claim go so the rest of the worker still runs.

    Independent of the redirect above on purpose: a guard that shares its
    mechanism with the thing it guards reports nothing when that mechanism is
    removed. It runs before the redirect releases, so what it reads is what
    the test left.

    Mutation check: resolved the machine directory from whatever the test had
    claimed rather than from the real anchor, which is how a claim landing
    outside the test's own anchor looks. The borrow that a refused disk
    preflight drives then failed this assertion by name, naming the anchor;
    restoring the real resolution passed. The mutation is the way round it is
    because claiming the real anchor to provoke the guard is the very thing
    it exists to stop.
    """
    yield
    from .. import _gpu_owner
    from .._anchor_claim import hardware_anchor_path, release_anchor_claim

    try:
        machine = os.path.normcase(hardware_anchor_path("gpu-owner.lock").parent)
    except OSError:
        return
    with _gpu_owner._guard:
        left = [
            held
            for held in _gpu_owner._held
            if os.path.normcase(str(Path(held).parent)) == machine
        ]
        for held in left:
            release_anchor_claim(_gpu_owner._held.pop(held), pid_record=True)
    assert not left, (
        f"this test claimed the machine's own hardware anchor: {left}. "
        "Every anchor a test reaches must resolve inside its tmp_path."
    )


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
    from .. import CodebaseIndexer, VaultIndexer
    from ..store_runtime import VaultStore

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
    return EmbeddingModel()


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
    reset_config()
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
    reset_config()
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
def vaultspec_config() -> Generator[VaultSpecConfig]:
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
def config_override() -> Generator[Callable[[dict[str, object]], VaultSpecConfig]]:
    """Factory fixture: call with overrides dict to get a custom config.

    Example::

        def test_custom_port(config_override):
            cfg = config_override({"mcp_port": 9999})
            assert cfg.mcp_port == 9999
    """
    created: list[VaultSpecConfig] = []

    def _make(overrides: dict[str, object]) -> VaultSpecConfig:
        cfg = VaultSpecConfig.from_environment(overrides=overrides)
        created.append(cfg)
        return cfg

    yield _make
    reset_config()
    reset_rag_config()


@pytest.fixture
def clean_config() -> Generator[None]:
    """Reset the config singleton before and after the test."""
    reset_config()
    reset_rag_config()
    yield
    reset_config()
    reset_rag_config()


@pytest.fixture
def control_service() -> typing.Iterator[_JobService]:
    """A real loopback job service for the watch-interface suites.

    Imported here rather than at module scope because this conftest is loaded
    by EVERY pytest invocation and the harness is wanted by four files. It
    reaches the watch interface, which reaches the CLI and the indexer behind
    it: 674 modules and 0.72s, on top of the 275 and 0.24s the rest of this
    file costs. That was most of the price of collecting a single test, and
    all of it was paid by runs that never build a job service.
    """
    from ._jobs_tui_harness import _JobService

    server = _JobService()
    try:
        yield server
    finally:
        server.close()
