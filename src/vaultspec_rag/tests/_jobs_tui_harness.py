"""Shared harness for the server-watch suites.

Everything needed to drive a real Textual app: the record and payload
builders, the fake service answering the routes the watch polls, the app
fixture, and the settle helpers that wait for a repaint rather than sleep.
One home, so the suites can be split by subject without each growing its
own copy - which is how fixtures drift apart.
"""

from __future__ import annotations

import asyncio
import http.server
import json
import threading
import time
import typing
import urllib.parse

import pytest
from textual.app import ScreenStackError
from textual.widgets import DataTable

from ..cli._jobs_tui import (
    _SPINNER_INTERVAL,
    ServerWatchApp,
)
from ..service_quiesce import QuiesceSnapshot, QuiesceState
from ..serviceclient._transport import DEFAULT_ADMIN_TIMEOUT_SECONDS, _try_http_admin

#: The harness surface the watch suites import. Declared because these are
#: this module's public API to its siblings, not module-private helpers -
#: without it a checker reads every one as defined and never used, since
#: nothing inside this module calls them.
__all__ = [
    "_HANDOFF_TIMEOUT",
    "_NARROW",
    "_POLL_INTERVAL",
    "_READY_RETRIES",
    "_WIDE",
    "_JobService",
    "_app",
    "_await_gone",
    "_await_painted",
    "_await_painted_when",
    "_finished_job",
    "_header_line",
    "_health_payload",
    "_hold",
    "_job",
    "_jobs_payload",
    "_line_with",
    "_log_payload",
    "_quiesce_block",
    "_ready",
    "_requested_state",
    "_row_line",
    "_screen_failure",
    "_screen_text",
    "_search_activity_payload",
    "_served_search",
    "_settle",
    "_settled_paint",
    "_summarise",
    "_unpainted",
]


pytestmark = [pytest.mark.unit]
_HANDOFF_TIMEOUT = DEFAULT_ADMIN_TIMEOUT_SECONDS * 1.5
_READY_RETRIES = 3
_POLL_INTERVAL = 0.005
_WIDE = (200, 24)
_NARROW = (80, 24)


def _job(
    job_id: str,
    **overrides: object,
) -> dict[str, object]:
    """Build one job resource in the shape the service publishes."""
    defaults: dict[str, object] = {
        "phase": "running",
        "state": "running",
        "desired": None,
        "root": "/repos/example-worktrees/main",
        "completed": 300,
        "total": 1000,
        "remaining": 140.0,
        "rate": 5.0,
        "capabilities": None,
    }
    details = defaults | overrides
    state = str(details["state"])
    desired = details["desired"]
    capabilities = details["capabilities"]
    return {
        "id": job_id,
        "revision": 3,
        "phase": details["phase"],
        "state": state,
        "desired_state": desired if desired is not None else state,
        "source": "code",
        "trigger": "tool",
        "started_at": 1000.0,
        "finished_at": None,
        "admission_acquired_at": 1001.0,
        "runtime_seconds": 75.0,
        "last_progress_age_seconds": 1.0,
        "stalled": False,
        "progress_rate_per_second": details["rate"],
        "estimated_remaining_seconds": details["remaining"],
        "progress": {
            "step": "embed + upsert chunks",
            "completed": details["completed"],
            "total": details["total"],
            "last_updated": 1070.0,
        },
        "initiator": {
            "kind": "tool",
            "command": "reindex_codebase",
            "project_root": details["root"],
        },
        "capabilities": capabilities
        if capabilities is not None
        else {
            "pausable": True,
            "resumable": False,
            "cancellable": True,
            "retryable": False,
            "deletable": False,
            "force_killable": False,
        },
    }


def _finished_job(job_id: str) -> dict[str, object]:
    """Build a job in the state most of an operator's list is actually in.

    ``phase`` is the compatibility label and ``state`` the canonical one, and
    they are not the same vocabulary: completed work is phase ``finished`` and
    state ``succeeded``. A fixture that puts the phase word in both fields
    matches no canonical state at all, and every count over it reads zero.
    """
    return _job(
        job_id,
        phase="finished",
        state="succeeded",
        remaining=None,
        rate=None,
        capabilities={
            "pausable": False,
            "resumable": False,
            "cancellable": False,
            "retryable": True,
            "deletable": True,
            "force_killable": False,
        },
    )


