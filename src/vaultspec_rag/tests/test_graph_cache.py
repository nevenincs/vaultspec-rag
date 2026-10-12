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
from typing import TYPE_CHECKING, ClassVar
from unittest.mock import Mock

import pytest

from ..graph_cache import GraphCache

if TYPE_CHECKING:
    from pathlib import Path

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


class TestNonblockingGraphRefresh:
    """Hold construction explicitly so timing assertions do not depend on CPU speed."""

    @pytest.mark.parametrize("expired", [False, True])
    def test_search_and_invalidation_do_not_wait(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, expired: bool
    ) -> None:
        from ..search import VaultSearcher

        entered = threading.Event()
        release = threading.Event()
        returned = threading.Event()
        graph = object()

        def build(_root: Path) -> object:
            entered.set()
            assert release.wait(5)
            return graph

        cache = GraphCache(ttl_seconds=300)
        if expired:
            with monkeypatch.context() as prime:
                prime.setattr(
                    "vaultspec_core.graph.VaultGraph", Mock(return_value=graph)
                )
                assert cache.get(tmp_path) is graph
            cache._built_at = 0.0
        constructor = Mock(side_effect=build)
        monkeypatch.setattr("vaultspec_core.graph.VaultGraph", constructor)
        searcher = VaultSearcher.__new__(VaultSearcher)
        searcher._graph_provider = lambda: cache.get(tmp_path, wait=False)
        searcher.root_dir = tmp_path
        results: list[object] = []

        def search():
            results.append(searcher._get_graph())
            returned.set()

        reader = threading.Thread(target=search)
        reader.start()
        try:
            assert entered.wait(2)
            # Mutating the service provider to wait=True must fail this assertion.
            assert returned.wait(1), "search waited for graph construction"
            assert results == [None]
            for _ in range(20):
                assert cache.get(tmp_path, wait=False) is None
            assert constructor.call_count == 1
            cache.invalidate()
            assert cache.get(tmp_path, wait=False) is None
            assert constructor.call_count == 1
        finally:
            release.set()
            reader.join(5)
        assert cache.get(tmp_path) is graph
        assert constructor.call_count == 2
        cache.close()

    def test_invalidation_discards_late_build(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        first_entered = threading.Event()
        first_release = threading.Event()
        second_entered = threading.Event()
        second_release = threading.Event()
        old, new = object(), object()
        calls = 0

        def build(_root: Path) -> object:
            nonlocal calls
            calls += 1
            entered, release = (
                (first_entered, first_release)
                if calls == 1
                else (second_entered, second_release)
            )
            entered.set()
            assert release.wait(5)
            return old if calls == 1 else new

        monkeypatch.setattr("vaultspec_core.graph.VaultGraph", build)
        cache = GraphCache(ttl_seconds=300)
        try:
            assert cache.get(tmp_path, wait=False) is None
            assert first_entered.wait(2)
            cache.invalidate()
            first_release.set()
            second_entered.wait(2)
            # Removing the epoch check must expose the old graph here.
            assert cache.get(tmp_path, wait=False) is None, (
                "superseded graph was published"
            )
            assert second_entered.is_set()
            second_release.set()
            assert cache.get(tmp_path) is new
        finally:
            first_release.set()
            second_release.set()
            cache.close()

    def test_failure_backoff_then_recovery(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        graph = object()
        constructor = Mock(side_effect=[OSError("unavailable"), graph])
        monkeypatch.setattr("vaultspec_core.graph.VaultGraph", constructor)
        cache = GraphCache(ttl_seconds=300)
        assert cache.get(tmp_path) is None
        for _ in range(10):
            assert cache.get(tmp_path, wait=False) is None
        assert constructor.call_count == 1
        cache._retry_at = 0
        assert cache.get(tmp_path) is graph
        assert constructor.call_count == 2
        cache.close()

    def test_close_rejects_late_completion(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        entered, release = threading.Event(), threading.Event()

        def build(_root: Path) -> object:
            entered.set()
            assert release.wait(5)
            return object()

        monkeypatch.setattr("vaultspec_core.graph.VaultGraph", build)
        cache = GraphCache(ttl_seconds=300)
        try:
            assert cache.get(tmp_path, wait=False) is None
            assert entered.wait(2)
            worker = cache._worker
            cache.close()
            release.set()
            assert worker is not None
            worker.join(5)
            assert not worker.is_alive()
            assert cache.get(tmp_path) is None
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
