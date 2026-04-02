"""Tests for ServiceRegistry (service.py).

Covers:
- load_model() succeeds on GPU
- get_project() creates components for a project root
- Two project roots share one EmbeddingModel (object identity)
- close_project() removes from dict and closes store
- close_all() cleans everything
- health() returns correct state
- Concurrent get_project() calls are thread-safe
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING, ClassVar

import pytest

from vaultspec_rag.service import ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.integration]


def _make_vault_dir(tmp_path: Path) -> Path:
    """Create a minimal .vault/ with one document for VaultGraph."""
    vault = tmp_path / ".vault" / "research"
    vault.mkdir(parents=True)
    doc = vault / "test-doc.md"
    doc.write_text(
        '---\ntags: ["#research", "#test"]\ndate: 2026-01-01\n---\n# test document\n',
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture(scope="module")
def registry(embedding_model) -> Iterator[ServiceRegistry]:
    """Provide a ServiceRegistry with the session-scoped model pre-loaded.

    Reuses the session-scoped ``embedding_model`` fixture from conftest
    to avoid loading ~900MB of GPU models a second time.
    """
    reg = ServiceRegistry()
    reg._model = embedding_model
    yield reg
    # Only clear projects, don't nullify model (owned by session fixture)
    with reg._lock:
        for slot in reg._projects.values():
            slot.store.close()
        reg._projects.clear()


class TestLoadModel:
    """load_model() loads GPU models into the registry."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_load_model_idempotent(self, registry: ServiceRegistry) -> None:
        original = registry._model
        registry.load_model()  # should not replace existing model
        assert registry.model is original

    def test_model_property_raises_before_load(self) -> None:
        reg = ServiceRegistry()
        with pytest.raises(RuntimeError, match="not loaded"):
            _ = reg.model


class TestGetProject:
    """get_project() creates per-project components."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_creates_components(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        slot = registry.get_project(root)
        try:
            assert slot.store is not None
            assert slot.searcher is not None
            assert slot.vault_indexer is not None
            assert slot.code_indexer is not None
            assert slot.graph_cache is not None
        finally:
            registry.close_project(root)

    def test_returns_same_slot_on_repeat(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        s1 = registry.get_project(root)
        s2 = registry.get_project(root)
        try:
            assert s1 is s2
        finally:
            registry.close_project(root)

    def test_searcher_uses_shared_model(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        slot = registry.get_project(root)
        try:
            assert slot.searcher.model is registry.model
        finally:
            registry.close_project(root)


class TestMultiProject:
    """Two project roots share one EmbeddingModel."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_shared_model_identity(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root_a = _make_vault_dir(tmp_path / "project_a")
        root_b = _make_vault_dir(tmp_path / "project_b")
        slot_a = registry.get_project(root_a)
        slot_b = registry.get_project(root_b)
        try:
            # Same EmbeddingModel instance
            assert slot_a.searcher.model is slot_b.searcher.model
            # Different stores (independent Qdrant)
            assert slot_a.store is not slot_b.store
            # Different graph caches
            assert slot_a.graph_cache is not slot_b.graph_cache
        finally:
            registry.close_project(root_a)
            registry.close_project(root_b)


class TestCloseProject:
    """close_project() removes the slot and closes the store."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_close_removes_from_dict(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        registry.get_project(root)
        resolved = root.resolve()
        assert resolved in registry._projects
        registry.close_project(root)
        assert resolved not in registry._projects

    def test_close_closes_store(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        slot = registry.get_project(root)
        store = slot.store
        registry.close_project(root)
        assert store._client is None

    def test_close_nonexistent_is_safe(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        registry.close_project(tmp_path / "does-not-exist")


class TestCloseAll:
    """close_all() closes all stores and releases the model."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_close_all_clears_state(
        self,
        embedding_model,
        tmp_path: Path,
    ) -> None:
        # Use a separate registry to avoid corrupting the shared fixture
        reg = ServiceRegistry()
        reg._model = embedding_model
        root = _make_vault_dir(tmp_path)
        slot = reg.get_project(root)
        store = slot.store

        reg.close_all()

        assert reg._model is None
        assert len(reg._projects) == 0
        assert store._client is None


class TestHealth:
    """health() returns correct diagnostics."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_health_before_load(self) -> None:
        reg = ServiceRegistry()
        h = reg.health()
        assert h["model_loaded"] is False
        assert h["project_count"] == 0
        assert h["projects"] == []

    def test_health_with_project(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        registry.get_project(root)
        try:
            h = registry.health()
            assert h["model_loaded"] is True
            assert h["project_count"] >= 1
            assert str(root.resolve()) in h["projects"]
        finally:
            registry.close_project(root)


class TestConcurrency:
    """Concurrent get_project() calls are thread-safe."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_concurrent_get_project_same_root(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        results: list[object] = []
        barrier = threading.Barrier(4)

        def worker() -> None:
            barrier.wait()
            slot = registry.get_project(root)
            results.append(slot)

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        try:
            assert len(results) == 4
            # All threads got the same ProjectSlot
            assert all(r is results[0] for r in results)
        finally:
            registry.close_project(root)
