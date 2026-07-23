"""Intent-aware ranking harness: graded-relevance metrics over a real-vault copy.

Drives the labeled query set (``tests/quality/intent_queries.toml``) against a
real GPU index built from a hermetic copy of the project's own ``.vault/`` -
the corpus where a feature's adr, research, plan, and exec genuinely compete on
the same vocabulary, which is where the ranking failure lives. Each query's
results are scored with the role-aware metrics (``tests/quality/metrics.py``)
using the rubric-derived gold grades, per declared intent.

This module builds the evaluator and a structural gate. The strict per-intent
thresholds and the named orientation regression (the accepted ADR must outrank
the exec record that implements it) are asserted once the intent prior ships;
asserting them here, against the bare reranker, would fail by design, and the
test mandate forbids skips and xfails.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

import pytest

from .._model_setup import (
    model_setup_timeout_seconds,
    models_are_cached,
    run_bounded_process,
)
from ..quality.metrics import (
    authoritative_at_k,
    mrr_at_first_grade,
    ndcg_at_k,
    role_precision_at_k,
)
from ..quality.rubric import Intent

if TYPE_CHECKING:
    from ...search import SearchResult

pytestmark = [pytest.mark.integration, pytest.mark.quality]

_QUERYSET = Path(__file__).resolve().parents[1] / "quality" / "intent_queries.toml"
_NDCG_K = 10
_AUTHORITATIVE_GRADE = 3

# A single labeled query: ``text``, ``intent``, and a list of ``{doc_id, grade}``.
type Query = dict[str, object]


class QueryEvidence(TypedDict):
    """One real search result set together with its computed quality report."""

    report: dict[str, object]
    ranked_ids: list[str]
    doc_types: list[str]


class IntentRankingEvidence(TypedDict):
    """Serializable evidence produced by the bounded real-GPU worker."""

    corpus_documents: int
    indexed_documents: int
    queries: list[QueryEvidence]


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
def real_vault_evidence(
    tmp_path_factory: pytest.TempPathFactory,
) -> IntentRankingEvidence:
    """Run the complete real-GPU ranking setup inside one bounded process.

    The worker copies the complete live project vault, excluding only index
    storage and lock files, so the original ADR/research/plan/exec competition
    remains unchanged. Model construction, production indexing, and every
    production search run under one deadline; the parent consumes the worker's
    JSON evidence for normal assertions.
    """
    from ...config import get_config

    output_path = tmp_path_factory.mktemp("intent-ranking") / "evidence.json"
    cfg = get_config()
    model_ids = (
        str(cfg.embedding_model),
        str(cfg.sparse_model),
        str(cfg.reranker_model),
    )
    local_files_only = models_are_cached(model_ids)
    command = [
        sys.executable,
        "-m",
        "vaultspec_rag.tests.integration.test_intent_ranking",
        "--worker",
        "--repo-root",
        str(_repo_root()),
        "--output",
        str(output_path),
    ]
    if local_files_only:
        command.append("--local-files-only")

    timeout_seconds = model_setup_timeout_seconds()
    run_bounded_process(
        command,
        timeout_seconds=timeout_seconds,
        operation="real intent-ranking session fixture",
        context=(
            f"models={model_ids!r}, local_files_only={local_files_only}, "
            f"corpus='complete project vault', "
            f"deadline={timeout_seconds:.3f}s"
        ),
    )
    try:
        payload = json.loads(output_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"intent-ranking worker did not produce valid evidence at {output_path}"
        raise RuntimeError(msg) from exc
    return cast("IntentRankingEvidence", payload)


def _copy_real_vault_corpus(destination_root: Path) -> int:
    """Copy the complete real vault except mutable index data and lock files."""
    source_vault = _repo_root() / ".vault"
    destination_vault = destination_root / ".vault"
    shutil.copytree(
        source_vault,
        destination_vault,
        ignore=shutil.ignore_patterns("data", "*.lock"),
    )
    (destination_root / ".vaultspec").mkdir(parents=True, exist_ok=True)

    for query in _load_queries():
        for doc_id in _gold_map(query):
            if not (destination_vault / f"{doc_id}.md").is_file():
                msg = f"labeled document absent from intent corpus: {doc_id}"
                raise RuntimeError(msg)
    return _real_vault_document_count(destination_vault)


def _real_vault_document_count(vault_root: Path | None = None) -> int:
    """Count the Markdown documents in the complete immutable corpus surface."""
    root = vault_root or (_repo_root() / ".vault")
    return sum(
        1 for path in root.rglob("*.md") if "data" not in path.relative_to(root).parts
    )


def _run_worker(*, output_path: Path, local_files_only: bool) -> None:
    """Build and evaluate the real feature corpus in the bounded child."""
    from ... import EmbeddingModel, VaultSearcher
    from ..conftest import _index_corpus

    with tempfile.TemporaryDirectory(prefix="vaultspec-intent-ranking-") as temp_dir:
        root = Path(temp_dir)
        corpus_documents = _copy_real_vault_corpus(root)
        print(
            f"stage=corpus-ready documents={corpus_documents}",
            flush=True,
        )
        model = EmbeddingModel(local_files_only=local_files_only)
        print("stage=embedding-model-ready", flush=True)
        components = _index_corpus(root, model)
        print(
            f"stage=index-ready documents={components['index_result'].total}",
            flush=True,
        )
        searcher = VaultSearcher(
            root,
            components["model"],
            components["store"],
            local_files_only=local_files_only,
        )
        try:
            query_evidence: list[QueryEvidence] = []
            for query in _load_queries():
                print(f"stage=query-start text={query['text']!r}", flush=True)
                results: list[SearchResult] = searcher.search_vault(
                    str(query["text"]),
                    top_k=_NDCG_K,
                    intent=str(query["intent"]),
                )
                ranked_ids = [result.id for result in results]
                query_evidence.append(
                    QueryEvidence(
                        report=evaluate_query(ranked_ids, query),
                        ranked_ids=ranked_ids,
                        doc_types=[result.doc_type for result in results],
                    ),
                )
                print(f"stage=query-complete text={query['text']!r}", flush=True)
            evidence = IntentRankingEvidence(
                corpus_documents=corpus_documents,
                indexed_documents=components["index_result"].total,
                queries=query_evidence,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                json.dumps(evidence, indent=2, sort_keys=True),
                encoding="utf-8",
            )
        finally:
            components["store"].close()


def _query_evidence(
    evidence: IntentRankingEvidence,
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
        real_vault_evidence: IntentRankingEvidence,
    ) -> None:
        """Every labeled query yields well-formed per-intent metrics."""
        reports = [query["report"] for query in real_vault_evidence["queries"]]
        assert reports, "the labeled query set must not be empty"
        assert real_vault_evidence["corpus_documents"] == _real_vault_document_count()
        assert real_vault_evidence["indexed_documents"] > 0
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
        real_vault_evidence: IntentRankingEvidence,
    ) -> None:
        """The accepted ADR reaches the top 3 for (nearly) every orientation query."""
        reports = [query["report"] for query in real_vault_evidence["queries"]]
        orient = [r for r in reports if r["intent"] == Intent.ORIENTATION.value]
        rate = sum(bool(r["authoritative_at_3"]) for r in orient) / len(orient)
        assert rate >= _ORIENTATION_AUTH3_FLOOR, (
            f"orientation Authoritative@3 rate {rate:.3f} below "
            f"{_ORIENTATION_AUTH3_FLOOR}"
        )

    def test_index_documents_never_surface(
        self,
        real_vault_evidence: IntentRankingEvidence,
    ) -> None:
        """Auto-generated feature-index documents must not appear in results."""
        query = _query_evidence(
            real_vault_evidence,
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
        real_vault_evidence: IntentRankingEvidence,
    ) -> None:
        """The accepted ADR must outrank the exec record it governs (the live case)."""
        query = _query_evidence(
            real_vault_evidence,
            _REGRESSION_QUERY,
        )
        ids = query["ranked_ids"]
        assert _REGRESSION_ADR in ids, f"accepted ADR missing from top 10: {ids}"
        if _REGRESSION_EXEC in ids:
            assert ids.index(_REGRESSION_ADR) < ids.index(_REGRESSION_EXEC), (
                "accepted ADR must outrank the exec record that implements it"
            )


def _parse_args() -> argparse.Namespace:
    """Parse the private intent-ranking worker command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--local-files-only", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Run the private bounded intent-ranking worker."""
    args = _parse_args()
    if not args.worker or args.repo_root is None or args.output is None:
        raise SystemExit("this module is a private intent-ranking worker")
    if args.repo_root.resolve() != _repo_root().resolve():
        raise SystemExit(
            f"worker repository mismatch: {args.repo_root} != {_repo_root()}",
        )
    _run_worker(
        output_path=args.output,
        local_files_only=args.local_files_only,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
