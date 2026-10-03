"""Retrieval fixtures for the live hosted search check.

Full functions from this checkout, each with a fixed retrieval score. The
scores are fixtures, not a measured GPU baseline; every judgment over them
comes from the real hosted endpoint.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

from vaultspec_rag.search._models import SearchResult

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
