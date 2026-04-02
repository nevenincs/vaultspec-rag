"""Tests for GraphCache (api.py) and VaultSearcher graph_provider (search.py).

Covers:
- GraphCache.get() with TTL expiry
- GraphCache.get() concurrent access at TTL boundary
- GraphCache.invalidate() triggers rebuild on next get
- VaultSearcher with graph_provider (delegation)
- VaultSearcher without graph_provider (internal fallback with lock)
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, ClassVar

import pytest

from vaultspec_rag.api import GraphCache

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
        # VaultGraph succeeds on a dir with no .vault/ — returns a graph
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

    def test_invalidate_resets_built_at(self, tmp_path: Path):
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=300.0)
        cache.get(root)
        assert cache._built_at > 0.0
        cache.invalidate()
        assert cache._built_at == 0.0


class TestGraphCacheConcurrency:
    """Concurrent access at TTL boundary produces exactly one rebuild.

    This is the R36-C1 fix: multiple threads hitting get() when the
    cache is stale must not trigger parallel VaultGraph constructions.
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
        # All threads got the same graph object — proves single construction
        first = results[0]
        assert all(r is first for r in results)


class TestGraphCacheFailureRecovery:
    """GraphCache.get() after a construction failure retries on next call.

    When VaultGraph raises, get() catches the exception, sets _graph=None
    and _built_at=now. Because _is_stale() returns True whenever _graph
    is None, the next call will attempt a fresh build — no TTL-based
    retry suppression.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_get_retries_after_simulated_failure(self, tmp_path: Path):
        """After a failure state (_graph=None, _built_at=recent), get()
        still rebuilds because _is_stale returns True when _graph is None."""
        root = _make_vault_dir(tmp_path)
        cache = GraphCache(ttl_seconds=300.0)

        # Simulate a prior failure: _graph is None but _built_at is recent
        cache._graph = None
        cache._root = root
        cache._built_at = time.monotonic()

        # get() should retry and succeed despite recent _built_at
        result = cache.get(root)
        assert result is not None
        # Verify it actually built a graph (not just returned stale None)
        from vaultspec_core.graph import VaultGraph

        assert isinstance(result, VaultGraph)

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


class TestVaultSearcherGraphProvider:
    """VaultSearcher delegates to graph_provider when supplied."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_get_graph_uses_provider(self, tmp_path: Path):
        from vaultspec_core.graph import VaultGraph

        root = _make_vault_dir(tmp_path)
        graph_instance = VaultGraph(root)
        call_count = 0

        def provider() -> VaultGraph:
            nonlocal call_count
            call_count += 1
            return graph_instance

        # Build a minimal VaultSearcher without GPU models — only test
        # _get_graph, which does not need the model or store.
        from vaultspec_rag.search import VaultSearcher

        searcher = VaultSearcher.__new__(VaultSearcher)
        searcher._graph_provider = provider
        searcher._graph_ttl = 300.0
        searcher._cached_graph = None
        searcher._graph_built_at = 0.0
        searcher._graph_lock = threading.Lock()
        searcher.root_dir = root

        result = searcher._get_graph()
        assert result is graph_instance
        assert call_count == 1

    def test_get_graph_fallback_without_provider(self, tmp_path: Path):
        """Without graph_provider, the internal lock+TTL cache is used."""
        root = _make_vault_dir(tmp_path)

        from vaultspec_rag.search import VaultSearcher

        searcher = VaultSearcher.__new__(VaultSearcher)
        searcher._graph_provider = None
        searcher._graph_ttl = 300.0
        searcher._cached_graph = None
        searcher._graph_built_at = 0.0
        searcher._graph_lock = threading.Lock()
        searcher.root_dir = root

        g1 = searcher._get_graph()
        assert g1 is not None
        # Second call returns same instance (within TTL)
        g2 = searcher._get_graph()
        assert g1 is g2

    def test_fallback_lock_prevents_concurrent_builds(self, tmp_path: Path):
        """Internal fallback path has a lock for R36-C1 safety."""
        root = _make_vault_dir(tmp_path)

        from vaultspec_rag.search import VaultSearcher

        searcher = VaultSearcher.__new__(VaultSearcher)
        searcher._graph_provider = None
        searcher._graph_ttl = 0.0  # always stale
        searcher._cached_graph = None
        searcher._graph_built_at = 0.0
        searcher._graph_lock = threading.Lock()
        searcher.root_dir = root

        results: list[object] = []
        barrier = threading.Barrier(4)

        def worker():
            barrier.wait()
            results.append(searcher._get_graph())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        assert len(results) == 4
        assert all(r is not None for r in results)
