"""Unit tests for sparse-tensor conversion parity and the query cache."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar, cast

import pytest

from ..embeddings import QueryEmbeddingCache, SparseResult, _sparse_tensor_to_results

# pytest.approx's `expected` parameter is untyped in the stub; cast once so
# call sites stay free of per-call ignores.
_approx = cast("type[Any]", pytest.approx)  # pyright: ignore[reportUnknownMemberType]


def _reference_conversion(dense_rows: list[list[float]]) -> list[SparseResult]:
    """Naive per-row reference: nonzero indices and values in order."""
    results: list[SparseResult] = []
    for row in dense_rows:
        indices = [i for i, v in enumerate(row) if v != 0.0]
        values = [row[i] for i in indices]
        results.append(SparseResult(indices=indices, values=values))
    return results


_ROWS = [
    [0.0, 1.5, 0.0, 0.25, 0.0],
    [0.0, 0.0, 0.0, 0.0, 0.0],
    [3.0, 0.0, 0.0, 0.0, 0.125],
    [0.0, 0.0, 2.0, 0.0, 0.0],
]


class TestSparseTensorConversionParity:
    pytestmark: ClassVar = [pytest.mark.unit]

    def _assert_matches_reference(self, converted: list[SparseResult]) -> None:
        reference = _reference_conversion(_ROWS)
        assert len(converted) == len(reference)
        for got, want in zip(converted, reference, strict=True):
            assert got.indices == want.indices
            assert got.values == _approx(want.values)

    def test_dense_tensor_path(self):
        import torch

        tensor = torch.tensor(_ROWS, dtype=torch.float32)
        self._assert_matches_reference(_sparse_tensor_to_results(tensor))

    def test_sparse_coo_path(self):
        import torch

        tensor = torch.tensor(_ROWS, dtype=torch.float32).to_sparse()
        self._assert_matches_reference(_sparse_tensor_to_results(tensor))

    def test_sparse_csr_path(self):
        import torch

        tensor = torch.tensor(_ROWS, dtype=torch.float32).to_sparse_csr()
        self._assert_matches_reference(_sparse_tensor_to_results(tensor))

    def test_all_zero_batch_yields_empty_results(self):
        import torch

        tensor = torch.zeros((3, 7), dtype=torch.float32)
        converted = _sparse_tensor_to_results(tensor)
        assert len(converted) == 3
        assert all(r.indices == [] and r.values == [] for r in converted)


class TestQueryEmbeddingCache:
    pytestmark: ClassVar = [pytest.mark.unit]

    def _entry(self, seed: float):
        import numpy as np

        return (
            np.full(4, seed, dtype=np.float32),
            SparseResult(indices=[int(seed)], values=[seed]),
        )

    def test_round_trip(self):
        cache = QueryEmbeddingCache(maxsize=4)
        key = ("vault", "how does eviction work")
        assert cache.get(key) is None
        cache.put(key, self._entry(1.0))
        entry = cache.get(key)
        assert entry is not None
        dense, sparse = entry
        assert dense[0] == 1.0
        assert sparse is not None
        assert sparse.values == [1.0]

    def test_lru_eviction_drops_least_recent(self):
        cache = QueryEmbeddingCache(maxsize=2)
        cache.put(("vault", "a"), self._entry(1.0))
        cache.put(("vault", "b"), self._entry(2.0))
        assert cache.get(("vault", "a")) is not None  # refresh "a"
        cache.put(("vault", "c"), self._entry(3.0))  # evicts "b"
        assert cache.get(("vault", "b")) is None
        assert cache.get(("vault", "a")) is not None
        assert cache.get(("vault", "c")) is not None

    def test_surfaces_are_distinct_keys(self):
        cache = QueryEmbeddingCache(maxsize=4)
        cache.put(("vault", "q"), self._entry(1.0))
        assert cache.get(("code", "q")) is None

    def test_concurrent_access_is_safe(self):
        cache = QueryEmbeddingCache(maxsize=8)

        def hammer(worker: int) -> None:
            for i in range(200):
                key = ("vault", f"q{(worker + i) % 16}")
                cache.put(key, self._entry(float(i)))
                cache.get(key)

        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(hammer, range(8)))
        # The cache never exceeds its bound and stays readable.
        assert len(cache._data) <= 8
