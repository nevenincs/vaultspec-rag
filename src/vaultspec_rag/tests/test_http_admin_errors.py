"""Admin-path error-surfacing tests for the shared service-client transport.

No mocks: a real in-process HTTP server stands in for the daemon and is driven
over the genuine ``urllib`` wire path through ``_try_http_admin``. The regression
guard (GitHub #199) is that an unexpected (non-refused, non-timeout) failure -
here a live route returning a malformed, non-JSON body - surfaces as the
structured ``http_call_failed`` envelope rather than a bare ``{}`` that a caller
cannot tell apart from a genuinely empty result.
"""

from __future__ import annotations

import contextlib
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import TYPE_CHECKING, ClassVar, cast

import pytest

from ..config._types import EnvVar
from ..serviceclient._transport import (
    DEFAULT_ADMIN_TIMEOUT_SECONDS,
    MAX_SERVICE_RESPONSE_BYTES,
    ServiceResponseTooLargeError,
    _get_admin_timeout,
    _send_call,
    _try_http_admin,
    _try_http_health,
)
from ._http_stubs import QuietHandler

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path
    from types import FrameType

    from _typeshed import TraceFunction

pytestmark = [pytest.mark.unit]


class _MalformedJSONHandler(QuietHandler):
    """Answer every GET with a 200 whose body is not valid JSON."""

    def do_GET(self) -> None:
        body = b"this is not json"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _EmptyJSONHandler(QuietHandler):
    """Answer every GET with a valid, genuinely-empty JSON object."""

    def do_GET(self) -> None:
        body = b"{}"
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _JSONArrayHandler(QuietHandler):
    """Answer every GET with a 200 whose body is a JSON array, not an object.

    A stray non-vaultspec-rag service answering on the port can send this, and
    it is the shape a bare ``cast`` waves through: valid JSON that no caller can
    call ``.get()`` on.
    """

    def do_GET(self) -> None:
        body = b'[{"not": "an object"}]'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _ErrorJSONArrayHandler(QuietHandler):
    """Answer every GET with a 503 whose body is a JSON array, not an object."""

    def do_GET(self) -> None:
        body = b'["service unavailable"]'
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _PopulatedJSONHandler(QuietHandler):
    """Answer every GET with a well-formed, populated JSON object."""

    payload: ClassVar[dict[str, object]] = {
        "ok": True,
        "projects": ["alpha", "beta"],
        "count": 2,
    }

    def do_GET(self) -> None:
        import json

        body = json.dumps(type(self).payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


# The refusal stage spends half the whole-call budget, so a budget
# renewed at re-authentication visibly outlives the original one; both halves
# are seconds wide, far above any loopback scheduling stall. The authenticated
# retry outlasts the budget but not the default admin timeout.
_AUTH_CALL_BUDGET_SECONDS = 3.0
_AUTH_REFUSAL_SECONDS = _AUTH_CALL_BUDGET_SECONDS / 2
_AUTH_RETRY_SECONDS = 15.0


class _AuthDeadlineHandler(QuietHandler):
    """Rotate discovery after refusal, then delay the authenticated retry."""

    service_token = "live-loopback-token"
    requests: ClassVar[list[str]] = []

    # The first refusal spends half the budget; the authenticated retry
    # outlasts the remaining budget and must expire against that deadline.
    def do_GET(self) -> None:
        authorization = self.headers.get("Authorization", "")
        type(self).requests.append(f"{self.path} {authorization}".rstrip())
        if authorization == f"Bearer {self.service_token}":
            time.sleep(_AUTH_RETRY_SECONDS)
            self._json(200, {"projects": []})
            return
        from ..serviceclient._discovery import _merge_service_status

        _merge_service_status({"service_token": self.service_token})
        time.sleep(_AUTH_REFUSAL_SECONDS)
        self._json(401, {"ok": False, "error": "unauthorized"})

    def _json(self, status: int, payload: dict[str, object]) -> None:
        import json

        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
        ):
            self.wfile.write(body)


class _RedirectSinkHandler(QuietHandler):
    """Stand in for the host a redirect names; record everything it receives.

    Answers with a body that would be mistaken for a genuine service response if
    a caller ever followed a redirect here, so a test that reaches this handler
    fails on the value it returns as well as on the request it recorded.
    """

    received: ClassVar[list[dict[str, str]]] = []

    def do_GET(self) -> None:
        type(self).received.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization", ""),
            }
        )
        body = b'{"service_token": "sink-token-never-legitimate"}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        self.do_GET()


