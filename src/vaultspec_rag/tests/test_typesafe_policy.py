"""Pure policy contracts with typed transport responses and complete evidence."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import patch

import pytest

from ..search import _typesafe_policy as policy
from ..search._models import DocumentSearchResult, SearchResult
from ..search._typesafe_answers import ChoiceAnswer, Evaluation, NoulAnswer, ScoreAnswer
from ..search._typesafe_questions import (
    candidate_questions,
    query_clauses,
)
from ..search._typesafe_transport import TypesafeUnavailableError

pytestmark = pytest.mark.unit


def _result(index: int, content: str | None = "complete evidence") -> SearchResult:
    return SearchResult(
        id=str(index),
        path=f"src/item{index}.py",
        title="Item",
        score=0.5,
        snippet="display only",
        source="codebase",
        rerank_text=content,
    )


def _session() -> policy.ClassificationSession:
    return policy.ClassificationSession(
        query="retry delivery",
        context={"query": "retry delivery", "constraints": {}},
        deadline=time.monotonic() + 10,
    )


def test_candidate_batches_overlap_with_at_most_two_calls() -> None:
    rendezvous = threading.Barrier(2)
    lock = threading.Lock()
    active = 0
    peak = 0

    def evaluate(
        state: dict[str, object],
        questions: dict[str, dict[str, object]],
        *,
        deadline: float | None = None,
    ) -> Evaluation:
        nonlocal active, peak
        assert state["query"] == "retry delivery"
        assert deadline is not None
        with lock:
            active += 1
            peak = max(peak, active)
        try:
            try:
                rendezvous.wait(timeout=1)
            except threading.BrokenBarrierError:
                pytest.fail("candidate batches must overlap within a bounded pair")
            return _evaluation([int(name.split("_")[0][1:]) for name in questions])
        finally:
            with lock:
                active -= 1

    with patch.object(policy.transport, "evaluate", side_effect=evaluate):
        ranked = _session().rank([_result(index) for index in range(32)])
    assert len(ranked) == 32
    assert peak == 2


def _evaluation(
    indices: list[int],
    *,
    useful: float = 0.8,
    confidence: float = 0.95,
    choice: str = "useful",
    clauses: int = 1,
) -> Evaluation:
    answers: dict[str, ChoiceAnswer | ScoreAnswer | NoulAnswer] = {}
    for index in indices:
        for clause in range(clauses):
            answers[f"c{index}_clause{clause}"] = ChoiceAnswer(
                choice,
                confidence,
                {"useful": useful, "not_useful": 1.0 - useful, "uncertain": 0.0},
            )
    return Evaluation(answers, "jev-1.13.0", 10, 10)


def _query(
    intent: str = "architecture", domain: str = "prod", confidence: float = 0.95
) -> Evaluation:
    values = {
        "intent": intent,
        "domain": domain,
        "wording": "natural_language",
        "evidence": "decision",
    }
    answers: dict[str, ChoiceAnswer | ScoreAnswer | NoulAnswer] = {
        name: ChoiceAnswer(value, confidence, {value: 1.0})
        for name, value in values.items()
    }
    answers["clarity"] = ScoreAnswer(2.0, confidence, {"0": 0.0, "1": 0.0, "2": 1.0})
    return Evaluation(answers, "jev-1.13.0", 10, 10)


def test_unavailable_key_never_evaluates() -> None:
    # Proven: bypassing availability fails this guard; restoring it passes.
    with (
        patch.object(policy.transport, "available", return_value=False),
        patch.object(policy.transport, "evaluate", return_value=_query()) as evaluate,
    ):
        assert policy.prepare_query("retry delivery", "code") is None
        evaluate.assert_not_called()


@pytest.mark.parametrize("query", ["", "  ", "x" * 24_000])
def test_empty_or_oversize_query_abstains(query: str) -> None:
    with (
        patch.object(policy.transport, "available", return_value=True),
        patch.object(policy.transport, "evaluate") as evaluate,
    ):
        assert policy.prepare_query(query, "code") is None
        evaluate.assert_not_called()


@pytest.mark.parametrize(
    "intent,domain,confidence,filters,expected",
    [
        ("architecture", "prod", 0.95, {}, ("orientation", "prod")),
        ("debugging", "tests", 0.95, {}, ("debugging", "tests")),
        ("architecture", "prod", 0.6, {}, (None, None)),
        ("cross_reference", "prod", 0.95, {}, (None, None)),
        ("architecture", "mixed", 0.95, {}, ("orientation", None)),
        ("architecture", "prod", 0.95, {"intent": "debugging"}, (None, None)),
        (
            "architecture",
            "prod",
            0.95,
            {"only_domains": ["tests"]},
            ("orientation", None),
        ),
    ],
)
def test_query_hints_respect_confidence_and_constraints(
    intent: str,
    domain: str,
    confidence: float,
    filters: dict[str, object],
    expected: tuple[str | None, str | None],
) -> None:
    query = "Why does this retry? only:tests"
    with (
        patch.object(policy.transport, "available", return_value=True),
        patch.object(
            policy.transport,
            "evaluate",
            return_value=_query(intent, domain, confidence),
        ) as evaluate,
    ):
        session = policy.prepare_query(query, "combined", filters)
    assert session is not None
    assert (session.vault_intent, session.prefer) == expected
    assert session.query == query
    assert session.timings["typesafe_requests"] == 1.0
    assert session.timings["typesafe_input_tokens"] == 10.0
    assert session.timings["typesafe_output_tokens"] == 10.0
    assessment = session.context["query_assessment"]
    assert assessment == {
        "intent": intent if confidence >= 0.85 else "unknown",
        "domain": domain if confidence >= 0.85 else "unknown",
        "wording": "natural_language" if confidence >= 0.85 else "unknown",
        "evidence": "decision" if confidence >= 0.85 else "unknown",
    }
    assert evaluate.call_args.args[0]["query"] == query
    assert set(evaluate.call_args.args[1]) == {
        "intent",
        "domain",
        "wording",
        "evidence",
        "clarity",
    }


def test_query_failure_abstains() -> None:
    with (
        patch.object(policy.transport, "available", return_value=True),
        patch.object(
            policy.transport,
            "evaluate",
            side_effect=TypesafeUnavailableError("payment"),
        ),
    ):
        assert policy.prepare_query("retry", "code") is None


def test_candidate_growth_does_not_reduce_legacy_budget() -> None:
    session = _session()
    assert session.candidate_limit(5, 10) == 32
    assert session.candidate_limit(10, 10) == 60
    assert session.candidate_limit(20, 10) == 64
    assert session.candidate_limit(20, 120) == 120


@pytest.mark.parametrize(
    "content,reason",
    [
        (None, "missing_content"),
        ("完整" * 24_000, "candidate_size"),
    ],
    ids=["missing", "oversize"],
)
def test_unscorable_window_falls_back_before_any_call(
    content: str | None, reason: str
) -> None:
    # Proven: substituting snippets bypasses oversize fallback; restoration passes.
    results = [_result(0), _result(1, content)]
    session = _session()
    with (
        patch.object(
            policy.transport, "evaluate", return_value=_evaluation([0, 1])
        ) as call,
        pytest.raises(TypesafeUnavailableError, match=reason),
    ):
        session.rank(results)
    call.assert_not_called()
    assert session.failed
    assert [result.score for result in results] == [0.5, 0.5]


def test_entire_content_and_metadata_reach_questions() -> None:
    result = _result(0, "start\n" + "complete content\n" * 100 + "END")
    result.path = "tests/test_retry.py"
    with patch.object(
        policy.transport, "evaluate", return_value=_evaluation([0])
    ) as call:
        ranked = _session().rank([result])
    state = call.call_args.args[0]
    assert state["candidates"]["c0"]["content"] == result.rerank_text
    assert state["candidates"]["c0"]["domain"] == "tests"
    assert ranked[0].score == pytest.approx(0.8)
    assert ranked[0] is not result
    assert result.score == 0.5


@pytest.mark.parametrize(
    "choice,confidence,useful,dropped",
    [
        ("not_useful", 0.95, 0.01, True),
        ("not_useful", 0.84, 0.01, False),
        ("not_useful", 0.95, 0.11, False),
        ("uncertain", 0.95, 0.01, False),
    ],
)
def test_drop_requires_confident_not_useful_choice(
    choice: str, confidence: float, useful: float, dropped: bool
) -> None:
    with patch.object(
        policy.transport,
        "evaluate",
        return_value=_evaluation(
            [0],
            useful=useful,
            confidence=confidence,
            choice=choice,
        ),
    ):
        ranked = _session().rank([_result(0)])
    assert len(ranked) == (0 if dropped else 1)


def test_any_useful_clause_preserves_evidence_and_sets_max_score() -> None:
    # Proven: changing all-clause rejection to any-clause fails; restoration passes.
    session = _session()
    session.query = "Inspect cache behavior; explain invalidation."
    count = len(query_clauses(session.query))
    answer = _evaluation([0], useful=0.01, choice="not_useful", clauses=count)
    answer.answers[f"c0_clause{count - 1}"] = ChoiceAnswer(
        "useful", 0.3, {"useful": 0.78, "not_useful": 0.12, "uncertain": 0.1}
    )
    with patch.object(policy.transport, "evaluate", return_value=answer):
        ranked = session.rank([_result(0)])
    assert len(ranked) == 1
    assert ranked[0].score == 0.78


def test_uncertainty_retains_evidence_but_soft_ranks_without_baseline_slots() -> None:
    # Proven: retaining raw retrieval scores fails the order; restoration passes.
    results = [_result(0), _result(1), _result(2)]
    results[0].score = 30
    answer = _evaluation([0, 1, 2], useful=0.9, confidence=0.3)
    answer.answers["c0_clause0"] = ChoiceAnswer(
        "uncertain", 0.2, {"useful": 0.2, "not_useful": 0.3, "uncertain": 0.5}
    )
    with patch.object(policy.transport, "evaluate", return_value=answer):
        ranked = _session().rank(results)
    assert [result.id for result in ranked] == ["1", "2", "0"]
    assert [result.score for result in ranked] == [0.9, 0.9, 0.2]
    assert [result.score for result in results] == [30, 0.5, 0.5]


def test_batch_failure_is_atomic() -> None:
    results = [_result(index) for index in range(10)]
    session = _session()
    with (
        patch.object(
            policy.transport,
            "evaluate",
            side_effect=[
                _evaluation(list(range(8))),
                TypesafeUnavailableError("timeout"),
            ],
        ),
        pytest.raises(TypesafeUnavailableError, match="timeout"),
    ):
        session.rank(results)
    assert session.failed
    assert [result.score for result in results] == [0.5] * 10


def test_request_and_session_bounds_preserve_complete_windows() -> None:
    session = _session()
    results = [_result(index, "完整证据" * 200) for index in range(64)]

    def evaluate(
        state: dict[str, object],
        questions: dict[str, dict[str, object]],
        *,
        deadline: float | None = None,
    ) -> Evaluation:
        assert (
            len(json.dumps({"state": state, "questions": questions}).encode()) < 64_000
        )
        assert deadline == session.deadline
        indices = sorted({int(key.split("_")[0][1:]) for key in questions})
        assert len(indices) <= 8
        return _evaluation(indices)

    with patch.object(policy.transport, "evaluate", side_effect=evaluate) as call:
        for _ in range(3):
            assert len(session.rank(results)) == 64
        before = call.call_count
        assert session.timings["typesafe_requests"] == float(before)
        assert session.timings["typesafe_input_tokens"] == float(before * 10)
        assert session.timings["typesafe_output_tokens"] == float(before * 10)
        with pytest.raises(TypesafeUnavailableError, match="candidate_budget"):
            session.rank(results)
        assert call.call_count == before
    assert session.evaluated == 192
    assert session.timings["typesafe_abstained"] == 64


def test_compound_questions_fit_eight_complete_candidates() -> None:
    session = _session()
    clauses = (
        "Find the first behavior; explain the second; verify the third.",
        "the first behavior",
        "the second behavior",
        "the third behavior",
    )
    batches = session._batches(
        [_result(index, "evidence " * 200) for index in range(8)], clauses
    )
    assert len(batches) == 1
    assert batches[0][1] == list(range(8))


def test_overlarge_window_never_mixes_unscored_results() -> None:
    # Proven: allowing one extra candidate misses this raise; restoration passes.
    with (
        patch.object(
            policy.transport, "evaluate", return_value=_evaluation(list(range(65)))
        ) as call,
        pytest.raises(TypesafeUnavailableError, match="candidate_budget"),
    ):
        _session().rank([_result(index) for index in range(65)])
    call.assert_not_called()


def test_document_identity_and_locators_survive_score_replacement() -> None:
    result = DocumentSearchResult(
        id="a",
        path="guide.pdf",
        title="Guide",
        score=0.1,
        snippet="display",
        anchor="page=2",
        rerank_text="full",
    )
    with patch.object(
        policy.transport, "evaluate", return_value=_evaluation([0])
    ) as call:
        ranked = _session().rank([result])
    assert ranked[0].anchor == "page=2"
    assert ranked[0].id == "a"
    assert call.call_args.args[0]["candidates"]["c0"]["domain"] == "docs"


@pytest.mark.parametrize(
    "query",
    [
        "plain_identifier",
        "Explain both source and destination",
        "Find the cache and explain the eviction. Why did it fail?",
        "Inspect 缓存;verify 状态;explain 失效",
        "a.b(c);\nlook elsewhere",
        "  Original whitespace.\nSecond sentence?  ",
        "Look at the effect and the cause and the resolution.",
        "First. Second. Third. Fourth. Fifth. Sixth. Seventh.",
    ],
)
def test_clauses_are_bounded_verbatim_and_keep_whole_query(query: str) -> None:
    clauses = query_clauses(query)
    assert clauses[0] == query
    assert 1 <= len(clauses) <= 6
    assert all(clause in query for clause in clauses)
    assert len(set(clauses)) == len(clauses)


def test_clause_overflow_keeps_whole_query_including_late_request() -> None:
    # Proven: truncating excerpts discards late requests; restoration passes.
    query = "; ".join(f"Explain request {number}" for number in range(20))
    assert query_clauses(query) == (query,)


def test_compound_requests_produce_local_excerpts_without_removing_coverage() -> None:
    query = "Find both the cache lookup and the eviction behavior. Verify the callback."
    clauses = query_clauses(query)
    assert clauses == (
        query,
        "the cache lookup",
        "the eviction behavior",
        "Verify the callback",
    )
    questions = candidate_questions([2], clauses)
    assert len(questions) == len(clauses)
    for index, clause in enumerate(clauses):
        question = questions[f"c2_clause{index}"]
        assert repr(clause) in str(question["instructions"])
        assert "state.candidates.c2.content" in str(question["instructions"])
        assert question["type"] == "choice"


@pytest.mark.parametrize(
    "prefix",
    [
        "Find both",
        "Locate",
        "Show me",
        "Explain",
        "Describe",
        "Identify",
        "Trace",
        "Please find both",
        "Find please",
        "Please show me both",
    ],
)
def test_extracted_request_boilerplate_is_removed_verbatim(prefix: str) -> None:
    query = f"{prefix} the request path. Explain whether the callback handles errors?"
    assert query_clauses(query) == (
        query,
        "the request path",
        "the callback handles errors",
    )
    assert all(clause in query for clause in query_clauses(query))


@pytest.mark.parametrize(
    "query",
    [
        "Find both the request and response.",
        "  Explain whether the callback handles errors?  ",
        "find(); explain(); trace()",
        "if ready:\n    find(); explain()",
        "if (ready) { find(); explain(); }",
        "\u0060\u0060\u0060python\nfind(); explain()\n\u0060\u0060\u0060",
    ],
)
def test_single_clause_and_code_queries_keep_original_only(query: str) -> None:
    # Proven: bypassing these guards adds changed excerpts; restoration passes.
    assert query_clauses(query) == (query,)


def test_empty_normalized_excerpt_is_omitted_without_losing_original() -> None:
    query = "Explain. Find the request path."
    assert query_clauses(query) == (query, "the request path")


@pytest.mark.parametrize("marker", ["whether", "Whether", "WHETHER"])
def test_only_leading_whether_is_removed_from_extracted_proposition(
    marker: str,
) -> None:
    query = f"Explain {marker} flags determine whether to retry; Locate the caller."
    clauses = query_clauses(query)
    assert clauses == (query, "flags determine whether to retry", "the caller")
    assert all(clause in query for clause in clauses)


def test_nonleading_whether_and_original_are_preserved_verbatim() -> None:
    # Proven: removing the prefix anchor loses an internal word; restoration passes.
    query = "Check whether flags control retries; Explain whether errors are handled."
    assert query_clauses(query) == (
        query,
        "Check whether flags control retries",
        "errors are handled",
    )
