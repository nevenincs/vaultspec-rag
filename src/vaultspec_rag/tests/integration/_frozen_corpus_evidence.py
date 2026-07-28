"""One real-GPU experiment producing every frozen-corpus ranking gate's evidence.

The intent-ranking metrics and the persona testimonials are two views of the
same experiment: both score pre-declared authorities against a real GPU index
of the frozen reference vault (see :mod:`..quality._frozen_corpus`). Building
that index is by far the most expensive setup in the suite - it materialises
and embeds the whole pinned vault - and running it once per gate indexed the
identical corpus twice for no additional coverage.

So the corpus is materialised and indexed exactly once here, both gates' real
searches run against it, and the observations are handed back as one typed
record. The work runs on the session-shared embedding model and reranker: a
private copy of either is a second full model set on a card the suite already
fills, and oversubscribing the device spills into shared system memory and
slows every later forward pass. Hugging Face acquisition stays bounded where
it belongs - in the killable snapshot worker those two session fixtures call
before constructing anything cache-only - so no metadata retry can reach this
module. It runs the experiment; the test modules decide what the results mean.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, cast

from ..quality._frozen_corpus import (
    frozen_vault_document_count,
    materialize_frozen_vault,
)
from ..quality.metrics import (
    authoritative_at_k,
    mrr_at_first_grade,
    ndcg_at_k,
    role_precision_at_k,
)
from ..quality.rubric import Intent

if TYPE_CHECKING:
    from sentence_transformers import CrossEncoder

    from ...embeddings import EmbeddingModel
    from ...search import SearchResult

#: Depth the intent gate scores to, and the ``top_k`` its searches request.
NDCG_K = 10

#: The gold grade that marks a document as the authority for its query.
AUTHORITATIVE_GRADE = 3

#: Depth a persona actually reads, and the ``top_k`` testimonial searches request.
TESTIMONIAL_TOP_K = 5

_QUERYSET = Path(__file__).resolve().parents[1] / "quality" / "intent_queries.toml"

# A single labeled query: ``text``, ``intent``, and a list of ``{doc_id, grade}``.
type Query = dict[str, object]


@dataclass
class Scenario:
    """A persona's pre-declared search expectation."""

    persona: str
    intent: str
    query: str
    expected_authority: str  # doc_id that should lead for this persona


# Personas map one-to-one to intents. Each expected_authority is the document
# the persona expects to lead, declared before any search runs.
SCENARIOS: list[Scenario] = [
    Scenario(
        persona="orienting newcomer",
        intent="orientation",
        query="decision on gpu lock scope",
        expected_authority="adr/2026-06-12-service-concurrency-adr",
    ),
    Scenario(
        persona="orienting newcomer",
        intent="orientation",
        query="qdrant server mode with provisioned binary verification",
        expected_authority="adr/2026-06-12-qdrant-server-provisioning-adr",
    ),
    Scenario(
        persona="debugging maintainer",
        intent="debugging",
        query="narrow the gpu lock to model forward calls in the search path",
        expected_authority=(
            "exec/2026-06-12-service-concurrency/"
            "2026-06-12-service-concurrency-W03-P06-S15"
        ),
    ),
]


class QueryEvidence(TypedDict):
    """One real search result set together with its computed quality report."""

    report: dict[str, object]
    ranked_ids: list[str]
    doc_types: list[str]


class TestimonialEvidence(TypedDict):
    """One persona scenario's real observed ranking, before any verdict."""

    persona: str
    intent: str
    query: str
    expected_authority: str
    observed_top: list[str]


class FrozenCorpusEvidence(TypedDict):
    """Serializable evidence produced by the bounded real-GPU worker."""

    corpus_documents: int
    indexed_documents: int
    queries: list[QueryEvidence]
    testimonials: list[TestimonialEvidence]


def repo_root() -> Path:
    """Return the worktree root containing the project ``.vault/``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / ".vault").is_dir():
            return parent
    msg = "could not locate project .vault/ above the test module"
    raise RuntimeError(msg)


def load_queries() -> list[Query]:
    """Load the labeled query set; each entry has text, intent, and gold."""
    data = tomllib.loads(_QUERYSET.read_text(encoding="utf-8"))
    return cast("list[Query]", data.get("query", []))


def gold_map(query: Query) -> dict[str, int]:
    """Build a ``{doc_id: grade}`` mapping from a query's gold judgments."""
    judgments = cast("list[dict[str, object]]", query.get("gold", []))
    return {str(j["doc_id"]): int(cast("int", j["grade"])) for j in judgments}