def _served_search(
    request_id: str,
    *,
    state: str = "active",
    query: str = "why is the index behind",
    outcome: str | None = None,
) -> dict[str, object]:
    """Build one actual activity-route record for a rendered TUI regression."""
    return {
        "request_id": request_id,
        "state": state,
        "source": "code",
        "type": "code",
        "root": "/repos/example-worktrees/main",
        "top_k": 8,
        "started_at": 1000.0,
        "finished_at": 1001.5 if state == "terminal" else None,
        "total_seconds": 1.5 if state == "terminal" else None,
        "status_code": 200 if state == "terminal" else None,
        "outcome": outcome,
        "result_count": 3 if state == "terminal" else None,
        "timings": {"search": 0.4} if state == "terminal" else {},
        "availability_cause": None,
        "error_code": None,
        "error_message": None,
        "query": query,
    }


def _summarise(records: list[dict[str, object]]) -> dict[str, object]:
    """Tally records by canonical state, in the shape the service publishes."""
    states = [str(record.get("state", "")) for record in records]
    tally: dict[str, object] = {name: states.count(name) for name in set(states)}
    tally["states"] = {name: states.count(name) for name in set(states)}
    # The job-health tallies ride beside the states, counted over every
    # record's service-stamped verdict - exactly as the service does.
    verdicts = [str(record.get("degradation", "")) for record in records]
    tally["degraded"] = verdicts.count("degraded")
    tally["stalled"] = verdicts.count("stalled")
    return tally


def _hold(gate: threading.Event | None) -> None:
    """Block a served request until the test releases *gate*.

    Bounded on the same deadline every wait in this file fails at, so a test
    that never reaches its release - because an assertion above it failed -
    leaves no server thread parked behind the session that ended.
    """
    if gate is not None:
        gate.wait(_HANDOFF_TIMEOUT)


