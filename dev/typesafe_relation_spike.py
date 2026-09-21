"""Live relation classification and answer-dependent refutation verification.

No production-policy changes, fabricated answers, or credential handling. Run with
the dedicated key already enrolled. --describe never calls the provider. Rankings
compare the same initial judgments before and after an additional refutation check.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass

from typesafe_chaining_spike import FACETS, Meter
from typesafe_evaluation import CANDIDATES

from vaultspec_rag.search._typesafe_answers import ChoiceAnswer, NoulAnswer
from vaultspec_rag.search._typesafe_transport import TypesafeUnavailableError


@dataclass(frozen=True)
class Case:
    name: str
    query: str
    relevant: tuple[str, ...]


CASES = (
    Case(
        "unrelated",
        "Find production code implementing AES-GCM encryption of uploaded "
        "customer invoices.",
        (),
    ),
    Case(
        "false_sorting_premise",
        "Locator formatting sorts results by score. Find the actual sorting code "
        "and verify this claim against the formatter implementation.",
        ("locator", "merge"),
    ),
    Case(
        "grouping_and_order",
        "Find both the logic selecting the best chunk for a vault document and "
        "the cross-source final ordering using score, source, path and ID. "
        "Explain whether locator formatting itself determines ranking ties.",
        ("group", "merge", "locator"),
    ),
    Case(
        "filter_crossreference",
        "Cross-reference how explicit status filters remove inactive ADRs and how "
        "code domain filters remove hidden test results.",
        ("status", "domain_filter"),
    ),
)

RELATIONS = {
    "supports": "Provides requested evidence or directly answers part of the question.",
    "refutes": (
        "Addresses the same actual subject and provides concrete evidence that a "
        "factual premise is false. Merely not implementing the requested feature "
        "does not refute it. Code on a different subject cannot refute the query."
    ),
    "unrelated": (
        "Concerns a different subject or supplies none of the requested evidence. "
        "Shared generic terms such as data or results do not establish relevance."
    ),
    "insufficient": (
        "Concerns the same subject, but lacks enough evidence to answer or refute "
        "the specific question. Reserve this for an actual topical connection."
    ),
}


def _choice(question: str, criteria: dict[str, str]) -> dict[str, object]:
    return {"type": "choice", "instructions": question, "criteria": criteria}


def _noul(question: str) -> dict[str, object]:
    return {"type": "noul", "instructions": question}


def _choice_answer(value: object) -> ChoiceAnswer:
    if not isinstance(value, ChoiceAnswer):
        raise TypeError("expected_choice")
    return value


def _probability(value: object) -> float:
    if not isinstance(value, NoulAnswer):
        raise TypeError("expected_noul")
    return value.noul


def _content() -> dict[str, object]:
    candidates: dict[str, object] = {}
    for rank, candidate in enumerate(CANDIDATES):
        result = candidate.result(rank)
        if not result.rerank_text:
            raise RuntimeError("missing_full_content")
        candidates[candidate.id] = {"content": result.rerank_text}
    return candidates


@dataclass
class Relation:
    answer: ChoiceAnswer
    vague_contradiction: float
    same_subject: float | None = None
    contrary_evidence: float | None = None
    absence_only: float | None = None

    @property
    def initial_score(self) -> float:
        return (
            self.answer.probabilities["supports"] + self.answer.probabilities["refutes"]
        )

    @property
    def verified_refutation(self) -> bool:
        return (
            self.same_subject is not None
            and self.same_subject >= 0.7
            and self.contrary_evidence is not None
            and self.contrary_evidence >= 0.7
            and self.absence_only is not None
            and self.absence_only <= 0.3
        )

    @property
    def checked_score(self) -> float:
        if self.answer.choice != "refutes" or self.verified_refutation:
            return self.initial_score
        return self.answer.probabilities["supports"]

    def report(self) -> dict[str, object]:
        return {
            "class": self.answer.choice,
            "confidence": self.answer.confidence,
            "probabilities": self.answer.probabilities,
            "vague_contradiction": self.vague_contradiction,
            "initial_score": self.initial_score,
            "checked_score": self.checked_score,
            "same_subject": self.same_subject,
            "contrary_evidence": self.contrary_evidence,
            "absence_only": self.absence_only,
            "verified_refutation": self.verified_refutation,
        }


def initial_relations(case: Case, meter: Meter) -> dict[str, Relation]:
    content = _content()
    keys = list(content)
    relations: dict[str, Relation] = {}
    for start in range(0, len(keys), 2):
        batch = {key: content[key] for key in keys[start : start + 2]}
        questions: dict[str, dict[str, object]] = {}
        for key in batch:
            target = f"Evaluate state.candidates.{key}.content against state.query. "
            questions[key + ":relation"] = _choice(
                target + "How does this passage relate to the requested evidence?",
                RELATIONS,
            )
            questions[key + ":old_contradiction"] = _noul(
                target
                + "Does this provide evidence contradicting a premise in the query?"
            )
        answer = meter.ask({"query": case.query, "candidates": batch}, questions)
        for key in batch:
            relations[key] = Relation(
                _choice_answer(answer.answers[key + ":relation"]),
                _probability(answer.answers[key + ":old_contradiction"]),
            )
    return relations


def verify_refutations(
    case: Case, relations: dict[str, Relation], meter: Meter
) -> None:
    content = _content()
    proposed = [
        key
        for key, relation in relations.items()
        if relation.answer.choice == "refutes"
    ]
    for start in range(0, len(proposed), 2):
        keys = proposed[start : start + 2]
        questions: dict[str, dict[str, object]] = {}
        for key in keys:
            target = (
                f"Recheck state.candidates.{key}.content against state.query. "
                "An earlier answer proposed refutation; independently verify it. "
            )
            questions[key + ":subject"] = _noul(
                target
                + "Does this address the same actual subject as the factual premise?"
            )
            questions[key + ":contrary"] = _noul(
                target
                + "Does this contain concrete evidence disproving the factual premise?"
            )
            questions[key + ":absence"] = _noul(
                target
                + "Is the proposed refutation based only on absence of the requested "
                "implementation from code doing a different job?"
            )
        answer = meter.ask(
            {
                "query": case.query,
                "candidates": {key: content[key] for key in keys},
                "proposed_relations": {
                    key: relations[key].answer.probabilities for key in keys
                },
            },
            questions,
        )
        for key in keys:
            relations[key].same_subject = _probability(answer.answers[key + ":subject"])
            relations[key].contrary_evidence = _probability(
                answer.answers[key + ":contrary"]
            )
            relations[key].absence_only = _probability(answer.answers[key + ":absence"])


def facet_membership(case: Case, meter: Meter) -> dict[str, object]:
    decisions: dict[str, object] = {}
    choice_selected: list[str] = []
    noul_selected: list[str] = []
    facets = list(FACETS)
    for start in range(0, len(facets), 2):
        questions: dict[str, dict[str, object]] = {}
        for key in facets[start : start + 2]:
            question = "Does the query request evidence about " + FACETS[key] + "?"
            questions[key + ":noul"] = _noul(question)
            questions[key + ":choice"] = _choice(
                question,
                {
                    "requested": "Explicitly asks about this topic, "
                    "even as one part of a compound question.",
                    "unmentioned": "Does not ask about this topic; "
                    "unrelated or merely incidental.",
                },
            )
        answer = meter.ask({"query": case.query}, questions)
        for key in facets[start : start + 2]:
            choice = _choice_answer(answer.answers[key + ":choice"])
            noul = _probability(answer.answers[key + ":noul"])
            decisions[key] = {
                "class": choice.choice,
                "confidence": choice.confidence,
                "probabilities": choice.probabilities,
                "noul": noul,
            }
            if choice.choice == "requested":
                choice_selected.append(key)
            if noul >= 0.5:
                noul_selected.append(key)
    return {
        "method": "facet_membership",
        "case": case.name,
        "decisions": decisions,
        "choice_selected": choice_selected,
        "noul_selected": noul_selected,
        "forced_facet": False,
        **meter.report(),
    }


def _ranking(case: Case, scores: dict[str, float]) -> dict[str, object]:
    ranked = sorted(scores, key=lambda key: scores[key], reverse=True)
    retained = [key for key in ranked if scores[key] >= 0.5]
    positions = {
        key: retained.index(key) + 1 if key in retained else None
        for key in case.relevant
    }
    passed = (
        all(position is not None and position <= 3 for position in positions.values())
        if case.relevant
        else not retained
    )
    return {
        "ranked_all": ranked,
        "retained": retained,
        "positions": positions,
        "passed": passed,
    }


def run_case(case: Case) -> dict[str, object]:
    initial_meter = Meter()
    checked_meter = Meter()
    relations = initial_relations(case, initial_meter)
    verify_refutations(case, relations, checked_meter)
    initial_ranking = _ranking(
        case, {key: relation.initial_score for key, relation in relations.items()}
    )
    checked_ranking = _ranking(
        case, {key: relation.checked_score for key, relation in relations.items()}
    )
    return {
        "case": case.name,
        "expected": case.relevant,
        "passed": checked_ranking["passed"],
        "decisions": {key: relation.report() for key, relation in relations.items()},
        "independent_relation": {
            **initial_ranking,
            **initial_meter.report(),
        },
        "checked_relation": {
            **checked_ranking,
            "additional_cost": checked_meter.report(),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--describe", action="store_true")
    parser.add_argument("--case", choices=[case.name for case in CASES])
    parser.add_argument("--facets-only", action="store_true")
    args = parser.parse_args()
    cases = [case for case in CASES if not args.case or case.name == args.case]
    if args.describe:
        print(
            json.dumps(
                {
                    "cases": [
                        {"case": case.name, "expected": case.relevant} for case in cases
                    ],
                    "candidates": len(CANDIDATES),
                    "maximum_calls": 50,
                    "retention_threshold": 0.5,
                    "refutation_subject_threshold": 0.7,
                    "refutation_evidence_threshold": 0.7,
                    "absence_threshold": 0.3,
                }
            )
        )
        return 0
    reports: list[dict[str, object]] = []
    try:
        for case in cases:
            if not args.facets_only:
                report = run_case(case)
                reports.append(report)
                print(json.dumps(report), flush=True)
            if args.facets_only or case.name in {"grouping_and_order", "unrelated"}:
                print(json.dumps(facet_membership(case, Meter())), flush=True)
    except TypesafeUnavailableError as exc:
        print(json.dumps({"provider_failure": exc.reason}), flush=True)
        return 2
    passed = sum(report["passed"] is True for report in reports)
    print(
        json.dumps({"relation_cases": len(reports), "checked_passed": passed}),
        flush=True,
    )
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
