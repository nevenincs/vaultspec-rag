"""Bounded hosted classification with conservative, atomic ranking decisions."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING

from .._domain import classify_domain
from . import _typesafe_transport as transport
from ._models import DocumentSearchResult, SearchResult
from ._typesafe_answers import ChoiceAnswer, Evaluation, ScoreAnswer
from ._typesafe_questions import candidate_questions, query_clauses, query_questions

if TYPE_CHECKING:
    from collections.abc import Sequence

_MAX_CANDIDATES = 64
_MAX_BATCH = 8
_REQUEST_BYTES = 24_000
_SESSION_SECONDS = 10.0


def classification_window[T: (SearchResult, DocumentSearchResult)](
    results: list[T], top_k: int
) -> list[T]:
    """Select full-content evidence after local ranking, not before retrieval.

    Path filtering needs retrieval headroom independent of hosted capacity.
    Reserve room for rejection without mixing unclassified tail scores into
    the returned page. Requests exceeding hosted capacity still abstain.
    """
    limit = max(top_k, min(_MAX_CANDIDATES, max(32, top_k * 2)))
    return results[:limit]


def _fits(state: dict[str, object], questions: dict[str, dict[str, object]]) -> bool:
    # Reserve room for the pinned model and transport envelope; include JSON escapes.
    try:
        payload = json.dumps(
            {"state": state, "questions": questions}, ensure_ascii=True, allow_nan=False
        )
    except (TypeError, ValueError):
        return False
    return len(payload.encode("utf-8")) + 256 <= _REQUEST_BYTES


def _choice(evaluation: Evaluation, name: str) -> str | None:
    answer = evaluation.answers[name]
    if isinstance(answer, ChoiceAnswer) and answer.confidence >= 0.85:
        return answer.choice
    return None


def prepare_query(
    query: str, surface: str, filters: dict[str, object] | None = None
) -> ClassificationSession | None:
    """Probe credential usability with the query's independent typed questions."""
    if not query.strip() or not transport.available():
        return None
    started = time.monotonic()
    context: dict[str, object] = {
        "query": query,
        "surface": surface,
        "constraints": dict(filters or {}),
    }
    questions = query_questions()
    if not _fits(context, questions):
        return None
    deadline = started + _SESSION_SECONDS
    try:
        evaluation = transport.evaluate(context, questions, deadline=deadline)
    except transport.TypesafeUnavailableError:
        return None
    intent = _choice(evaluation, "intent")
    domain = _choice(evaluation, "domain")
    context["query_assessment"] = {
        name: _choice(evaluation, name) or "unknown"
        for name in ("intent", "wording", "evidence", "domain")
    }
    constraints = filters or {}
    vault_intent = {"architecture": "orientation", "debugging": "debugging"}.get(
        intent or ""
    )
    if any(constraints.get(key) for key in ("intent", "doc_type", "type", "status")):
        vault_intent = None
    prefer = domain if domain in {"prod", "tests", "docs"} else None
    if intent == "cross_reference" or domain == "mixed" or any(constraints.values()):
        prefer = None
    timings = {
        "typesafe_query_ms": (time.monotonic() - started) * 1000,
        "typesafe_requests": 1.0,
        "typesafe_input_tokens": float(evaluation.input_tokens),
        "typesafe_output_tokens": float(evaluation.output_tokens),
    }
    for name, answer in evaluation.answers.items():
        if isinstance(answer, (ChoiceAnswer, ScoreAnswer)):
            timings[f"typesafe_{name}_confidence"] = answer.confidence
    return ClassificationSession(
        query=query,
        context=context,
        deadline=deadline,
        vault_intent=vault_intent,
        prefer=prefer,
        timings=timings,
    )


def _candidate(result: SearchResult | DocumentSearchResult) -> dict[str, object]:
    candidate: dict[str, object] = {
        "content": result.rerank_text,
        "source": result.source,
        "path": result.path,
        "domain": classify_domain(result.path)
        if result.source == "codebase"
        else "docs",
    }
    if isinstance(result, SearchResult):
        candidate.update(doc_type=result.doc_type, status=result.status)
    return candidate


