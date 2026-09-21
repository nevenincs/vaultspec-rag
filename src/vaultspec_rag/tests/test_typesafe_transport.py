"""GPU-free provider contracts and real loopback HTTP boundary checks.

Guard mutation evidence: bypassing response validation failed all 21 invalid-schema
cases; allowing absent credentials failed enrollment; disabling circuit writes
failed all 11 failure cases; enlarging either byte cap failed its exact reason
assertion; removing redirect refusal failed all five redirect cases; widening the
Score expectation tolerance failed the contradictory score/distribution case.
Each mutation was restored and its selected tests passed immediately afterward.
Releasing the network slot before completion failed the occupied-slot assertion;
applying a stale failure to the current credential failed rotated-key availability.
Both passed again with the original functions restored.
"""

from __future__ import annotations

import copy
import json
import threading
import time
import urllib.error
from contextlib import contextmanager
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, cast, override

import pytest

from ..config._types import EnvVar
from ..search import _typesafe_transport as transport
from ..search._typesafe_answers import (
    MODEL,
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    validate_evaluation,
)

if TYPE_CHECKING:
    from collections.abc import Generator

pytestmark = pytest.mark.unit
QUESTIONS: dict[str, dict[str, object]] = {
    "intent": {
        "type": "choice",
        "instructions": "Pick",
        "criteria": {"a": "A", "b": "B"},
    },
    "use": {"type": "score", "instructions": "Rate", "criteria": ["Low", "High"]},
    "relevant": {"type": "noul", "instructions": "Relevant?"},
}


def _answers() -> dict[str, dict[str, object]]:
    return {
        "intent": {
            "type": "choice",
            "choice": "a",
            "confidence": 0.99,
            "probabilities": {"a": 1.0, "b": 0.0},
        },
        "use": {
            "type": "score",
            "score": 0.8,
            "confidence": 0.6,
            "probabilities": {"0": 0.2, "1": 0.8},
            "legend": {"0": "Low", "1": "High"},
        },
        "relevant": {"type": "noul", "noul": 0.9},
    }


def _envelope(answers: object = None) -> dict[str, object]:
    return {
        "model": MODEL,
        "answers": _answers() if answers is None else answers,
        "usage": {"input_tokens": 100, "output_tokens": 20},
    }


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "synthetic-credential")
    monkeypatch.setattr(transport, "_ENDPOINT", "http://127.0.0.1:1/never-external")
    monkeypatch.setattr(transport, "_CIRCUIT", transport._Circuit())
    monkeypatch.setattr(transport, "_SLOTS", threading.BoundedSemaphore(2))


def test_typed_complete_response_and_rounded_probabilities() -> None:
    answers = _answers()
    answers["intent"]["probabilities"] = {"a": 0.67, "b": 0.34}
    evaluated = validate_evaluation(_envelope(answers), QUESTIONS)
    assert evaluated.answers["intent"] == ChoiceAnswer(
        "a", 0.99, {"a": 0.67, "b": 0.34}
    )
    assert evaluated.answers["use"] == ScoreAnswer(0.8, 0.6, {"0": 0.2, "1": 0.8})
    assert evaluated.answers["relevant"] == NoulAnswer(0.9)
    assert evaluated.input_tokens == 100


@pytest.mark.parametrize(
    ("question", "field", "value"),
    [
        ("relevant", "noul", True),
        ("relevant", "noul", float("nan")),
        ("relevant", "noul", float("inf")),
        ("relevant", "noul", -0.1),
        ("relevant", "noul", 1.1),
        ("intent", "confidence", "0.9"),
        ("intent", "choice", "unknown"),
        ("intent", "choice", "b"),
        ("intent", "probabilities", {"a": 0.5}),
        ("intent", "probabilities", {"a": 0.5, "b": 0.4}),
        ("intent", "probabilities", {"a": 1.1, "b": -0.1}),
        ("use", "score", 2),
        ("use", "score", 0),
        ("use", "type", "choice"),
        ("use", "legend", {"0": "Low", "2": "High"}),
        ("use", "legend", {"0": "Changed", "1": "High"}),
        ("use", "probabilities", {"0": 0.2, "2": 0.8}),
    ],
)
def test_invalid_answer_rejects_entire_evaluation(
    question: str, field: str, value: object
) -> None:
    answers = _answers()
    answers[question][field] = value
    with pytest.raises(ValueError):
        validate_evaluation(_envelope(answers), QUESTIONS)


@pytest.mark.parametrize(
    "mutation", ["missing_id", "extra_id", "field", "model", "usage"]
)
def test_incomplete_or_foreign_envelopes(mutation: str) -> None:
    answers = _answers()
    envelope = _envelope(answers)
    if mutation == "missing_id":
        del answers["relevant"]
    elif mutation == "extra_id":
        answers["other"] = answers["relevant"]
    elif mutation == "field":
        del answers["intent"]["confidence"]
    elif mutation == "model":
        envelope["model"] = "jev-latest"
    else:
        envelope["usage"] = {"input_tokens": True, "output_tokens": 20}
    with pytest.raises(ValueError):
        validate_evaluation(envelope, QUESTIONS)


