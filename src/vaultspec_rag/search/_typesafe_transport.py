"""Environment-enrolled, bounded hosted classification with quiet fallback."""

from __future__ import annotations

import hashlib
import json
import os
import queue
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.client import HTTPException
from typing import TYPE_CHECKING, cast, override

from ..config._types import EnvVar
from ._typesafe_answers import MODEL, Evaluation, validate_evaluation

if TYPE_CHECKING:
    from http.client import HTTPResponse

_ENDPOINT = "https://api.typesafe.ai/v1/systemone"
MAX_REQUEST_BYTES = 128 * 1024
MAX_RESPONSE_BYTES = 128 * 1024
REQUEST_TIMEOUT = 5.0
_COOLDOWN = 30.0
_SLOTS = threading.BoundedSemaphore(2)
_LOCK = threading.Lock()


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


_CIRCUIT = _Circuit()


def _credential() -> tuple[str, bytes]:
    key = os.environ.get(EnvVar.TYPESAFE_API_KEY, "").strip()
    fingerprint = hashlib.sha256(key.encode()).digest() if key else b""
    with _LOCK:
        if _CIRCUIT.fingerprint != fingerprint:
            _CIRCUIT.fingerprint = fingerprint
            _CIRCUIT.disabled = False
            _CIRCUIT.retry_at = 0.0
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


def _failed(fingerprint: bytes, permanent: bool = False) -> None:
    with _LOCK:
        if _CIRCUIT.fingerprint == fingerprint:
            _CIRCUIT.disabled |= permanent
            _CIRCUIT.retry_at = time.monotonic() + _COOLDOWN


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    @override
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: object,
        code: int,
        msg: str,
        headers: object,
        newurl: str,
    ) -> None:
        raise TypesafeUnavailableError("redirect")


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TypesafeUnavailableError("deadline")
    return remaining


def _request(key: str, payload: bytes, deadline: float) -> bytes:
    request = urllib.request.Request(
        _ENDPOINT,
        data=payload,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(_NoRedirect())
    with cast(
        "HTTPResponse", opener.open(request, timeout=_remaining(deadline))
    ) as response:
        chunks: list[bytes] = []
        size = 0
        while True:
            _remaining(deadline)
            chunk = response.read1(min(8192, MAX_RESPONSE_BYTES + 1 - size))
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
            size += len(chunk)
            if size > MAX_RESPONSE_BYTES:
                raise TypesafeUnavailableError("response_size")


def _run(
    credential: tuple[str, bytes],
    payload: bytes,
    questions: dict[str, dict[str, object]],
    deadline: float,
    result: queue.Queue[Evaluation | TypesafeUnavailableError],
) -> None:
    key, fingerprint = credential
    try:
        body = _request(key, payload, deadline)
        raw: object = json.loads(body)
        evaluation = validate_evaluation(raw, questions)
        _remaining(deadline)
        result.put_nowait(evaluation)
    except urllib.error.HTTPError as exc:
        permanent = exc.code in {401, 402, 403}
        exc.close()
        _failed(fingerprint, permanent)
        result.put_nowait(
            TypesafeUnavailableError("credential_rejected" if permanent else "http")
        )
    except TypesafeUnavailableError as exc:
        _failed(fingerprint)
        result.put_nowait(TypesafeUnavailableError(exc.reason))
    except (
        OSError,
        HTTPException,
        ValueError,
        TypeError,
        OverflowError,
        RecursionError,
    ):
        _failed(fingerprint)
        result.put_nowait(TypesafeUnavailableError("invalid_or_unreachable"))
    finally:
        _SLOTS.release()


def evaluate(
    state: dict[str, object],
    questions: dict[str, dict[str, object]],
    *,
    deadline: float | None = None,
) -> Evaluation:
    """Evaluate once; resource, transport and schema failures request fallback."""
    credential = _credential()
    expires = time.monotonic() + REQUEST_TIMEOUT
    if deadline is not None:
        expires = min(expires, deadline)
    _remaining(expires)
    try:
        payload = json.dumps(
            {"model": MODEL, "state": state, "questions": questions}, allow_nan=False
        ).encode()
    except (ValueError, TypeError, OverflowError, RecursionError):
        raise TypesafeUnavailableError("invalid_request") from None
    if len(payload) > MAX_REQUEST_BYTES:
        raise TypesafeUnavailableError("request_size")
    _remaining(expires)
    if not _SLOTS.acquire(blocking=False):
        raise TypesafeUnavailableError("busy")
    result: queue.Queue[Evaluation | TypesafeUnavailableError] = queue.Queue(maxsize=1)
    worker = threading.Thread(
        target=_run, args=(credential, payload, questions, expires, result), daemon=True
    )
    try:
        worker.start()
    except RuntimeError:
        _SLOTS.release()
        raise TypesafeUnavailableError("busy") from None
    try:
        outcome = result.get(timeout=_remaining(expires))
    except queue.Empty:
        _failed(credential[1])
        raise TypesafeUnavailableError("deadline") from None
    if isinstance(outcome, TypesafeUnavailableError):
        raise outcome
    return outcome