class _JobService:
    """A real loopback service holding the job state it publishes.

    Deleting through it removes the job from what the next ``GET`` returns, and
    a desired-state request changes what the next ``GET`` says about that job.
    A fixture that answers every read from a fixed list cannot tell an action
    that converged from one whose answer was thrown away.
    """

    def __init__(self) -> None:
        self.requests: list[tuple[str, str]] = []
        self.jobs: list[dict[str, object]] = []
        self.control_delay = 0.0
        self.fetch_delay = 0.0
        # When set, a control - or a jobs read - is held until the test
        # releases it. A transient the interface paints for the length of a
        # delay is a race the test loses on a loaded machine: delivering the
        # keystroke pumps the event loop for as long as the box makes it, and
        # measurably outruns a several-hundred-millisecond delay, so the stage
        # is over before the first frame the test is able to read. Held on an
        # event instead, the stage ends on the observation that proves it, and
        # the ordering the assertion claims is the ordering the service
        # enforces rather than one the schedule happened to allow.
        self.control_gate: threading.Event | None = None
        self.fetch_gate: threading.Event | None = None
        # When set, ``/logs`` answers with these lines verbatim instead of the
        # per-job placeholder, so a test can serve the service's real log
        # dialects - including adversarial content - through the real route.
        self.log_lines: list[str] | None = None
        # The managed Qdrant producer has its own retained source group. The
        # all-source route must not fold this into the service group merely
        # because a selected-job inspection only asks the latter for lines.
        self.qdrant_log_lines: list[str] = ["a qdrant log line"]
        self.search_active: list[dict[str, object]] = []
        self.search_recent: list[dict[str, object]] = []
        # When set, the response reports more retained records than it
        # returns, which is what a bounded projection over a busy ledger
        # looks like. Absent, every record is served and no marker is due.
        self.search_total_override: int | None = None
        # When set, the jobs listing carries this GPU pressure block; when
        # ``None`` the key is omitted entirely, which is how a daemon older
        # than the field answers.
        self.gpu: dict[str, object] | None = None
        # When set, the jobs listing carries this machine pressure block;
        # ``None`` omits the key - a daemon that predates the tier.
        self.pressure: dict[str, object] | None = None
        # When set, the jobs listing carries this quiesce controller
        # observation; ``None`` omits the key, which is how a daemon older
        # than the controller answers.
        self.quiesce: dict[str, object] | None = None
        # What ``/health`` reports as the daemon's release. ``None`` omits
        # the field, which is how a daemon that predates version reporting
        # answers - not an empty string, and never the client's own number.
        self.package_version: str | None = None
        # When set, every control is answered with this ``(code, message)``
        # rather than performed - the shape a service uses to decline a
        # request it understood.
        self.refusal: tuple[str, str] | None = None
        self._lock = threading.Lock()
        service = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.0"

            def log_message(self, format: str, *args: object) -> None:
                # Named to match the override; the server logs nothing.
                del format, args

            def _answer(self, payload: dict[str, object]) -> None:
                body = json.dumps(payload).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _record(self, method: str) -> tuple[str, dict[str, list[str]]]:
                with service._lock:
                    service.requests.append((method, self.path))
                parsed = urllib.parse.urlparse(self.path)
                return parsed.path, urllib.parse.parse_qs(parsed.query)

            def do_GET(self) -> None:
                path, query = self._record("GET")
                response = {
                    "/health": _health_payload,
                    "/search-activity": _search_activity_payload,
                }.get(path)
                if response is not None:
                    self._answer(response(service))
                    return
                if path.startswith("/logs"):
                    self._answer(_log_payload(service, query))
                    return
                time.sleep(service.fetch_delay)
                _hold(service.fetch_gate)
                self._answer(_jobs_payload(service, query))

            def _mutate(self, method: str) -> None:
                path, _query = self._record(method)
                state = _requested_state(self)
                time.sleep(service.control_delay)
                # Held before the lock, so the reads the interface keeps
                # issuing while a control is outstanding are answered rather
                # than queued behind it.
                _hold(service.control_gate)
                segments = path.strip("/").split("/")
                job_id = urllib.parse.unquote(segments[1]) if len(segments) > 1 else ""
                suffix = segments[2] if len(segments) > 2 else ""
                with service._lock:
                    found = next(
                        (job for job in service.jobs if job.get("id") == job_id), None
                    )
                    if found is None:
                        # The envelope the service actually returns for a
                        # control naming a job it no longer holds.
                        self._answer(
                            {
                                "ok": False,
                                "code": "job_not_found",
                                "message": "The job was not found.",
                            }
                        )
                        return
                    if service.refusal is not None:
                        code, message = service.refusal
                        self._answer({"ok": False, "code": code, "message": message})
                        return
                    if method == "DELETE":
                        service.jobs.remove(found)
                    elif suffix == "desired-state":
                        found["desired_state"] = state
                self._answer({"ok": True, "code": "accepted", "job": {}})

            def do_PUT(self) -> None:
                self._mutate("PUT")

            def do_POST(self) -> None:
                self._mutate("POST")

            def do_DELETE(self) -> None:
                self._mutate("DELETE")

        # Threading, because the interface issues a control and a poll from
        # separate worker threads and a single-threaded server would make the
        # slower of the two look like a hang.
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.server.daemon_threads = True
        # ``shutdown`` blocks until the accept loop next checks its flag, so the
        # poll interval is paid in full by every teardown. The default half
        # second dominates a file that stands one of these up per test.
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            kwargs={"poll_interval": 0.005},
            daemon=True,
        )
        self.thread.start()

    @property
    def port(self) -> int:
        return int(self.server.server_address[1])

    def set_jobs(self, jobs: list[dict[str, object]]) -> None:
        with self._lock:
            self.jobs = list(jobs)

    def job_ids(self) -> list[str]:
        with self._lock:
            return [str(job.get("id")) for job in self.jobs]

    def set_search_activity(
        self,
        *,
        active: list[dict[str, object]],
        recent: list[dict[str, object]],
    ) -> None:
        with self._lock:
            self.search_active = list(active)
            self.search_recent = list(recent)

    def close(self) -> None:
        # A test that failed before its release left a request held. Freeing
        # them here costs a teardown nothing and keeps a failing assertion from
        # also spending the hold's whole bound.
        for gate in (self.control_gate, self.fetch_gate):
            if gate is not None:
                gate.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=_HANDOFF_TIMEOUT)

    def control_paths(self) -> list[str]:
        with self._lock:
            return [path for method, path in self.requests if method != "GET"]


