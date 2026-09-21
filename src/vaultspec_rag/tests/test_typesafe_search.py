"""GPU-free tests of hosted classification through the production search paths."""

from __future__ import annotations

import threading
from contextlib import nullcontext
from dataclasses import asdict, dataclass, field, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, Mock

import pytest

from .. import _public_search
from .._public_search import CombinedSearchRequest
from .._search_state import (
    AbsenceAuthority,
    SearchAvailability,
    SearchFreshness,
    SearchSourceFact,
)
from .._source_types import PublicSourceType
from ..config._types import EnvVar
from ..search import _typesafe_context, _typesafe_policy, _typesafe_transport
from ..search._models import DocumentSearchResult, ParsedQuery, SearchResult
from ..search._parsing import parse_query
from ..search._searcher import VaultSearcher
from ..search._typesafe_answers import MODEL, ChoiceAnswer, Evaluation
from ..search._typesafe_transport import TypesafeUnavailableError

if TYPE_CHECKING:
    from pathlib import Path

    from .._source_types import IndexSource
    from .._store_search import HybridSearchRequest
    from ..search._typesafe_policy import ClassificationSession
    from ..service import ServiceRegistry

pytestmark = pytest.mark.unit


@dataclass
class _Session:
    fail_on_call: int = 0
    failed: bool = False
    vault_intent: str | None = None
    prefer: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    seen: list[list[str | None]] = field(default_factory=list)

    def candidate_limit(self, top_k: int, legacy_limit: int) -> int:
        return max(legacy_limit, top_k * 6, 32)

    def rank[T: SearchResult | DocumentSearchResult](self, results: list[T]) -> list[T]:
        self.seen.append([row.rerank_text for row in results])
        if len(self.seen) == self.fail_on_call:
            self.failed = True
            raise TypesafeUnavailableError("test_failure")
        kept = [row for row in results if "useful" in (row.rerank_text or "")]
        return [replace(row, score=0.95) for row in reversed(kept)]


def _row(index: int, *, content: str = "unrelated") -> dict[str, object]:
    return {
        "id": str(index),
        "path": f"src/item_{index}.py",
        "source_path": f"manuals/item_{index}.txt",
        "title": str(index),
        "doc_type": "adr",
        "status": "accepted",
        "domain": "prod",
        "content": content,
        "_relevance_score": 0.8 - index * 0.01,
    }


def _searcher(
    monkeypatch: pytest.MonkeyPatch, root: Path, rows: list[dict[str, object]]
) -> tuple[VaultSearcher, Mock]:
    store = Mock()

    def fetch(request: HybridSearchRequest) -> list[dict[str, object]]:
        return rows[: request.limit]

    store.hybrid_search.side_effect = fetch
    store.hybrid_search_codebase.side_effect = fetch
    store.hybrid_search_document.side_effect = fetch
    searcher = VaultSearcher.__new__(VaultSearcher)
    searcher.root_dir = root
    searcher.store = store
    searcher._reranker_enabled = False

    def encode(
        raw_query: str, **_kwargs: object
    ) -> tuple[ParsedQuery, str, list[float], None]:
        parsed = parse_query(raw_query)
        return parsed, parsed.text, [1.0, 0.0], None

    def graph_order[T](results: list[T], *_args: object, **_kwargs: object) -> list[T]:
        return results

    monkeypatch.setattr(searcher, "_encode_query", encode)
    monkeypatch.setattr(searcher, "_get_graph", lambda: None)
    monkeypatch.setattr(
        "vaultspec_rag.search._searcher.rerank_with_graph",
        graph_order,
    )
    monkeypatch.delenv(EnvVar.TYPESAFE_API_KEY, raising=False)
    return searcher, store


def _enroll(monkeypatch: pytest.MonkeyPatch, session: _Session) -> Mock:
    prepare = Mock(return_value=cast("ClassificationSession", session))
    monkeypatch.setattr(_typesafe_context, "prepare_query", prepare)
    return prepare


