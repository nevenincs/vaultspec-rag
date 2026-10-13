"""Tests for GraphCache (graph_cache.py) and VaultSearcher graph_provider (search.py).

Covers:
- GraphCache.get() with TTL expiry
- GraphCache.get() concurrent access at TTL boundary
- GraphCache.invalidate() triggers rebuild on next get
- VaultSearcher with graph_provider (delegation)
- VaultSearcher without graph_provider (shared nonblocking implementation)
"""

from __future__ import annotations

import threading
import time
from contextlib import contextmanager
from typing import TYPE_CHECKING, ClassVar

import pytest

from ..graph_cache import GraphCache

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path
    from types import FrameType

    from vaultspec_core.graph import VaultGraph

pytestmark = [pytest.mark.unit]


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


class TestGraphCacheGet:
    """GraphCache.get() builds and caches a VaultGraph."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_get_returns_vault_graph(self, tmp_path: Path):
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=300.0)
        graph = cache.get(root)
        assert graph is not None

    def test_get_returns_same_instance_within_ttl(self, tmp_path: Path):
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=300.0)
        g1 = cache.get(root)
        g2 = cache.get(root)
        assert g1 is g2

    def test_get_rebuilds_after_ttl_expiry(self, tmp_path: Path):
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=0.01)
        g1 = cache.get(root)
        time.sleep(0.02)
        g2 = cache.get(root)
        assert g1 is not g2

    def test_get_returns_graph_for_missing_vault(self, tmp_path: Path):
        cache = GraphCache(ttl_seconds=300.0)
        result = cache.get(tmp_path)
        # VaultGraph succeeds on a dir with no .vault/ - returns a graph
        # with zero nodes rather than raising.
        from vaultspec_core.graph import VaultGraph

        assert isinstance(result, VaultGraph)


class TestGraphCacheInvalidate:
    """GraphCache.invalidate() forces rebuild on next get."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_invalidate_forces_rebuild(self, tmp_path: Path):
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=300.0)
        g1 = cache.get(root)
        assert g1 is not None
        cache.invalidate()
        g2 = cache.get(root)
        assert g2 is not None
        assert g1 is not g2


class TestGraphCacheConcurrency:
    """Concurrent access at TTL boundary produces exactly one rebuild.

    Multiple threads hitting get() when the cache is stale must not
    trigger parallel VaultGraph constructions.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_concurrent_get_single_construction(self, tmp_path: Path):
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=10.0)
        # Pre-build, then force stale by backdating _built_at
        cache.get(root)
        cache._built_at = 0.0

        results: list[object] = []
        barrier = threading.Barrier(8)

        def worker():
            barrier.wait()
            g = cache.get(root)
            results.append(g)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(results) == 8
        # All threads got the same graph object - proves single construction
        first = results[0]
        assert all(r is first for r in results)


class TestGraphCacheRootChange:
    """Cache data cannot cross project roots."""

    def test_get_recovers_after_root_change(self, tmp_path: Path):
        """Changing root_dir triggers rebuild even within TTL."""
        root1 = _make_vault_dir(tmp_path / "project1")
        root2 = _make_vault_dir(tmp_path / "project2")
        cache = GraphCache(ttl_seconds=300.0)

        g1 = cache.get(root1)
        assert g1 is not None
        assert cache._root == root1

        g2 = cache.get(root2)
        assert g2 is not None
        assert cache._root == root2
        # Different root should produce a different graph instance
        assert g1 is not g2


class TestGraphCacheConcurrentInvalidate:
    """Concurrent invalidate() and get() must not crash or corrupt state."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_invalidate_during_concurrent_get(self, tmp_path: Path):
        from vaultspec_core.graph import VaultGraph

        root = _make_vault_dir(tmp_path)
        gc = GraphCache(ttl_seconds=300.0)
        gc.get(root)  # prime cache

        results: list[object] = []

        def reader():
            for _ in range(10):
                results.append(gc.get(root))

        def invalidator():
            for _ in range(5):
                gc.invalidate()

        t1 = threading.Thread(target=reader)
        t2 = threading.Thread(target=invalidator)
        t1.start()
        t2.start()
        t1.join(10)
        t2.join(10)
        # All results must be a VaultGraph (never None for a valid root)
        assert all(r is None or isinstance(r, VaultGraph) for r in results)
        assert len(results) == 10


@contextmanager
def _hold_graph_builds(
    root: Path,
    barriers: list[tuple[threading.Event, threading.Event]],
) -> Generator[list[VaultGraph]]:
    """Observe real constructors, holding their returns at deterministic barriers."""
    from vaultspec_core.graph import VaultGraph

    graphs: list[VaultGraph] = []
    previous = threading.getprofile()

    def observe(frame: FrameType, event: str, _arg: object) -> None:
        if (
            frame.f_code is VaultGraph.__init__.__code__
            and event == "return"
            and frame.f_locals["root_dir"] == root
            and frame.f_back is not None
            and frame.f_back.f_code is GraphCache._build.__code__
        ):
            graphs.append(frame.f_locals["self"])
            index = len(graphs) - 1
            if index < len(barriers):
                entered, release = barriers[index]
                entered.set()
                assert release.wait(10), "graph test did not release its builder"

    threading.setprofile(observe)
    try:
        yield graphs
    finally:
        for _entered, release in barriers:
            release.set()
        threading.setprofile(previous)


