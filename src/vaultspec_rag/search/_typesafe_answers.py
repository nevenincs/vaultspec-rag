"""Validate hosted judgments against the complete submitted question contract."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import cast

MODEL = "jev-1.13.0"


@dataclass(frozen=True)
class ChoiceAnswer:
    choice: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class ScoreAnswer:
    score: float
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class NoulAnswer:
    noul: float


type Answer = ChoiceAnswer | ScoreAnswer | NoulAnswer


@dataclass(frozen=True)
class Evaluation:
    answers: dict[str, Answer]
    model: str
    input_tokens: int
    output_tokens: int


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("invalid_mapping")
    items = cast("dict[object, object]", value)
    if any(not isinstance(key, str) for key in items):
        raise ValueError("invalid_keys")
    return cast("dict[str, object]", items)


def _number(value: object, upper: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("invalid_number")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= upper:
        raise ValueError("invalid_range")
    return result


def _distribution(value: object, keys: set[str]) -> dict[str, float]:
    raw = _mapping(value)
    if set(raw) != keys or not keys:
        raise ValueError("invalid_probability_keys")
    result = {key: _number(probability) for key, probability in raw.items()}
    if abs(sum(result.values()) - 1.0) > 0.03:
        raise ValueError("invalid_probability_sum")
    return result


def _answer(raw: object, question: dict[str, object]) -> Answer:
    answer = _mapping(raw)
    kind = question.get("type")
    if answer.get("type") != kind:
        raise ValueError("invalid_answer_type")
    if kind == "noul":
        if set(answer) != {"type", "noul"}:
            raise ValueError("invalid_answer_fields")
        return NoulAnswer(_number(answer["noul"]))
    if kind == "choice":
        if set(answer) != {"type", "choice", "confidence", "probabilities"}:
            raise ValueError("invalid_answer_fields")
        probabilities = _distribution(
            answer["probabilities"], set(_mapping(question.get("criteria")))
        )
        choice = answer["choice"]
        if not isinstance(choice, str) or choice not in probabilities:
            raise ValueError("invalid_choice")
        if probabilities[choice] < max(probabilities.values()):
            raise ValueError("invalid_choice_probability")
        return ChoiceAnswer(choice, _number(answer["confidence"]), probabilities)
    if kind == "score":
        return _score(answer, question)
    raise ValueError("invalid_question_type")


def _score(answer: dict[str, object], question: dict[str, object]) -> ScoreAnswer:
    if set(answer) != {"type", "score", "confidence", "probabilities", "legend"}:
        raise ValueError("invalid_answer_fields")
    raw_levels = question.get("criteria")
    if not isinstance(raw_levels, list):
        raise ValueError("invalid_levels")
    levels = cast("list[object]", raw_levels)
    if not 2 <= len(levels) <= 10:
        raise ValueError("invalid_level_count")
    legend = _mapping(answer["legend"])
    expected = {str(index): description for index, description in enumerate(levels)}
    if legend != expected:
        raise ValueError("invalid_legend")
    probabilities = _distribution(answer["probabilities"], set(expected))
    score = _number(answer["score"], len(levels) - 1)
    expectation = sum(int(level) * value for level, value in probabilities.items())
    if abs(score - expectation) > 0.03 * (len(levels) - 1) + 0.01:
        raise ValueError("invalid_score_expectation")
    return ScoreAnswer(
        score,
        _number(answer["confidence"]),
        probabilities,
    )


def _tokens(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("invalid_usage")
    return value


def validate_evaluation(
    raw: object, questions: dict[str, dict[str, object]]
) -> Evaluation:
    """Reject the whole evaluation if any judgment violates its request."""
    envelope = _mapping(raw)
    if envelope.get("model") != MODEL:
        raise ValueError("invalid_model")
    answers = _mapping(envelope.get("answers"))
    if not questions or set(answers) != set(questions):
        raise ValueError("invalid_answer_ids")
    usage = _mapping(envelope.get("usage"))
    return Evaluation(
        {key: _answer(answers[key], question) for key, question in questions.items()},
        MODEL,
        _tokens(usage.get("input_tokens")),
        _tokens(usage.get("output_tokens")),
    )
