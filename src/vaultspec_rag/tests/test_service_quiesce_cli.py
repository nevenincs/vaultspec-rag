"""Guard tests for the ``server pause`` / ``server resume`` envelope contract.

These are guard tests, not positive coverage: the load-bearing properties are
that an already-satisfied request is a SUCCESS (exit 0 with an ``already_*``
status), and that a request which did NOT achieve the state - a pause the daemon
refused because a shutdown latched the gate open - is a FAILURE (exit 1), never a
false success a broker would read as done. Each is proven able to fail by the
branch it exercises: flip the expected exit code and the assertion reports it.
"""

from __future__ import annotations

import contextlib
import http.server
import json
import threading
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from collections.abc import Generator

    from typer.testing import Result

from ..cli import app
from ..serviceclient._transport import _try_http_admin
from ._http_stubs import QuietHandler

pytestmark = [pytest.mark.unit]

runner = CliRunner()

_QUIESCED_SNAPSHOT: dict[str, object] = {
    "state": "quiesced",
    "admission_epoch": 4,
    "admissions_open": False,
    "active_compute_tickets": 0,
    "drain_complete": True,
    "vram_released": True,
    "safe_to_borrow_gpu": True,
    "pause_requested_at": 100.0,
    "drain_acknowledged_at": 101.0,
    "quiesced_at": 102.0,
    "warming_started_at": None,
    "failure_reason": None,
}
_RUNNING_SNAPSHOT: dict[str, object] = {
    "state": "running",
    "admission_epoch": 5,
    "admissions_open": True,
    "active_compute_tickets": 0,
    "drain_complete": False,
    "vram_released": False,
    "safe_to_borrow_gpu": False,
    "pause_requested_at": None,
    "drain_acknowledged_at": None,
    "quiesced_at": None,
    "warming_started_at": None,
    "failure_reason": None,
}
_RETRYABLE_FAILURE: dict[str, object] = {
    "ok": False,
    "status": "quiesce_transition_conflict",
    "error": "quiesce_transition_conflict",
    "message": "service-owned transition conflict",
    "retryable": True,
    "quiesce": {
        "state": "pausing",
        "admission_epoch": 4,
        "admissions_open": False,
        "active_compute_tickets": 1,
        "drain_complete": False,
        "vram_released": False,
        "safe_to_borrow_gpu": False,
        "pause_requested_at": 100.0,
        "drain_acknowledged_at": None,
        "quiesced_at": None,
        "warming_started_at": None,
        "failure_reason": None,
    },
}