class _RedirectingHandler(QuietHandler):
    """Answer every request with a 302 pointing at the sink server."""

    sink_port: ClassVar[int] = 0
    seen_authorization: ClassVar[list[str]] = []

    def do_GET(self) -> None:
        type(self).seen_authorization.append(self.headers.get("Authorization", ""))
        self.send_response(302)
        self.send_header(
            "Location", f"http://127.0.0.1:{type(self).sink_port}/redirected"
        )
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:
        self.do_GET()


def _serve(handler: type[BaseHTTPRequestHandler]) -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


@contextlib.contextmanager
def _observed_http_errors() -> Generator[list[urllib.error.HTTPError]]:
    """Retain the actual wire error to observe closure independently of GC."""
    errors: list[urllib.error.HTTPError] = []
    previous = sys.gettrace()

    def observe(frame: FrameType, event: str, argument: object) -> TraceFunction:
        if (
            frame.f_code in (_try_http_health.__code__, _send_call.__code__)
            and event == "exception"
        ):
            exception = cast("tuple[object, BaseException, object]", argument)[1]
            if isinstance(exception, urllib.error.HTTPError):
                errors.append(exception)
        return observe

    sys.settrace(observe)
    try:
        yield errors
    finally:
        sys.settrace(previous)


class _OversizedErrorHandler(QuietHandler):
    def do_GET(self) -> None:
        body = b"x" * (MAX_SERVICE_RESPONSE_BYTES + 2)
        self.send_response(503)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        with contextlib.suppress(
            BrokenPipeError, ConnectionAbortedError, ConnectionResetError
        ):
            self.wfile.write(body)


@pytest.mark.usefixtures("isolated_status_dir")
class TestHTTPErrorResponseLifetime:
    def test_health_error_response_closes_before_return(self) -> None:
        server, port = _serve(_ErrorJSONArrayHandler)
        errors: list[urllib.error.HTTPError] = []
        try:
            with _observed_http_errors() as errors:
                result = _try_http_health(port)
            assert result == {"status": "error", "http_code": 503}
            assert errors
            # Removing the health error context fails this closure assertion.
            assert all(error.closed for error in errors)
        finally:
            server.shutdown()
            server.server_close()
            for error in errors:
                error.close()

    def test_error_response_closes_when_the_body_exceeds_its_limit(self) -> None:
        server, port = _serve(_OversizedErrorHandler)
        errors: list[urllib.error.HTTPError] = []
        try:
            request = urllib.request.Request(f"http://127.0.0.1:{port}/projects")
            with (
                _observed_http_errors() as errors,
                pytest.raises(ServiceResponseTooLargeError, match="client limit"),
            ):
                _send_call(request, 5.0)
            assert errors
            # Removing the error-body context fails this closure assertion.
            assert all(error.closed for error in errors)
        finally:
            server.shutdown()
            server.server_close()
            for error in errors:
                error.close()