def evaluate_query(ranked_ids: list[str], query: Query) -> dict[str, object]:
    """Score one query's ranked result ids against its gold grades.

    Returns a per-query report carrying the intent, NDCG@k, the
    intent-appropriate headline (Authoritative@3 for orientation, MRR for
    debugging/implementation), and role-precision@3.
    """
    gold = gold_map(query)
    intent = Intent(str(query["intent"]))
    report: dict[str, object] = {
        "text": query["text"],
        "intent": str(intent),
        "ndcg_at_k": round(ndcg_at_k(ranked_ids, gold, NDCG_K), 4),
        "role_precision_at_3": round(role_precision_at_k(ranked_ids, gold, 3), 4),
    }
    if intent is Intent.ORIENTATION:
        report["authoritative_at_3"] = authoritative_at_k(
            ranked_ids, gold, 3, min_grade=AUTHORITATIVE_GRADE
        )
    else:
        # Debugging/implementation: how high the top gold artifact (the grade-3
        # exec record or plan) lands.
        report["mrr_at_grade_3"] = round(
            mrr_at_first_grade(ranked_ids, gold, min_grade=AUTHORITATIVE_GRADE), 4
        )
    return report


def real_vault_document_count(vault_root: Path | None = None) -> int:
    """Count the Markdown documents in the frozen reference corpus.

    With no explicit root, count the frozen ref's tree directly so the
    harness corpus-count invariant matches the materialised frozen corpus,
    not the live vault that keeps growing under it.
    """
    if vault_root is None:
        return frozen_vault_document_count(repo_root=repo_root())
    return sum(
        1
        for path in vault_root.rglob("*.md")
        if "data" not in path.relative_to(vault_root).parts
    )


def _copy_real_vault_corpus(destination_root: Path) -> int:
    """Materialise the frozen reference vault so the gold cannot drift.

    See :mod:`..quality._frozen_corpus`: the gold is scored against the vault
    at its calibration commit, not the live, still-growing tree.
    """
    destination_vault = materialize_frozen_vault(
        destination_root, repo_root=repo_root()
    )
    (destination_root / ".vaultspec").mkdir(parents=True, exist_ok=True)

    for query in load_queries():
        for doc_id in gold_map(query):
            if not (destination_vault / f"{doc_id}.md").is_file():
                msg = f"labeled document absent from intent corpus: {doc_id}"
                raise RuntimeError(msg)
    return real_vault_document_count(destination_vault)


def build_frozen_corpus_evidence(
    root: Path,
    model: EmbeddingModel,
    reranker: CrossEncoder,
) -> FrozenCorpusEvidence:
    """Index the frozen corpus under *root* and record every gate's observations.

    Takes the session's own model and reranker rather than constructing either:
    the reranker arrives the way the service injects it, so no searcher here
    lazily loads a private copy, and nothing in this module can reach Hugging
    Face.
    """
    from ... import VaultSearcher
    from ..conftest import _index_corpus

    corpus_documents = _copy_real_vault_corpus(root)
    components = _index_corpus(root, model)
    searcher = VaultSearcher(
        root,
        components["model"],
        components["store"],
        reranker=reranker,
    )
    try:
        query_evidence: list[QueryEvidence] = []
        for query in load_queries():
            results: list[SearchResult] = searcher.search_vault(
                str(query["text"]),
                top_k=NDCG_K,
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

        testimonial_evidence: list[TestimonialEvidence] = []
        for scenario in SCENARIOS:
            scenario_results = searcher.search_vault(
                scenario.query,
                top_k=TESTIMONIAL_TOP_K,
                intent=scenario.intent,
            )
            testimonial_evidence.append(
                TestimonialEvidence(
                    persona=scenario.persona,
                    intent=scenario.intent,
                    query=scenario.query,
                    expected_authority=scenario.expected_authority,
                    observed_top=[result.id for result in scenario_results],
                ),
            )

        return FrozenCorpusEvidence(
            corpus_documents=corpus_documents,
            indexed_documents=components["index_result"].total,
            queries=query_evidence,
            testimonials=testimonial_evidence,
        )
    finally:
        # Releases the local-Qdrant sqlite handles; on Windows an open handle
        # survives the directory it was opened under.
        components["store"].close()
