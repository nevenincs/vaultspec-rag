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
import time
from typing import TYPE_CHECKING, ClassVar

import pytest

from ..progress import NullProgressReporter
from ..service import ProjectSlot, RegistryFullError, ServiceRegistry

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from ..embeddings import EmbeddingModel
    from ..search import SearchResult

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
def registry(embedding_model: EmbeddingModel) -> Iterator[ServiceRegistry]:
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
        slot = registry.peek_project(root)
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
        s1 = registry.peek_project(root)
        s2 = registry.peek_project(root)
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
        slot = registry.peek_project(root)
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
        slot_a = registry.peek_project(root_a)
        slot_b = registry.peek_project(root_b)
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
        registry.peek_project(root)
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
        slot = registry.peek_project(root)
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
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        # Use a separate registry to avoid corrupting the shared fixture
        reg = ServiceRegistry()
        reg._model = embedding_model
        root = _make_vault_dir(tmp_path)
        slot = reg.peek_project(root)
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
        registry.peek_project(root)
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
            slot = registry.peek_project(root)
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


def _make_project(tmp_path: Path, name: str, docs: dict[str, str]) -> Path:
    """Create a project directory with .vault/ documents.

    Args:
        tmp_path: Base temporary directory.
        name: Project directory name.
        docs: Mapping of ``subdir/filename.md`` to markdown content.
            Each file gets YAML frontmatter prepended automatically.

    Returns:
        The project root path.
    """
    root = tmp_path / name
    for relpath, body in docs.items():
        p = root / ".vault" / relpath
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