def test_no_key_never_constructs_client(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(EnvVar.TYPESAFE_API_KEY)
    monkeypatch.setenv("TYPESAFE_API_KEY", "generic-must-not-enroll")
    calls: list[object] = []

    def opener(*args: object) -> None:
        calls.append(args)

    monkeypatch.setattr(transport.urllib.request, "build_opener", opener)
    assert not transport.available()
    with pytest.raises(transport.TypesafeUnavailableError, match=r"^no_key$"):
        transport.evaluate({}, QUESTIONS)
    assert calls == []


@pytest.mark.parametrize("status", [401, 402, 403, 429, 500, 529])
def test_status_circuit_and_rotation(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    calls: list[str] = []

    def request(key: str, _payload: bytes, _deadline: float) -> bytes:
        calls.append(key)
        raise urllib.error.HTTPError(
            "http://unused", status, "sensitive", Message(), None
        )

    monkeypatch.setattr(transport, "_request", request)
    with pytest.raises(transport.TypesafeUnavailableError):
        transport.evaluate({}, QUESTIONS)
    assert not transport.available()
    with pytest.raises(transport.TypesafeUnavailableError):
        transport.evaluate({}, QUESTIONS)
    assert calls == ["synthetic-credential"]
    transport._CIRCUIT.retry_at = 0
    assert transport.available() is (status not in {401, 402, 403})
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "rotated-synthetic-credential")
    assert transport.available()


@pytest.mark.parametrize("body", [b"not json", b"{}", b'{"model":"jev-1.13.0"}'])
def test_invalid_body_cools_down(monkeypatch: pytest.MonkeyPatch, body: bytes) -> None:
    def request(_key: str, _payload: bytes, _deadline: float) -> bytes:
        return body

    monkeypatch.setattr(transport, "_request", request)
    with pytest.raises(
        transport.TypesafeUnavailableError, match="invalid_or_unreachable"
    ):
        transport.evaluate({}, QUESTIONS)
    assert not transport.available()


@pytest.mark.parametrize(
    "error", [OSError("sensitive"), transport.HTTPException("sensitive")]
)
def test_network_failure_is_safe(
    monkeypatch: pytest.MonkeyPatch, error: Exception
) -> None:
    def request(_key: str, _payload: bytes, _deadline: float) -> bytes:
        raise error

    monkeypatch.setattr(transport, "_request", request)
    with pytest.raises(transport.TypesafeUnavailableError) as caught:
        transport.evaluate({}, QUESTIONS)
    assert str(caught.value) == "invalid_or_unreachable"
    assert "sensitive" not in repr(caught.value)
    assert not transport.available()


def test_request_size_and_expired_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "MAX_REQUEST_BYTES", 20)
    with pytest.raises(transport.TypesafeUnavailableError, match=r"^request_size$"):
        transport.evaluate({}, QUESTIONS)
    with pytest.raises(transport.TypesafeUnavailableError, match=r"^deadline$"):
        transport.evaluate({}, QUESTIONS, deadline=time.monotonic() - 1)
    assert transport.available()


def test_deadline_and_concurrency_remain_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finish = threading.Event()
    ended = threading.Event()

    def request(_key: str, _payload: bytes, _deadline: float) -> bytes:
        finish.wait(2)
        ended.set()
        return json.dumps(_envelope()).encode()

    monkeypatch.setattr(transport, "_request", request)
    slots = threading.BoundedSemaphore(1)
    monkeypatch.setattr(transport, "_SLOTS", slots)
    try:
        started = time.monotonic()
        with pytest.raises(transport.TypesafeUnavailableError, match=r"^deadline$"):
            transport.evaluate({}, QUESTIONS, deadline=started + 0.03)
        assert time.monotonic() - started < 0.5
        assert not slots.acquire(blocking=False)
        # A spent search budget is not evidence that the provider is unavailable.
        assert transport.available()
        with pytest.raises(transport.TypesafeUnavailableError, match=r"^busy$"):
            transport.evaluate({}, QUESTIONS)
    finally:
        finish.set()
        assert ended.wait(1)
        assert slots.acquire(timeout=1)
        slots.release()
    assert transport.available()


@contextmanager
def _server(
    monkeypatch: pytest.MonkeyPatch, status: int, body: bytes
) -> Generator[list[dict[str, object]]]:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        @override
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            raw: object = json.loads(
                self.rfile.read(int(self.headers["Content-Length"]))
            )
            received.append(cast("dict[str, object]", raw))
            self.send_response(status)
            self.send_header("Location", "/must-not-follow")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr(
        transport, "_ENDPOINT", f"http://127.0.0.1:{server.server_port}/evaluate"
    )
    try:
        yield received
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=1)


def test_real_http_request_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    with _server(monkeypatch, 200, json.dumps(_envelope()).encode()) as received:
        assert transport.evaluate({"query": "synthetic"}, QUESTIONS).model == MODEL
        assert transport.available()
    assert received == [
        {"model": MODEL, "state": {"query": "synthetic"}, "questions": QUESTIONS}
    ]


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_redirect_never_forwards_credentials(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    with (
        _server(monkeypatch, status, b"") as received,
        pytest.raises(transport.TypesafeUnavailableError, match=r"^redirect$"),
    ):
        transport.evaluate({}, QUESTIONS)
    assert len(received) == 1


def test_real_http_response_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(transport, "MAX_RESPONSE_BYTES", 100)
    with (
        _server(monkeypatch, 200, b"x" * 101),
        pytest.raises(transport.TypesafeUnavailableError, match=r"^response_size$"),
    ):
        transport.evaluate({}, QUESTIONS)


def test_stale_failure_does_not_disable_rotated_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, old = transport._credential()
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "new-synthetic")
    assert transport.available()
    transport._failed(old, permanent=True)
    assert transport.available()


def test_validation_does_not_modify_submitted_contract() -> None:
    original = copy.deepcopy(QUESTIONS)
    validate_evaluation(_envelope(), QUESTIONS)
    assert original == QUESTIONS
