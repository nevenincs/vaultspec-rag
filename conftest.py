"""Root conftest for all vaultspec tests.

RAG test constants and fixtures live in
src/vaultspec_rag/tests/conftest.py and src/vaultspec_rag/tests/constants.py.
"""

import atexit
import os
import shutil
import tempfile
import time
import warnings
from pathlib import Path

# Identify pytest before importing project modules or collecting test modules.
# Until pytest_configure pins the session root, guarded effects fail closed.
_PYTEST_SINGLETON_BOOTSTRAP_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_BOOTSTRAP"
_PRIOR_PYTEST_SINGLETON_BOOTSTRAP = os.environ.get(_PYTEST_SINGLETON_BOOTSTRAP_ENV)
os.environ[_PYTEST_SINGLETON_BOOTSTRAP_ENV] = "1"

import pytest  # noqa: E402  # bootstrap sentinel must precede project imports

_PYTEST_SINGLETON_ACTIVE_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ACTIVE"
_PYTEST_SINGLETON_ROOT_ENV = "_VAULTSPEC_RAG_PYTEST_SINGLETON_ROOT"
_STATUS_DIR_ENV = "VAULTSPEC_RAG_STATUS_DIR"
_QDRANT_STORAGE_DIR_ENV = "VAULTSPEC_RAG_QDRANT_STORAGE_DIR"
_SINGLETON_ENV_NAMES = (
    _PYTEST_SINGLETON_ACTIVE_ENV,
    _PYTEST_SINGLETON_ROOT_ENV,
    _STATUS_DIR_ENV,
    _QDRANT_STORAGE_DIR_ENV,
)
_singleton_prior_env: dict[str, str | None] | None = None
_singleton_root: Path | None = None
_singleton_root_owned = False

# The tier vocabulary and its collection-time gate live in the package, at
# vaultspec_rag.tests._tier_gate, so they can be exercised by ordinary tests.
# They are imported inside the hooks below rather than here: this module runs
# before the pytest session pins its root, and the guarded effects above must
# stay the first thing that happens.


def _load_dotenv_if_available() -> None:
    """Load .env file from project root if python-dotenv is available."""
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


_load_dotenv_if_available()


def _capture_host_provisioned_qdrant() -> tuple[Path, Path] | None:
    """Capture the real managed Qdrant install before pytest redirects it.

    ``pytest_configure`` replaces the status directory before session fixtures
    run. Resolve the production-managed install now, while the ambient config
    still names it, and retain only its binary and manifest paths. The binary
    is still re-verified from the copied manifest before execution.
    """
    from vaultspec_rag.qdrant_runtime._constants import (
        MANIFEST_FILENAME,
        QDRANT_SERVER_VERSION,
    )
    from vaultspec_rag.qdrant_runtime._resolve import resolve_binary

    resolved = resolve_binary(QDRANT_SERVER_VERSION)
    if resolved is None or resolved.source != "provisioned":
        return None
    manifest = resolved.path.parent / MANIFEST_FILENAME
    if not manifest.is_file():
        return None
    return resolved.path, manifest


_HOST_PROVISIONED_QDRANT = _capture_host_provisioned_qdrant()


@pytest.fixture(scope="session")
def host_provisioned_qdrant_source() -> tuple[Path, Path] | None:
    """Return the manifest-backed host install captured before isolation."""
    return _HOST_PROVISIONED_QDRANT


@pytest.fixture(scope="session")
def required_host_provisioned_qdrant_source(
    host_provisioned_qdrant_source: tuple[Path, Path] | None,
) -> tuple[Path, Path]:
    """Require the captured managed install for real daemon tests."""
    if host_provisioned_qdrant_source is None:
        pytest.fail(
            "No provisioned qdrant binary on the host; run "
            "'vaultspec-rag server qdrant install' before this lifecycle test."
        )
    return host_provisioned_qdrant_source


def _reset_singleton_config_caches() -> None:
    """Make early environment containment visible to both config layers."""
    from vaultspec_core.config import reset_config

    from vaultspec_rag.config._settings import reset_config as reset_rag_config

    reset_config()
    reset_rag_config()


