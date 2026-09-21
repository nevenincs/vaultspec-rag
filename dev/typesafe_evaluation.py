"""Live hosted ranking evaluation over full functions from this checkout.

Run explicitly with VAULTSPEC_RAG_TYPESAFE_API_KEY in the process environment.
Candidate scores are fixed retrieval fixtures, not a measured GPU baseline.
Every query and candidate judgment comes from the real hosted endpoint.
"""

from __future__ import annotations

import ast
import json
import os
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from vaultspec_rag.config._types import EnvVar
from vaultspec_rag.search._models import SearchResult
from vaultspec_rag.search._typesafe_policy import prepare_query

ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Candidate:
    id: str
    path: str
    function: str

    def result(self, rank: int) -> SearchResult:
        content = (ROOT / self.path).read_text(encoding="utf-8")
        node = next(
            node
            for node in ast.walk(ast.parse(content))
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == self.function
        )
        full = ast.get_source_segment(content, node)
        if full is None:
            raise RuntimeError(f"function content unavailable: {self.id}")
        return SearchResult(
            id=self.id,
            path=self.path,
            title=self.function,
            score=0.9 - rank * 0.05,
            snippet=full[:200],
            source="codebase",
            rerank_text=full,
            function_name=self.function,
            language="python",
            line_start=node.lineno,
            line_end=node.end_lineno,
        )


CANDIDATES = (
    Candidate(
        "locator", "src/vaultspec_rag/search/_result_shaping.py", "format_locator"
    ),
    Candidate(
        "glob", "src/vaultspec_rag/search/_result_shaping.py", "expand_path_pattern"
    ),
    Candidate("noise", "src/vaultspec_rag/search/_noise.py", "resolve_noise_policy"),
    Candidate(
        "group",
        "src/vaultspec_rag/search/_result_shaping.py",
        "group_chunks_by_document",
    ),
    Candidate("fusion", "src/vaultspec_rag/_store_search.py", "_execute_hybrid_query"),
    Candidate("feedback", "src/vaultspec_rag/_store_search.py", "_build_dense_query"),
    Candidate(
        "domain_filter", "src/vaultspec_rag/search/_noise.py", "partition_hard_domains"
    ),
    Candidate(
        "merge",
        "src/vaultspec_rag/search/_result_shaping.py",
        "select_combined_results",
    ),
    Candidate(
        "status", "src/vaultspec_rag/search/_intent_rank.py", "apply_status_filter"
    ),
    Candidate(
        "env_test",
        "src/vaultspec_rag/tests/test_env_example_coverage.py",
        "test_env_example_documents_every_env_var",
    ),
)


@dataclass(frozen=True)
class Case:
    name: str
    query: str
    relevant: tuple[str, ...]


CASES = (
    Case(
        "hybrid_fusion",
        "Find the implementation that fuses dense and sparse search with "
        "reciprocal rank fusion and falls back to dense-only on failure.",
        ("fusion",),
    ),
    Case(
        "domain_policy",
        "How does a request hide code noise domains or re-admit a hidden domain "
        "through include_domains?",
        ("noise", "domain_filter"),
    ),
    Case(
        "chunk_grouping",
        "Find code that collapses multiple vault chunks into one document "
        "result, keeping the best-scoring chunk.",
        ("group",),
    ),
    Case(
        "combined_sort",
        "Where are vault, codebase and document hits merged and sorted using "
        "score, source, path and ID tie breaks?",
        ("merge",),
    ),
    Case(
        "test_intent",
        "Find the test asserting that .env.example documents every supported "
        "environment variable.",
        ("env_test",),
    ),
    Case(
        "feedback_ids",
        "How do positive and negative document IDs steer the dense "
        "recommendation query?",
        ("feedback",),
    ),
    Case(
        "status_and_noise",
        "Cross-reference how explicit status filters remove inactive ADRs "
        "and how code domain filters remove hidden test results.",
        ("status", "domain_filter"),
    ),
    Case(
        "unrelated",
        "Find production code implementing AES-GCM encryption of uploaded "
        "customer invoices.",
        (),
    ),
    Case(
        "grouping_and_order",
        "Find both the logic selecting the best chunk for a vault document and "
        "the cross-source final ordering using score, source, path and ID. "
        "Explain whether locator formatting itself determines ranking ties.",
        ("group", "merge", "locator"),
    ),
    Case(
        "false_sorting_premise",
        "Locator formatting sorts results by score. Find the actual sorting code "
        "and verify this claim against the formatter implementation.",
        ("locator", "merge"),
    ),
)


def run_case(case: Case) -> dict[str, object]:
    results = [candidate.result(rank) for rank, candidate in enumerate(CANDIDATES)]
    started = time.monotonic()
    session = prepare_query(case.query, "code", {})
    if session is None:
        raise RuntimeError("live query classification unavailable; no mocked fallback")
    ranked = session.rank(results)
    ids = [result.id for result in ranked]
    positions = {
        key: ids.index(key) + 1 if key in ids else None for key in case.relevant
    }
    # Labels are selected by the fixture author before the provider is called.
    passed = (
        all(position is not None and position <= 3 for position in positions.values())
        if case.relevant
        else not ranked
    )
    return {
        **asdict(case),
        "passed": passed,
        "expected_positions": positions,
        "baseline_ids": [result.id for result in results],
        "ranked": [{"id": result.id, "score": result.score} for result in ranked],
        "dropped": [result.id for result in results if result.id not in ids],
        "query_assessment": session.context.get("query_assessment"),
        "timings": session.timings,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def main() -> int:
    if not os.environ.get(EnvVar.TYPESAFE_API_KEY, "").strip():
        raise RuntimeError("set the dedicated TypeSafe key for this live evaluation")
    reports: list[dict[str, object]] = []
    for case in CASES:
        report = run_case(case)
        reports.append(report)
        print(json.dumps(report), flush=True)
    passed = sum(report["passed"] is True for report in reports)
    print(json.dumps({"cases": len(reports), "passed": passed}), flush=True)
    return 0 if passed == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
