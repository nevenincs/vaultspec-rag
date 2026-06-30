"""Multi-repo concurrent search + index load (plan W04.P07.S25).

No mocks, real GPU: two independent repos (separate roots, separate stores)
share the one GPU model - the actual multi-repo contention a single service
serves. Concurrent full searches across both repos, interleaved with a reindex
on one, must all complete without error or deadlock under saturation. This
exercises the GPU lock and the backend-aware per-collection store locks under
the load profile a multi-user, multi-repo service sees.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import pytest

from ... import VaultIndexer, VaultSearcher, VaultStore
from ...progress import NullProgressReporter
from ..corpus import build_synthetic_vault

if TYPE_CHECKING:
    from pathlib import Path

    from ...embeddings import EmbeddingModel

pytestmark = [pytest.mark.integration]

_QUERIES = (
    "architecture decision record",
    "implementation plan steps",
    "research findings and tradeoffs",
    "audit of the storage layer",
)


class TestMultiRepoConcurrentLoad:
    def test_concurrent_searches_and_reindex_across_two_repos_hold(
        self,
        embedding_model: EmbeddingModel,
        tmp_path: Path,
    ) -> None:
        # One shared GPU lock serialises every GPU-bound operation across both
        # repos, exactly as the single service does (service.py wires the same
        # lock into every searcher and indexer). Without it, two roots' forward
        # passes and lazy model loads race on the one device and crash.
        gpu_lock = threading.Lock()
        repos: list[tuple[Path, VaultStore]] = []
        searchers: list[VaultSearcher] = []
        for i in range(2):
            root = tmp_path / f"repo{i}"
            build_synthetic_vault(root, n_docs=16, seed=300 + i)
            store = VaultStore(root)
            VaultIndexer(root, embedding_model, store, gpu_lock=gpu_lock).full_index(
                reporter=NullProgressReporter()
            )
            repos.append((root, store))
            searchers.append(
                VaultSearcher(root, embedding_model, store, gpu_lock=gpu_lock)
            )

        def do_search(task: int) -> int:
            searcher = searchers[task % 2]
            results = searcher.search_vault(_QUERIES[task % len(_QUERIES)], top_k=5)
            return len(results)

        def do_reindex() -> None:
            root, store = repos[0]
            VaultIndexer(root, embedding_model, store, gpu_lock=gpu_lock).full_index(
                reporter=NullProgressReporter()
            )

        errors: list[Exception] = []
        search_returns: list[int] = []
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                futures: list[Future[object]] = [
                    pool.submit(do_search, task) for task in range(24)
                ]
                # Interleave a reindex on repo0 concurrently with the searches:
                # the index write and the searches contend on repo0's collection
                # lock while repo1 searches proceed independently.
                futures.append(pool.submit(do_reindex))
                for future in as_completed(futures):
                    try:
                        result = future.result()
                    except Exception as exc:  # collect, assert below
                        errors.append(exc)
                    else:
                        if isinstance(result, int):
                            search_returns.append(result)

            assert not errors, f"multi-repo concurrent load raised: {errors}"
            # Every search completed; under a populated corpus they return hits.
            assert len(search_returns) == 24
            assert all(count > 0 for count in search_returns)
        finally:
            for _root, store in repos:
                store.close()
