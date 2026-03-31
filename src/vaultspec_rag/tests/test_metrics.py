"""Unit tests for retrieval metric helpers."""

from __future__ import annotations

import pytest

from vaultspec_rag.tests.metrics import ndcg_at_k, precision_at_k, reciprocal_rank

pytestmark = [pytest.mark.unit]


class TestPrecisionAtK:
    def test_all_relevant(self):
        rel = {"a", "b", "c"}
        assert precision_at_k(rel, ["a", "b", "c"], k=3) == pytest.approx(1.0)

    def test_none_relevant(self):
        assert precision_at_k({"x"}, ["a", "b", "c"], k=3) == pytest.approx(0.0)

    def test_partial(self):
        assert precision_at_k({"a", "c"}, ["a", "b", "c"], k=3) == pytest.approx(2 / 3)

    def test_k_truncates(self):
        assert precision_at_k({"c"}, ["a", "b", "c"], k=2) == pytest.approx(0.0)

    def test_empty_retrieved(self):
        assert precision_at_k({"a"}, [], k=5) == pytest.approx(0.0)


class TestReciprocalRank:
    def test_first_position(self):
        assert reciprocal_rank({"a"}, ["a", "b", "c"]) == pytest.approx(1.0)

    def test_second_position(self):
        assert reciprocal_rank({"b"}, ["a", "b", "c"]) == pytest.approx(0.5)

    def test_not_found(self):
        assert reciprocal_rank({"x"}, ["a", "b", "c"]) == pytest.approx(0.0)

    def test_empty(self):
        assert reciprocal_rank({"a"}, []) == pytest.approx(0.0)


class TestNdcgAtK:
    def test_perfect_ranking(self):
        assert ndcg_at_k({"a", "b"}, ["a", "b", "c"], k=2) == pytest.approx(1.0)

    def test_no_relevant(self):
        assert ndcg_at_k({"x"}, ["a", "b", "c"], k=3) == pytest.approx(0.0)

    def test_empty_relevant(self):
        assert ndcg_at_k(set(), ["a", "b"], k=2) == pytest.approx(0.0)
