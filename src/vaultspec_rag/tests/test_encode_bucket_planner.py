"""Unit tests for token-budget encode bucket planning and bucketed encoding."""

import threading
from itertools import pairwise
from typing import Any, ClassVar, cast

import pytest

from ..embeddings import (
    EmbeddingModel,
    EncodeBatchCeiling,
    EncodeBucket,
    EncodeBucketProgress,
    plan_encode_buckets,
)


def _texts_of_lengths(lengths: list[int]) -> list[str]:
    """Build texts whose character lengths are exactly *lengths*."""
    return ["x" * length for length in lengths]


class TestPlanEncodeBuckets:
    pytestmark: ClassVar = [pytest.mark.unit]

    def test_empty_input_plans_no_buckets(self):
        assert (
            plan_encode_buckets([], token_budget=100, chars_per_token=4, max_items=32)
            == []
        )

    def test_partition_is_contiguous_ordered_and_exhaustive(self):
        texts = _texts_of_lengths([400, 400, 200, 200, 100, 50, 50, 10])
        buckets = plan_encode_buckets(
            texts, token_budget=250, chars_per_token=4, max_items=32
        )
        assert buckets[0].start == 0
        assert buckets[-1].end == len(texts)
        for previous, current in pairwise(buckets):
            assert previous.end == current.start
        assert all(bucket.end > bucket.start for bucket in buckets)

    def test_every_multi_item_bucket_respects_the_token_budget(self):
        texts = _texts_of_lengths([397, 401, 213, 199, 120, 88, 41, 12, 3])
        budget = 150
        buckets = plan_encode_buckets(
            texts, token_budget=budget, chars_per_token=4, max_items=32
        )
        for bucket in buckets:
            if bucket.end - bucket.start > 1:
                assert bucket.estimated_tokens <= budget

    def test_footprint_is_items_times_padded_longest_estimate(self):
        # Two texts of 8 and 4 chars at 4 chars/token estimate 2 and 1
        # tokens; padded to the bucket's longest item the footprint is
        # 2 items x 2 tokens = 4, not the 3-token sum.
        texts = _texts_of_lengths([8, 4])
        buckets = plan_encode_buckets(
            texts, token_budget=100, chars_per_token=4, max_items=32
        )
        assert buckets == [EncodeBucket(start=0, end=2, estimated_tokens=4)]

    def test_item_count_cap_binds_even_under_a_loose_budget(self):
        texts = _texts_of_lengths([4] * 10)
        buckets = plan_encode_buckets(
            texts, token_budget=10_000, chars_per_token=4, max_items=4
        )
        assert [bucket.end - bucket.start for bucket in buckets] == [4, 4, 2]

    def test_single_item_over_budget_forms_its_own_bucket(self):
        # The 800-char text alone estimates 200 tokens against a budget of
        # 100: it must still be planned (as a bucket of one), and must not
        # absorb the short neighbours whose padded cost it would inflate.
        texts = _texts_of_lengths([800, 40, 40])
        buckets = plan_encode_buckets(
            texts, token_budget=100, chars_per_token=4, max_items=32
        )
        assert buckets[0] == EncodeBucket(start=0, end=1, estimated_tokens=200)
        assert buckets[1] == EncodeBucket(start=1, end=3, estimated_tokens=20)

    def test_empty_text_estimates_one_token(self):
        # Special tokens mean no input is free; a zero estimate would let
        # unbounded counts of empty strings into one bucket.
        buckets = plan_encode_buckets(
            ["", ""], token_budget=1, chars_per_token=4, max_items=32
        )
        assert [bucket.estimated_tokens for bucket in buckets] == [1, 1]

    def test_length_sorted_input_yields_homogeneous_buckets(self):
        lengths = [1600, 1500, 1450, 800, 780, 400, 390, 380, 40, 20]
        texts = _texts_of_lengths(lengths)
        buckets = plan_encode_buckets(
            texts, token_budget=800, chars_per_token=4, max_items=4
        )
        # Descending input keeps every bucket's padded estimate equal to
        # its first item's estimate, so no bucket pays padding for a
        # longer item introduced later.
        for bucket in buckets:
            first_estimate = max(1, -(-lengths[bucket.start] // 4))
            assert bucket.estimated_tokens == (
                (bucket.end - bucket.start) * first_estimate
            )

    @pytest.mark.parametrize(
        ("token_budget", "chars_per_token", "max_items"),
        [(0, 4, 32), (100, 0, 32), (100, 4, 0), (-1, 4, 32)],
    )
    def test_non_positive_bounds_are_rejected(
        self, token_budget: int, chars_per_token: int, max_items: int
    ):
        with pytest.raises(ValueError, match="must be a positive integer"):
            plan_encode_buckets(
                ["text"],
                token_budget=token_budget,
                chars_per_token=chars_per_token,
                max_items=max_items,
            )


def _model_shell(
    token_budget: int = 100,
    chars_per_token: int = 4,
) -> EmbeddingModel:
    """An ``EmbeddingModel`` shell that skips real model loading."""
    model = object.__new__(EmbeddingModel)
    model._dense_batch_ceiling = EncodeBatchCeiling()
    model._sparse_batch_ceiling = EncodeBatchCeiling()
    model._encode_token_budget = token_budget
    model._encode_chars_per_token = chars_per_token
    return model


class _BucketRecordingDenseModel:
    """Dense-model double recording each encode call's exact text list.

    ``oom_on_first`` names text lists whose first encode attempt raises a
    simulated CUDA OOM; any later attempt (a replanned smaller bucket)
    succeeds. Each returned row carries its input text's length so tests
    can prove row-to-input alignment across bucket boundaries.
    """

    def __init__(self, oom_on_first: list[list[str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.batch_sizes: list[int] = []
        self._oom_pending = [list(entry) for entry in (oom_on_first or [])]

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        show_progress_bar: bool,
        normalize_embeddings: bool,
    ) -> Any:
        # Mirrors the production call site's keyword set; a double that
        # accepts only batch_size fails on the call rather than on the
        # behaviour the test is actually about.
        del show_progress_bar, normalize_embeddings
        import numpy as np
        import torch

        self.calls.append(list(texts))
        self.batch_sizes.append(batch_size)
        if list(texts) in self._oom_pending:
            self._oom_pending.remove(list(texts))
            raise torch.cuda.OutOfMemoryError("simulated CUDA OOM")
        return np.array([[float(len(t))] * 2 for t in texts], dtype=np.float32)


class _LockAssertingTensorDenseModel:
    """Tensor-returning dense double that requires the GPU lock be held.

    Exercises the on-device output mode: the production call passes the
    tensor-retention keywords, and each bucket's forward must run inside
    its own hold of the supplied lock.
    """

    def __init__(self, gpu_lock: threading.Lock) -> None:
        self.calls: list[list[str]] = []
        self._gpu_lock = gpu_lock

    def encode(
        self,
        texts: list[str],
        *,
        batch_size: int,
        show_progress_bar: bool,
        normalize_embeddings: bool,
        **retention: bool,
    ) -> Any:
        del batch_size, show_progress_bar, normalize_embeddings
        assert retention == {"convert_to_numpy": False, "convert_to_tensor": True}
        import torch

        assert self._gpu_lock.locked(), "bucket forward ran outside the GPU lock"
        self.calls.append(list(texts))
        return torch.tensor([[float(len(t))] * 2 for t in texts])


class TestBucketedDenseEncode:
    """The dense encode path plans buckets and scopes OOM retry to one bucket."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def _texts(self, count: int, length: int = 200) -> list[str]:
        # Distinct single-character bodies keep every text identifiable in
        # the double's call log. 200 chars at 4 chars/token estimate 50
        # tokens each, so a 100-token budget plans two-item buckets.
        alphabet = "abcdefghijklmnopqrstuvwxyz"
        return [alphabet[i] * length for i in range(count)]

    def test_each_planned_bucket_is_one_encode_call(self):
        texts = self._texts(4)
        fake = _BucketRecordingDenseModel()
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        result = model.encode_documents(texts)
        assert fake.calls == [texts[0:2], texts[2:4]]
        # The bucket is handed over as a single library sub-batch, so the
        # library's internal loop degenerates to exactly one forward.
        assert fake.batch_sizes == [2, 2]
        assert result.shape == (4, 2)

    def test_oom_discards_only_the_failing_bucket(self):
        texts = self._texts(6)
        fake = _BucketRecordingDenseModel(oom_on_first=[texts[2:4]])
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        result = model.encode_documents(texts)
        # Catches the retry scope regressing from the bucket to the whole
        # call: a slice-wide retry discards completed outputs and replans
        # from the first text, so the completed [t0, t1] bucket shows up
        # encoded a second time. Bucket-scoped retry re-encodes nothing
        # before the failing bucket and splits only from its start; the
        # 100-token failing footprint halves the budget to 50, so the
        # replanned tail is single-item buckets.
        assert fake.calls == [
            texts[0:2],
            texts[2:4],
            [texts[2]],
            [texts[3]],
            [texts[4]],
            [texts[5]],
        ]
        # Every input still comes back exactly once, in input order.
        assert [row[0] for row in result.tolist()] == [200.0] * 6

    def test_single_text_bucket_oom_reraises(self):
        import torch

        texts = self._texts(1)
        fake = _BucketRecordingDenseModel(oom_on_first=[texts[0:1]])
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        with pytest.raises(torch.cuda.OutOfMemoryError):
            model.encode_documents(texts)
        # A one-text bucket cannot shrink, so there is no retry attempt.
        assert fake.calls == [texts[0:1]]

    def test_learned_token_ceiling_sticks_across_calls(self):
        texts = self._texts(4)
        fake = _BucketRecordingDenseModel(oom_on_first=[texts[2:4]])
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        model.encode_documents(texts)
        first_call_count = len(fake.calls)
        model.encode_documents(texts)
        # Catches the ceiling resetting between calls: an unclamped second
        # call would replan two-item 100-token buckets and rediscover the
        # OOM; under the learned 50-token ceiling it plans single-item
        # buckets from the start.
        assert fake.calls[first_call_count:] == [[t] for t in texts]

    def test_mixed_length_outputs_return_in_input_order(self):
        lengths = [300, 200, 100, 50]
        texts = _texts_of_lengths(lengths)
        fake = _BucketRecordingDenseModel()
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        result = model.encode_documents(texts)
        # Estimates 75/50/25/13 plan buckets [t0], [t1, t2], [t3]; the
        # concatenated rows must still follow the input order.
        assert fake.calls == [texts[0:1], texts[1:3], texts[3:4]]
        assert [row[0] for row in result.tolist()] == [float(n) for n in lengths]

    def test_empty_input_is_one_library_call(self):
        fake = _BucketRecordingDenseModel()
        model = _model_shell()
        model._dense_model = cast("Any", fake)
        result = model.encode_documents([])
        assert fake.calls == [[]]
        assert result.shape[0] == 0

    def test_on_device_buckets_hold_the_gpu_lock_and_concatenate(self):
        gpu_lock = threading.Lock()
        fake = _LockAssertingTensorDenseModel(gpu_lock)
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        texts = self._texts(4)
        result = model.encode_documents_on_device(texts, gpu_lock=gpu_lock)
        assert fake.calls == [texts[0:2], texts[2:4]]
        assert not gpu_lock.locked()
        assert [row[0] for row in result.tolist()] == [200.0] * 4

    def test_bucket_callback_reports_progress_and_budget(self):
        texts = self._texts(4)
        fake = _BucketRecordingDenseModel(oom_on_first=[texts[2:4]])
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        events: list[tuple[str, EncodeBucketProgress]] = []

        def observe(phase: str, progress: EncodeBucketProgress) -> None:
            events.append((phase, progress))

        model._encode_documents_output(
            texts,
            batch_size=None,
            retain_on_device=False,
            on_bucket=observe,
        )
        phases = [phase for phase, _progress in events]
        # The failing [t2, t3] attempt fires "before" without an "after";
        # its replanned single-item retries each fire a full pair.
        assert phases == [
            "before",
            "after",
            "before",
            "before",
            "after",
            "before",
            "after",
        ]
        done = [progress.items_done for phase, progress in events if phase == "after"]
        assert done == [2, 3, 4]
        assert events[0][1].token_budget == 100
        assert events[0][1].oom_count == 0
        # After the OOM the live budget halves and the counter advances.
        assert events[3][1].token_budget == 50
        assert events[3][1].oom_count == 1
        assert all(progress.items_total == 4 for _phase, progress in events)