@contextlib.contextmanager
def _quiesce_service(envelope: dict[str, Any] | None) -> Generator[int | None]:
    """Serve one pause/resume envelope over real HTTP on a real port.

    The command under test resolves a port, opens a socket and parses a wire
    response, so that is what it is given. Substituting the transport proved
    only that the exit-code branches format a dictionary handed to them, and
    could not fail when the call site moved - which is exactly how the sibling
    locked-store tests came to fail on a patch target instead of an assertion.

    ``None`` means no service at all: nothing is bound and no port is passed,
    so the command meets a genuinely absent daemon rather than a function
    returning ``None``.
    """
    if envelope is None:
        yield None
        return

    body = json.dumps(envelope).encode()

    class _Handler(QuietHandler):
        def do_POST(self) -> None:
            # Route-checked so a verb pointed at the wrong path fails here
            # rather than being answered anyway, and the request body is drained
            # before replying: answering an unread request aborts the client's
            # send on Windows and surfaces as a connection error, not a verdict.
            length = int(self.headers.get("Content-Length", "0"))
            self.rfile.read(length)
            if self.path not in ("/pause", "/resume"):
                self.send_response(404)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = http.server.HTTPServer(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield int(server.server_address[1])
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _invoke(verb: str, port: int | None) -> Result:
    """Run one quiesce verb, passing the real port when a service is up."""
    args = ["server", verb, "--json"]
    if port is not None:
        args += ["--port", str(port)]
    return runner.invoke(app, args)


def _json(result: Result) -> dict[str, Any]:
    return json.loads(result.output)


def test_pause_change_is_success_exit_zero() -> None:
    with _quiesce_service(
        {"ok": True, "status": "quiesced", "quiesce": _QUIESCED_SNAPSHOT}
    ) as port:
        result = _invoke("pause", port)
    assert result.exit_code == 0, result.output
    body = _json(result)
    assert body["ok"] is True
    assert body["data"] == {
        "ok": True,
        "status": "quiesced",
        "quiesce": _QUIESCED_SNAPSHOT,
    }


def test_pause_already_paused_is_idempotent_success() -> None:
    # Idempotent success is decided by the service-owned ``ok`` field, not a
    # client inference from a legacy ``paused`` flag.
    with _quiesce_service(
        {
            "ok": True,
            "status": "already_quiesced",
            "quiesce": _QUIESCED_SNAPSHOT,
        }
    ) as port:
        result = _invoke("pause", port)
    assert result.exit_code == 0, result.output
    assert _json(result)["data"]["status"] == "already_quiesced"


def test_resume_already_running_is_idempotent_success() -> None:
    with _quiesce_service(
        {"ok": True, "status": "running", "quiesce": _RUNNING_SNAPSHOT}
    ) as port:
        result = _invoke("resume", port)
    assert result.exit_code == 0, result.output
    assert _json(result)["data"]["status"] == "running"


@pytest.mark.parametrize(
    ("verb", "status", "snapshot"),
    [
        ("pause", "quiesced", _RUNNING_SNAPSHOT),
        ("resume", "running", _QUIESCED_SNAPSHOT),
    ],
)
def test_ok_response_with_unachieved_canonical_state_is_failure(
    verb: str,
    status: str,
    snapshot: dict[str, object],
) -> None:
    """An ``ok`` flag cannot override the canonical quiesce state.

    The status deliberately claims the requested terminal state, proving the
    adapter reads the canonical ``quiesce.state`` rather than inferring local
    success from an advisory response field.

    Mutation: remove the expected-state condition in ``_quiesce``. Both cases
    become false exit-zero successes instead of preserving the wire payload.
    """
    envelope: dict[str, object] = {
        "ok": True,
        "status": status,
        "quiesce": snapshot,
    }
    with _quiesce_service(envelope) as port:
        result = _invoke(verb, port)

    assert result.exit_code == 1, result.output
    assert _json(result) == {
        "ok": False,
        "command": f"service.{verb}",
        "error": "invalid_service_response",
        "message": "The service returned an invalid quiesce response.",
        "data": envelope,
    }


def test_retryable_pause_failure_preserves_the_service_owned_envelope() -> None:
    """An unachieved retryable transition keeps every service-owned field."""
    with _quiesce_service(_RETRYABLE_FAILURE) as port:
        result = _invoke("pause", port)
    assert result.exit_code == 1, result.output
    body = _json(result)
    assert body["ok"] is False
    assert body["error"] == _RETRYABLE_FAILURE["error"]
    assert body["status"] == _RETRYABLE_FAILURE["status"]
    assert body["message"] == _RETRYABLE_FAILURE["message"]
    assert body["retryable"] is True
    assert body["data"] == _RETRYABLE_FAILURE


def test_transport_preserves_the_retryable_service_envelope() -> None:
    """The real transport returns the daemon's full payload without reshaping."""
    with _quiesce_service(_RETRYABLE_FAILURE) as port:
        assert port is not None
        result = _try_http_admin("resume_service", {}, port)
    assert result == _RETRYABLE_FAILURE


def test_retryable_resume_failure_is_failure_exit_one() -> None:
    with _quiesce_service(_RETRYABLE_FAILURE) as port:
        result = _invoke("resume", port)
    assert result.exit_code == 1, result.output
    assert _json(result)["error"] == _RETRYABLE_FAILURE["error"]


def test_unreachable_service_is_failure_exit_one() -> None:
    # A None result means the daemon did not answer: there is no gate to hold,
    # so the request failed rather than being vacuously satisfied.
    with _quiesce_service(None) as port:
        result = _invoke("pause", port)
    assert result.exit_code == 1, result.output
    assert _json(result)["error"] == "service_unreachable"


def test_exactly_one_json_envelope_per_invocation() -> None:
    # The broker contract requires exactly one structured document on stdout on
    # every exit path; more than one line would break machine parsing.
    #
    # Asserted against stdout alone, deliberately. ``result.output`` interleaves
    # stdout and stderr, and this CLI routes diagnostics and progress to stderr
    # on purpose so they survive --json without touching the result channel;
    # asserting on the mix would fail on legitimate stderr output while proving
    # nothing extra. Counting every stdout line - rather than only the ones that
    # parse as JSON - is what makes this catch stray prose on the result
    # channel, so do not relax it to a "lines starting with {" filter.
    with _quiesce_service(
        {"ok": True, "status": "quiesced", "quiesce": _QUIESCED_SNAPSHOT}
    ) as port:
        result = _invoke("pause", port)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    json.loads(lines[0])
