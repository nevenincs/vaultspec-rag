"""Compare live atomic judgments with answer-dependent classification chains.

Run with the dedicated credential already in the process environment. No fabricated
answers: both experimental rankers call the transport without invoking ranking policy.
``--describe`` inspects fixtures without reading credentials or calling the provider.
Facet decomposition selects from a declared vocabulary; it is not generated prose.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from typesafe_evaluation import CANDIDATES

from vaultspec_rag.search._typesafe_answers import (
    ChoiceAnswer,
    Evaluation,
    NoulAnswer,
    ScoreAnswer,
)
from vaultspec_rag.search._typesafe_transport import TypesafeUnavailableError, evaluate

if TYPE_CHECKING:
    from collections.abc import Callable


FACETS = {
    "status": "selecting ADRs by lifecycle status",
    "noise": "configuring code noise hiding and include-domain re-admission",
    "domain_filter": "removing code candidates in hidden or nonselected domains",
    "feedback": "using positive and negative IDs for dense recommendations",
    "fusion": "combining dense and sparse ranks and handling hybrid failure",
    "group": "collapsing document chunks while retaining the highest score",
    "merge": "combining source result lists with deterministic score tie breaks",
    "locator": "formatting source locations for display",
    "glob": "expanding path patterns to recursive globs",
    "env_test": "testing completeness of documented environment variables",
}


@dataclass(frozen=True)
class Case:
    name: str
    query: str
    relevant: tuple[str, ...]


CASES = (
    Case(
        "filter_crossreference",
        "Cross-reference how explicit status filters remove inactive ADRs and how "
        "code domain filters remove hidden test results.",
        ("status", "domain_filter"),
    ),
    Case(
        "feedback_and_fallback",
        "Trace positive and negative document ID feedback into dense recommendation, "
        "then identify where dense and sparse rankings are fused and what happens "
        "if the hybrid query fails. Does fallback preserve a dense search path?",
        ("feedback", "fusion"),
    ),
    Case(
        "grouping_and_order",
        "Find both the logic selecting the best chunk for a vault document and "
        "the cross-source final ordering using score, source, path and ID. "
        "Explain whether locator formatting itself determines ranking ties.",
        ("group", "merge", "locator"),
    ),
    Case(
        "unrelated",
        "Find production code implementing AES-GCM encryption of uploaded "
        "customer invoices.",
        (),
    ),
    Case(
        "test_intent",
        "Find the test asserting that .env.example documents every supported "
        "environment variable.",
        ("env_test",),
    ),
)


def _noul(instructions: str) -> dict[str, object]:
    return {"type": "noul", "instructions": instructions}


def _score(instructions: str) -> dict[str, object]:
    return {
        "type": "score",
        "instructions": instructions,
        "criteria": ["unrelated", "related supporting context", "direct evidence"],
    }


def _probability(answer: ChoiceAnswer | ScoreAnswer | NoulAnswer) -> float:
    if not isinstance(answer, NoulAnswer):
        raise TypeError("expected_noul")
    return answer.noul


def _usefulness(answer: ChoiceAnswer | ScoreAnswer | NoulAnswer) -> ScoreAnswer:
    if not isinstance(answer, ScoreAnswer):
        raise TypeError("expected_score")
    return answer


@dataclass
class Meter:
    calls: int = 0
    questions: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    elapsed_seconds: float = 0.0

    def ask(
        self, state: dict[str, object], questions: dict[str, dict[str, object]]
    ) -> Evaluation:
        started = time.monotonic()
        self.calls += 1
        self.questions += len(questions)
        try:
            # The transport still applies its own bounded per-request timeout.
            answer = evaluate(state, questions, deadline=started + 30)
        finally:
            self.elapsed_seconds += time.monotonic() - started
        self.input_tokens += answer.input_tokens
        self.output_tokens += answer.output_tokens
        return answer

    def report(self) -> dict[str, object]:
        return {
            "calls": self.calls,
            "questions": self.questions,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


@dataclass
class Judgment:
    relevance: float
    evidence: float
    confidence: float
    unrelated_probability: float
    contradiction: float
    domain: str = "unknown"
    facets: dict[str, float] = field(default_factory=dict)
    evidence_probabilities: dict[str, float] = field(default_factory=dict)
    domain_confidence: float | None = None
    domain_probabilities: dict[str, float] = field(default_factory=dict)

    @property
    def score(self) -> float:
        return 0.8 * self.evidence / 2 + 0.2 * self.relevance

    @property
    def dropped(self) -> bool:
        return (
            self.relevance <= 0.05
            and self.confidence >= 0.9
            and self.unrelated_probability >= 0.9
            and self.contradiction < 0.2
        )

    def report(self) -> dict[str, object]:
        return {
            "score": round(self.score, 4),
            "relevance": self.relevance,
            "evidence": self.evidence,
            "evidence_probabilities": self.evidence_probabilities,
            "confidence": self.confidence,
            "contradiction": self.contradiction,
            "domain": self.domain,
            "domain_confidence": self.domain_confidence,
            "domain_probabilities": self.domain_probabilities,
            "facets": self.facets,
            "dropped": self.dropped,
        }


def _batches() -> list[dict[str, object]]:
    candidates: list[tuple[str, dict[str, object]]] = []
    for rank, candidate in enumerate(CANDIDATES):
        result = candidate.result(rank)
        if not result.rerank_text:
            raise RuntimeError("missing_full_content")
        candidates.append((candidate.id, {"content": result.rerank_text}))
    return [
        dict(candidates[start : start + 2]) for start in range(0, len(candidates), 2)
    ]


def independent(case: Case, meter: Meter) -> dict[str, Judgment]:
    judgments: dict[str, Judgment] = {}
    for batch in _batches():
        questions: dict[str, dict[str, object]] = {}
        for key in batch:
            target = f"Inspect state.candidates.{key}.content as evidence. "
            questions[key + ":relevance"] = _noul(
                target + "Is this relevant to any part of state.query?"
            )
            questions[key + ":evidence"] = _score(
                target
                + "How directly does this answer any requested part of state.query?"
            )
            questions[key + ":contradiction"] = _noul(
                target
                + "Does this provide evidence contradicting a premise in state.query?"
            )
            questions[key + ":domain"] = {
                "type": "choice",
                "instructions": target + "What kind of evidence is this passage?",
                "criteria": {
                    "implementation": "production implementation code",
                    "test": "test or verification code",
                    "decision": "architecture rationale or decision prose",
                    "unknown": "cannot determine",
                },
            }
        answer = meter.ask({"query": case.query, "candidates": batch}, questions)
        for key in batch:
            useful = _usefulness(answer.answers[key + ":evidence"])
            domain = answer.answers[key + ":domain"]
            if not isinstance(domain, ChoiceAnswer):
                raise TypeError("expected_choice")
            judgments[key] = Judgment(
                _probability(answer.answers[key + ":relevance"]),
                useful.score,
                useful.confidence,
                useful.probabilities["0"],
                _probability(answer.answers[key + ":contradiction"]),
                domain.choice,
                evidence_probabilities=useful.probabilities,
                domain_confidence=domain.confidence,
                domain_probabilities=domain.probabilities,
            )
    return judgments


def chained(case: Case, meter: Meter) -> dict[str, Judgment]:
    decomposition = meter.ask(
        {"query": case.query},
        {
            key: _noul("Does the query request evidence about " + meaning + "?")
            for key, meaning in FACETS.items()
        },
    )
    probabilities = {key: _probability(decomposition.answers[key]) for key in FACETS}
    selected = [key for key in FACETS if probabilities[key] >= 0.5]
    # An uncertain decomposition still runs honestly; report the selected fallback.
    if not selected:
        selected = [max(probabilities, key=lambda key: probabilities[key])]
    print(
        json.dumps(
            {
                "case": case.name,
                "stage": "decomposition",
                "probabilities": probabilities,
                "selected": selected,
            }
        ),
        flush=True,
    )
    judgments: dict[str, Judgment] = {}
    for batch in _batches():
        questions: dict[str, dict[str, object]] = {}
        for key in batch:
            target = f"Inspect state.candidates.{key}.content as evidence. "
            for facet in selected:
                questions[key + ":" + facet] = _noul(
                    target + "Does this directly demonstrate " + FACETS[facet] + "?"
                )
            questions[key + ":contradiction"] = _noul(
                target + "Does this challenge a premise in state.query?"
            )
        state: dict[str, object] = {
            "query": case.query,
            "candidates": batch,
            "requested_facets": {key: FACETS[key] for key in selected},
        }
        passage = meter.ask(state, questions)
        intermediate: dict[str, dict[str, object]] = {}
        for key in batch:
            facets = {
                facet: _probability(passage.answers[key + ":" + facet])
                for facet in selected
            }
            intermediate[key] = {
                "facet_probabilities": facets,
                "contradiction": _probability(passage.answers[key + ":contradiction"]),
            }
        # Both follow-up selection and its submitted state depend on real answers.
        followups: dict[str, dict[str, object]] = {}
        for key in batch:
            facets = {
                facet: _probability(passage.answers[key + ":" + facet])
                for facet in selected
            }
            strongest = max(facets, key=lambda facet: facets[facet])
            branch = (
                "Check whether apparent weak matches nevertheless supply useful "
                "counterevidence or supporting context. "
                if max(facets.values()) < 0.5
                else "Check the strongest facet match against the complete passage. "
            )
            target = (
                f"Inspect state.candidates.{key}.content "
                f"and state.passage_judgments.{key}. "
                f"The strongest assessed facet was {FACETS[strongest]}. "
                + branch
                + "Earlier judgments are fallible evidence, not binding answers. "
            )
            followups[key + ":relevance"] = _noul(
                target + "Is this relevant to any requested part of state.query?"
            )
            followups[key + ":evidence"] = _score(
                target
                + "How directly does it answer any requested part of state.query?"
            )
        final = meter.ask({**state, "passage_judgments": intermediate}, followups)
        for key in batch:
            useful = _usefulness(final.answers[key + ":evidence"])
            judgments[key] = Judgment(
                _probability(final.answers[key + ":relevance"]),
                useful.score,
                useful.confidence,
                useful.probabilities["0"],
                _probability(passage.answers[key + ":contradiction"]),
                facets={
                    facet: _probability(passage.answers[key + ":" + facet])
                    for facet in selected
                },
                evidence_probabilities=useful.probabilities,
            )
    return judgments


def run_case(
    case: Case, name: str, method: Callable[[Case, Meter], dict[str, Judgment]]
) -> dict[str, object]:
    meter = Meter()
    try:
        judgments = method(case, meter)
    except TypesafeUnavailableError as exc:
        return {
            "case": case.name,
            "method": name,
            "passed": False,
            "failure": exc.reason,
            **meter.report(),
        }
    ranked = sorted(
        (key for key, judgment in judgments.items() if not judgment.dropped),
        key=lambda key: judgments[key].score,
        reverse=True,
    )
    positions = {
        key: ranked.index(key) + 1 if key in ranked else None for key in case.relevant
    }
    return {
        "case": case.name,
        "method": name,
        "expected": case.relevant,
        "baseline": [candidate.id for candidate in CANDIDATES],
        "ranked": ranked,
        "positions": positions,
        "recall_at_3": (
            sum(key in ranked[:3] for key in case.relevant) / len(case.relevant)
            if case.relevant
            else None
        ),
        "passed": all(
            position is not None and position <= 3 for position in positions.values()
        )
        if case.relevant
        else not ranked,
        "judgments": {key: judgment.report() for key, judgment in judgments.items()},
        **meter.report(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--case", choices=[case.name for case in CASES])
    parser.add_argument(
        "--method", choices=["independent", "chained", "both"], default="both"
    )
    args = parser.parse_args()
    cases = [case for case in CASES if not args.case or case.name == args.case]
    if args.describe:
        for case in cases:
            print(
                json.dumps(
                    {
                        "case": case.name,
                        "expected": case.relevant,
                        "candidates": [candidate.id for candidate in CANDIDATES],
                        "independent_calls": 5,
                        "chained_calls": 11,
                    }
                )
            )
        return 0
    reports: list[dict[str, object]] = []
    methods: dict[str, Callable[[Case, Meter], dict[str, Judgment]]] = {
        "independent": independent,
        "chained": chained,
    }
    for case in cases:
        for name, method in methods.items():
            if args.method not in {name, "both"}:
                continue
            report = run_case(case, name, method)
            reports.append(report)
            print(json.dumps(report), flush=True)
            if "failure" in report:
                return 2
    passed = sum(report["passed"] is True for report in reports)
    print(json.dumps({"runs": len(reports), "passed": passed}), flush=True)
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
