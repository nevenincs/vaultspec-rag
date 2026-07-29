"""Unit tests for token-budget encode bucket planning and bucketed encoding."""

import threading
from itertools import pairwise
from typing import Any, ClassVar, Protocol, cast

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


class _TokenCounter(Protocol):
    """The concrete tokenizer operation the calibration guard exercises."""

    def tokenize(
        self,
        text: str,
        pair: str | None = None,
        add_special_tokens: bool = False,
    ) -> list[str]: ...


def _token_count(tokenizer: _TokenCounter, text: str) -> int:
    """Count one text with the tokenizer interface the guard requires."""
    return len(tokenizer.tokenize(text, add_special_tokens=True))


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


class TestEncodeBatchCeilingTokenSemantics:
    """The learned ceiling records, clamps, and probes in token units.

    A per-count ceiling learned on one length regime is wrong for every
    other; the token denomination makes one learned number regime-aware.
    The recovery design is unchanged: sustained success at the ceiling
    earns one bounded upward probe.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_unlearned_ceiling_returns_the_requested_budget(self):
        assert EncodeBatchCeiling().clamp(24_000) == 24_000

    def test_success_before_any_oom_is_inert(self):
        ceiling = EncodeBatchCeiling()
        ceiling.record_success(24_000)
        assert ceiling.clamp(24_000) == 24_000

    def test_record_oom_halves_the_failing_footprint_and_returns_it(self):
        ceiling = EncodeBatchCeiling()
        # Replanning at the footprint that just failed would reproduce the
        # same failing bucket shape, so the learned ceiling must sit
        # strictly below it.
        assert ceiling.record_oom(1600) == 800
        assert ceiling.clamp(24_000) == 800

    def test_record_oom_floors_at_one_token(self):
        assert EncodeBatchCeiling().record_oom(1) == 1

    def test_probe_doubles_after_sustained_success_bounded_by_request(self):
        ceiling = EncodeBatchCeiling()
        ceiling.record_oom(1600)
        for _ in range(EncodeBatchCeiling.RECOVERY_SUCCESSES):
            assert ceiling.clamp(24_000) == 800
            ceiling.record_success(800)
        # One doubling per probe, never a jump straight back to the
        # requested budget.
        assert ceiling.clamp(24_000) == 1600

    def test_probe_never_exceeds_the_requested_budget(self):
        ceiling = EncodeBatchCeiling()
        ceiling.record_oom(1600)
        for _ in range(EncodeBatchCeiling.RECOVERY_SUCCESSES):
            ceiling.record_success(ceiling.clamp(1000))
        assert ceiling.clamp(1000) == 1000

    def test_successful_probe_raises_the_ceiling(self):
        ceiling = EncodeBatchCeiling()
        ceiling.record_oom(1600)
        for _ in range(EncodeBatchCeiling.RECOVERY_SUCCESSES):
            ceiling.record_success(ceiling.clamp(24_000))
        probe = ceiling.clamp(24_000)
        assert probe == 1600
        ceiling.record_success(probe)
        # The raised ceiling holds without an immediate second probe.
        assert ceiling.clamp(24_000) == 1600

    def test_failed_probe_reclamps_and_restarts_the_count(self):
        ceiling = EncodeBatchCeiling()
        ceiling.record_oom(1600)
        for _ in range(EncodeBatchCeiling.RECOVERY_SUCCESSES):
            ceiling.record_success(ceiling.clamp(24_000))
        probe = ceiling.clamp(24_000)
        assert probe == 1600
        # The probe OOMs at its own estimated footprint: re-clamp below it
        # and do not probe again on the next call.
        assert ceiling.record_oom(probe) == 800
        assert ceiling.clamp(24_000) == 800


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


class _BucketRecordingSparseModel:
    """Sparse-model double recording each encode call's exact text list.

    ``oom_on_first`` names text lists whose first encode attempt raises a
    simulated CUDA OOM; any later attempt (a replanned smaller bucket)
    succeeds. Each returned row carries its input text's length in
    column 0 so tests can prove row-to-input alignment.
    """

    def __init__(self, oom_on_first: list[list[str]] | None = None) -> None:
        self.calls: list[list[str]] = []
        self.batch_sizes: list[int] = []
        self._oom_pending = [list(entry) for entry in (oom_on_first or [])]

    def encode_document(
        self,
        texts: list[str],
        *,
        batch_size: int,
        **options: object,
    ) -> Any:
        # Mirrors the production call site's keyword set; the sparse
        # encode path passes these explicitly, so a double that accepts
        # only batch_size fails on the call rather than on the behaviour
        # the test is actually about.
        del options
        import torch

        self.calls.append(list(texts))
        self.batch_sizes.append(batch_size)
        if list(texts) in self._oom_pending:
            self._oom_pending.remove(list(texts))
            raise torch.cuda.OutOfMemoryError("simulated CUDA OOM")
        return torch.tensor([[float(len(t)), 0.0] for t in texts])


def _distinct_texts(count: int, length: int = 200) -> list[str]:
    """Distinct single-character bodies, identifiable in a call log.

    200 chars at 4 chars/token estimate 50 tokens each, so a 100-token
    budget plans two-item buckets.
    """
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return [alphabet[i] * length for i in range(count)]


class TestBucketedDenseEncode:
    """The dense encode path plans buckets and scopes OOM retry to one bucket."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_each_planned_bucket_is_one_encode_call(self):
        texts = _distinct_texts(4)
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
        texts = _distinct_texts(6)
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

        texts = _distinct_texts(1)
        fake = _BucketRecordingDenseModel(oom_on_first=[texts[0:1]])
        model = _model_shell(token_budget=100)
        model._dense_model = cast("Any", fake)
        with pytest.raises(torch.cuda.OutOfMemoryError):
            model.encode_documents(texts)
        # A one-text bucket cannot shrink, so there is no retry attempt.
        assert fake.calls == [texts[0:1]]

    def test_learned_token_ceiling_sticks_across_calls(self):
        texts = _distinct_texts(4)
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
        texts = _distinct_texts(4)
        result = model.encode_documents_on_device(texts, gpu_lock=gpu_lock)
        assert fake.calls == [texts[0:2], texts[2:4]]
        assert not gpu_lock.locked()
        assert [float(result[index, 0]) for index in range(4)] == [200.0] * 4

    def test_bucket_callback_reports_progress_and_budget(self):
        texts = _distinct_texts(4)
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


