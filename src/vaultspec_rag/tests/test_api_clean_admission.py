"""CPU proofs that API cleanup owns its store through the registry."""

from __future__ import annotations

import ast
import inspect
import sys
import textwrap
import threading
from contextlib import contextmanager
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from .. import api
from .._index_breadth import index_meta_path
from .._source_types import PublicSourceType
from ..api import clean
from ..registry import get_registry, reset_registry
from ..service import ProjectBusyError, ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def isolated_registry() -> Generator[ServiceRegistry]:
    """Build and discard the process-wide registry around one cleanup proof."""
    reset_registry()
    registry = get_registry()
    try:
        yield registry
    finally:
        reset_registry()


def _write_vault_sidecar(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    sidecar = index_meta_path(root, PublicSourceType.VAULT)
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text('{"state": "must-survive-busy-cleanup"}', encoding="utf-8")
    return sidecar


def test_clean_rejects_a_leased_warm_project_before_mutating_sidecars(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """Maintenance fails before deletion when a request currently pins a slot."""
    root = tmp_path / "leased-warm-project"
    sidecar = _write_vault_sidecar(root)
    warm_slot = isolated_registry.peek_project(root)

    with isolated_registry.lease(root) as leased_slot:
        assert leased_slot is warm_slot
        with pytest.raises(ProjectBusyError):
            clean(root, clean_type="vault", registry=isolated_registry)
        assert sidecar.exists(), "busy cleanup must not erase a breadth claim"

    assert isolated_registry.peek_project(root) is warm_slot


def test_clean_waits_for_a_cold_store_lease_then_recreates_the_collection(
    tmp_path: Path,
    isolated_registry: ServiceRegistry,
) -> None:
    """Cleanup waits for the real cold lease that owns this root's storage lock."""
    root = tmp_path / "cold-store-lease"
    sidecar = _write_vault_sidecar(root)
    completed = threading.Event()
    failures: list[BaseException] = []
    outcomes: list[list[str]] = []

    def run_cleanup() -> None:
        try:
            outcomes.append(clean(root, clean_type="vault", registry=isolated_registry))
        except BaseException as exc:
            failures.append(exc)
        finally:
            completed.set()

    worker = threading.Thread(target=run_cleanup, name="clean-after-cold-lease")
    try:
        with isolated_registry.lease_store(root) as cold_store:
            assert not cold_store.client.collection_exists(cold_store.TABLE_NAME)
            worker.start()
            assert not completed.wait(timeout=0.25)
            assert sidecar.exists(), "cleanup must not mutate before root admission"
    finally:
        worker.join(timeout=10)

    assert not worker.is_alive(), (
        "cleanup did not complete after the cold lease released"
    )
    assert failures == []
    assert outcomes == [["vault"]]
    assert not sidecar.exists()
    with isolated_registry.lease_store(root) as inspected_store:
        assert inspected_store.client.collection_exists(inspected_store.TABLE_NAME)


def _attribute_calls(node: ast.AST, attr: str) -> list[ast.Call]:
    """Return every call in *node* made through an attribute named *attr*."""
    return [
        found
        for found in ast.walk(node)
        if isinstance(found, ast.Call)
        and isinstance(found.func, ast.Attribute)
        and found.func.attr == attr
    ]


def _name_calls(node: ast.AST, name: str) -> list[ast.Call]:
    """Return every call in *node* made through a bare name *name*."""
    return [
        found
        for found in ast.walk(node)
        if isinstance(found, ast.Call)
        and isinstance(found.func, ast.Name)
        and found.func.id == name
    ]


def _imported_names(node: ast.AST, module: str, name: str) -> list[str]:
    """Return each import of *name* from *module* found under *node*."""
    return [
        imported.name
        for found in ast.walk(node)
        if isinstance(found, ast.ImportFrom) and found.module == module
        for imported in found.names
        if imported.name == name
    ]


def test_clean_does_not_construct_or_import_vault_store_directly() -> None:
    """The facade delegates store lifecycle ownership to ServiceRegistry.

    The scan reads ``clean``'s own AST, so a guard that stopped reaching the
    function would pass on an empty walk rather than object.

    Mutation: added ``from .store_runtime import VaultStore`` and a
    ``VaultStore(root_dir)`` construction to ``api.clean``. Observed the
    import assertion fail with ``['VaultStore'] == []``, naming
    "api.clean must not import VaultStore". Restored, and it passes.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(clean)))
    clean_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "clean"
    )

    assert _imported_names(clean_node, "store_runtime", "VaultStore") == [], (
        "api.clean must not import VaultStore"
    )
    assert _name_calls(clean_node, "VaultStore") == [], (
        "api.clean must not construct VaultStore"
    )
    assert _attribute_calls(clean_node, "close_project") == [], (
        "api.clean must not evict projects directly"
    )
    assert len(_attribute_calls(clean_node, "lease_maintenance_store")) == 1
    assert api.clean is clean


def test_status_reports_mps_as_unified_memory_not_zero_vram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The public capability snapshot keeps MPS out of CUDA VRAM fields."""
    gib = 1024**3
    fake_torch = ModuleType("torch")
    fake_torch.__dict__.update(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
        mps=SimpleNamespace(
            current_allocated_memory=lambda: gib,
            driver_allocated_memory=lambda: 2 * gib,
            recommended_max_memory=lambda: 4 * gib,
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)

    class _Store:
        db_path = tmp_path / "search-data"

        @staticmethod
        def count() -> int:
            return 1

        @staticmethod
        def count_code() -> int:
            return 2

        @staticmethod
        def count_document() -> int:
            return 3

    class _Registry:
        @contextmanager
        def lease_store(self, root: Path):
            assert root == tmp_path.resolve()
            yield _Store()

    status = api._get_status(
        tmp_path.resolve(),
        cast("ServiceRegistry", _Registry()),
    )

    assert status["accelerator_available"] is True
    assert status["accelerator_backend"] == "mps"
    assert status["accelerator_name"] == "Apple MPS"
    assert status["memory_kind"] == "unified"
    assert status["memory_mib"] == 4096
    assert status["memory_measure"] == "recommended_working_set"
    assert status["vram_mib"] is None
    assert status["vram_gb"] is None


def test_benchmark_reports_mps_as_unified_memory_not_zero_vram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The benchmark payload uses the same truthful accelerator semantics."""
    mib = 1024**2
    fake_torch = ModuleType("torch")
    fake_torch.__dict__.update(
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
        mps=SimpleNamespace(
            current_allocated_memory=lambda: 384 * mib,
            driver_allocated_memory=lambda: 512 * mib,
            recommended_max_memory=lambda: 4096 * mib,
        ),
    )
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)

    class _Store:
        @staticmethod
        def count() -> int:
            return 1

        @staticmethod
        def count_code() -> int:
            return 2

    class _Searcher:
        @staticmethod
        def search_vault(_query: str, *, top_k: int) -> list[object]:
            assert top_k in {1, 5}
            return []

    class _Registry:
        @contextmanager
        def lease_store(self, _root: Path):
            yield _Store()

        @contextmanager
        def search_lease(self, _root: Path):
            yield SimpleNamespace(searcher=_Searcher())

    result = api.run_benchmark(
        tmp_path,
        n_queries=1,
        registry=cast("ServiceRegistry", _Registry()),
    )

    assert result["gpu"] == "Apple MPS"
    assert result["accelerator_backend"] == "mps"
    assert result["memory_kind"] == "unified"
    assert result["memory_allocated_mib"] == 384
    assert result["vram_mib"] is None