@pytest.fixture
def refused_port() -> Iterator[int]:
    """Yield a port that deterministically refuses connections.

    A socket bound to an ephemeral port but never put into ``listen()`` rejects
    every connect with ECONNREFUSED for as long as it is held - so there is no
    bind/close/reuse window (which returning a closed port number would leave).

    macOS is the exception: it answers a connect to such a socket with
    silence, so the caller times out instead of being refused. There the port
    is released before it is handed over, which that system refuses at once,
    and the reuse window is accepted as the smaller error.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    if sys.platform == "darwin":
        sock.close()
    try:
        yield port
    finally:
        sock.close()


@pytest.fixture
def isolated_admin_timeout_env() -> Iterator[None]:
    """Isolate the admin-timeout environment override for precedence tests."""
    key = "VAULTSPEC_RAG_ADMIN_TIMEOUT"
    previous = os.environ.pop(key, None)
    try:
        yield
    finally:
        if previous is not None:
            os.environ[key] = previous


@pytest.mark.usefixtures("isolated_admin_timeout_env")
class TestAdminTimeoutResolution:
    def test_default_allows_real_service_observability_work(self) -> None:
        assert DEFAULT_ADMIN_TIMEOUT_SECONDS == 30.0
        assert _get_admin_timeout() == 30.0

    def test_explicit_timeout_wins(self) -> None:
        os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "17"
        assert _get_admin_timeout(2.5) == 2.5

    def test_environment_override_wins_over_default(self) -> None:
        os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "17"
        assert _get_admin_timeout() == 17.0


@pytest.mark.usefixtures("isolated_status_dir")
class TestAdminErrorSurfacing:
    def test_malformed_response_returns_http_call_failed_envelope(self) -> None:
        server, port = _serve(_MalformedJSONHandler)
        try:
            result = _try_http_admin("list_projects", {}, port)
        finally:
            server.shutdown()
            server.server_close()
        assert result is not None, "a live-but-broken call must not look unreachable"
        assert result != {}, "the failure must not be swallowed into a bare empty dict"
        assert result.get("ok") is False
        assert result.get("error") == "http_call_failed"
        assert result.get("message")

    def test_non_object_success_body_becomes_a_structured_refusal(self) -> None:
        """A 200 carrying a JSON array must not reach a caller as a list.

        Without the transport's isinstance check the array is cast to a mapping
        and handed on, so the first caller that reads it - every CLI reader does
        ``result.get(...)`` - dies with ``AttributeError`` far from this cause.
        The assertions below name the refusal envelope, not merely "not a list",
        so a mutation that returns some other error still fails here.
        """
        server, port = _serve(_JSONArrayHandler)
        try:
            result = _try_http_admin("list_projects", {}, port)
        finally:
            server.shutdown()
            server.server_close()
        assert result is not None, "a live-but-broken call must not look unreachable"
        assert isinstance(result, dict), "the caller contract is a mapping"
        assert result.get("ok") is False
        assert result.get("error") == "http_error"
        assert result.get("http_code") == 200
        message = result.get("message")
        assert isinstance(message, str)
        assert "a JSON body that is not an object (list)" in message
        assert "not the vaultspec-rag daemon" in message

    def test_non_object_error_body_becomes_a_structured_refusal(self) -> None:
        """The same refusal covers an HTTP error status carrying a JSON array."""
        server, port = _serve(_ErrorJSONArrayHandler)
        try:
            result = _try_http_admin("list_projects", {}, port)
        finally:
            server.shutdown()
            server.server_close()
        assert result is not None
        assert isinstance(result, dict)
        assert result.get("ok") is False
        assert result.get("error") == "http_error"
        assert result.get("http_code") == 503
        message = result.get("message")
        assert isinstance(message, str)
        assert "a JSON body that is not an object (list)" in message

    def test_well_formed_object_body_passes_through_unchanged(self) -> None:
        """A well-formed answer must be returned byte-for-byte as decoded."""
        server, port = _serve(_PopulatedJSONHandler)
        try:
            result = _try_http_admin("list_projects", {}, port)
        finally:
            server.shutdown()
            server.server_close()
        assert result == _PopulatedJSONHandler.payload

    def test_genuinely_empty_result_stays_empty_dict(self) -> None:
        # A successful call whose body is an empty object is a legitimate empty
        # result and must remain distinguishable from the failure envelope above.
        server, port = _serve(_EmptyJSONHandler)
        try:
            result = _try_http_admin("list_projects", {}, port)
        finally:
            server.shutdown()
            server.server_close()
        assert result == {}

    def test_unreachable_service_returns_none(self, refused_port: int) -> None:
        # Nothing listening on the port: the refused connection is the
        # service-down sentinel and must stay None, not an envelope.
        result = _try_http_admin("list_projects", {}, refused_port)
        assert result is None

    def test_auth_recovery_obeys_one_whole_call_deadline(self) -> None:
        """Discovery refresh and authenticated retry share the original deadline."""
        _AuthDeadlineHandler.requests = []
        server, port = _serve(_AuthDeadlineHandler)
        from ..serviceclient._discovery import _merge_service_status

        _merge_service_status(
            {"pid": os.getpid(), "port": port, "service_token": "stale-token"}
        )
        started = time.monotonic()
        try:
            result = _try_http_admin(
                "list_projects", {}, port, timeout=_AUTH_CALL_BUDGET_SECONDS
            )
            elapsed = time.monotonic() - started
        finally:
            server.shutdown()
            server.server_close()

        assert result is not None
        assert result.get("ok") is False
        assert result.get("error") == "admin_timeout"
        message = str(result.get("message"))
        assert "3 seconds" in message
        assert any(
            stage in message
            for stage in (
                "discovery-token refresh",
                "authenticated retry",
                "authenticated retry response",
            )
        ), message
        assert (
            _AUTH_CALL_BUDGET_SECONDS
            <= elapsed
            < _AUTH_CALL_BUDGET_SECONDS + _AUTH_REFUSAL_SECONDS
        )
        assert len(_AuthDeadlineHandler.requests) == 2
        assert all(
            path.startswith("/projects ") for path in _AuthDeadlineHandler.requests
        )


@pytest.mark.usefixtures("isolated_status_dir")
class TestRedirectsAreRefused:
    """The transport declines 3xx on every path rather than following it.

    A redirect means something other than the intended loopback service
    answered. Following one lets that responder choose the destination, and
    because the standard library copies request headers onto the redirect
    target without comparing hosts, a redirected credential-bearing call would
    carry the bearer token off-host. Both handlers below are real servers on
    loopback; the sink records anything that reaches it.
    """

    def _serve_pair(self) -> tuple[ThreadingHTTPServer, ThreadingHTTPServer, int]:
        _RedirectSinkHandler.received.clear()
        _RedirectingHandler.seen_authorization.clear()
        sink, sink_port = _serve(_RedirectSinkHandler)
        _RedirectingHandler.sink_port = sink_port
        redirector, redirector_port = _serve(_RedirectingHandler)
        return sink, redirector, redirector_port

    def test_health_probe_refuses_a_redirect(self) -> None:
        from ..serviceclient._transport import _try_http_health

        sink, redirector, port = self._serve_pair()
        try:
            answer = _try_http_health(port, timeout=5.0)
        finally:
            for server in (redirector, sink):
                server.shutdown()
                server.server_close()

        # The redirect was declined, so no token was obtained at all - and in
        # particular not the sink's, which would have been taken as genuine.
        assert answer == {"status": "error", "http_code": 302}
        assert _RedirectSinkHandler.received == []

    def test_credential_bearing_call_refuses_a_redirect_and_withholds_the_token(
        self,
    ) -> None:
        import json as _json

        from ..serviceclient._discovery import _status_file
        from ..serviceclient._transport import _try_http_admin

        token = "loopback-bearer-token"
        sink, redirector, port = self._serve_pair()
        _status_file().write_text(
            _json.dumps({"pid": os.getpid(), "port": port, "service_token": token}),
            encoding="utf-8",
        )
        try:
            result = _try_http_admin("list_projects", {}, port, timeout=5.0)
        finally:
            for server in (redirector, sink):
                server.shutdown()
                server.server_close()

        # Guard against a vacuous pass: the call must genuinely have carried the
        # credential, or "the token did not leak" would prove nothing.
        assert any(
            sent == f"Bearer {token}" for sent in _RedirectingHandler.seen_authorization
        )

        # The credential never reached the redirect target.
        assert _RedirectSinkHandler.received == []

        # And the sink's body was never adopted as a service response.
        assert result is not None
        assert "sink-token-never-legitimate" not in str(result)


class _SlowHandler(QuietHandler):
    """Answer only after a delay far longer than any bound under test."""

    def do_GET(self) -> None:
        time.sleep(5.0)
        body = b"{}"
        with contextlib.suppress(
            BrokenPipeError,
            ConnectionAbortedError,
            ConnectionResetError,
        ):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)


@pytest.mark.usefixtures("isolated_status_dir", "isolated_admin_timeout_env")
class TestOmittedTimeoutIsBounded:
    """A call that names no timeout is bounded, not left to wait forever.

    An unbounded wait is both a wedged command and, because these requests carry
    the service bearer credential, an unbounded window in which that credential
    is in flight. The bound is asserted against a real server that never answers
    within it, so the test proves the caller gave up rather than that the server
    happened to be quick.
    """

    def test_call_without_a_timeout_argument_gives_up(self) -> None:
        from ..serviceclient._transport import _do_http_call

        os.environ["VAULTSPEC_RAG_ADMIN_TIMEOUT"] = "0.75"
        server, port = _serve(_SlowHandler)
        started = time.monotonic()
        try:
            with pytest.raises(TimeoutError):
                # No timeout argument: the resolved policy must supply one.
                _do_http_call(port, "/service-state", None)
        finally:
            elapsed = time.monotonic() - started
            server.shutdown()
            server.server_close()

        # Bounded by the resolved policy rather than by the server's own delay,
        # which is several times longer.
        assert elapsed < 4.0


class _NonObjectBodyHandler(QuietHandler):
    """Answer with valid JSON that is not an object.

    This is the shape a foreign process on the port produces - the very
    condition the redirect and identity work is written around - and it is
    valid JSON, so it survives every parse guard that only catches malformed
    input.
    """

    def do_GET(self) -> None:
        body = b'["not", "a", "dict"]'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _HealthyHandler(QuietHandler):
    """Answer the health route the way a live daemon does."""

    def do_GET(self) -> None:
        import json as _json

        body = _json.dumps(
            {"status": "ready", "pid": 4242, "service_token": "live-token"}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _UnhealthyHandler(QuietHandler):
    """Answer with a server error: the service is up, but not well."""

    def do_GET(self) -> None:
        self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "0")
        self.end_headers()


# Bound for a probe whose stub answers at once. The shipped health bound is a few
# seconds, and a loaded runner can stall a stub's reply thread past that, which
# turns an answered probe into the timeout outcome and fails the assertion on
# the answer. A stub that answers never waits this long, so it costs nothing.
_ANSWERED_PROBE_TIMEOUT_SECONDS = 60.0


@pytest.mark.usefixtures("isolated_status_dir")
class TestHealthProbeContract:
    """The health owner reports four outcomes and raises for none of them.

    Callers branch on the returned value rather than catching, because several
    sit inside lifecycle verbs that must emit exactly one structured outcome on
    every exit path. An exception escaping here would become a second one, so
    "never raises" is a contract rather than a convenience.
    """

    def test_live_service_returns_the_parsed_body(self) -> None:
        from ..serviceclient._transport import _try_http_health

        server, port = _serve(_HealthyHandler)
        try:
            result = _try_http_health(port, timeout=_ANSWERED_PROBE_TIMEOUT_SECONDS)
        finally:
            server.shutdown()
            server.server_close()

        assert result is not None
        assert result["status"] == "ready", result
        assert result["service_token"] == "live-token"

    def test_unhealthy_service_is_distinguished_from_unreachable(self) -> None:
        from ..serviceclient._transport import _try_http_health

        server, port = _serve(_UnhealthyHandler)
        try:
            result = _try_http_health(port, timeout=_ANSWERED_PROBE_TIMEOUT_SECONDS)
        finally:
            server.shutdown()
            server.server_close()

        # Answered, so not the unreachable sentinel - a caller must be able to
        # tell a sick daemon from an absent one.
        assert result is not None
        assert result["status"] == "error", result
        assert result.get("http_code") == 503, result

    def test_unreachable_service_returns_the_sentinel(self, refused_port: int) -> None:
        from ..serviceclient._transport import _try_http_health

        assert _try_http_health(refused_port) is None

    def test_timed_out_probe_is_distinguished_from_unreachable(self) -> None:
        from ..serviceclient._transport import _try_http_health, health_probe_timed_out

        server, port = _serve(_SlowHandler)
        try:
            result = _try_http_health(port, timeout=0.4)
        finally:
            server.shutdown()
            server.server_close()

        # Accepted but unanswered is presence without an answer, not absence.
        # Proven able to fail: folding the timeout back into the unreachable
        # sentinel returns None here and fails the not-None assertion; stamping
        # it with a different discriminator fails the predicate assertion.
        assert result is not None
        assert health_probe_timed_out(result)
        assert result["status"] == "error"

    def test_no_outcome_raises(self, refused_port: int) -> None:
        from ..serviceclient._transport import _try_http_health

        # The three outcomes above, plus a port that answers nothing at all,
        # all return rather than raise. Any escape here would reach a verb
        # bound to emit exactly one structured outcome.
        healthy, healthy_port = _serve(_HealthyHandler)
        unhealthy, unhealthy_port = _serve(_UnhealthyHandler)
        try:
            for port in (healthy_port, unhealthy_port, refused_port):
                _try_http_health(port)
        finally:
            for server in (healthy, unhealthy):
                server.shutdown()
                server.server_close()


class _SlowHealthyHandler(QuietHandler):
    """Accept promptly, then answer well after the fast connect deadline.

    Stands in for a live daemon whose worker threads are busy: the kernel
    completes the TCP handshake immediately, the HTTP answer takes a while.
    """

    def do_GET(self) -> None:
        import json

        time.sleep(0.5)
        body = json.dumps(
            {"status": "ready", "pid": 4242, "service_token": "slow-token"}
        ).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.mark.usefixtures("isolated_status_dir")
class TestConnectGateSemantics:
    """The transport bounds the TCP connect alone, not the whole exchange.

    On Windows a connect to a dead loopback port surfaces WSAECONNREFUSED only
    after ~1s of SYN retransmission, so every "is the service up" decision that
    waited for the full refusal paid that second. The gate cuts the wait while
    changing no verdict: a dead port still reads as down (the refused path,
    never the timeout envelope), and a live-but-slow responder still gets the
    full response deadline.
    """

    def test_dead_port_reads_as_down_well_under_the_refusal_floor(
        self, refused_port: int
    ) -> None:
        from ..serviceclient._transport import _try_http_health

        started = time.perf_counter()
        result = _try_http_health(refused_port)
        elapsed = time.perf_counter() - started

        assert result is None
        # Proven able to fail: removing the fast connect gate from
        # _try_http_health leaves the probe waiting out the Windows SYN
        # retransmission (~1s) and fails this bound.
        assert elapsed < 0.9, f"dead-port health probe took {elapsed:.3f}s"

    def test_dead_port_general_call_reads_as_down_not_as_a_timeout(
        self, refused_port: int
    ) -> None:
        started = time.perf_counter()
        result = _try_http_admin("list_projects", {}, refused_port)
        elapsed = time.perf_counter() - started

        # None is the refused/service-down sentinel. Proven able to fail: a
        # gate that surfaced its bounded connect as a TimeoutError instead of
        # ConnectionRefusedError comes back as the admin_timeout envelope and
        # fails the sentinel assertion - the distinction every caller's
        # fallback decision rides on.
        assert result is None
        assert elapsed < 0.9, f"dead-port admin call took {elapsed:.3f}s"

    def test_slow_responder_is_not_misread_as_down(self) -> None:
        from ..serviceclient._transport import _try_http_health

        server, port = _serve(_SlowHealthyHandler)
        try:
            result = _try_http_health(port)
        finally:
            server.shutdown()
            server.server_close()

        # Proven able to fail: applying the fast connect bound to the whole
        # exchange (passing it as the urllib timeout) turns this slow answer
        # into the unreachable sentinel and fails the not-None assertion.
        assert result is not None
        assert result["status"] == "ready"
        assert result["service_token"] == "slow-token"

    def test_conservative_probe_waits_for_the_authoritative_refusal(
        self, refused_port: int
    ) -> None:
        from ..serviceclient._transport import _try_http_health

        started = time.perf_counter()
        result = _try_http_health(refused_port, connect_timeout=None)
        elapsed = time.perf_counter() - started

        assert result is None
        if sys.platform == "win32":
            # The opt-out exists for callers whose success claim rides on the
            # answer (stop verification): they wait for the OS's authoritative
            # refusal, which Windows delivers only after ~1s of SYN
            # retransmission. Proven able to fail: an opt-out that silently
            # kept the fast gate returns in ~0.15s and fails this lower bound.
            assert elapsed > 0.5, f"opt-out probe returned in {elapsed:.3f}s"


@pytest.mark.usefixtures("isolated_status_dir")
class TestNonObjectHealthBodyCannotEscape:
    """A live peer answering with non-object JSON must not reach the callers.

    Every caller of the health owner treats its result as a mapping. A value
    that is valid JSON but not an object would satisfy the parse and then fail
    at the first attribute access - inside verbs that must emit exactly one
    structured outcome on every exit path. The owner therefore reports it as
    unreachable rather than passing the shape through.

    This is the branch the dead-port guard cannot reach: only a LIVE responder
    can produce it, so a test that never binds a port asserts the property for
    the easy half of the input space.
    """

    def test_owner_reports_a_non_object_body_as_unreachable(self) -> None:
        from ..serviceclient._transport import _try_http_health

        server, port = _serve(_NonObjectBodyHandler)
        try:
            result = _try_http_health(port)
        finally:
            server.shutdown()
            server.server_close()

        # Not the list, and not an exception: the sentinel.
        assert result is None

    def test_stop_verb_still_emits_one_envelope_against_such_a_peer(
        self, tmp_path: Path
    ) -> None:
        server, port = _serve(_NonObjectBodyHandler)
        os.environ[EnvVar.STATUS_DIR.value] = str(tmp_path)
        try:
            from ._cli_helpers import app, runner

            result = runner.invoke(
                app, ["server", "stop", "--port", str(port), "--json"]
            )
        finally:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
            server.shutdown()
            server.server_close()

        payloads = [
            line for line in result.output.splitlines() if line.strip().startswith("{")
        ]
        # The regression this guards: previously the verb raised AttributeError
        # and emitted nothing at all, which is the one outcome a supervising
        # broker cannot interpret.
        assert len(payloads) == 1, f"expected one envelope, got {result.output!r}"
        assert "AttributeError" not in result.output
