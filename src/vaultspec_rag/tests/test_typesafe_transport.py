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
Cache/pool guards were mutation-proven: ignoring expiry returned an expired body;
discarding reusable sockets failed the reuse assertion; omitting payload from the
cache key reused answers after content changed. Each selected test failed at its
named assertion, then passed immediately after restoration.
The incomplete-frame guard failed (no exception) before its framing check was
added, then passed: valid JSON is insufficient when declared bytes are missing.
"""

from __future__ import annotations

import copy
import json
import threading
import time
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from email.message import Message
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, cast, override

import pytest

from ..config._types import EnvVar
from ..operator_state._features import TypesafeState
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
    monkeypatch.setattr(transport, "_CACHE", transport.ResponseCache())
    monkeypatch.setattr(transport, "_POOL", transport.ConnectionPool())
    monkeypatch.setattr(transport, "_FLIGHTS", {})


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


def test_enrollment_status_is_redacted_and_never_probes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Inserting a status-side _request failed the no-call guard; restored passed."""

    def forbidden(*_args: object, **_kwargs: object) -> bytes:
        raise AssertionError("status must not make a provider call")

    monkeypatch.setattr(transport, "_request", forbidden)
    transport._credential()
    pending = transport.enrollment_status()
    assert pending.state is TypesafeState.PENDING
    assert "synthetic-credential" not in pending.model_dump_json()
    transport._CIRCUIT.last_success = time.monotonic()
    assert transport.enrollment_status().state is TypesafeState.ACTIVE
    transport._CIRCUIT.last_success -= 61
    assert transport.enrollment_status().state is TypesafeState.PENDING
    transport._failed(transport._credential()[1])
    assert transport.enrollment_status().state is TypesafeState.COOLDOWN
    transport._CIRCUIT.disabled = True
    assert transport.enrollment_status().state is TypesafeState.REJECTED
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "replacement")
    assert transport.enrollment_status().state is TypesafeState.PENDING
    monkeypatch.delenv(EnvVar.TYPESAFE_API_KEY)
    off = transport.enrollment_status()
    assert off.state is TypesafeState.OFF and not off.state.is_enabled