def _quiesce_block(
    *,
    state: QuiesceState,
    vram_released: bool,
    safe_to_borrow_gpu: bool,
) -> dict[str, object]:
    """Publish one controller observation exactly as the service renders it.

    Built through the controller's own snapshot rather than as a literal
    mapping, so a field added to or dropped from the canonical vocabulary
    reaches this fixture instead of leaving it asserting against a shape the
    service stopped publishing.
    """
    return QuiesceSnapshot(
        state=state,
        admission_epoch=7,
        admissions_open=state is QuiesceState.RUNNING,
        active_compute_tickets=0,
        drain_complete=state is not QuiesceState.RUNNING,
        vram_released=vram_released,
        safe_to_borrow_gpu=safe_to_borrow_gpu,
        pause_requested_at=None,
        drain_acknowledged_at=None,
        quiesced_at=None,
        warming_started_at=None,
        failure_reason=None,
    ).as_envelope()


def _jobs_payload(
    service: _JobService, query: dict[str, list[str]]
) -> dict[str, object]:
    """Answer the jobs listing: the page, the tallies, and the GPU block."""
    limit = int(query.get("limit", ["20"])[0])
    with service._lock:
        held = list(service.jobs)
        gpu = service.gpu
        pressure = service.pressure
        quiesce = service.quiesce
    page = held[:limit]
    payload: dict[str, object] = {
        "ok": True,
        "jobs": page,
        "total": len(held),
        "returned": len(page),
        # Tallied over everything held, exactly as the service does - the
        # page is not the population.
        "summary": _summarise(held),
    }
    if gpu is not None:
        payload["gpu"] = gpu
    if pressure is not None:
        payload["pressure"] = pressure
    if quiesce is not None:
        payload["quiesce"] = quiesce
    return payload


def _health_payload(service: _JobService) -> dict[str, object]:
    """Answer ``/health`` the way the real daemon does.

    The version field is present exactly when the fixture was given one;
    a daemon that predates version reporting omits the field entirely.
    """
    with service._lock:
        version = service.package_version
    payload: dict[str, object] = {"ok": True, "status": "ready"}
    if version is not None:
        payload["package_version"] = version
    return payload


def _log_payload(
    service: _JobService, query: dict[str, list[str]]
) -> dict[str, object]:
    """Answer ``/logs`` with the grouped managed-log transport contract."""
    scope = query.get("job_id", ["none"])[0]
    source = query.get("source", ["all"])[0]
    lines = int(query.get("lines", ["200"])[0])
    filters = {
        key: values[0]
        for key, values in query.items()
        if key in {"job_id", "contains"} and values and values[0]
    }
    with service._lock:
        service_lines = (
            list(service.log_lines)
            if service.log_lines is not None
            else [f"a logged line for {scope}"]
        )
        qdrant_lines = list(service.qdrant_log_lines)
    source_lines = {
        "service": service_lines[-lines:],
        "qdrant": qdrant_lines[-lines:],
    }
    selected = ("service", "qdrant") if source == "all" else (source,)
    return {
        "ok": True,
        "source": source,
        "limit": lines,
        "groups": [
            {"source": producer, "lines": source_lines[producer]}
            for producer in selected
        ],
        "filters": filters,
    }


def _search_activity_payload(service: _JobService) -> dict[str, object]:
    """Return the bounded activity response the authenticated admin route owns."""
    with service._lock:
        active = list(service.search_active)
        recent = list(service.search_recent)
    return {
        "ok": True,
        "active": active,
        "recent": recent,
        "counts": {
            "active": len(active),
            "recent": len(recent),
            "total": service.search_total_override or (len(active) + len(recent)),
        },
        "returned": len(active) + len(recent),
        "filters": {
            "state": None,
            "type": None,
            "root": None,
            "request_id": None,
            "since": None,
            "limit": 100,
        },
    }


def _requested_state(handler: http.server.BaseHTTPRequestHandler) -> object:
    """Read the desired state out of a control request's body."""
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return None
    payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    if not isinstance(payload, dict):
        return None
    fields = typing.cast("dict[str, object]", payload)
    return fields.get("state")


def _app(
    service: _JobService,
    jobs: list[dict[str, object]] | None = None,
    *,
    limit: int = 20,
    interval: float = 3600.0,
    watch_mode: str = "jobs",
) -> ServerWatchApp:
    """Build the interface over *service*, reached through the real transport."""
    if jobs is not None:
        service.set_jobs(jobs)

    def fetch() -> dict[str, object] | None:
        return _try_http_admin("get_jobs", {"limit": limit}, service.port)

    # A long interval keeps the periodic refresh out of the way; every test
    # drives the first load explicitly.
    return ServerWatchApp(
        fetch=fetch,
        port=service.port,
        interval=interval,
        watch_mode=watch_mode,
    )