class TestBucketedSparseEncode:
    """The sparse path shares the planner and the token-denominated ceiling."""

    pytestmark: ClassVar = [pytest.mark.unit]

    def test_each_planned_bucket_is_one_forward(self):
        texts = _distinct_texts(4)
        fake = _BucketRecordingSparseModel()
        model = _model_shell(token_budget=100)
        model._sparse_model = cast("Any", fake)
        results = model.encode_documents_sparse(texts)
        assert fake.calls == [texts[0:2], texts[2:4]]
        # The bucket is handed over as a single library sub-batch, so the
        # library's internal loop degenerates to exactly one forward.
        assert fake.batch_sizes == [2, 2]
        assert [row.values[0] for row in results] == [200.0] * 4

    def test_oom_discards_only_the_failing_bucket(self):
        texts = _distinct_texts(6)
        fake = _BucketRecordingSparseModel(oom_on_first=[texts[2:4]])
        model = _model_shell(token_budget=100)
        model._sparse_model = cast("Any", fake)
        results = model.encode_documents_sparse(texts)
        # Catches the retry scope regressing from the bucket to the whole
        # call: a slice-wide retry discards completed rows and replans
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
        assert [row.values[0] for row in results] == [200.0] * 6

    def test_single_text_bucket_oom_reraises(self):
        import torch

        texts = _distinct_texts(1)
        fake = _BucketRecordingSparseModel(oom_on_first=[texts[0:1]])
        model = _model_shell(token_budget=100)
        model._sparse_model = cast("Any", fake)
        with pytest.raises(torch.cuda.OutOfMemoryError):
            model.encode_documents_sparse(texts)
        # A one-text bucket cannot shrink, so there is no retry attempt.
        assert fake.calls == [texts[0:1]]

    def test_learned_token_ceiling_sticks_across_calls(self):
        texts = _distinct_texts(4)
        fake = _BucketRecordingSparseModel(oom_on_first=[texts[2:4]])
        model = _model_shell(token_budget=100)
        model._sparse_model = cast("Any", fake)
        model.encode_documents_sparse(texts)
        first_call_count = len(fake.calls)
        model.encode_documents_sparse(texts)
        # Catches the ceiling resetting between calls: an unclamped second
        # call would replan two-item 100-token buckets and rediscover the
        # OOM; under the learned 50-token ceiling it plans single-item
        # buckets from the start.
        assert fake.calls[first_call_count:] == [[t] for t in texts]

    def test_dense_and_sparse_ceilings_learn_independently(self):
        texts = _distinct_texts(4)
        sparse_fake = _BucketRecordingSparseModel(oom_on_first=[texts[2:4]])
        dense_fake = _BucketRecordingDenseModel()
        model = _model_shell(token_budget=100)
        model._sparse_model = cast("Any", sparse_fake)
        model._dense_model = cast("Any", dense_fake)
        model.encode_documents_sparse(texts)
        model.encode_documents(texts)
        # The sparse OOM must not clamp the dense budget: dense still
        # plans full two-item 100-token buckets.
        assert dense_fake.calls == [texts[0:2], texts[2:4]]

    def test_empty_input_returns_no_rows_without_a_forward(self):
        fake = _BucketRecordingSparseModel()
        model = _model_shell()
        model._sparse_model = cast("Any", fake)
        assert model.encode_documents_sparse([]) == []
        assert fake.calls == []

    def test_non_positive_batch_size_is_rejected(self):
        model = _model_shell()
        model._sparse_model = cast("Any", _BucketRecordingSparseModel())
        with pytest.raises(ValueError, match="batch_size must be a positive integer"):
            model.encode_documents_sparse(["text"], batch_size=0)


