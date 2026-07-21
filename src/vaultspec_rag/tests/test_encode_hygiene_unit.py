"""Unit tests for sparse-tensor conversion parity and the query cache."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar, cast

import pytest

from ..embeddings import (
    EmbeddingModel,
    QueryEmbeddingCache,
    SparseResult,
    _sparse_tensor_to_results,
)

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


class _OOMDenseModel:
    """Dense-model double that OOMs until the batch size is small enough."""

    def __init__(self, succeed_at: int | None = None) -> None:
        self.batch_sizes: list[int] = []
        self._succeed_at = succeed_at

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        show_progress_bar: bool,
        normalize_embeddings: bool,
    ) -> Any:
        del show_progress_bar, normalize_embeddings
        import torch

        self.batch_sizes.append(batch_size)
        if self._succeed_at is not None and batch_size <= self._succeed_at:
            import numpy as np

            return np.zeros((len(texts), 4), dtype=np.float32)
        raise torch.cuda.OutOfMemoryError("simulated CUDA OOM")


class _OOMSparseModel:
    """Sparse-model double mirroring :class:`_OOMDenseModel`."""

    def __init__(self) -> None:
        self.batch_sizes: list[int] = []

    def encode_document(self, texts: list[str], *, batch_size: int) -> Any:
        del texts
        import torch

        self.batch_sizes.append(batch_size)
        raise torch.cuda.OutOfMemoryError("simulated CUDA OOM")


def _model_shell() -> EmbeddingModel:
    """An ``EmbeddingModel`` shell that skips real model loading."""
    return object.__new__(EmbeddingModel)


class TestOomLadderIsFloorBounded:
    """The CUDA-OOM recovery must terminate - never loop forever (#242).

    A persistent allocator failure (e.g. host commit exhaustion on a full
    disk) must abort the run with the real error after the halving ladder
    reaches batch size 1, so no unbounded retry loop can stand between a
    storage-pressure condition and a failed job.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_dense_ladder_halves_then_raises(self):
        import torch

        fake = _OOMDenseModel()
        model = _model_shell()
        model._dense_model = fake  # type: ignore[assignment]
        with pytest.raises(torch.cuda.OutOfMemoryError):
            model.encode_documents(["text"] * 4, batch_size=8)
        assert fake.batch_sizes == [8, 4, 2, 1]

    def test_dense_ladder_recovers_at_smaller_batch(self):
        fake = _OOMDenseModel(succeed_at=2)
        model = _model_shell()
        model._dense_model = fake  # type: ignore[assignment]
        result = model.encode_documents(["text"] * 4, batch_size=8)
        assert result.shape == (4, 4)
        assert fake.batch_sizes == [8, 4, 2]

    def test_sparse_ladder_halves_then_raises(self):
        import torch

        fake = _OOMSparseModel()
        model = _model_shell()
        model._sparse_model = fake  # type: ignore[assignment]
        with pytest.raises(torch.cuda.OutOfMemoryError):
            model.encode_documents_sparse(["text"] * 4, batch_size=8)
        assert fake.batch_sizes == [8, 4, 2, 1]


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