def _screen_text(app: ServerWatchApp) -> str:
    """Return what the interface actually painted, as text.

    Pill contents use non-breaking spaces so a pill wraps as one unit; they
    read as ordinary spaces, so they are normalised here and every
    assertion matches what an operator sees.
    """
    return "\n".join(
        strip.text.replace("\u2800", " ")
        for strip in app.screen._compositor.render_strips()
    )


def _line_with(painted: str, needle: str) -> str:
    """Return the first painted line carrying *needle*, or an empty string."""
    for line in painted.splitlines():
        if needle in line:
            return line
    return ""


def _header_line(app: ServerWatchApp) -> str:
    """Return the painted jobs header line.

    Found by its content rather than by its position: this screen carries
    other bars, and which one lands on the first row is not this file's
    business. An index would silently start asserting about a neighbour.
    """
    for line in _screen_text(app).splitlines():
        if "vaultspec-rag" in line:
            return line
    return ""


def _row_line(app: ServerWatchApp, *needles: str) -> str | None:
    """Return the painted line carrying every one of *needles*, or ``None``.

    A row's second line holds the state cell's second line beside that job's
    own id, so requiring both pins the assertion to the row. Searching the
    whole screen instead would be satisfied by the toast and the header, which
    carry the same words - and those are exactly what the row is supposed to
    outlive.
    """
    for line in _screen_text(app).splitlines():
        if all(needle in line for needle in needles):
            return line
    return None


async def _ready(pilot: typing.Any, app: ServerWatchApp) -> None:
    """Wait until the interface has completed its first real paint.

    Mounting, the threaded fetch, and the column division each take their own
    turn of the event loop, and the division waits again on the layout pass
    that gives the table its final width. Asserting before all of that would be
    asserting about a half-drawn frame.

    The width alone is not enough to know the layout has settled: before the
    log pane is placed the table briefly reports the whole terminal, and the
    shares divided from that agree with it. So the division has to survive a
    frame tick - the interval at which the interface re-reads the width - to
    count as settled.

    The tick is spanned by holding the agreement rather than by sleeping over
    it: the match is re-read every poll and the clock restarts the moment it
    breaks, so the window closes only on a division that agreed for the whole
    of it. Sleeping a tick and re-reading afterwards checks two instants and
    is blind to everything between them, and pays a full tick for each of the
    several rounds the first paint takes.

    That held interval is a stability requirement and not a tolerance:
    lengthening it demands agreement over more of the interface's own beat and
    can only ever refuse a frame it would previously have accepted. The
    deadline is the opposite kind of number and is documented where it is set.
    """
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    matched_at: float | None = None
    matched_width: int | None = None
    retries = _READY_RETRIES
    while time.monotonic() < deadline:
        await pilot.pause()
        # A failed fetch is not a paint still on its way: nothing else will ask
        # again inside this test's lifetime, so the wait would sit out its whole
        # bound over one refused socket and report it as an interface that never
        # painted. Re-asked only once per finished attempt, and only a bounded
        # number of times, so a service that is genuinely silent still ends at
        # the deadline rather than being hammered until it.
        if (
            app._last_error is not None
            and retries > 0
            and not any(worker.is_running for worker in app.workers)
        ):
            retries -= 1
            app.action_refresh_now()
        unmet = _unpainted(app)
        if unmet:
            matched_at = None
            await asyncio.sleep(_POLL_INTERVAL)
            continue
        width = app.query_one("#jobs", DataTable).size.width
        now = time.monotonic()
        if matched_at is None or matched_width != width:
            matched_at, matched_width = now, width
        elif now - matched_at >= _SPINNER_INTERVAL * 1.5:
            return
        await asyncio.sleep(_POLL_INTERVAL)
    raise AssertionError(
        "the interface never completed its first paint after "
        f"{_HANDOFF_TIMEOUT:g}s: {'; '.join(_unpainted(app)) or 'nothing outstanding'}"
        + (
            f"; the interface last reported: {app._last_error}"
            if app._last_error is not None
            else ""
        )
    )


