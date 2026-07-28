"""Intent-aware ranking harness: graded-relevance metrics over a real-vault copy.

Drives the labeled query set (``tests/quality/intent_queries.toml``) against a
real GPU index built from the frozen reference vault (see
``tests/quality/_frozen_corpus.py``) - the tree at the gold's calibration
commit, where a feature's adr, research, plan, and exec genuinely compete on
the same vocabulary and where the ranking failure lives. Freezing the corpus
keeps the gate measuring ranking quality rather than racing an ever-growing
vault. Each query's results are scored with the role-aware metrics
(``tests/quality/metrics.py``) using the rubric-derived gold grades, per intent.

The searches themselves run in the shared bounded worker (see
``_frozen_corpus_evidence``); this module holds the structural gate and the
acceptance thresholds. The strict per-intent thresholds and the named
orientation regression (the accepted ADR must outrank the exec record that
implements it) are asserted once the intent prior ships; asserting them here,
against the bare reranker, would fail by design, and the test mandate forbids
skips and xfails.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..quality.rubric import Intent
from ._frozen_corpus_evidence import real_vault_document_count

if TYPE_CHECKING:
    from ._frozen_corpus_evidence import FrozenCorpusEvidence, QueryEvidence

pytestmark = [pytest.mark.integration, pytest.mark.quality]


def _query_evidence(
    evidence: FrozenCorpusEvidence,
    text: str,
) -> QueryEvidence:
    """Return the evidence row for one labeled query."""
    for query in evidence["queries"]:
        if query["report"]["text"] == text:
            return query
    msg = f"intent-ranking evidence missing query {text!r}"
    raise AssertionError(msg)


# Acceptance thresholds. Orientation Authoritative@3 is capped below 1.0 by the
# one orientation query whose gold tops out at grade 2 (the superseded-ADR trap,
# which by construction has no grade-3 document), so the achievable ceiling on
# the shipped set is 5/6 ~ 0.83.
_ORIENTATION_AUTH3_FLOOR = 0.8
_REGRESSION_QUERY = "decision on gpu lock scope"
_REGRESSION_ADR = "adr/2026-06-12-service-concurrency-adr"
_REGRESSION_EXEC = (
    "exec/2026-06-12-service-concurrency/2026-06-12-service-concurrency-W03-P06-S15"
)


class TestIntentRankingHarness:
    """Structural gate plus the acceptance thresholds for the intent prior."""

    def test_harness_produces_wellformed_metrics(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
    ) -> None:
        """Every labeled query yields well-formed per-intent metrics."""
        reports = [query["report"] for query in frozen_corpus_evidence["queries"]]
        assert reports, "the labeled query set must not be empty"
        assert frozen_corpus_evidence["corpus_documents"] == real_vault_document_count()
        assert frozen_corpus_evidence["indexed_documents"] > 0
        for report in reports:
            ndcg = report["ndcg_at_k"]
            assert isinstance(ndcg, float)
            assert 0.0 <= ndcg <= 1.0, f"NDCG out of range for {report['text']!r}"
            assert report["intent"] in {i.value for i in Intent}
            if report["intent"] == Intent.ORIENTATION.value:
                assert "authoritative_at_3" in report
            else:
                assert "mrr_at_grade_3" in report

    def test_orientation_authoritative_rate_meets_floor(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
    ) -> None:
        """The accepted ADR reaches the top 3 for (nearly) every orientation query."""
        reports = [query["report"] for query in frozen_corpus_evidence["queries"]]
        orient = [r for r in reports if r["intent"] == Intent.ORIENTATION.value]
        rate = sum(bool(r["authoritative_at_3"]) for r in orient) / len(orient)
        assert rate >= _ORIENTATION_AUTH3_FLOOR, (
            f"orientation Authoritative@3 rate {rate:.3f} below "
            f"{_ORIENTATION_AUTH3_FLOOR}"
        )

    def test_index_documents_never_surface(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
    ) -> None:
        """Auto-generated feature-index documents must not appear in results."""
        query = _query_evidence(
            frozen_corpus_evidence,
            "qdrant server mode with provisioned binary verification",
        )
        assert query["ranked_ids"], "expected results for a feature-named query"
        offenders = [
            doc_id
            for doc_id, doc_type in zip(
                query["ranked_ids"],
                query["doc_types"],
                strict=True,
            )
            if doc_type == "index"
        ]
        assert not offenders, f"index documents leaked into results: {offenders}"

    def test_named_orientation_regression(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
    ) -> None:
        """The accepted ADR must outrank the exec record it governs (the live case)."""
        query = _query_evidence(
            frozen_corpus_evidence,
            _REGRESSION_QUERY,
        )
        ids = query["ranked_ids"]
        assert _REGRESSION_ADR in ids, f"accepted ADR missing from top 10: {ids}"
        if _REGRESSION_EXEC in ids:
            assert ids.index(_REGRESSION_ADR) < ids.index(_REGRESSION_EXEC), (
                "accepted ADR must outrank the exec record that implements it"
            )
