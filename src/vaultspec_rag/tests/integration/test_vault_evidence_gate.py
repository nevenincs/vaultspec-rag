"""Evidence gate: does a vault hit show, and locate, the passage that answers?

Ranking gates ask whether the right record leads. This gate asks what the
caller then holds: whether the snippet of the best-ranked gold record carries
the labelled evidence span, and whether a reported line span points at exactly
the text the snippet shows. The cases (``tests/quality/evidence_queries.toml``)
were written from the frozen reference vault without viewing search output, so
the labels are independent of the ranker they score.

The searches run in the shared frozen-corpus experiment (see
``_frozen_corpus_evidence``). Floors live in ``tests/quality/evidence_baseline.json``
beside the measurements they were taken from; a floor only ever rises.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict

import pytest

from ..quality.metrics import contains_evidence, rank_of_first_grade
from ._frozen_corpus_evidence import load_evidence_cases

if TYPE_CHECKING:
    from collections.abc import Callable

    from ._frozen_corpus_evidence import (
        EvidenceCase,
        EvidenceObservation,
        FrozenCorpusEvidence,
    )

pytestmark = [pytest.mark.integration, pytest.mark.quality]

_BASELINE = Path(__file__).resolve().parents[1] / "quality" / "evidence_baseline.json"


class EvidenceSummary(TypedDict):
    """Per-set rates; each is a fraction of the labelled cases."""

    cases: int
    hit_at_1: float
    mrr: float
    evidence_in_snippet: float
    hits_with_span: int


def _case_outcome(
    case: EvidenceCase, observation: EvidenceObservation
) -> tuple[int | None, bool]:
    """Return the best gold rank and whether that hit's snippet holds its evidence."""
    ranked = [hit["doc_id"] for hit in observation["hits"]]
    rank = rank_of_first_grade(
        ranked, {gold["doc_id"]: 1 for gold in case["gold"]}, min_grade=1
    )
    if rank is None:
        return None, False
    hit = observation["hits"][rank - 1]
    shows = any(
        contains_evidence(hit["snippet"], gold["evidence"])
        for gold in case["gold"]
        if gold["doc_id"] == hit["doc_id"]
    )
    return rank, shows


def _summarize(evidence: FrozenCorpusEvidence) -> EvidenceSummary:
    observations = {obs["case_id"]: obs for obs in evidence["evidence"]}
    cases = load_evidence_cases()
    outcomes = [_case_outcome(case, observations[case["id"]]) for case in cases]
    count = len(cases)
    return EvidenceSummary(
        cases=count,
        hit_at_1=sum(rank == 1 for rank, _ in outcomes) / count,
        mrr=sum(1 / rank for rank, _ in outcomes if rank) / count,
        evidence_in_snippet=sum(shows for _, shows in outcomes) / count,
        hits_with_span=sum(
            hit["span_text"] is not None
            for obs in evidence["evidence"]
            for hit in obs["hits"]
        ),
    )


def _floors() -> dict[str, float]:
    data = json.loads(_BASELINE.read_text(encoding="utf-8"))
    return {str(key): float(value) for key, value in data["floors"].items()}


class TestVaultEvidenceGate:
    """What a caller holds after a vault search, scored against blind labels."""

    def test_every_case_is_observed(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
    ) -> None:
        """Every labelled case ran and returned a result page."""
        cases = {case["id"] for case in load_evidence_cases()}
        observed = {obs["case_id"] for obs in frozen_corpus_evidence["evidence"]}
        assert cases, "the evidence case set must not be empty"
        assert observed == cases
        empty = [
            obs["case_id"]
            for obs in frozen_corpus_evidence["evidence"]
            if not obs["hits"]
        ]
        assert not empty, f"evidence cases returned no hits: {empty}"

    @pytest.mark.parametrize("metric", ["hit_at_1", "mrr", "evidence_in_snippet"])
    def test_metric_meets_floor(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
        record_property: Callable[[str, object], None],
        metric: str,
    ) -> None:
        """Each rate stays at or above the floor recorded for it."""
        summary = _summarize(frozen_corpus_evidence)
        record_property("evidence_summary", json.dumps(summary))
        rates = {
            "hit_at_1": summary["hit_at_1"],
            "mrr": summary["mrr"],
            "evidence_in_snippet": summary["evidence_in_snippet"],
        }
        floor = _floors()[metric]
        value = rates[metric]
        assert value >= floor, f"{metric} {value:.4f} fell below its floor {floor}"

    def test_reported_span_holds_exactly_the_snippet(
        self,
        frozen_corpus_evidence: FrozenCorpusEvidence,
    ) -> None:
        """A hit's line span covers its snippet verbatim and nothing wider."""
        offenders: list[str] = []
        for obs in frozen_corpus_evidence["evidence"]:
            for hit in obs["hits"]:
                span = hit["span_text"]
                if span is None:
                    continue
                snippet = hit["snippet"].strip("\n")
                # The line-count comparison is what rejects a span shifted or
                # widened by a line: containment alone passes either.
                if snippet not in span or span.count("\n") != snippet.count("\n"):
                    offenders.append(
                        f"{obs['case_id']} {hit['doc_id']} "
                        f"L{hit['line_start']}-{hit['line_end']}"
                    )
        assert not offenders, f"spans that do not hold their snippet: {offenders}"