def _unpainted(app: ServerWatchApp) -> list[str]:
    """Name whatever the first paint is still missing, in the operator's terms.

    The wait and its failure message read the same list, so a timeout says which
    part never arrived instead of leaving the next reader to guess between a
    list that never landed, a division that never settled and a fetch that
    failed. Three separate investigations have started from that guess.
    """
    found = app.query("#jobs")
    if not found:
        return ["the table is not mounted"]
    table = app._table()
    if table is None:
        return ["the table is not mounted"]
    missing: list[str] = []
    if not app._jobs:
        missing.append("no job list has been applied")
    elif table.row_count != len(app._jobs):
        missing.append(f"{table.row_count} rows painted for {len(app._jobs)} jobs")
    if app._layout.bar_cells <= 0:
        missing.append("the columns have not been divided")
    elif app._layout.divided_width != table.size.width:
        missing.append(
            f"the division is for width {app._layout.divided_width}, "
            f"the table is {table.size.width}"
        )
    # A row must be selected too. Every control acts on the selection, so a test
    # that starts pressing keys before one exists is testing a frame no operator
    # ever sees.
    if not app.selected_id:
        missing.append("no row is selected")
    return missing


async def _settle(pilot: typing.Any) -> None:
    """Wait for the interface's worker threads to finish their requests."""
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    while time.monotonic() < deadline:
        await pilot.pause()
        if not any(worker.is_running for worker in pilot.app.workers):
            return
        await asyncio.sleep(_POLL_INTERVAL)
    raise AssertionError("the interface's workers did not settle")


async def _settled_paint(pilot: typing.Any, app: ServerWatchApp) -> None:
    """Let the layout settle after a change that re-divides the columns.

    Held across a frame tick rather than slept over, for the reason given in
    ``_ready``.
    """
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    matched_at: float | None = None
    matched_width: int | None = None
    while time.monotonic() < deadline:
        await pilot.pause()
        table = app.query("#jobs")
        # A table the layout has taken off the screen has no width to settle
        # on, and none of its own to divide.
        if not table or not table.only_one(DataTable).display:
            return
        width = table.only_one(DataTable).size.width
        now = time.monotonic()
        if app._layout.divided_width != width:
            matched_at = None
        elif matched_at is None or matched_width != width:
            matched_at, matched_width = now, width
        elif now - matched_at >= _SPINNER_INTERVAL * 1.5:
            return
        await asyncio.sleep(_POLL_INTERVAL)


async def _await_painted(pilot: typing.Any, app: ServerWatchApp, needle: str) -> str:
    """Return the painted screen once *needle* is on it.

    Every outcome this asserts on arrives through a worker thread and a
    repaint, so the wait is on the pixels rather than on a worker count: a
    control whose answer was discarded leaves the workers idle and the screen
    unchanged, which is precisely the defect being tested for.
    """
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    painted = ""
    while time.monotonic() < deadline:
        await pilot.pause()
        painted = _screen_text(app)
        if needle in painted:
            return painted
        await asyncio.sleep(_POLL_INTERVAL)
    raise AssertionError(f"{needle!r} was never painted; last frame:\n{painted}")


async def _await_painted_when(
    pilot: typing.Any,
    app: ServerWatchApp,
    predicate: typing.Callable[[str], bool],
    described: str,
) -> str:
    """Return the painted screen once *predicate* accepts it."""
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    painted = ""
    while time.monotonic() < deadline:
        await pilot.pause()
        painted = _screen_text(app)
        if predicate(painted):
            return painted
        await asyncio.sleep(_POLL_INTERVAL)
    raise AssertionError(f"{described} was never painted; last frame:\n{painted}")


async def _await_gone(pilot: typing.Any, app: ServerWatchApp, needle: str) -> str:
    """Return the painted screen once *needle* has left it."""
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    painted = ""
    while time.monotonic() < deadline:
        await pilot.pause()
        painted = _screen_text(app)
        if needle not in painted:
            return painted
        await asyncio.sleep(_POLL_INTERVAL)
    raise AssertionError(f"{needle!r} never left the screen; last frame:\n{painted}")


def _screen_failure(deliver: typing.Callable[[], object]) -> ScreenStackError | None:
    """Run *deliver*, returning the screen error it raised, or ``None``.

    The raise is the finding, so it is captured and named by an assertion
    rather than left to surface as an error on the run.
    """
    try:
        deliver()
    except ScreenStackError as error:
        return error
    return None