def test_keyless_search_preserves_budget_scores_and_makes_no_api_call(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    searcher, store = _searcher(monkeypatch, tmp_path, [_row(i) for i in range(40)])
    evaluate = Mock(side_effect=AssertionError("keyless provider call"))
    monkeypatch.setattr(_typesafe_transport, "evaluate", evaluate)
    results = searcher.search_codebase("retry delivery", top_k=2)
    assert [(row.id, row.score) for row in results] == [("0", 0.8), ("1", 0.79)]
    assert store.hybrid_search_codebase.call_args.args[0].limit == 4
    evaluate.assert_not_called()


@pytest.mark.parametrize("surface", ["codebase", "vault", "document", "combined"])
@pytest.mark.parametrize(("query", "top_k"), [("retry delivery", 0), ("path:src/", 2)])
def test_zero_or_filter_only_search_never_attempts_classification(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    surface: str,
    query: str,
    top_k: int,
) -> None:
    searcher, _store = _searcher(monkeypatch, tmp_path, [_row(0)])
    # Passing raw/encoded text into enrollment must trip this interception.
    available = Mock(return_value=True)
    evaluate = Mock(side_effect=AssertionError("unnecessary provider call"))
    monkeypatch.setattr(_typesafe_transport, "available", available)
    monkeypatch.setattr(_typesafe_transport, "evaluate", evaluate)
    operation = getattr(searcher, f"search_{surface}")
    results = operation(query, top_k=top_k)
    if top_k == 0:
        assert results == []
    available.assert_not_called()
    evaluate.assert_not_called()


@pytest.mark.parametrize("surface", ["codebase", "vault", "document"])
def test_classification_widens_and_scores_full_content_before_truncation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, surface: str
) -> None:
    full_content = "# context\n" * 40 + "useful retry implementation"
    rows = [_row(i) for i in range(5)] + [_row(5, content=full_content)]
    searcher, _store = _searcher(monkeypatch, tmp_path, rows)
    session = _Session()
    prepare = _enroll(monkeypatch, session)
    operation = getattr(searcher, f"search_{surface}")
    results = operation("retry delivery", top_k=1)
    assert [row.id for row in results] == ["5"]
    assert session.seen == [[str(row["content"]) for row in rows]]
    assert "useful" not in results[0].snippet
    prepare.assert_called_once()


