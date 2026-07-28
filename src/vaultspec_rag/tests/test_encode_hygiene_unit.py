"""Unit tests for sparse-tensor conversion parity and the query cache."""

from concurrent.futures import ThreadPoolExecutor
from typing import Any, ClassVar, cast

import pytest

from ..embeddings import (
    EmbeddingModel,
    EncodeBatchCeiling,
    QueryEmbeddingCache,
    SparseResult,
    _sparse_tensor_to_results,
)

# pytest.approx's `expected` parameter is untyped in the stub; cast once so
# call sites stay free of per-call ignores.
_approx = cast("type[Any]", pytest.approx)


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

    def __init__(self, succeed_at: int | None = None) -> None:
        self.batch_sizes: list[int] = []
        self._succeed_at = succeed_at

    def encode_document(
        self,
        texts: list[str],
        *,
        batch_size: int,
        **options: object,
    ) -> Any:
        # Mirrors the production call site's keyword set; the sparse
        # encode path passes these explicitly, so a double that accepts
        # only batch_size fails on the call rather than on the OOM the
        # test is actually about.
        del options
        import torch

        self.batch_sizes.append(batch_size)
        if self._succeed_at is not None and batch_size <= self._succeed_at:
            return torch.zeros((len(texts), 4), dtype=torch.float32)
        raise torch.cuda.OutOfMemoryError("simulated CUDA OOM")


def _model_shell() -> EmbeddingModel:
    """An ``EmbeddingModel`` shell that skips real model loading."""
    model = object.__new__(EmbeddingModel)
    model._dense_batch_ceiling = EncodeBatchCeiling()
    model._sparse_batch_ceiling = EncodeBatchCeiling()
    return model


class TestOomLadderIsFloorBounded:
    """The CUDA-OOM recovery must terminate - never loop forever.

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
        model._dense_model = cast("Any", fake)
        with pytest.raises(torch.cuda.OutOfMemoryError):
            model.encode_documents(["text"] * 4, batch_size=8)
        assert fake.batch_sizes == [8, 4, 2, 1]

    def test_dense_ladder_recovers_at_smaller_batch(self):
        fake = _OOMDenseModel(succeed_at=2)
        model = _model_shell()
        model._dense_model = cast("Any", fake)
        result = model.encode_documents(["text"] * 4, batch_size=8)
        assert result.shape == (4, 4)
        assert fake.batch_sizes == [8, 4, 2]

    def test_sparse_ladder_halves_then_raises(self):
        import torch

        fake = _OOMSparseModel()
        model = _model_shell()
        model._sparse_model = cast("Any", fake)
        with pytest.raises(torch.cuda.OutOfMemoryError):
            model.encode_documents_sparse(["text"] * 4, batch_size=8)
        assert fake.batch_sizes == [8, 4, 2, 1]


class TestOomLadderCeilingIsSticky:
    """A learned OOM batch ceiling persists across calls and recovers upward.

    A per-call ladder rediscovers the same ceiling on every call, paying a
    discarded forward pass and an allocator cache flush each time; the
    ceiling must therefore survive the call that learned it. It must also
    not stay pinned forever, or one transient memory squeeze becomes a
    permanent throughput loss - after sustained success at the ceiling the
    next call probes upward, bounded by one doubling.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_dense_ceiling_sticks_across_calls(self):
        fake = _OOMDenseModel(succeed_at=2)
        model = _model_shell()
        model._dense_model = cast("Any", fake)
        model.encode_documents(["text"] * 4, batch_size=8)
        model.encode_documents(["text"] * 4, batch_size=8)
        # Failure direction proven: making EncodeBatchCeiling.clamp return
        # the requested size unchanged restores the per-call reset, so the
        # second call restarts at 8, OOMs its way down again, and this
        # records [8, 4, 2, 8, 4, 2]; with the sticky ceiling the second
        # call starts directly at the learned 2. Restoring clamp passes.
        assert fake.batch_sizes == [8, 4, 2, 2]

    def test_sparse_ceiling_sticks_across_calls(self):
        fake = _OOMSparseModel(succeed_at=2)
        model = _model_shell()
        model._sparse_model = cast("Any", fake)
        model.encode_documents_sparse(["text"] * 4, batch_size=8)
        model.encode_documents_sparse(["text"] * 4, batch_size=8)
        # Same failure direction as the dense sticky test: a per-call
        # reset records a second descent [8, 4, 2, 2] after the first
        # instead of two clamped sub-batch calls at 2.
        assert fake.batch_sizes == [8, 4, 2, 2, 2, 2]

    def test_dense_ceiling_probes_upward_after_sustained_success(self):
        fake = _OOMDenseModel(succeed_at=2)
        model = _model_shell()
        model._dense_model = cast("Any", fake)
        model.encode_documents(["text"], batch_size=8)
        assert fake.batch_sizes == [8, 4, 2]
        # Memory pressure lifts: everything fits from now on.
        fake._succeed_at = 64
        for _ in range(EncodeBatchCeiling.RECOVERY_SUCCESSES - 1):
            model.encode_documents(["text"], batch_size=8)
        assert set(fake.batch_sizes[3:]) == {2}
        model.encode_documents(["text"], batch_size=8)
        # One doubling per probe, never a jump straight back to 8.
        assert fake.batch_sizes[-1] == 4

    def test_failed_probe_reclamps_and_restarts_the_count(self):
        fake = _OOMDenseModel(succeed_at=2)
        model = _model_shell()
        model._dense_model = cast("Any", fake)
        model.encode_documents(["text"], batch_size=8)
        for _ in range(EncodeBatchCeiling.RECOVERY_SUCCESSES - 1):
            model.encode_documents(["text"], batch_size=8)
        # The probe at 4 still OOMs: the call must converge back at 2 and
        # the following call must not probe again immediately.
        model.encode_documents(["text"], batch_size=8)
        assert fake.batch_sizes[-2:] == [4, 2]
        model.encode_documents(["text"], batch_size=8)
        assert fake.batch_sizes[-1] == 2


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
