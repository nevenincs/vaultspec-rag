"""Environment-enrolled, bounded hosted classification with quiet fallback."""

from __future__ import annotations

import atexit
import copy
import hashlib
import json
import os
import threading
import time
import urllib.error
from concurrent.futures import Future
from dataclasses import dataclass, field, replace
from http.client import HTTPException

from ..config._types import EnvVar
from ._typesafe_answers import MODEL, Evaluation, validate_evaluation
from ._typesafe_cache import ResponseCache
from ._typesafe_pool import ConnectionPool

_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
REQUEST_TIMEOUT = 5.0
_COOLDOWN = 30.0
_SLOTS = threading.BoundedSemaphore(2)
_LOCK = threading.Lock()
_POOL = ConnectionPool()
_CACHE = ResponseCache()
atexit.register(_POOL.close)


class TypesafeUnavailableError(Exception):
    """A safe reason code; never includes provider text or submitted content."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


@dataclass
class _Circuit:
    fingerprint: bytes = b""
    disabled: bool = False
    retry_at: float = 0.0
    last_success: float | None = None


_CIRCUIT = _Circuit()


@dataclass
class _Flight:
    cache_key: bytes
    future: Future[tuple[bytes, dict[str, float]]] = field(default_factory=Future)


_FLIGHTS: dict[bytes, _Flight] = {}


@dataclass(frozen=True)
class _RequestBudget:
    deadline: float
    search_limited: bool


def _credential() -> tuple[str, bytes]:
    key = os.environ.get(EnvVar.TYPESAFE_API_KEY, "").strip()
    fingerprint = hashlib.sha256(key.encode()).digest() if key else b""
    with _LOCK:
        if _CIRCUIT.fingerprint != fingerprint:
            _CIRCUIT.fingerprint = fingerprint
            _CIRCUIT.disabled = False
            _CIRCUIT.retry_at = 0.0
            _CIRCUIT.last_success = None
            _CACHE.clear()
            _POOL.close()
        if not key:
            raise TypesafeUnavailableError("no_key")
        if _CIRCUIT.disabled:
            raise TypesafeUnavailableError("credential_disabled")
        if time.monotonic() < _CIRCUIT.retry_at:
            raise TypesafeUnavailableError("cooldown")
    return key, fingerprint


def available() -> bool:
    """Check enrollment and circuit state without creating a network client."""
    try:
        _credential()
    except TypesafeUnavailableError:
        return False
    return True


def enrollment_status() -> dict[str, object]:
    """Report redacted process-local evidence without making a provider call."""
    reason = ""
    try:
        _credential()
    except TypesafeUnavailableError as exc:
        reason = exc.reason
    with _LOCK:
        now = time.monotonic()
        age = (
            None
            if _CIRCUIT.last_success is None
            else max(0.0, now - _CIRCUIT.last_success)
        )
        state = {
            "no_key": "off",
            "credential_disabled": "rejected",
            "cooldown": "cooldown",
        }.get(reason)
        if state is None:
            recently_verified = (
                age is not None
                and age < _CACHE.ttl
                and _CIRCUIT.last_success is not None
                and _CIRCUIT.last_success >= _CIRCUIT.retry_at
            )
            state = "active" if recently_verified else "pending"
        return {
            "enrolled": bool(_CIRCUIT.fingerprint),
            "state": state,
            "model": MODEL,
            "last_success_age_seconds": round(age, 1) if age is not None else None,
            "retry_after_seconds": round(max(0.0, _CIRCUIT.retry_at - now), 1),
        }


def _failed(fingerprint: bytes, permanent: bool = False) -> None:
    with _LOCK:
        if _CIRCUIT.fingerprint == fingerprint:
            _CIRCUIT.disabled |= permanent
            _CIRCUIT.retry_at = time.monotonic() + _COOLDOWN
            _CACHE.clear()
            _POOL.close()


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TypesafeUnavailableError("deadline")
    return remaining


def _request(
    key: str,
    payload: bytes,
    deadline: float,
    *,
    timings: dict[str, float] | None = None,
) -> bytes:
    stats = timings if timings is not None else {}
    started = time.monotonic()
    lease = _POOL.acquire(
        (hashlib.sha256(key.encode()).digest(), _ENDPOINT), _remaining(deadline)
    )
    connection = lease.connection
    reusable = False
    response = None
    try:
        stats["pool_ms"] = (time.monotonic() - started) * 1000
        stats["connections_reused"] = float(lease.reused)
        started = time.monotonic()
        if connection.sock is None:
            connection.connect()
        stats["connect_ms"] = (time.monotonic() - started) * 1000
        if connection.sock is not None:
            connection.sock.settimeout(_remaining(deadline))
        started = time.monotonic()
        connection.request(
            "POST",
            lease.target,
            body=payload,
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
            },
        )
        stats["upload_ms"] = (time.monotonic() - started) * 1000
        if connection.sock is not None:
            connection.sock.settimeout(_remaining(deadline))
        started = time.monotonic()
        response = connection.getresponse()
        stats["response_wait_ms"] = (time.monotonic() - started) * 1000
        if 300 <= response.status < 400:
            raise TypesafeUnavailableError("redirect")
        if response.status != 200:
            raise urllib.error.HTTPError(
                _ENDPOINT, response.status, "http", response.headers, None
            )
        started = time.monotonic()
        chunks: list[bytes] = []
        size = 0
        while True:
            remaining = _remaining(deadline)
            if connection.sock is not None:
                connection.sock.settimeout(remaining)
            chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                if response.length not in (None, 0):
                    raise HTTPException("incomplete_response")
                stats["download_ms"] = (time.monotonic() - started) * 1000
                reusable = not response.will_close
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise TypesafeUnavailableError("response_size")
    finally:
        if response is not None:
            response.close()
        _POOL.release(lease, reusable=reusable)


def _successful_response(
    credential: tuple[str, bytes],
    payload: bytes,
    questions: dict[str, dict[str, object]],
    deadline: float,
    flight: _Flight,
) -> tuple[bytes, dict[str, float]]:
    key, fingerprint = credential
    stats: dict[str, float] = {}
    body = _request(key, payload, deadline, timings=stats)
    started = time.monotonic()
    raw: object = json.loads(body)
    validate_evaluation(raw, questions)
    stats["validation_ms"] = (time.monotonic() - started) * 1000
    _remaining(deadline)
    with _LOCK:
        if (
            _CIRCUIT.fingerprint == fingerprint
            and not _CIRCUIT.disabled
            and time.monotonic() >= _CIRCUIT.retry_at
        ):
            _CACHE.put(flight.cache_key, body, time.monotonic())
            _CIRCUIT.last_success = time.monotonic()
    return body, stats


def _run(
    credential: tuple[str, bytes],
    payload: bytes,
    questions: dict[str, dict[str, object]],
    budget: _RequestBudget,
    flight: _Flight,
) -> None:
    _, fingerprint = credential
    outcome: Future[tuple[bytes, dict[str, float]]] = Future()
    try:
        response = _successful_response(
            credential, payload, questions, budget.deadline, flight
        )
        outcome.set_result(response)
    except urllib.error.HTTPError as exc:
        permanent = exc.code in {401, 402, 403}
        exc.close()
        _failed(fingerprint, permanent)
        outcome.set_exception(
            TypesafeUnavailableError("credential_rejected" if permanent else "http")
        )
    except TypesafeUnavailableError as exc:
        if exc.reason != "deadline" or not budget.search_limited:
            _failed(fingerprint)
        outcome.set_exception(TypesafeUnavailableError(exc.reason))
    except (TimeoutError, urllib.error.URLError) as exc:
        timed_out = isinstance(exc, TimeoutError) or isinstance(
            exc.reason, TimeoutError
        )
        if not (timed_out and budget.search_limited):
            _failed(fingerprint)
        outcome.set_exception(
            TypesafeUnavailableError(
                "deadline" if timed_out else "invalid_or_unreachable"
            )
        )
    except (
        OSError,
        HTTPException,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
    ):
        _failed(fingerprint)
        outcome.set_exception(TypesafeUnavailableError("invalid_or_unreachable"))
    finally:
        with _LOCK:
            _FLIGHTS.pop(flight.cache_key, None)
            _SLOTS.release()
        if outcome.done():
            error = outcome.exception()
            if error is not None:
                flight.future.set_exception(error)
            else:
                flight.future.set_result(outcome.result())


def _payload(
    state: dict[str, object], questions: dict[str, dict[str, object]]
) -> bytes:
    try:
        payload = json.dumps(
            {"model": MODEL, "state": state, "questions": questions},
            allow_nan=False,
            sort_keys=True,
        ).encode()
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise TypesafeUnavailableError("invalid_request") from None
    if len(payload) > MAX_REQUEST_BYTES:
        raise TypesafeUnavailableError("request_size")
    return payload


def evaluate(
    state: dict[str, object],
    questions: dict[str, dict[str, object]],
    *,
    deadline: float | None = None,
) -> Evaluation:
    """Evaluate once; resource, transport and schema failures request fallback."""
    credential = _credential()
    started = time.monotonic()
    expires = time.monotonic() + REQUEST_TIMEOUT
    search_limited = deadline is not None and deadline < expires
    if deadline is not None:
        expires = min(expires, deadline)
    _remaining(expires)
    payload = _payload(state, questions)
    _remaining(expires)
    stats = {"encode_ms": (time.monotonic() - started) * 1000}
    cache_key = hashlib.sha256(
        credential[1] + _ENDPOINT.encode() + b"\x00" + payload
    ).digest()
    started = time.monotonic()
    with _LOCK:
        body = _CACHE.get(cache_key, time.monotonic())
        flight = _FLIGHTS.get(cache_key)
        leader = body is None and flight is None
        if leader:
            if not _SLOTS.acquire(blocking=False):
                raise TypesafeUnavailableError("busy")
            flight = _Flight(cache_key)
            _FLIGHTS[cache_key] = flight
    stats["cache_lookup_ms"] = (time.monotonic() - started) * 1000
    if body is not None:
        if _credential() != credential:
            raise TypesafeUnavailableError("credential_changed")
        return replace(
            validate_evaluation(json.loads(body), questions),
            requests=0,
            input_tokens=0,
            output_tokens=0,
            cache_hits=1,
            timings=stats,
        )
    assert flight is not None
    if leader:
        worker = threading.Thread(
            target=_run,
            args=(
                credential,
                payload,
                copy.deepcopy(questions),
                _RequestBudget(expires, search_limited),
                flight,
            ),
            daemon=True,
        )
        try:
            worker.start()
        except RuntimeError:
            with _LOCK:
                _FLIGHTS.pop(cache_key, None)
                _SLOTS.release()
            flight.future.set_exception(TypesafeUnavailableError("busy"))
    started = time.monotonic()
    try:
        body, network_stats = flight.future.result(timeout=_remaining(expires))
    except TimeoutError:
        if leader and not search_limited:
            _failed(credential[1])
        raise TypesafeUnavailableError("deadline") from None
    stats["request_wait_ms" if leader else "coalesced_wait_ms"] = (
        time.monotonic() - started
    ) * 1000
    if _credential() != credential:
        raise TypesafeUnavailableError("credential_changed")
    evaluation = validate_evaluation(json.loads(body), questions)
    if leader:
        return replace(evaluation, timings={**stats, **network_stats})
    return replace(
        evaluation,
        requests=0,
        input_tokens=0,
        output_tokens=0,
        coalesced=1,
        timings=stats,
    )