def test_failed_widened_classification_repeats_the_exact_legacy_budget(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    searcher, store = _searcher(
        monkeypatch, tmp_path, [_row(i, content="useful") for i in range(40)]
    )
    baseline = searcher.search_codebase("retry delivery", top_k=2)
    store.hybrid_search_codebase.reset_mock()
    _enroll(monkeypatch, _Session(fail_on_call=1))
    results, timings = searcher.search_codebase_timed("retry delivery", top_k=2)
    assert [asdict(row) for row in results] == [asdict(row) for row in baseline]
    assert [
        call.args[0].limit for call in store.hybrid_search_codebase.call_args_list
    ] == [32, 4]
    assert timings["classification_fallback"] == 1.0


def test_failed_widened_classification_restores_original_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [_row(i, content="useful production") for i in range(4)] + [
        {**_row(4), "path": "tests/test_retry.py", "domain": "tests"}
    ]
    searcher, store = _searcher(monkeypatch, tmp_path, rows)
    notes: dict[str, object] = {"caller_note": "retain"}
    at_failure: list[dict[str, object]] = []
    session = _Session(fail_on_call=1)
    original_rank = session.rank

    def rank[T: SearchResult | DocumentSearchResult](results: list[T]) -> list[T]:
        at_failure.append(dict(notes))
        return original_rank(results)

    monkeypatch.setattr(session, "rank", rank)
    _enroll(monkeypatch, session)
    results, timings = searcher.search_codebase_timed(
        "retry", top_k=2, exclude_domains=["tests"], notes=notes
    )
    assert at_failure == [{"caller_note": "retain", "dropped_domains": {"tests": 1}}]
    # Omitting snapshot clearing must leave widened diagnostics and fail here.
    assert notes == {"caller_note": "retain"}
    assert [row.id for row in results] == ["0", "1"]
    assert [
        call.args[0].limit for call in store.hybrid_search_codebase.call_args_list
    ] == [32, 4]
    assert timings["classification_fallback"] == 1.0


def test_vault_alternate_chunks_are_classified_before_document_grouping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [
        _row(0),
        {**_row(0, content="useful second chunk"), "_relevance_score": 0.1},
    ]
    searcher, _store = _searcher(monkeypatch, tmp_path, rows)
    session = _Session()
    _enroll(monkeypatch, session)
    results = searcher.search_vault("retry delivery", top_k=1)
    assert session.seen == [["unrelated", "useful second chunk"]]
    assert results[0].rerank_text == "useful second chunk"


def test_explicit_domains_paths_and_intent_remain_authoritative(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    rows = [
        _row(0, content="useful production"),
        {
            **_row(1, content="useful test"),
            "path": "tests/test_retry.py",
            "domain": "tests",
        },
    ]
    searcher, _store = _searcher(monkeypatch, tmp_path, rows)
    session = _Session(prefer="tests", vault_intent="debugging")
    prepare = _enroll(monkeypatch, session)
    results = searcher.search_codebase(
        "retry only:prod path:src/", top_k=2, prefer="prod"
    )
    assert [row.path for row in results] == ["src/item_0.py"]
    assert results[0].score == pytest.approx(1.0)
    assert prepare.call_args.args[2]["only_domain"] == "prod"

    def preserve_order[T](results: list[T], _intent: object) -> list[T]:
        return results

    prior = Mock(side_effect=preserve_order)
    monkeypatch.setattr(searcher, "_apply_intent_prior", prior)
    searcher.search_vault("retry intent:orientation", top_k=2)
    assert prior.call_args.args[1] == "orientation"


@pytest.mark.parametrize("inline", [True, False], ids=["inline", "programmatic"])
def test_only_prod_excludes_tests_and_docs_without_hosted_classification(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, inline: bool
) -> None:
    rows = [
        _row(0),
        {**_row(1), "path": "tests/test_retry.py", "domain": "tests"},
        {**_row(2), "path": "docs/retry.md", "domain": "docs"},
    ]
    searcher, store = _searcher(monkeypatch, tmp_path, rows)
    evaluate = Mock(side_effect=AssertionError("keyless provider call"))
    monkeypatch.setattr(_typesafe_transport, "evaluate", evaluate)
    results = searcher.search_codebase(
        "retry only:prod" if inline else "retry",
        top_k=3,
        only_domains=None if inline else ["prod"],
    )
    assert [(row.path, row.score) for row in results] == [("src/item_0.py", 0.8)]
    assert store.hybrid_search_codebase.call_args.args[0].only_domains == ["prod"]
    evaluate.assert_not_called()


def test_direct_combined_shares_query_and_does_not_rerank_classified_hits_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    searcher, _store = _searcher(monkeypatch, tmp_path, [_row(0, content="useful")])
    session = _Session()
    prepare = _enroll(monkeypatch, session)
    rerank = Mock(wraps=searcher._rerank)
    monkeypatch.setattr(searcher, "_rerank", rerank)
    results = searcher.search_combined("retry across code and decisions", top_k=3)
    assert len(results) == 3
    assert len(session.seen) == 3
    assert rerank.call_count == 3
    prepare.assert_called_once()


def test_direct_combined_failure_restores_all_legacy_domains(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    searcher, _store = _searcher(
        monkeypatch, tmp_path, [_row(i, content="useful") for i in range(6)]
    )
    baseline = searcher.search_combined("retry", top_k=3)
    _enroll(monkeypatch, _Session(fail_on_call=2))
    results, timings = searcher.search_combined_timed("retry", top_k=3)
    assert [asdict(row) for row in results] == [asdict(row) for row in baseline]
    assert timings["classification_fallback"] == 1.0


def _public_registry(
    monkeypatch: pytest.MonkeyPatch, searcher: VaultSearcher
) -> ServiceRegistry:
    registry = Mock()
    lease = MagicMock()
    lease.__enter__.return_value = SimpleNamespace(searcher=searcher)
    registry.search_lease.return_value = lease
    source_kinds: tuple[tuple[PublicSourceType, IndexSource], ...] = (
        (PublicSourceType.VAULT, "vault"),
        (PublicSourceType.CODE, "code"),
        (PublicSourceType.DOCUMENT, "document"),
    )
    facts = {
        source: SearchSourceFact(
            source=kind,
            availability=SearchAvailability.USABLE,
            freshness=SearchFreshness.CURRENT,
            absence_authority=AbsenceAuthority.AUTHORITATIVE,
        )
        for source, kind in source_kinds
    }
    monkeypatch.setattr(
        _public_search,
        "_count_combined_domains",
        Mock(return_value=(dict.fromkeys(facts, 6), {}, facts, {})),
    )
    return cast("ServiceRegistry", registry)


def test_public_combined_fallback_restores_scores_and_preserves_domain_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    searcher, store = _searcher(
        monkeypatch, tmp_path, [_row(i, content="useful") for i in range(6)]
    )
    store.hybrid_search_document.side_effect = RuntimeError("document unavailable")
    registry = _public_registry(monkeypatch, searcher)
    request = CombinedSearchRequest(tmp_path, "retry", top_k=3)
    baseline, _timings = _public_search.search_combined_timed(
        request, registry=registry
    )
    session = _Session(fail_on_call=2)
    prepare = _enroll(monkeypatch, session)
    outcome, timings = _public_search.search_combined_timed(request, registry=registry)
    assert outcome.partial
    assert outcome.document.detail == "document unavailable"
    assert outcome.document.error_kind == baseline.document.error_kind
    assert outcome.source_facts == baseline.source_facts
    assert [asdict(row) for row in outcome.results] == [
        asdict(row) for row in baseline.results
    ]
    assert timings["classification_fallback"] == 1.0
    prepare.assert_called_once()


@pytest.mark.parametrize(
    ("query", "top_k"), [("retry", 0), ("retry", -1), ("path:src/", 2)]
)
def test_public_combined_empty_request_never_enrolls(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, query: str, top_k: int
) -> None:
    # Removing the positive-limit guard triggered the provider interception for
    # zero and negative limits; restoring it made all three request cases pass.
    searcher, _store = _searcher(monkeypatch, tmp_path, [_row(0)])
    registry = _public_registry(monkeypatch, searcher)
    available = Mock(return_value=True)
    evaluate = Mock(side_effect=AssertionError("unnecessary provider call"))
    monkeypatch.setattr(_typesafe_transport, "available", available)
    monkeypatch.setattr(_typesafe_transport, "evaluate", evaluate)
    rejection = (
        pytest.raises(ValueError, match="top_k must be a non-negative integer")
        if top_k < 0
        else nullcontext()
    )
    with rejection:
        _public_search.search_combined_timed(
            CombinedSearchRequest(tmp_path, query, top_k=top_k), registry=registry
        )
    available.assert_not_called()
    evaluate.assert_not_called()


def test_direct_combined_notes_are_private_and_do_not_disable_preference(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Including notes in combined constraints failed the empty-constraints
    # assertion; excluding them restored this test's pass.
    searcher, _store = _searcher(monkeypatch, tmp_path, [_row(0)])
    notes: dict[str, object] = {"diagnostic": "local-only diagnostic"}
    evaluation = Evaluation(
        {
            name: ChoiceAnswer(choice, 0.99, {choice: 1.0})
            for name, choice in (
                ("intent", "implementation"),
                ("wording", "natural_language"),
                ("evidence", "snippet"),
                ("domain", "tests"),
            )
        },
        MODEL,
        100,
        20,
    )
    evaluate = Mock(return_value=evaluation)
    monkeypatch.setattr(_typesafe_transport, "available", Mock(return_value=True))
    monkeypatch.setattr(_typesafe_transport, "evaluate", evaluate)
    sessions: list[ClassificationSession] = []

    def keep_results[T: SearchResult | DocumentSearchResult](
        session: ClassificationSession, results: list[T]
    ) -> list[T]:
        sessions.append(session)
        return results

    monkeypatch.setattr(_typesafe_policy.ClassificationSession, "rank", keep_results)
    searcher.search_combined("Find test code for retry", top_k=3, notes=notes)
    evaluate.assert_called_once()
    assert evaluate.call_args.args[0]["constraints"] == {}
    assert sessions and sessions[0].prefer == "tests"
    assert notes == {"diagnostic": "local-only diagnostic"}


def test_keyless_code_search_does_not_copy_opaque_notes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Restoring asdict before removing notes raised cannot-pickle-lock here;
    # filtering fields before reading their values restored the successful search.
    searcher, _store = _searcher(monkeypatch, tmp_path, [_row(0)])
    opaque = threading.Lock()
    notes: dict[str, object] = {"opaque": opaque}
    evaluate = Mock(side_effect=AssertionError("keyless provider call"))
    monkeypatch.setattr(_typesafe_transport, "evaluate", evaluate)
    results = searcher.search_codebase("retry", top_k=1, notes=notes)
    assert [row.id for row in results] == ["0"]
    assert notes["opaque"] is opaque
    evaluate.assert_not_called()