def test_reading_enrollment_never_resets_the_circuit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A status poll must not clear a rejection the request path recorded.

    Mutation check: resolving the credential inside the status read, as it
    once did, resets the circuit on the key change and fails the ``disabled``
    assertion; restoring the pure read passes.
    """
    transport._credential()
    transport._CIRCUIT.disabled = True
    monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "replacement")

    assert transport.enrollment_status().state is TypesafeState.PENDING
    assert transport._CIRCUIT.disabled is True


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

    monkeypatch.setattr(transport._POOL, "acquire", opener)
    assert not transport.available()
    with pytest.raises(transport.TypesafeUnavailableError, match=r"^no_key$"):
        transport.evaluate({}, QUESTIONS)
    assert calls == []


@pytest.mark.parametrize("status", [401, 402, 403, 429, 500, 529])
def test_status_circuit_and_rotation(
    monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    calls: list[str] = []

    def request(
        key: str, _payload: bytes, _deadline: float, **_kwargs: object
    ) -> bytes:
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
    def request(
        _key: str, _payload: bytes, _deadline: float, **_kwargs: object
    ) -> bytes:
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
    def request(
        _key: str, _payload: bytes, _deadline: float, **_kwargs: object
    ) -> bytes:
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


@pytest.mark.parametrize("search_limited", [True, False])
def test_wrapped_timeout_only_cools_down_provider_budget(
    monkeypatch: pytest.MonkeyPatch, search_limited: bool
) -> None:
    def request(
        _key: str, _payload: bytes, _deadline: float, **_kwargs: object
    ) -> bytes:
        raise urllib.error.URLError(TimeoutError("sensitive"))

    monkeypatch.setattr(transport, "_request", request)
    deadline = time.monotonic() + (1 if search_limited else 10)
    with pytest.raises(transport.TypesafeUnavailableError):
        transport.evaluate({}, QUESTIONS, deadline=deadline)
    assert transport.available() is search_limited


def test_deadline_and_concurrency_remain_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    finish = threading.Event()
    ended = threading.Event()

    def request(
        _key: str, _payload: bytes, _deadline: float, **_kwargs: object
    ) -> bytes:
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
            transport.evaluate({"distinct": True}, QUESTIONS)
    finally:
        finish.set()
        assert ended.wait(1)
        assert slots.acquire(timeout=1)
        slots.release()
    assert transport.available()


@contextmanager
def _server(
    monkeypatch: pytest.MonkeyPatch,
    status: int,
    body: bytes,
    ports: list[int] | None = None,
) -> Generator[list[dict[str, object]]]:
    received: list[dict[str, object]] = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        @override
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_POST(self) -> None:
            if ports is not None:
                ports.append(self.client_address[1])
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
        transport._POOL.close()
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


def test_incomplete_http_frame_is_not_cached(monkeypatch: pytest.MonkeyPatch) -> None:
    original = BaseHTTPRequestHandler.send_header

    def header(handler: BaseHTTPRequestHandler, name: str, value: str) -> None:
        if name == "Content-Length":
            value = str(int(value) + 5)
            original(handler, "Connection", "close")
        original(handler, name, value)

    monkeypatch.setattr(BaseHTTPRequestHandler, "send_header", header)
    with (
        _server(monkeypatch, 200, json.dumps(_envelope()).encode()),
        pytest.raises(
            transport.TypesafeUnavailableError, match="invalid_or_unreachable"
        ),
    ):
        transport.evaluate({}, QUESTIONS)
    assert not transport._CACHE.values


def test_validation_does_not_modify_submitted_contract() -> None:
    original = copy.deepcopy(QUESTIONS)
    validate_evaluation(_envelope(), QUESTIONS)
    assert original == QUESTIONS


def test_persistent_connection_and_exact_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    ports: list[int] = []
    with _server(monkeypatch, 200, json.dumps(_envelope()).encode(), ports) as received:
        first = transport.evaluate({"query": "one"}, QUESTIONS)
        assert transport.enrollment_status().state is TypesafeState.ACTIVE
        second = transport.evaluate({"query": "two"}, QUESTIONS)
        cached = transport.evaluate({"query": "one"}, QUESTIONS)
        assert first.timings["connections_reused"] == 0
        assert second.timings["connections_reused"] == 1
        assert first.requests == second.requests == 1
        assert cached.requests == cached.input_tokens == cached.output_tokens == 0
        assert cached.cache_hits == 1
        assert len(received) == 2
        assert ports[0] == ports[1]
        cached.answers.clear()
        assert transport.evaluate({"query": "one"}, QUESTIONS).answers
        transport._failed(transport._credential()[1], permanent=True)
        with pytest.raises(
            transport.TypesafeUnavailableError, match="credential_disabled"
        ):
            transport.evaluate({"query": "one"}, QUESTIONS)
        monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "replacement")
        rotated = transport.evaluate({"query": "one"}, QUESTIONS)
        assert rotated.requests == 1
        assert rotated.timings["connections_reused"] == 0
        assert len(received) == 3
        monkeypatch.delenv(EnvVar.TYPESAFE_API_KEY)
        with pytest.raises(transport.TypesafeUnavailableError, match="no_key"):
            transport.evaluate({"query": "one"}, QUESTIONS)


def test_cache_covers_complete_state_and_questions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _server(monkeypatch, 200, json.dumps(_envelope()).encode()) as received:
        for state in (
            {"content": "old"},
            {"content": "new"},
            {"content": "new", "only": "prod"},
        ):
            assert transport.evaluate(dict(state), QUESTIONS).requests == 1
        questions = copy.deepcopy(QUESTIONS)
        questions["intent"]["instructions"] = "Different instruction"
        assert transport.evaluate({"content": "new"}, questions).requests == 1
        assert len(received) == 4


def test_cache_absolute_expiry_and_memory_bounds() -> None:
    cache = transport.ResponseCache(ttl=10, entries=2, byte_limit=4)
    cache.put(b"a", b"12", 0)
    assert cache.get(b"a", 9) == b"12"
    assert cache.get(b"a", 10) is None
    assert cache.size == 0
    cache.put(b"a", b"1", 10)
    cache.put(b"b", b"2", 10)
    assert cache.get(b"a", 11) == b"1"
    cache.put(b"c", b"3", 11)
    assert cache.get(b"b", 11) is None
    cache.put(b"d", b"1234", 11)
    assert list(cache.values) == [b"d"]
    cache.put(b"e", b"12345", 11)
    assert cache.size == 4
    cache.clear()
    assert not cache.values and cache.size == 0


def test_duplicate_waiter_timeout_does_not_cancel_paid_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, finish = threading.Event(), threading.Event()
    calls: list[bytes] = []

    def request(
        _key: str, payload: bytes, _deadline: float, **_kwargs: object
    ) -> bytes:
        calls.append(payload)
        entered.set()
        assert finish.wait(2)
        return json.dumps(_envelope()).encode()

    monkeypatch.setattr(transport, "_request", request)
    with ThreadPoolExecutor(max_workers=2) as executor:
        owner = executor.submit(transport.evaluate, {}, QUESTIONS)
        assert entered.wait(1)
        try:
            with pytest.raises(transport.TypesafeUnavailableError, match="deadline"):
                transport.evaluate({}, QUESTIONS, deadline=time.monotonic() + 0.02)
            assert transport.available()
            joined = threading.Event()
            flight = next(iter(transport._FLIGHTS.values()))
            original = flight.future.result

            def wait(timeout: float | None = None) -> tuple[bytes, dict[str, float]]:
                joined.set()
                return original(timeout)

            monkeypatch.setattr(flight.future, "result", wait)
            waiter = executor.submit(transport.evaluate, {}, QUESTIONS)
            assert joined.wait(1)
        finally:
            finish.set()
        assert owner.result().requests == 1
        shared = waiter.result()
        assert shared.coalesced == 1
        assert shared.requests == shared.input_tokens == shared.output_tokens == 0
        assert len(calls) == 1


def test_idle_connection_expires(monkeypatch: pytest.MonkeyPatch) -> None:
    ports: list[int] = []
    clock = [100.0]
    monkeypatch.setattr(transport.time, "monotonic", lambda: clock[0])
    with _server(monkeypatch, 200, json.dumps(_envelope()).encode(), ports):
        transport.evaluate({"query": "one"}, QUESTIONS)
        clock[0] += 16
        next_answer = transport.evaluate({"query": "two"}, QUESTIONS)
        assert next_answer.timings["connections_reused"] == 0
        assert ports[0] != ports[1]


def test_thread_start_failure_releases_admission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(_self: threading.Thread) -> None:
        raise RuntimeError("cannot start")

    monkeypatch.setattr(threading.Thread, "start", fail)
    with pytest.raises(transport.TypesafeUnavailableError, match="busy"):
        transport.evaluate({}, QUESTIONS)
    assert not transport._FLIGHTS
    assert transport._SLOTS.acquire(blocking=False)
    assert transport._SLOTS.acquire(blocking=False)


def test_rotated_credential_rejects_late_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entered, finish = threading.Event(), threading.Event()

    def request(
        _key: str, _payload: bytes, _deadline: float, **_kwargs: object
    ) -> bytes:
        entered.set()
        assert finish.wait(2)
        return json.dumps(_envelope()).encode()

    monkeypatch.setattr(transport, "_request", request)
    with ThreadPoolExecutor(max_workers=1) as executor:
        owner = executor.submit(transport.evaluate, {}, QUESTIONS)
        try:
            assert entered.wait(1)
            monkeypatch.setenv(EnvVar.TYPESAFE_API_KEY, "replacement")
            assert transport.available()
        finally:
            finish.set()
        with pytest.raises(
            transport.TypesafeUnavailableError, match="credential_changed"
        ):
            owner.result()
    assert not transport._CACHE.values
