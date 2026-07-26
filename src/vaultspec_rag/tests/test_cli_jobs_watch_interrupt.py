"""Guard tests for the ``server jobs --watch`` interrupt path.

These are guard tests, not positive coverage. Their subject is that an operator
interrupt is NOT swallowed and NOT deferred:

- the refresh runs off the main thread, so an interrupt arriving while the
  service has yet to answer is serviced immediately instead of after the
  request's timeout (on Windows a thread parked in a blocking socket read
  reaches no interpreter check, so an inline refresh makes Ctrl+C inert for
  however long the service takes);
- the interrupt terminates the view on the conventional interrupted status
  rather than the success the operator never got;
- the refresh is a read request, so abandoning one mid-flight cannot leave the
  service modified.

The first test asserts the interrupt lands while the refresh is *still
blocked*: run the refresh inline again and it fails, because the main thread
never reaches its wait.

The off-thread mechanism itself is shared with the start command's health
wait, so those tests drive it at its own home rather than through a
jobs-local alias, and a separate test holds the watch loop to using it.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING, Any

import pytest
from typer.testing import CliRunner

from ..cli import _service_jobs as jobs
from ..cli import app
from ..cli._process import _call_interruptibly

if TYPE_CHECKING:
    from collections.abc import Callable

pytestmark = [pytest.mark.unit]

runner = CliRunner()

# Bound on every cross-thread handoff below. Generous enough that a loaded
# machine never trips it, finite so a broken test fails instead of hanging.
_HANDOFF_TIMEOUT = 5.0


def test_interrupt_lands_while_the_refresh_is_still_blocked() -> None:
    """The main thread must not be waiting on the refresh to return.

    The refresh here is a real blocking wait, standing in for a service that
    has not answered yet. The interrupt is raised from the main thread's own
    wait - exactly where a console Ctrl+C is converted - and must propagate
    out with the refresh still in flight.
    """
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    def blocked_refresh() -> str:
        started.set()
        # Deliberately not asserted: run this refresh inline and the wait times
        # out, the refresh returns, and the guard fails on the interrupt that
        # never arrived rather than on a wait that never finished.
        release.wait(timeout=_HANDOFF_TIMEOUT)
        finished.set()
        return "answered late"

    ticks = 0

    def interrupting_wait(_seconds: float) -> None:
        nonlocal ticks
        ticks += 1
        # Only meaningful once the refresh is genuinely running concurrently:
        # if it were inline, this wait would never be reached at all.
        assert started.wait(timeout=_HANDOFF_TIMEOUT)
        raise KeyboardInterrupt

    try:
        with pytest.raises(KeyboardInterrupt):
            _call_interruptibly(blocked_refresh, sleep=interrupting_wait)
        assert ticks == 1
        # The load-bearing assertion: the operator got out before the service
        # answered, rather than after its timeout expired.
        assert not finished.is_set()
    finally:
        release.set()


def test_a_failed_refresh_is_reported_not_flattened_to_no_result() -> None:
    """A refresh that raises must reach the caller as that exception.

    Swallowing it in the worker would surface as ``None``, which the watch
    loop reads as "service not running" - a wrong diagnosis for a live
    service that merely failed one request.
    """
    boom = RuntimeError("refresh failed")

    def failing_refresh() -> dict[str, object]:
        raise boom

    with pytest.raises(RuntimeError) as caught:
        _call_interruptibly(failing_refresh)
    assert caught.value is boom


def test_watch_interrupt_exits_on_the_interrupted_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ctrl+C ends the view on 130 with the stop line and no traceback.

    Reporting 0 here would tell a script the watch completed normally. The
    interrupt is delivered from the real sleep the loop waits in, so the
    command's own handler is what is under test.
    """

    def _payload(_spec: jobs._JobsQuery) -> dict[str, object]:
        return {"jobs": [], "total": 0, "returned": 0}

    def _interrupt(_seconds: float) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr(jobs, "_default_service_port", lambda: 8766)
    monkeypatch.setattr(jobs, "_fetch_jobs_result", _payload)
    monkeypatch.setattr(time, "sleep", _interrupt)

    result = runner.invoke(app, ["server", "jobs", "--watch"])

    assert result.exit_code == 130
    assert "Stopped watching jobs." in result.output
    assert "Traceback" not in result.output
    assert result.exception is None or isinstance(result.exception, SystemExit)


def test_the_watch_loop_refreshes_through_the_shared_helper(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The watch loop must not grow its own copy of the off-thread wait.

    Two copies of this mechanism would drift into a Ctrl+C that works in one
    operator view and not the other, so the guard is that the loop routes
    through the shared helper. The stand-in delegates to the real one rather
    than replacing it, so the loop still runs for real.
    """
    calls = 0
    real = jobs._call_interruptibly

    def _counting[T](work: Callable[[], T], **kwargs: Any) -> T:
        nonlocal calls
        calls += 1
        return real(work, **kwargs)

    from ._cli_helpers import _jobs_empty_contract_server

    # Only the call counter is substituted, and it delegates to the real helper
    # rather than replacing it: the loop still fetches over a real socket from a
    # real server, and what is observed - that production routed through the
    # shared helper - is decided by production, not by the counter.
    monkeypatch.setattr(jobs, "_call_interruptibly", _counting)

    server, thread, requests = _jobs_empty_contract_server()
    try:
        result = runner.invoke(
            app,
            [
                "server",
                "jobs",
                "--watch",
                "--refresh-count",
                "2",
                "--port",
                str(server.server_address[1]),
            ],
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    assert result.exit_code == 0
    assert calls == 2, "each refresh must route through the shared helper"
    assert len(requests) == 2, "each refresh must reach the service"


def test_the_watch_refresh_is_a_read_only_request() -> None:
    """Abandoning a refresh cannot modify service state, a job, or a lock.

    The refresh runs against a bound server that serves GET and nothing else,
    so a mutating request would not have been answered. That is a stronger
    claim than resolving a captured tool name here, which only proved the
    resolver agrees with itself.

    Proven able to fail: routing the fetch through a POST tool leaves the GET
    handler unused and the request log empty.
    """
    from ._cli_helpers import _jobs_empty_contract_server

    server, thread, requests = _jobs_empty_contract_server()
    try:
        jobs._fetch_jobs_result(jobs._JobsQuery(port=server.server_address[1], limit=5))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    # The server answers GET only, so a mutating refresh would not have been
    # served at all. Observing the request it did receive binds the method to
    # what the loop actually sent rather than to a resolution recomputed here
    # from a captured tool name.
    assert len(requests) == 1, "the refresh must reach the service"
    assert requests[0].startswith("/jobs")


def test_the_refresh_thread_never_outlives_the_process() -> None:
    """An abandoned refresh must not hold the interpreter open at exit.

    A non-daemon worker would turn the prompt interrupt into a hang at
    shutdown, which is the same symptom by another route.
    """
    release = threading.Event()
    running: list[threading.Thread] = []

    def blocked_refresh() -> str:
        running.append(threading.current_thread())
        release.wait(timeout=_HANDOFF_TIMEOUT)
        return "answered late"

    def interrupting_wait(_seconds: float) -> None:
        while not running:
            time.sleep(0.01)
        raise KeyboardInterrupt

    try:
        with pytest.raises(KeyboardInterrupt):
            _call_interruptibly(blocked_refresh, sleep=interrupting_wait)
        assert running[0].daemon
    finally:
        release.set()
