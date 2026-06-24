"""Intent-aware ranking harness: graded-relevance metrics over a real-vault copy.

Drives the labeled query set (``tests/quality/intent_queries.toml``) against a
real GPU index built from a hermetic copy of the project's own ``.vault/`` -
the corpus where a feature's adr, research, plan, and exec genuinely compete on
the same vocabulary, which is where the ranking failure lives. Each query's
results are scored with the role-aware metrics (``tests/quality/metrics.py``)
using the rubric-derived gold grades, per declared intent.

This module builds the evaluator and a structural gate. The strict per-intent
thresholds and the named orientation regression (the accepted ADR must outrank
the exec record that implements it) are asserted once the intent prior lands in
Wave W03; asserting them here, against the bare reranker, would fail by design,
and the test mandate forbids skips and xfails.
"""

from __future__ import annotations

import shutil
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from ..quality.metrics import (
    authoritative_at_k,
    mrr_at_first_grade,
    ndcg_at_k,
    role_precision_at_k,
)
from ..quality.rubric import Intent

if TYPE_CHECKING:
    from collections.abc import Generator

    from ...embeddings import EmbeddingModel
    from ...search import SearchResult, VaultSearcher

pytestmark = [pytest.mark.quality]

_QUERYSET = Path(__file__).resolve().parents[1] / "quality" / "intent_queries.toml"
_NDCG_K = 10
_AUTHORITATIVE_GRADE = 3

# A single labeled query: ``text``, ``intent``, and a list of ``{doc_id, grade}``.
type Query = dict[str, object]


def _repo_root() -> Path:
    """Return the worktree root containing the project ``.vault/``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".vault").is_dir():
            return parent
    msg = "could not locate project .vault/ above the test module"
    raise RuntimeError(msg)


def _load_queries() -> list[Query]:
    """Load the labeled query set; each entry has text, intent, and gold."""
    data = tomllib.loads(_QUERYSET.read_text(encoding="utf-8"))
    return cast("list[Query]", data.get("query", []))


def _gold_map(query: Query) -> dict[str, int]:
    """Build a ``{doc_id: grade}`` mapping from a query's gold judgments."""
    judgments = cast("list[dict[str, object]]", query.get("gold", []))
    return {str(j["doc_id"]): int(cast("int", j["grade"])) for j in judgments}


def evaluate_query(ranked_ids: list[str], query: Query) -> dict[str, object]:
    """Score one query's ranked result ids against its gold grades.

    Returns a per-query report carrying the intent, NDCG@k, the
    intent-appropriate headline (Authoritative@3 for orientation, MRR for
    debugging/implementation), and role-precision@3.
    """
    gold = _gold_map(query)
    intent = Intent(str(query["intent"]))
    report: dict[str, object] = {
        "text": query["text"],
        "intent": str(intent),
        "ndcg_at_k": round(ndcg_at_k(ranked_ids, gold, _NDCG_K), 4),
        "role_precision_at_3": round(role_precision_at_k(ranked_ids, gold, 3), 4),
    }
    if intent is Intent.ORIENTATION:
        report["authoritative_at_3"] = authoritative_at_k(
            ranked_ids, gold, 3, min_grade=_AUTHORITATIVE_GRADE
        )
    else:
        # Debugging/implementation: how high the top gold artifact (the grade-3
        # exec record or plan) lands.
        report["mrr_at_grade_3"] = round(
            mrr_at_first_grade(ranked_ids, gold, min_grade=_AUTHORITATIVE_GRADE), 4
        )
    return report


@pytest.fixture(scope="session")
def real_vault_searcher(
    embedding_model: EmbeddingModel,
    tmp_path_factory: pytest.TempPathFactory,
) -> Generator[VaultSearcher]:
    """Index a hermetic copy of the project ``.vault/`` and yield a searcher.

    Copies the live vault (excluding its on-disk index data) into a temp root so
    the gate runs against the real corpus without touching the project index or
    contending with a running service for the store lock.
    """
    from ... import VaultSearcher
    from ..conftest import _index_corpus

    root = tmp_path_factory.mktemp("real-vault-eval")
    shutil.copytree(
        _repo_root() / ".vault",
        root / ".vault",
        ignore=shutil.ignore_patterns("data", "*.lock"),
    )
    (root / ".vaultspec").mkdir(parents=True, exist_ok=True)

    components = _index_corpus(root, embedding_model)
    searcher = VaultSearcher(root, components["model"], components["store"])
    try:
        yield searcher
    finally:
        components["store"].close()


def run_evaluation(
    searcher: VaultSearcher,
    *,
    top_k: int = _NDCG_K,
) -> list[dict[str, object]]:
    """Run every labeled query through the searcher and score it.

    Returns the list of per-query reports. Pure orchestration over the injected
    searcher so the same routine scores baseline and post-prior rankings.
    """
    reports: list[dict[str, object]] = []
    for query in _load_queries():
        results: list[SearchResult] = searcher.search_vault(
            str(query["text"]), top_k=top_k, intent=str(query["intent"])
        )
        ranked_ids = [r.id for r in results]
        reports.append(evaluate_query(ranked_ids, query))
    return reports


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
        self, real_vault_searcher: VaultSearcher
    ) -> None:
        """Every labeled query yields well-formed per-intent metrics."""
        reports = run_evaluation(real_vault_searcher)
        assert reports, "the labeled query set must not be empty"
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
        self, real_vault_searcher: VaultSearcher
    ) -> None:
        """The accepted ADR reaches the top 3 for (nearly) every orientation query."""
        reports = run_evaluation(real_vault_searcher)
        orient = [r for r in reports if r["intent"] == Intent.ORIENTATION.value]
        rate = sum(bool(r["authoritative_at_3"]) for r in orient) / len(orient)
        assert rate >= _ORIENTATION_AUTH3_FLOOR, (
            f"orientation Authoritative@3 rate {rate:.3f} below "
            f"{_ORIENTATION_AUTH3_FLOOR}"
        )

    def test_index_documents_never_surface(
        self, real_vault_searcher: VaultSearcher
    ) -> None:
        """Auto-generated feature-index documents must not appear in results (D6)."""
        results = real_vault_searcher.search_vault(
            "qdrant server mode binary provisioning", top_k=10, intent="orientation"
        )
        assert results, "expected results for a feature-named query"
        offenders = [r.id for r in results if r.doc_type == "index"]
        assert not offenders, f"index documents leaked into results: {offenders}"

    def test_named_orientation_regression(
        self, real_vault_searcher: VaultSearcher
    ) -> None:
        """The accepted ADR must outrank the exec record it governs (the live case)."""
        results = real_vault_searcher.search_vault(
            _REGRESSION_QUERY, top_k=10, intent=Intent.ORIENTATION.value
        )
        ids = [r.id for r in results]
        assert _REGRESSION_ADR in ids, f"accepted ADR missing from top 10: {ids}"
        if _REGRESSION_EXEC in ids:
            assert ids.index(_REGRESSION_ADR) < ids.index(_REGRESSION_EXEC), (
                "accepted ADR must outrank the exec record that implements it"
            )
