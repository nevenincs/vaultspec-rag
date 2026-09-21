"""Live classifier through real search orchestration over synthetic retrieval.

Only encoding, storage and graph leaves are fixtures. No hosted answer is mocked.
Run explicitly with VAULTSPEC_RAG_TYPESAFE_API_KEY; no resident service is needed.
"""

from __future__ import annotations

import json
import os
from contextlib import ExitStack
from typing import TYPE_CHECKING
from unittest.mock import Mock, patch

from typesafe_evaluation import CANDIDATES, ROOT

from vaultspec_rag.config._types import EnvVar
from vaultspec_rag.search._parsing import parse_query
from vaultspec_rag.search._searcher import VaultSearcher

if TYPE_CHECKING:
    from vaultspec_rag._store_search import HybridSearchRequest
    from vaultspec_rag.search._models import ParsedQuery


def code_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for rank, candidate in enumerate(CANDIDATES):
        result = candidate.result(rank)
        rows.append(
            {
                "id": result.id,
                "path": result.path,
                "content": result.rerank_text,
                "function_name": result.function_name,
                "language": "python",
                "line_start": result.line_start,
                "line_end": result.line_end,
                "domain": "tests" if result.id == "env_test" else "prod",
                "_relevance_score": result.score,
            }
        )
    return rows


def encode(
    raw_query: str, **_kwargs: object
) -> tuple[ParsedQuery, str, list[float], None]:
    parsed = parse_query(raw_query)
    return parsed, parsed.text, [1.0, 0.0], None


def graph_order[T](results: list[T], *_args: object, **_kwargs: object) -> list[T]:
    return results


def main() -> int:
    if not os.environ.get(EnvVar.TYPESAFE_API_KEY, "").strip():
        raise RuntimeError("set the dedicated key; live classification is required")
    rows = code_rows()
    store = Mock()
    budgets: list[int] = []

    def fetch(request: HybridSearchRequest) -> list[dict[str, object]]:
        budgets.append(request.limit)
        return rows[: request.limit]

    document = {
        "id": "noise_guide",
        "path": "guides/noise.md",
        "source_path": "manuals/noise.txt",
        "title": "Code noise exclusions",
        "doc_type": "reference",
        "status": "accepted",
        "content": "Code noise filtering hides generated and worktree domains by "
        "default. Explicit exclude_domains removes named domains, only_domains "
        "retains named domains, and include_domains re-admits hidden domains. "
        "These filters apply before result ranking.",
        "_relevance_score": 0.1,
    }
    store.hybrid_search_codebase.side_effect = fetch
    store.hybrid_search.return_value = [document]
    store.hybrid_search_document.return_value = [document]
    searcher = VaultSearcher.__new__(VaultSearcher)
    searcher.root_dir = ROOT
    searcher.store = store
    cases = (
        (
            "test_lookup",
            "codebase",
            "Find the test asserting that .env.example "
            "documents every supported environment variable.",
        ),
        (
            "explicit_prod",
            "codebase",
            "Find the test asserting that .env.example "
            "documents every supported environment variable. only:prod",
        ),
        (
            "no_match",
            "codebase",
            "Find production code implementing AES-GCM "
            "encryption of uploaded customer invoices.",
        ),
        ("guide", "document", "Explain how code noise exclusions work."),
        (
            "cross_reference",
            "combined",
            "Cross-reference production code for "
            "excluding noise domains with documentation explaining those exclusions.",
        ),
    )
    passed = 0
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(searcher, "_reranker_enabled", False, create=True)
        )
        stack.enter_context(patch.object(searcher, "_encode_query", encode))
        stack.enter_context(patch.object(searcher, "_get_graph", return_value=None))
        stack.enter_context(
            patch("vaultspec_rag.search._searcher.rerank_with_graph", graph_order)
        )
        for name, surface, query in cases:
            budgets.clear()
            operation = getattr(searcher, f"search_{surface}_timed")
            results, timings = operation(query, top_k=5)
            ids = [result.id for result in results]
            sources = {result.source for result in results}
            live = timings.get("typesafe_requests", 0) >= 2 and not timings.get(
                "classification_fallback", 0
            )
            expected = {
                "test_lookup": "env_test" in ids,
                "explicit_prod": "env_test" not in ids
                and not any("/tests/" in result.path for result in results),
                "no_match": not results,
                "guide": "noise_guide" in ids,
                "cross_reference": "codebase" in sources
                and bool(sources & {"vault", "document"}),
            }[name]
            ok = live and expected
            passed += int(ok)
            print(
                json.dumps(
                    {
                        "case": name,
                        "passed": ok,
                        "results": [
                            {
                                "id": result.id,
                                "source": result.source,
                                "score": result.score,
                            }
                            for result in results
                        ],
                        "code_budgets": budgets,
                        "timings": timings,
                    }
                ),
                flush=True,
            )
    print(json.dumps({"cases": len(cases), "passed": passed}), flush=True)
    return 0 if passed == len(cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