def pytest_configure(config: pytest.Config) -> None:
    """Pin singleton containment before pytest imports any test module."""
    global _singleton_prior_env, _singleton_root, _singleton_root_owned
    if _singleton_root is not None:
        return

    _singleton_prior_env = {name: os.environ.get(name) for name in _SINGLETON_ENV_NAMES}
    inherited_root = os.environ.get(_PYTEST_SINGLETON_ROOT_ENV)
    inherited_active = os.environ.get(_PYTEST_SINGLETON_ACTIVE_ENV) == "1"
    if inherited_active and inherited_root:
        root = Path(inherited_root).expanduser().resolve()
    else:
        root = Path(tempfile.mkdtemp(prefix="vaultspec-rag-pytest-")).resolve()
        _singleton_root_owned = True

    worker = os.environ.get("PYTEST_XDIST_WORKER")
    pytest_temp_name = "pytest-temp" if not worker else f"pytest-temp-{worker}"
    config.option.basetemp = str(root / pytest_temp_name)
    base_name = "machine-singleton" if not worker else f"machine-singleton-{worker}"
    base = root / base_name
    status_dir = base / "status"
    qdrant_storage_dir = base / "qdrant-server" / "storage"
    status_dir.mkdir(parents=True, exist_ok=True)
    qdrant_storage_dir.mkdir(parents=True, exist_ok=True)

    os.environ[_PYTEST_SINGLETON_ACTIVE_ENV] = "1"
    os.environ[_PYTEST_SINGLETON_ROOT_ENV] = str(root)
    os.environ[_STATUS_DIR_ENV] = str(status_dir)
    os.environ[_QDRANT_STORAGE_DIR_ENV] = str(qdrant_storage_dir)

    from vaultspec_rag._test_isolation import (
        register_pytest_singleton_root,
        sweep_orphaned_singleton_roots,
    )

    _singleton_root = register_pytest_singleton_root(root)
    _reset_singleton_config_caches()
    if _singleton_root_owned:
        # Register an atexit backstop so a soft exit that bypasses
        # pytest_unconfigure still reclaims this run's ~100MB root, and reclaim
        # leftover roots from prior runs killed before any cleanup ran. A hard
        # external kill skips atexit too; its leftover is reclaimed by the next
        # run's sweep here.
        atexit.register(_atexit_reclaim_singleton_root)
        sweep_orphaned_singleton_roots(keep=root, now=time.time())


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore ambient configuration after the complete pytest session."""
    del config
    global _singleton_prior_env, _singleton_root
    prior = _singleton_prior_env
    root = _singleton_root
    if prior is not None:
        for name, value in prior.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
        _reset_singleton_config_caches()
    if _PRIOR_PYTEST_SINGLETON_BOOTSTRAP is None:
        os.environ.pop(_PYTEST_SINGLETON_BOOTSTRAP_ENV, None)
    else:
        os.environ[_PYTEST_SINGLETON_BOOTSTRAP_ENV] = _PRIOR_PYTEST_SINGLETON_BOOTSTRAP
    if _singleton_root_owned and root is not None:
        try:
            shutil.rmtree(root)
        except OSError as exc:
            warnings.warn(
                f"could not remove pytest singleton root {root}: {exc}",
                ResourceWarning,
                stacklevel=1,
            )
    _singleton_prior_env = None
    _singleton_root = None


def _atexit_reclaim_singleton_root() -> None:
    """Reclaim the owned session root if pytest_unconfigure did not run.

    pytest_unconfigure is the normal-exit cleanup and clears ``_singleton_root``
    once it removes the root; this backstop covers a pytest process that exits
    without it (an aborted or errored session), so the root is not leaked. It is
    idempotent - a no-op once pytest_unconfigure has cleared the root - and a
    hard external kill bypasses it, leaving the next run's startup sweep to
    reclaim the leftover.
    """
    root = _singleton_root
    if _singleton_root_owned and root is not None:
        shutil.rmtree(root, ignore_errors=True)


def _has_hf_token() -> bool:
    """Return True when Hugging Face auth is available to test code."""
    if os.environ.get("HF_TOKEN"):
        return True
    try:
        from huggingface_hub import get_token
    except ImportError:
        return False
    return bool(get_token())


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Group GPU-bound tests for xdist, and refuse any test with a bad tier.

    Raises:
        pytest.UsageError: When a collected test declares no tier, or declares
            the fast tier alongside a slow one.
    """
    from vaultspec_rag.tests._tier_gate import enforce_tiers, group_gpu_items

    group_gpu_items(items)
    enforce_tiers(items)


def pytest_runtestloop(session: pytest.Session) -> None:
    """Fail fast if Hugging Face auth is missing for selected GPU tests.

    Runs after deselection so only *selected* items are checked.
    This avoids blocking unit-only runs that don't need GPU access.
    """
    from vaultspec_rag.tests._tier_gate import GPU_MARKERS, SUBPROCESS_GPU

    needs_token = GPU_MARKERS | {SUBPROCESS_GPU}
    for item in session.items:
        item_markers = {m.name for m in item.iter_markers()}
        if item_markers & needs_token:
            if not _has_hf_token():
                pytest.exit(
                    "Hugging Face authentication is required for GPU "
                    "tests (gated model naver/splade-v3). Set HF_TOKEN, "
                    "put it in .env, or run `hf auth login` before running "
                    "tests.",
                    returncode=1,
                )
            break