def _judgment(
    evaluation: Evaluation, index: int, clause_count: int
) -> tuple[bool, float]:
    answers: list[ChoiceAnswer] = []
    for clause_index in range(clause_count):
        answer = evaluation.answers[f"c{index}_clause{clause_index}"]
        if not isinstance(answer, ChoiceAnswer):
            raise transport.TypesafeUnavailableError("invalid_answers")
        answers.append(answer)
    drop = all(
        answer.choice == "not_useful"
        and answer.confidence >= 0.85
        and answer.probabilities["not_useful"] >= 0.9
        for answer in answers
    )
    return drop, max(answer.probabilities["useful"] for answer in answers)


@dataclass
class ClassificationSession:
    """Query interpretation and one shared deadline for all candidate windows."""

    query: str
    context: dict[str, object]
    deadline: float
    vault_intent: str | None = None
    prefer: str | None = None
    timings: dict[str, float] = field(default_factory=dict)
    failed: bool = False
    evaluated: int = 0

    def candidate_limit(self, top_k: int, legacy_limit: int) -> int:
        """Grow only the hosted window without reducing a larger legacy budget."""
        return max(legacy_limit, min(_MAX_CANDIDATES, max(legacy_limit, top_k * 6, 32)))

    def _batches(
        self,
        results: Sequence[SearchResult | DocumentSearchResult],
        clauses: tuple[str, ...],
    ) -> list[tuple[dict[str, object], list[int]]]:
        batches: list[tuple[dict[str, object], list[int]]] = []
        candidates: dict[str, object] = {}
        indices: list[int] = []
        limit = min(_MAX_CANDIDATES, max(0, 192 - self.evaluated))
        if len(results) > limit:
            raise transport.TypesafeUnavailableError("candidate_budget")
        for index, result in enumerate(results):
            if not result.rerank_text:
                raise transport.TypesafeUnavailableError("missing_content")
            candidate = _candidate(result)
            single = {**self.context, "candidates": {f"c{index}": candidate}}
            if not _fits(single, candidate_questions([index], clauses)):
                raise transport.TypesafeUnavailableError("candidate_size")
            proposed = {**candidates, f"c{index}": candidate}
            state = {**self.context, "candidates": proposed}
            if len(indices) >= _MAX_BATCH or not _fits(
                state, candidate_questions([*indices, index], clauses)
            ):
                batches.append(({**self.context, "candidates": candidates}, indices))
                candidates, indices = {}, []
            candidates[f"c{index}"] = candidate
            indices.append(index)
        if indices:
            batches.append(({**self.context, "candidates": candidates}, indices))
        return batches

    def rank[T: (SearchResult, DocumentSearchResult)](
        self, results: list[T]
    ) -> list[T]:
        """Soft-rank all candidates; uncertainty prevents drops, not score updates."""
        started = time.monotonic()
        judgments: dict[int, tuple[bool, float]] = {}
        clauses = query_clauses(self.query)
        try:
            if self.failed:
                raise transport.TypesafeUnavailableError("session_failed")
            for state, indices in self._batches(results, clauses):
                evaluation = transport.evaluate(
                    state, candidate_questions(indices, clauses), deadline=self.deadline
                )
                self.evaluated += len(indices)
                self.timings["typesafe_requests"] = (
                    self.timings.get("typesafe_requests", 0.0) + 1
                )
                for name, count in (
                    ("typesafe_input_tokens", evaluation.input_tokens),
                    ("typesafe_output_tokens", evaluation.output_tokens),
                ):
                    self.timings[name] = self.timings.get(name, 0.0) + count
                for index in indices:
                    judgments[index] = _judgment(evaluation, index, len(clauses))
        except transport.TypesafeUnavailableError:
            self.failed = True
            self.timings["typesafe_abstained"] = float(len(results))
            raise
        finally:
            self.timings["typesafe_rank_ms"] = (
                self.timings.get("typesafe_rank_ms", 0.0)
                + (time.monotonic() - started) * 1000
            )
        self.timings["typesafe_candidates"] = float(self.evaluated)
        self.timings["typesafe_clauses"] = float(len(clauses))
        survivors: list[T] = []
        dropped = 0
        for index, result in enumerate(results):
            drop, score = judgments[index]
            if drop:
                dropped += 1
            else:
                survivors.append(replace(result, score=score))
        self.timings["typesafe_dropped"] = (
            self.timings.get("typesafe_dropped", 0.0) + dropped
        )
        return sorted(survivors, key=lambda result: result.score, reverse=True)
