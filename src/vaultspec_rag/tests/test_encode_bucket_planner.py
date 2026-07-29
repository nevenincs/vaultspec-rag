"""Unit tests for token-budget encode bucket planning."""

from itertools import pairwise
from typing import ClassVar

import pytest

from ..embeddings import EncodeBucket, plan_encode_buckets


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