class TestNonblockingGraphRefresh:
    """Hold real construction explicitly; assertions do not depend on CPU speed."""

    @pytest.mark.parametrize("expired", [False, True])
    def test_search_and_invalidation_do_not_wait(
        self, tmp_path: Path, expired: bool
    ) -> None:
        from ..search import VaultSearcher

        root = _make_vault_dir(tmp_path)
        entered, release, returned = (threading.Event() for _ in range(3))
        cache = GraphCache(ttl_seconds=300)
        if expired:
            assert cache.get(root) is not None
            cache._built_at = 0.0
        searcher = VaultSearcher.__new__(VaultSearcher)
        searcher._graph_provider = lambda: cache.get(root, wait=False)
        searcher.root_dir = root
        results: list[object] = []

        def search():
            results.append(searcher._get_graph())
            returned.set()

        with _hold_graph_builds(root, [(entered, release)]) as graphs:
            reader = threading.Thread(target=search)
            reader.start()
            try:
                assert entered.wait(5)
                # Mutation proof: wait=True fails this assertion; restoration passes.
                assert returned.wait(1), "search waited for graph construction"
                assert results == [None]
                for _ in range(20):
                    assert cache.get(root, wait=False) is None
                assert len(graphs) == 1
                cache.invalidate()
                assert cache.get(root, wait=False) is None
                assert len(graphs) == 1
            finally:
                release.set()
                reader.join(5)
            try:
                assert cache.get(root) is graphs[-1]
                assert len(graphs) == 2
            finally:
                cache.close()

    def test_invalidation_discards_late_build(self, tmp_path: Path) -> None:
        root = _make_vault_dir(tmp_path)
        first_entered, first_release = threading.Event(), threading.Event()
        second_entered, second_release = threading.Event(), threading.Event()
        cache = GraphCache(ttl_seconds=300)
        with _hold_graph_builds(
            root, [(first_entered, first_release), (second_entered, second_release)]
        ) as graphs:
            try:
                assert cache.get(root, wait=False) is None
                assert first_entered.wait(5)
                cache.invalidate()
                first_release.set()
                second_entered.wait(2)
                # Removing the epoch check failed here; restoring it passed.
                assert cache.get(root, wait=False) is None, (
                    "superseded graph was published"
                )
                assert second_entered.is_set()
                second_release.set()
                assert cache.get(root) is graphs[1]
                assert graphs[0] is not graphs[1]
            finally:
                first_release.set()
                second_release.set()
                cache.close()
                worker = cache._worker
                if worker is not None:
                    worker.join(5)

    def test_failure_backoff_then_recovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=300)
        try:
            # Real configuration validation rejects this; no constructor is replaced.
            with monkeypatch.context() as invalid:
                invalid.setenv("VAULTSPEC_IO_BUFFER_SIZE", "0")
                assert cache.get(root) is None
            retry_at = cache._retry_at
            assert retry_at > time.monotonic()
            # Removing the retry-time check failed below; restoration passed.
            for _ in range(10):
                assert cache.get(root, wait=False) is None
                assert cache._worker is None
                assert cache._retry_at == retry_at
            cache._retry_at = 0
            graph = cache.get(root)
            assert graph is not None
            assert "test-doc" in graph.nodes
        finally:
            cache.close()

    def test_close_rejects_late_completion(self, tmp_path: Path) -> None:
        root = _make_vault_dir(tmp_path)
        entered, release = threading.Event(), threading.Event()
        cache = GraphCache(ttl_seconds=300)
        with _hold_graph_builds(root, [(entered, release)]):
            try:
                assert cache.get(root, wait=False) is None
                assert entered.wait(5)
                worker = cache._worker
                cache.close()
                release.set()
                assert worker is not None
                worker.join(5)
                assert not worker.is_alive()
                assert cache.get(root) is None
                # Unconditional publication failed here; restoration passed.
                assert cache._graph is None
            finally:
                release.set()
                cache.close()

    def test_standalone_uses_same_nonblocking_cache(self, tmp_path: Path):
        from ..search import VaultSearcher

        searcher = VaultSearcher.__new__(VaultSearcher)
        searcher._graph_provider = None
        searcher._graph_cache = GraphCache(ttl_seconds=300)
        searcher.root_dir = _make_vault_dir(tmp_path)
        try:
            searcher._get_graph()
            graph = searcher._graph_cache.get(tmp_path)
            assert graph is not None
            assert searcher._get_graph() is graph
        finally:
            searcher._graph_cache.close()
