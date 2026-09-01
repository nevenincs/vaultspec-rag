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

    from sentence_transformers import CrossEncoder

    from ..embeddings import EmbeddingModel
    from ..search import SearchResult
    from ..store_runtime import VaultStore

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


def _wait_for_cold_store_construction(reg: ServiceRegistry) -> None:
    """Observe the real transient-construction interval before shutdown begins."""
    deadline = time.monotonic() + 10.0
    while time.monotonic() < deadline:
        with reg._lock:
            if reg._transient_store_constructions > 0:
                return
        time.sleep(0.001)
    raise AssertionError("no real cold-store construction was observed")


def _wait_for_registry_shutdown(reg: ServiceRegistry) -> None:
    """Wait until the registry has entered the shutdown state under test."""
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        with reg._lock:
            if reg._shutting_down:
                return
        time.sleep(0.001)
    raise AssertionError("registry did not enter shutdown")


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


class TestClosingReleasesTheResidentBaseline:
    """Closing a registry re-establishes the baseline its models raised."""

    pytestmark: ClassVar = [pytest.mark.integration, pytest.mark.cuda]

    def test_close_all_rebases_the_baseline_to_real_residency(
        self,
        embedding_model: EmbeddingModel,
    ) -> None:
        """Released device memory stops counting toward the enforced baseline.

        The baseline is what index enforcement subtracts from both a job's
        captured forward peak and its ceiling, and the net peak is clamped at
        zero. A baseline left describing memory nothing holds therefore does
        not skew the comparison - it puts every ceiling out of reach and
        silently retires the CUDA ceiling for the rest of the process.

        The allocation released here is a cycle-held CUDA tensor rather than the
        registry's own model stack, for two reasons. It reproduces the property
        that makes the collection load-bearing - a model stack is reachable only
        through reference cycles, so dropping the reference does not return the
        memory - and it releases deterministically. A real second model cannot:
        its constructor logs a caught import error, and pytest's log capture
        retains that record, whose traceback pins the constructor frame and with
        it the model, for as long as the test that loaded it runs.

        Proven able to fail, both directions on the same assertion: dropping the
        rebase call leaves the baseline at ``raised_mib``, and dropping only the
        ``gc.collect()`` leaves the cycle-held tensor still allocated for the
        rebase to measure. Either way ``released_mib < raised_mib`` fails.
        Restored, the baseline returns to the session model's own residency.
        """
        # Requested for its residency rather than its value: the session model
        # is the figure the rebased baseline must come back down to.
        del embedding_model
        from .._gpu import load_accelerator
        from ..memory_probe import (
            current_cuda_mib,
            resident_cuda_baseline_mib,
            sample_resident_cuda_baseline,
        )

        torch = load_accelerator().torch
        resident_mib = sample_resident_cuda_baseline()
        assert resident_mib > 0.0, (
            "premise: the session embedding model must be resident on the device"
        )

        # Reachable only through its own cycle, so refcounting alone cannot
        # return it - exactly how a released model stack behaves.
        holder: dict[str, object] = {}
        holder["cycle"] = holder
        holder["ballast"] = torch.empty(
            48 * 1024 * 1024,
            dtype=torch.float32,
            device="cuda",
        )
        raised_mib = sample_resident_cuda_baseline()
        assert raised_mib > resident_mib, (
            "premise: the ballast must be a real added device allocation"
        )
        del holder

        ServiceRegistry().close_all()

        released_mib = resident_cuda_baseline_mib()
        assert released_mib < raised_mib
        # The figure describes what is still resident - the session model - and
        # not the allocation that was released.
        assert released_mib == pytest.approx(current_cuda_mib()[0], abs=1.0)
        assert released_mib == pytest.approx(resident_mib, abs=1.0)


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
            assert slot.graph_cache is not None
            with registry.compute_lease(root) as lease:
                assert lease.runtime.searcher is not None
                assert lease.runtime.vault_indexer is not None
                assert lease.runtime.code_indexer is not None
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
        registry.peek_project(root)
        try:
            with registry.compute_lease(root) as lease:
                assert lease.runtime.searcher.model is registry.model
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
            with (
                registry.compute_lease(root_a) as first,
                registry.compute_lease(root_b) as second,
            ):
                # Same EmbeddingModel instance
                assert first.runtime.searcher.model is second.runtime.searcher.model
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
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        # Use a separate registry to avoid corrupting the shared fixture.
        # Seed the session reranker the same way the model is seeded: this
        # test exercises close_all's state clearing, not reranker
        # construction, and an unseeded registry lazily loads a private
        # ~2.3GB copy at slot creation.
        reg = ServiceRegistry()
        reg._model = embedding_model
        reg._reranker = shared_reranker
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
        assert h["reranker_loaded"] is False
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
            assert h["reranker_loaded"] is True
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
    ) -> Iterator[tuple[Path, Path]]:
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

        # Index both (real GPU encoding - no mocks)
        with (
            registry.compute_lease(root_a) as first,
            registry.compute_lease(root_b) as second,
        ):
            first.runtime.vault_indexer.full_index(reporter=NullProgressReporter())
            second.runtime.vault_indexer.full_index(reporter=NullProgressReporter())

        yield root_a, root_b

        registry.close_project(root_a)
        registry.close_project(root_b)

    def test_each_project_returns_its_own_docs(
        self,
        registry: ServiceRegistry,
        two_projects: tuple[Path, Path],
    ) -> None:
        """Search results are isolated: project A docs never appear in B."""
        root_a, root_b = two_projects
        results_a: list[SearchResult] = []
        results_b: list[SearchResult] = []
        with (
            registry.search_lease(root_a) as first,
            registry.search_lease(root_b) as second,
        ):
            results_a = first.searcher.search_vault(
                "PostgreSQL database persistence",
                top_k=5,
            )
            results_b = second.searcher.search_vault(
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
        registry: ServiceRegistry,
        two_projects: tuple[Path, Path],
    ) -> None:
        """Two threads searching different projects concurrently."""
        root_a, root_b = two_projects
        results: dict[str, list[SearchResult]] = {}
        barrier = threading.Barrier(2)

        def search(root: Path, query: str, key: str) -> None:
            barrier.wait()
            with registry.search_lease(root) as lease:
                results[key] = lease.searcher.search_vault(query, top_k=3)

        t1 = threading.Thread(
            target=search,
            args=(root_a, "REST API design", "a"),
        )
        t2 = threading.Thread(
            target=search,
            args=(root_b, "vector database Qdrant", "b"),
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
        registry: ServiceRegistry,
        two_projects: tuple[Path, Path],
    ) -> None:
        """Four threads (2 per project) all complete with valid results."""
        root_a, root_b = two_projects
        results: dict[str, list[SearchResult]] = {}
        barrier = threading.Barrier(4)

        def search(root: Path, query: str, key: str) -> None:
            barrier.wait()
            with registry.search_lease(root) as lease:
                results[key] = lease.searcher.search_vault(query, top_k=3)

        threads = [
            threading.Thread(
                target=search,
                args=(root_a, "database transactions", "a1"),
            ),
            threading.Thread(
                target=search,
                args=(root_a, "REST API pagination", "a2"),
            ),
            threading.Thread(
                target=search,
                args=(root_b, "embedding models Qwen3", "b1"),
            ),
            threading.Thread(
                target=search,
                args=(root_b, "SPLADE sparse vectors", "b2"),
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
        registry: ServiceRegistry,
        two_projects: tuple[Path, Path],
    ) -> None:
        """search_vault() on each project only returns that project's docs."""
        root_a, root_b = two_projects
        all_a: list[SearchResult] = []
        all_b: list[SearchResult] = []
        with (
            registry.search_lease(root_a) as first,
            registry.search_lease(root_b) as second,
        ):
            all_a = first.searcher.search_vault("architecture", top_k=5)
            all_b = second.searcher.search_vault("research", top_k=5)

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
        registry.peek_project(root_a)
        registry.peek_project(root_b)
        try:
            with (
                registry.compute_lease(root_a) as first,
                registry.compute_lease(root_b) as second,
            ):
                # Both searchers share the same CrossEncoder instance
                assert (
                    first.runtime.searcher._reranker
                    is second.runtime.searcher._reranker
                )
                # And it's the registry's shared instance
                assert first.runtime.searcher._reranker is registry.get_reranker()
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
        # Deliberately unseeded: this test exercises the registry's own
        # lazy reranker construction and its release by close_all, so it
        # must load a private instance rather than the session-shared one.
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
        registry.peek_project(root)
        try:
            with registry.compute_lease(root) as lease:
                assert lease.runtime.searcher._gpu_lock is registry.gpu_lock
        finally:
            registry.close_project(root)

    def test_two_projects_share_gpu_lock(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        root_a = _make_vault_dir(tmp_path / "proj_a")
        root_b = _make_vault_dir(tmp_path / "proj_b")
        registry.peek_project(root_a)
        registry.peek_project(root_b)
        try:
            with (
                registry.compute_lease(root_a) as first,
                registry.compute_lease(root_b) as second,
            ):
                assert (
                    first.runtime.searcher._gpu_lock
                    is second.runtime.searcher._gpu_lock
                )
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

    def test_close_project_keeps_the_root_store_guard(
        self,
        registry: ServiceRegistry,
        tmp_path: Path,
    ) -> None:
        """Closing a project keeps its guard, and the next open reuses it.

        A per-root mutex only serializes threads that resolve to the same
        object, so an entry dropped on eviction lets the next arrival mint a
        rival lock and open a store against storage the outgoing one has not
        released. Identity - not mere presence - is what makes the guard work.
        """
        root = _make_vault_dir(tmp_path)
        registry.peek_project(root)
        resolved = root.resolve()
        guard = registry._root_locks[resolved]
        registry.close_project(root)
        assert registry._root_locks.get(resolved) is guard
        registry.peek_project(root)
        assert registry._root_locks[resolved] is guard

    def test_close_all_clears_root_locks(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        # Seeded like the model: this test exercises root-lock clearing,
        # not reranker construction.
        reg = ServiceRegistry()
        reg._model = embedding_model
        reg._reranker = shared_reranker
        root = _make_vault_dir(tmp_path)
        reg.peek_project(root)
        assert len(reg._root_locks) > 0
        reg.close_all()
        assert len(reg._root_locks) == 0


class TestLeaseApi:
    """Lease, refcount, idle sweep, LRU admission, drain."""

    pytestmark: ClassVar = [pytest.mark.integration]

    def _reg(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        *,
        max_projects: int,
        idle_ttl: float,
    ) -> ServiceRegistry:
        # Seed the session reranker the same way the model is seeded: these
        # tests exercise lease, refcount, sweep and drain semantics, not
        # reranker construction, and an unseeded registry lazily loads a
        # private ~2.3GB copy at every slot creation - a dozen of them per
        # module is what once drove the tier into CUDA OOM here.
        reg = ServiceRegistry()
        reg._model = embedding_model
        reg._reranker = shared_reranker
        reg._max_projects = max_projects
        reg._idle_ttl_seconds = idle_ttl
        return reg

    def test_lease_increments_refcount(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
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
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        try:
            with reg.lease(root) as _slot:
                pass
            assert reg._projects[root].ref_count == 0
        finally:
            reg.close_all()

    def test_store_lease_pins_warm_store_against_concurrent_eviction(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        slot = reg.peek_project(root)
        outcomes: list[tuple[bool, str]] = []
        try:
            with reg.lease_store(root) as store:
                assert store is slot.store
                assert slot.ref_count == 1
                thread = threading.Thread(
                    target=lambda: outcomes.append(reg.try_evict(root)),
                    name="store-lease-eviction",
                )
                thread.start()
                thread.join(timeout=10)
                assert not thread.is_alive(), "concurrent eviction did not finish"
                assert outcomes == [(False, "busy")]
                assert store._client is not None

            assert slot.ref_count == 0
            assert reg.try_evict(root) == (True, "forced")
            assert slot.store._client is None
        finally:
            reg.close_all()

    def test_store_count_remains_leased_while_real_count_is_blocked(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        slot = reg.peek_project(root)
        slot.store.ensure_table()
        collection_lock = slot.store._collection_locks[slot.store.TABLE_NAME]
        results: list[int] = []
        errors: list[BaseException] = []

        def count() -> None:
            try:
                results.append(reg.vault_doc_count(root))
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        acquired = collection_lock.acquire(timeout=5)
        thread = threading.Thread(target=count, name="leased-store-count")
        assert acquired
        try:
            thread.start()
            deadline = time.monotonic() + 5.0
            while time.monotonic() < deadline:
                with reg._lock:
                    if slot.ref_count == 1:
                        break
                time.sleep(0.01)
            assert slot.ref_count == 1, "count never acquired its store lease"
            assert thread.is_alive(), "count bypassed the held production store lock"
            assert reg.try_evict(root) == (False, "busy")
        finally:
            collection_lock.release()
            if thread.ident is not None:
                thread.join(timeout=30)
            reg.close_all()

        assert not thread.is_alive()
        assert errors == []
        assert results == [0]

    def test_store_lease_excludes_warm_slot_from_idle_sweep(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=5.0)
        root = _make_vault_dir(tmp_path / "leased").resolve()
        trigger_root = _make_vault_dir(tmp_path / "trigger").resolve()
        slot = reg.peek_project(root)
        try:
            with reg.lease_store(root):
                with reg._lock:
                    slot.last_access = time.monotonic() - 100.0
                with reg.lease(trigger_root):
                    pass
                assert reg._projects[root] is slot
                assert slot.store._client is not None

            with reg.lease(trigger_root):
                pass
            assert root not in reg._projects
            assert slot.store._client is None
        finally:
            reg.close_all()

    def test_cold_store_lease_participates_in_bounded_shutdown_force_close(
        self,
        tmp_path: Path,
    ) -> None:
        reg = ServiceRegistry()
        root = _make_vault_dir(tmp_path).resolve()
        leased = threading.Event()
        release = threading.Event()
        stores: list[VaultStore] = []
        errors: list[BaseException] = []

        def hold_cold_lease() -> None:
            try:
                with reg.lease_store(root) as store:
                    stores.append(store)
                    leased.set()
                    assert release.wait(timeout=15), "lease release was never signalled"
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        thread = threading.Thread(target=hold_cold_lease, name="cold-store-lease")
        thread.start()
        assert leased.wait(timeout=10), "cold store lease was not established"
        with reg._lock:
            assert len(reg._transient_stores) == 1
            assert reg._transient_store_constructions == 0

        started = time.monotonic()
        reg.close_all()
        elapsed = time.monotonic() - started
        release.set()
        thread.join(timeout=10)

        assert 4.5 < elapsed < 7.0, f"transient drain took {elapsed:.2f}s"
        assert not thread.is_alive()
        assert errors == []
        assert len(stores) == 1
        assert stores[0]._client is None
        with reg._lock:
            assert reg._transient_stores == set()
            assert reg._transient_store_constructions == 0

    def test_cold_store_construction_racing_shutdown_cannot_escape(
        self,
        tmp_path: Path,
    ) -> None:
        reg = ServiceRegistry()
        worker_count = 8
        barrier = threading.Barrier(worker_count + 1)
        release = threading.Event()
        stores: list[VaultStore] = []
        outcomes: list[str] = []
        errors: list[BaseException] = []

        def race(root: Path) -> None:
            try:
                barrier.wait(timeout=10)
                with reg.lease_store(root) as store:
                    stores.append(store)
                    outcomes.append("leased")
                    assert release.wait(timeout=15), "race lease was never released"
            except RuntimeError as exc:
                if "shut down" not in str(exc) and "shutting down" not in str(exc):
                    errors.append(exc)
                else:
                    outcomes.append("shutdown")
            except BaseException as exc:  # pragma: no cover - reported below
                errors.append(exc)

        threads = [
            threading.Thread(
                target=race,
                args=(_make_vault_dir(tmp_path / f"cold-{index}").resolve(),),
                name=f"cold-construction-{index}",
            )
            for index in range(worker_count)
        ]
        for thread in threads:
            thread.start()
        barrier.wait(timeout=10)

        _wait_for_cold_store_construction(reg)

        shutdown = threading.Thread(target=reg.close_all, name="registry-shutdown")
        shutdown.start()
        _wait_for_registry_shutdown(reg)
        release.set()

        for thread in threads:
            thread.join(timeout=20)
        shutdown.join(timeout=20)

        assert not shutdown.is_alive()
        assert all(not thread.is_alive() for thread in threads)
        assert errors == []
        assert len(outcomes) == worker_count
        assert all(store._client is None for store in stores)
        with reg._lock:
            assert reg._transient_stores == set()
            assert reg._transient_store_constructions == 0

        with (
            pytest.raises(RuntimeError, match="shutting down"),
            reg.lease_store(tmp_path / "after-shutdown"),
        ):
            pass

    def test_peek_does_not_change_refcount(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
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
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        # Large TTL so the first lease doesn't immediately sweep itself;
        # we rewind last_access manually below.
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=5.0)
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
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=2, idle_ttl=0)
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

    def test_try_evict_reports_busy_while_leased(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        """try_evict refuses a leased slot and succeeds once the lease drops.

        Deterministic replacement for the timing-flaky daemon-level
        ``test_evict_busy_returns_busy``: a real lease pins ``ref_count`` above
        zero for the duration of the ``with`` block, so the busy branch of
        try_evict is exercised without racing a background search.
        """
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
        root = _make_vault_dir(tmp_path).resolve()
        try:
            with reg.lease(root):
                evicted, reason = reg.try_evict(root)
                assert evicted is False
                assert reason == "busy"
            # Lease released - the same evict now tears the slot down.
            evicted, reason = reg.try_evict(root)
            assert evicted is True
            assert reason == "forced"
            assert root not in reg._projects
        finally:
            reg.close_all()

    def test_lru_full_raises(
        self,
        embedding_model: EmbeddingModel,
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=1, idle_ttl=0)
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
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
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
        shared_reranker: CrossEncoder,
        tmp_path: Path,
    ) -> None:
        reg = self._reg(embedding_model, shared_reranker, max_projects=4, idle_ttl=0)
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
