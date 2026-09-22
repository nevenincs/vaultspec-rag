"""Explicit live query-routing experiment; never alters production search policy."""

from __future__ import annotations

import json
import time
from dataclasses import asdict

from vaultspec_rag.search._typesafe_answers import ChoiceAnswer, NoulAnswer
from vaultspec_rag.search._typesafe_transport import available, evaluate

CASES = (
    (
        "production",
        "Find production code that retries failed webhook delivery.",
        "prod",
    ),
    (
        "tests",
        "Find the test asserting that .env.example documents every supported "
        "environment variable.",
        "tests",
    ),
    (
        "mixed",
        "Find production retry code and the tests proving its backoff behavior.",
        "mixed",
    ),
    (
        "decisions",
        "Find the architecture decision explaining why search filters "
        "run before fusion.",
        "docs",
    ),
    (
        "crossref",
        "Cross-reference the architecture decision with production code and "
        "tests for domain filtering.",
        "mixed",
    ),
    ("ambiguous", "retry behavior", "unknown"),
    ("identifier", "_execute_hybrid_query", "unknown"),
    ("negative", "Find retry implementation, not tests or documentation.", "prod"),
)

DOMAINS = {
    "prod": (
        "The user requests implementation or production application code, "
        "not tests or documentation."
    ),
    "tests": (
        "The user requests test code, assertions, fixtures or test coverage, "
        "not production implementation."
    ),
    "docs": (
        "The user requests written documentation, architecture decisions or "
        "design rationale, not implementation."
    ),
    "mixed": (
        "The user explicitly requests evidence from two or more of production "
        "implementation, tests and documentation."
    ),
    "unknown": (
        "The user does not specify an evidence domain; do not assume production "
        "merely from a technical topic or symbol."
    ),
}

ATOMIC = {
    "prod": (
        "Does the user request implementation or production code? "
        "Excluded evidence does not count as requested."
    ),
    "tests": (
        "Does the user request tests, assertions or test coverage? "
        "Excluded evidence does not count as requested."
    ),
    "docs": (
        "Does the user request documentation, an architecture decision or "
        "written design rationale? Excluded evidence does not count as requested."
    ),
}

SOURCE_NAMES = {
    "prod": "production implementation",
    "tests": "test code",
    "docs": "documentation or architecture decisions",
}

CHILDREN = {
    "prod": {
        "snippet": "A function, symbol or concrete implementation",
        "behavior": "An explanation of runtime behavior",
        "unknown": "Neither is clear",
    },
    "tests": {
        "assertion": "A test verifying a specified claim",
        "coverage": "The extent or absence of testing",
        "unknown": "Neither is clear",
    },
    "docs": {
        "decision": "An architecture decision or design rationale",
        "guide": "Instructions or reference documentation",
        "unknown": "Neither is clear",
    },
}


def main() -> None:
    if not available():
        raise RuntimeError("A live dedicated API credential is required")
    totals = {"calls": 0, "questions": 0, "input_tokens": 0, "output_tokens": 0}
    for name, query, expected in CASES:
        started = time.monotonic()
        questions: dict[str, dict[str, object]] = {
            "labels": {
                "type": "choice",
                "instructions": "Which domain does the query emphasize?",
                "criteria": {label: label for label in DOMAINS},
            },
            "descriptions": {
                "type": "choice",
                "instructions": (
                    "Which evidence domain does state.query request? "
                    "Read exclusions literally."
                ),
                "criteria": DOMAINS,
            },
            **{
                f"requests_{domain}": {
                    "type": "noul",
                    "instructions": f"Read state.query. {instruction}",
                }
                for domain, instruction in ATOMIC.items()
            },
        }
        first = evaluate({"query": query}, questions)
        totals["calls"] += 1
        totals["questions"] += len(questions)
        totals["input_tokens"] += first.input_tokens
        totals["output_tokens"] += first.output_tokens
        selected = [
            domain
            for domain in ATOMIC
            if isinstance(answer := first.answers[f"requests_{domain}"], NoulAnswer)
            and answer.noul >= 0.8
        ]
        derived = (
            "mixed" if len(selected) > 1 else selected[0] if selected else "unknown"
        )
        choice = first.answers["descriptions"]
        membership: dict[str, object] = {}
        if isinstance(choice, ChoiceAnswer) and choice.confidence >= 0.85:
            if choice.choice == "mixed":
                membership_questions: dict[str, dict[str, object]] = {
                    domain: {
                        "type": "choice",
                        "instructions": (
                            f"How does state.query treat {SOURCE_NAMES[domain]}? "
                            "Classify this source alone, not the entire query."
                        ),
                        "criteria": {
                            "requested": (
                                "The query asks to include this evidence source"
                            ),
                            "excluded": "The query asks to omit this evidence source",
                            "unmentioned": (
                                "The query neither requests nor excludes "
                                "this evidence source"
                            ),
                        },
                    }
                    for domain in ATOMIC
                }
                members = evaluate(
                    {"query": query, "parent_assessment": asdict(choice)},
                    membership_questions,
                )
                totals["calls"] += 1
                totals["questions"] += len(membership_questions)
                totals["input_tokens"] += members.input_tokens
                totals["output_tokens"] += members.output_tokens
                membership = {
                    key: asdict(answer) for key, answer in members.answers.items()
                }
                selected = [
                    key
                    for key, answer in members.answers.items()
                    if isinstance(answer, ChoiceAnswer)
                    and answer.choice == "requested"
                    and answer.confidence >= 0.85
                ]
            else:
                selected = [choice.choice] if choice.choice in CHILDREN else []
        nested: dict[str, object] = {}
        if selected:
            followups: dict[str, dict[str, object]] = {
                domain: {
                    "type": "choice",
                    "instructions": (
                        f"For the requested {domain} evidence in state.query, "
                        "what specific form is sought? Earlier probabilities "
                        "are advisory, not ground truth."
                    ),
                    "criteria": CHILDREN[domain],
                }
                for domain in selected
            }
            second = evaluate(
                {
                    "query": query,
                    "earlier_domain_probabilities": {
                        domain: asdict(first.answers[f"requests_{domain}"])
                        for domain in ATOMIC
                    },
                },
                followups,
            )
            totals["calls"] += 1
            totals["questions"] += len(followups)
            totals["input_tokens"] += second.input_tokens
            totals["output_tokens"] += second.output_tokens
            nested = {key: asdict(answer) for key, answer in second.answers.items()}
        print(
            json.dumps(
                {
                    "case": name,
                    "query": query,
                    "expected": expected,
                    "answers": {
                        key: asdict(answer) for key, answer in first.answers.items()
                    },
                    "atomic_domain": derived,
                    "atomic_pass": derived == expected,
                    "chained_membership": membership,
                    "chained_sources": selected,
                    "descriptive_choice_pass": isinstance(choice, ChoiceAnswer)
                    and choice.choice == expected,
                    "conditional_children": nested,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                }
            ),
            flush=True,
        )
    print(json.dumps({"summary": totals}), flush=True)


if __name__ == "__main__":
    main()