#: Fixed worst-case calibration corpus: token-dense shapes a code or
#: document index actually ingests. Pure digit streams are the measured
#: tokenisation floor (~1 char/token under Qwen's digit-splitting BPE);
#: hex/id dumps sit near 1.2, symbol-heavy and minified source near 2.1;
#: ordinary indented code (~3.8) and prose (~6) act as controls.
_CALIBRATION_CORPUS: dict[str, str] = {
    "numeric_table": "\n".join(
        " ".join(f"{(row * 17 + col) * 0.137:.6f}" for col in range(8))
        for row in range(40)
    ),
    "hex_and_ids": "\n".join(
        f"0x{n * 2654435761 % (1 << 32):08x} "
        f"{n * 7919:05d}-{n * 104729 % 99999:05d} "
        f"deadbeef-{n:04d}-4abc-9def-{n * 31:012d}"
        for n in range(30)
    ),
    "symbol_heavy_source": (
        "if (!((a?.b ?? c[d]) && (e | f) ^ ~g) || h != i) { j += k[l]; }\n"
        'result = re.sub(r"[^a-z0-9_]+", "-", value.strip().lower())\n'
        "x=(y<<2)|(z>>3); q&=~mask; p^=0xDEADBEEF; r%=s;\n"
    )
    * 12,
    "minified_style": (
        "var a=function(b,c){return b&&c?b(c):null};"
        "for(var d=0;d<e.length;d++){f[g[d]]=h(i[d],j[d]||k)}"
        "window.q=window.q||[];q.push(['x',1,'y',2,'z',3]);"
    )
    * 8,
    "indented_code": (
        "    def compute(self, values: list[float]) -> dict[str, float]:\n"
        "        totals = {name: 0.0 for name in self._names}\n"
        "        for index, value in enumerate(values):\n"
        "            totals[self._names[index % 3]] += value * 1.5\n"
        "        return totals\n"
    )
    * 10,
    "prose_control": (
        "The indexing service partitions each slice of chunk text into "
        "bounded buckets before encoding, so activation memory stays "
        "within the planned budget on every forward pass. "
    )
    * 10,
}