class TestMultiProjectSearch:
    """Real GPU-backed search across multiple concurrent projects.

    Two independent projects are created with distinct vault content,
    indexed with real GPU embeddings, and searched concurrently to
    verify result isolation and GPU lock correctness.
    """

    pytestmark: ClassVar = [pytest.mark.integration]

    @pytest.fixture()
    def two_projects(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> Iterator[tuple[Path, ProjectSlot, Path, ProjectSlot]]:
        """Create and index two projects with non-overlapping content."""
        root_a = _make_project(
            tmp_path,
            "proj_alpha",
            {
                "adr/database-selection.md": (
                    "---\ntags:\n  - '#adr'\ndate: 2026-01-01\n---\n"
                    "# ADR: Use PostgreSQL for persistence\n\n"
                    "We chose PostgreSQL as our primary relational "
                    "database for ACID transactions, JSON columns, "
                    "and mature replication support.\n"
                ),
                "adr/api-design.md": (
                    "---\ntags:\n  - '#adr'\ndate: 2026-01-02\n---\n"
                    "# ADR: REST API design conventions\n\n"
                    "The HTTP API follows REST conventions with JSON "
                    "payloads, standard status codes, and pagination "
                    "via cursor tokens.\n"
                ),
            },
        )
        root_b = _make_project(
            tmp_path,
            "proj_beta",
            {
                "research/embedding-eval.md": (
                    "---\ntags:\n  - '#research'\ndate: 2026-02-01\n---\n"
                    "# Embedding model evaluation\n\n"
                    "Qwen3-Embedding-0.6B and BGE-M3 were benchmarked "
                    "for semantic search on vault documents. Qwen3 was "
                    "selected for its 1024-d dense output and multilingual "
                    "instruction tuning.\n"
                ),
                "research/vector-db.md": (
                    "---\ntags:\n  - '#research'\ndate: 2026-02-02\n---\n"
                    "# Vector database selection\n\n"
                    "Qdrant in local mode provides hybrid search with "
                    "dense and SPLADE sparse vectors via the Universal "
                    "Query API and RRF fusion.\n"
                ),
            },
        )

        slot_a = registry.peek_project(root_a)
        slot_b = registry.peek_project(root_b)

        # Index both (real GPU encoding - no mocks)
        slot_a.vault_indexer.full_index(reporter=NullProgressReporter())
        slot_b.vault_indexer.full_index(reporter=NullProgressReporter())

        yield root_a, slot_a, root_b, slot_b

        registry.close_project(root_a)
        registry.close_project(root_b)

    def test_each_project_returns_its_own_docs(
        self,
        two_projects: tuple[Path, ProjectSlot, Path, ProjectSlot],
    ) -> None:
        """Search results are isolated: project A docs never appear in B."""
        _root_a, slot_a, _root_b, slot_b = two_projects

        results_a = slot_a.searcher.search_vault(
            "PostgreSQL database persistence",
            top_k=5,
        )
        results_b = slot_b.searcher.search_vault(
            "embedding model semantic search",
            top_k=5,
        )

        assert len(results_a) > 0, "Project A search returned no results"
        assert len(results_b) > 0, "Project B search returned no results"

        a_ids = {r.id for r in results_a}
        b_ids = {r.id for r in results_b}
        assert a_ids.isdisjoint(b_ids), f"Result isolation violated: {a_ids & b_ids}"

    def test_concurrent_searches_two_projects(
        self,
        two_projects: tuple[Path, ProjectSlot, Path, ProjectSlot],
    ) -> None:
        """Two threads searching different projects concurrently."""
        _root_a, slot_a, _root_b, slot_b = two_projects
        results: dict[str, list[SearchResult]] = {}
        barrier = threading.Barrier(2)

        def search(slot: ProjectSlot, query: str, key: str) -> None:
            barrier.wait()
            results[key] = slot.searcher.search_vault(query, top_k=3)

        t1 = threading.Thread(
            target=search,
            args=(slot_a, "REST API design", "a"),
        )
        t2 = threading.Thread(
            target=search,
            args=(slot_b, "vector database Qdrant", "b"),
        )
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert "a" in results and "b" in results
        assert len(results["a"]) > 0
        assert len(results["b"]) > 0
        a_ids = {r.id for r in results["a"]}
        b_ids = {r.id for r in results["b"]}
        assert a_ids.isdisjoint(b_ids)

    def test_four_concurrent_searches(
        self,
        two_projects: tuple[Path, ProjectSlot, Path, ProjectSlot],
    ) -> None:
        """Four threads (2 per project) all complete with valid results."""
        _root_a, slot_a, _root_b, slot_b = two_projects
        results: dict[str, list[SearchResult]] = {}
        barrier = threading.Barrier(4)

        def search(slot: ProjectSlot, query: str, key: str) -> None:
            barrier.wait()
            results[key] = slot.searcher.search_vault(query, top_k=3)

        threads = [
            threading.Thread(
                target=search,
                args=(slot_a, "database transactions", "a1"),
            ),
            threading.Thread(
                target=search,
                args=(slot_a, "REST API pagination", "a2"),
            ),
            threading.Thread(
                target=search,
                args=(slot_b, "embedding models Qwen3", "b1"),
            ),
            threading.Thread(
                target=search,
                args=(slot_b, "SPLADE sparse vectors", "b2"),
            ),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=60)

        assert len(results) == 4, f"Expected 4 results, got {list(results)}"
        for key, res in results.items():
            assert len(res) > 0, f"Search '{key}' returned no results"
            assert all(isinstance(r.score, float) and r.score > 0 for r in res), (
                f"Search '{key}' has invalid scores"
            )
        # Cross-project isolation still holds
        a_ids = {r.id for r in results["a1"]} | {r.id for r in results["a2"]}
        b_ids = {r.id for r in results["b1"]} | {r.id for r in results["b2"]}
        assert a_ids.isdisjoint(b_ids)

    def test_search_vault_across_projects(
        self,
        two_projects: tuple[Path, ProjectSlot, Path, ProjectSlot],
    ) -> None:
        """search_vault() on each project only returns that project's docs."""
        _root_a, slot_a, _root_b, slot_b = two_projects

        all_a = slot_a.searcher.search_vault("architecture", top_k=5)
        all_b = slot_b.searcher.search_vault("research", top_k=5)

        assert len(all_a) > 0
        assert len(all_b) > 0
        a_ids = {r.id for r in all_a}
        b_ids = {r.id for r in all_b}
        assert a_ids.isdisjoint(b_ids)


class TestSharedReranker:
    """CrossEncoder is shared across all project slots (PERF-004)."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_get_reranker_returns_cross_encoder(
        self,
        registry: ServiceRegistry,
    ) -> None:
        from sentence_transformers import CrossEncoder

        reranker = registry.get_reranker()
        assert isinstance(reranker, CrossEncoder)

    def test_get_reranker_idempotent(
        self,
        registry: ServiceRegistry,
    ) -> None:
        r1 = registry.get_reranker()
        r2 = registry.get_reranker()
        assert r1 is r2

    def test_shared_reranker_across_projects(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root_a = _make_vault_dir(tmp_path / "proj_a")
        root_b = _make_vault_dir(tmp_path / "proj_b")
        slot_a = registry.peek_project(root_a)
        slot_b = registry.peek_project(root_b)
        try:
            # Both searchers share the same CrossEncoder instance
            assert slot_a.searcher._reranker is slot_b.searcher._reranker
            # And it's the registry's shared instance
            assert slot_a.searcher._reranker is registry.get_reranker()
        finally:
            registry.close_project(root_a)
            registry.close_project(root_b)

    def test_get_reranker_thread_safe(
        self,
        registry: ServiceRegistry,
    ) -> None:
        results: list[object] = []
        barrier = threading.Barrier(4)

        def worker() -> None:
            barrier.wait()
            results.append(registry.get_reranker())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(results) == 4
        assert all(r is results[0] for r in results)

    def test_close_all_clears_reranker(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = ServiceRegistry()
        reg._model = embedding_model
        root = _make_vault_dir(tmp_path)
        reg.peek_project(root)
        reranker = reg.get_reranker()
        assert reranker is not None

        reg.close_all()
        assert reg._reranker is None


class TestGpuLock:
    """GPU lock wired from registry into each VaultSearcher (PERF-001)."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_registry_gpu_lock_is_lock(
        self,
        registry: ServiceRegistry,
    ) -> None:
        assert isinstance(registry.gpu_lock, threading.Lock)

    def test_searcher_receives_gpu_lock(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        slot = registry.peek_project(root)
        try:
            assert slot.searcher._gpu_lock is registry.gpu_lock
        finally:
            registry.close_project(root)

    def test_two_projects_share_gpu_lock(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root_a = _make_vault_dir(tmp_path / "proj_a")
        root_b = _make_vault_dir(tmp_path / "proj_b")
        slot_a = registry.peek_project(root_a)
        slot_b = registry.peek_project(root_b)
        try:
            assert slot_a.searcher._gpu_lock is slot_b.searcher._gpu_lock
        finally:
            registry.close_project(root_a)
            registry.close_project(root_b)


class TestPerRootLocks:
    """Per-root locks allow parallel get_project() for different roots (PERF-002)."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def test_concurrent_different_roots_no_deadlock(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root_a = _make_vault_dir(tmp_path / "proj_a")
        root_b = _make_vault_dir(tmp_path / "proj_b")
        results: dict[str, ProjectSlot] = {}
        barrier = threading.Barrier(2)

        def worker(root: Path, key: str) -> None:
            barrier.wait()
            results[key] = registry.peek_project(root)

        t1 = threading.Thread(target=worker, args=(root_a, "a"))
        t2 = threading.Thread(target=worker, args=(root_b, "b"))
        t1.start()
        t2.start()
        t1.join(timeout=30)
        t2.join(timeout=30)

        try:
            assert "a" in results and "b" in results
            assert results["a"] is not results["b"]
            assert results["a"].store is not results["b"].store
        finally:
            registry.close_project(root_a)
            registry.close_project(root_b)

    def test_close_project_clears_root_lock(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root = _make_vault_dir(tmp_path)
        registry.peek_project(root)
        resolved = root.resolve()
        assert resolved in registry._root_locks
        registry.close_project(root)
        assert resolved not in registry._root_locks

    def test_close_all_clears_root_locks(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = ServiceRegistry()
        reg._model = embedding_model
        root = _make_vault_dir(tmp_path)
        reg.peek_project(root)
        assert len(reg._root_locks) > 0
        reg.close_all()
        assert len(reg._root_locks) == 0


class TestLeaseApi:
    """ADR D3/D4/D6 - lease, refcount, idle sweep, LRU admission, drain."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def _reg(
        self,
        embedding_model: EmbeddingModel,
        *,
        max_projects: int,
        idle_ttl: float,
    ) -> ServiceRegistry:
        reg = ServiceRegistry()
        reg._model = embedding_model
        reg._max_projects = max_projects
        reg._idle_ttl_seconds = idle_ttl
        return reg

    def test_lease_increments_refcount(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        try:
            with reg.lease(root) as slot:
                assert slot.ref_count == 1
                assert reg._projects[root].ref_count == 1
        finally:
            reg.close_all()

    def test_lease_decrements_on_exit(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        try:
            with reg.lease(root) as _slot:
                pass
            assert reg._projects[root].ref_count == 0
        finally:
            reg.close_all()

    def test_peek_does_not_change_refcount(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        try:
            slot = reg.peek_project(root)
            assert slot.ref_count == 0
            assert slot.last_access == 0.0
            slot2 = reg.peek_project(root)
            assert slot2 is slot
            assert slot.ref_count == 0
        finally:
            reg.close_all()

    def test_sweep_evicts_idle(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        # Large TTL so the first lease doesn't immediately sweep itself;
        # we rewind last_access manually below.
        reg = self._reg(embedding_model, max_projects=4, idle_ttl=5.0)
        root_a = _make_vault_dir(tmp_path / "a").resolve()
        root_b = _make_vault_dir(tmp_path / "b").resolve()
        try:
            with reg.lease(root_a):
                pass
            # Rewind A's last_access deep into the past.
            reg._projects[root_a].last_access = time.monotonic() - 100.0
            assert root_a in reg._projects

            with reg.lease(root_b):
                pass
            assert root_a not in reg._projects, "idle sweep should have evicted A"
            assert root_b in reg._projects
        finally:
            reg.close_all()

    def test_lru_admission_evicts_oldest(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, max_projects=2, idle_ttl=0)
        root_a = _make_vault_dir(tmp_path / "a").resolve()
        root_b = _make_vault_dir(tmp_path / "b").resolve()
        root_c = _make_vault_dir(tmp_path / "c").resolve()
        try:
            with reg.lease(root_a):
                pass
            with reg.lease(root_b):
                pass
            # Force A to be the LRU victim.
            reg._projects[root_a].last_access = 1.0
            reg._projects[root_b].last_access = 2.0
            with reg.lease(root_c):
                pass
            assert root_a not in reg._projects
            assert root_b in reg._projects
            assert root_c in reg._projects
        finally:
            reg.close_all()

    def test_lru_full_raises(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, max_projects=1, idle_ttl=0)
        root_a = _make_vault_dir(tmp_path / "a").resolve()
        root_b = _make_vault_dir(tmp_path / "b").resolve()
        try:
            cm = reg.lease(root_a)
            slot_a = cm.__enter__()
            try:
                assert slot_a.ref_count == 1
                with (
                    pytest.raises(RegistryFullError) as excinfo,
                    reg.lease(root_b),
                ):
                    pass
                assert excinfo.value.max_projects == 1
            finally:
                cm.__exit__(None, None, None)
        finally:
            reg.close_all()

    def test_acquire_blocks_during_shutdown(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        try:
            with reg.lease(root):
                pass
            with reg._lock:
                reg._shutting_down = True
            with (
                pytest.raises(RuntimeError, match="shutting down"),
                reg.lease(root),
            ):
                pass
        finally:
            with reg._lock:
                reg._shutting_down = False
            reg.close_all()

    def test_close_all_drains_then_force(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        # Seed the slot, then hold ref_count directly (simulating an
        # in-flight request pinned through the drain deadline).  We
        # mutate ref_count under _lock rather than going through
        # reg.lease() because the test needs to observe force-close
        # behavior while the ref is held past the deadline, and
        # lease's release after close_all would hit a cleared dict.
        reg.peek_project(root)
        with reg._lock:
            reg._projects[root].ref_count = 1
        t0 = time.monotonic()
        reg.close_all()
        elapsed = time.monotonic() - t0
        # 5s bounded drain + a small epsilon for teardown work.
        assert 4.5 < elapsed < 7.0, f"close_all took {elapsed:.2f}s"
        assert len(reg._projects) == 0
