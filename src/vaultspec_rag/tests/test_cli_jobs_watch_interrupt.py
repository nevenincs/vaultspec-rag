"""Guard tests for the interruptible off-thread wait, and the jobs fetch.

These are guard tests, not positive coverage. Their subject is that an
operator interrupt is NOT swallowed and NOT deferred:

- the wait runs off the main thread, so an interrupt arriving while a service
  has yet to answer is serviced immediately instead of after the request's
  timeout (on Windows a thread parked in a blocking socket read reaches no
  interpreter check, so an inline wait makes Ctrl+C inert for however long the
  service takes);
- a failing call reaches the caller as its own exception rather than as a
  missing result, which a caller would misread as a service being down;
- the worker never outlives the process.

The first test asserts the interrupt lands while the call is *still blocked*:
run it inline again and it fails, because the main thread never reaches its
wait. The remaining test holds the jobs fetch to being a read.

The live jobs view no longer polls on the main thread - it is an application
that owns its own event loop and runs its fetches on Textual workers, and is
covered by its own tests. What remains here is the shared wait, which the
start command's health poll still uses, and the fetch those views share.
"""

from __future__ import annotations

import threading
import time

import pytest
from typer.testing import CliRunner

from ..cli import _service_jobs as jobs
from ..cli._process import _call_interruptibly

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