class TestCalibrationBoundsUnderPlanning:
    """The chars-per-token estimate must not under-plan beyond its margin.

    The estimate is only a planning device - the learned token ceiling is
    the enforcement authority - but an estimator that under-plans real
    tokenisation too far turns every token-dense slice into an
    OOM-discard-replan cycle instead of a planned pass. This guard
    tokenises a fixed worst-case corpus with the real pinned dense
    tokenizer and bounds how far real token counts may exceed the
    production estimate. It never loads a model onto a device: the
    tokenizer is CPU-only text processing.
    """

    pytestmark: ClassVar = [pytest.mark.unit]

    #: Upper bound on real_tokens / estimated_tokens over the corpus.
    #: Derivation: one OOM re-clamp halves the planning budget, so two
    #: re-clamps absorb a 4x under-plan; 3.5 keeps headroom below that
    #: bound, so calibration or tokenizer drift is caught while the
    #: measured worst case (digit tables near 1 char/token, ~3x under a
    #: 3-chars/token divisor) still costs at most two discarded buckets.
    MAX_UNDER_PLAN_FACTOR = 3.5

    def test_estimator_under_plan_stays_within_the_stated_margin(self):
        from huggingface_hub import scan_cache_dir
        from transformers import PreTrainedTokenizerFast

        from ..config._settings import get_config
        from ._model_setup import ensure_model_snapshots, model_setup_timeout_seconds

        config = get_config()
        model_id = str(config.embedding_model)
        # Acquire the snapshot before loading it. A cache-only load on a host
        # that has never held the pinned model raises instead of running the
        # guard, and no lane guarantees a warm cache. Acquisition is a
        # killable child process under an explicit deadline; a warm cache
        # returns from it without spawning anything or touching the network,
        # and the load itself stays cache-only either way.
        ensure_model_snapshots(
            (model_id,),
            timeout_seconds=model_setup_timeout_seconds(),
        )
        snapshots = [
            revision.snapshot_path
            for repository in scan_cache_dir().repos
            if repository.repo_id == model_id
            for revision in repository.revisions
            if "main" in revision.refs
            and (revision.snapshot_path / "tokenizer.json").is_file()
        ]
        assert snapshots, f"no tokenizer snapshot resolved for {model_id}"
        tokenizer = PreTrainedTokenizerFast(
            tokenizer_file=str(snapshots[0] / "tokenizer.json")
        )
        divisor = int(config.embedding_encode_chars_per_token)
        offenders: dict[str, float] = {}
        for name, text in _CALIBRATION_CORPUS.items():
            # A single-item plan exposes the production estimator itself:
            # the bucket's footprint is exactly the per-text estimate.
            [bucket] = plan_encode_buckets(
                [text],
                token_budget=10**9,
                chars_per_token=divisor,
                max_items=1,
            )
            real_tokens = _token_count(tokenizer, text)
            factor = real_tokens / bucket.estimated_tokens
            if factor > self.MAX_UNDER_PLAN_FACTOR:
                offenders[name] = round(factor, 3)
        # Loosening the production divisor (raising
        # ``embedding_encode_chars_per_token``) or shrinking the margin
        # makes this fail here, naming each corpus text whose real
        # tokenisation exceeds its planned estimate by more than the
        # stated factor.
        assert not offenders, (
            f"chars-per-token calibration under-plans real tokenisation "
            f"beyond the {self.MAX_UNDER_PLAN_FACTOR}x margin for: {offenders}"
        )
