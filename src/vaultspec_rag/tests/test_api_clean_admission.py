"""CPU proofs that API cleanup owns its store through the registry."""

from __future__ import annotations

import ast
import inspect
import textwrap
import threading
from typing import TYPE_CHECKING

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


def test_clean_does_not_construct_or_import_vault_store_directly() -> None:
    """The facade delegates store lifecycle ownership to ServiceRegistry."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(clean)))
    clean_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "clean"
    )
    vault_store_imports = [
        imported.name
        for node in ast.walk(clean_node)
        if isinstance(node, ast.ImportFrom) and node.module == "store_runtime"
        for imported in node.names
        if imported.name == "VaultStore"
    ]
    vault_store_constructions = [
        node
        for node in ast.walk(clean_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "VaultStore"
    ]
    close_project_calls = [
        node
        for node in ast.walk(clean_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "close_project"
    ]
    maintenance_leases = [
        node
        for node in ast.walk(clean_node)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "lease_maintenance_store"
    ]

    assert vault_store_imports == [], "api.clean must not import VaultStore"
    assert vault_store_constructions == [], "api.clean must not construct VaultStore"
    assert close_project_calls == [], "api.clean must not evict projects directly"
    assert len(maintenance_leases) == 1
    assert api.clean is clean
