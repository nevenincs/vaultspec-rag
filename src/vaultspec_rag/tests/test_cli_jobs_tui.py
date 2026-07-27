"""Tests for the interactive jobs interface.

Operator feedback is a rendered artefact, so every assertion here runs against
what the interface actually painted, driven by real key presses through
Textual's pilot. Asserting on the model instead would prove only that a value
was computed, which is the failure mode this project has already paid for once.

The service behind the interface is a real loopback daemon holding real state:
its ``GET`` reflects the mutations its ``DELETE`` and ``PUT`` performed, and
the interface reaches it through the same transport the CLI uses. That is the
difference between proving a request was sent and proving the view converged
on what the service now holds - and a request that was sent, answered, and
then discarded is exactly the defect class this file exists to catch.
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
from textual.widgets import DataTable

from ..cli._jobs_tui import _SPINNER_FRAMES, _SPINNER_INTERVAL, JobsTuiApp
from ..serviceclient._transport import _try_http_admin

pytestmark = [pytest.mark.unit]

_HANDOFF_TIMEOUT = 10.0
# How often the waits below re-read the screen. Everything they wait on arrives
# on a worker thread, so the granularity is dead time added to every wait, not
# work: it buys nothing to sit on a settled frame for a whole tick.
_POLL_INTERVAL = 0.005
# Wide enough that a two-pane layout leaves every column, and a toast, room to
# paint whole. Anything asserted on rendered text needs the text to have fitted.
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


def _summarise(records: list[dict[str, object]]) -> dict[str, object]:
    """Tally records by canonical state, in the shape the service publishes."""
    states = [str(record.get("state", "")) for record in records]
    return {name: states.count(name) for name in set(states)} | {
        "states": {name: states.count(name) for name in set(states)}
    }


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
                if path.startswith("/logs"):
                    # Scoped to the job asked for, so a pane still showing the
                    # previous job's lines is distinguishable from one that
                    # refetched. A fixture answering every id identically
                    # cannot tell those two apart.
                    scope = query.get("job_id", ["none"])[0]
                    self._answer(
                        {
                            "ok": True,
                            "groups": [
                                {
                                    "source": "service",
                                    "lines": [f"a logged line for {scope}"],
                                }
                            ],
                        }
                    )
                    return
                time.sleep(service.fetch_delay)
                limit = int(query.get("limit", ["20"])[0])
                with service._lock:
                    held = list(service.jobs)
                page = held[:limit]
                self._answer(
                    {
                        "ok": True,
                        "jobs": page,
                        "total": len(held),
                        "returned": len(page),
                        # Tallied over everything held, exactly as the service
                        # does - the page is not the population.
                        "summary": _summarise(held),
                    }
                )

            def _mutate(self, method: str) -> None:
                path, _query = self._record(method)
                state = _requested_state(self)
                time.sleep(service.control_delay)
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

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=_HANDOFF_TIMEOUT)

    def control_paths(self) -> list[str]:
        with self._lock:
            return [path for method, path in self.requests if method != "GET"]


def _requested_state(handler: http.server.BaseHTTPRequestHandler) -> object:
    """Read the desired state out of a control request's body."""
    length = int(handler.headers.get("Content-Length") or 0)
    if length <= 0:
        return None
    payload = json.loads(handler.rfile.read(length).decode("utf-8"))
    return payload.get("state") if isinstance(payload, dict) else None


def _app(
    service: _JobService,
    jobs: list[dict[str, object]] | None = None,
    *,
    limit: int = 20,
    interval: float = 3600.0,
) -> JobsTuiApp:
    """Build the interface over *service*, reached through the real transport."""
    if jobs is not None:
        service.set_jobs(jobs)

    def fetch() -> dict[str, object] | None:
        return _try_http_admin("get_jobs", {"limit": limit}, service.port)

    # A long interval keeps the periodic refresh out of the way; every test
    # drives the first load explicitly.
    return JobsTuiApp(fetch=fetch, port=service.port, interval=interval)


def _screen_text(app: JobsTuiApp) -> str:
    """Return what the interface actually painted, as text."""
    return "\n".join(strip.text for strip in app.screen._compositor.render_strips())


def _line_with(painted: str, needle: str) -> str:
    """Return the first painted line carrying *needle*, or an empty string."""
    for line in painted.splitlines():
        if needle in line:
            return line
    return ""


def _header_line(app: JobsTuiApp) -> str:
    """Return the painted jobs header line.

    Found by its content rather than by its position: this screen carries
    other bars, and which one lands on the first row is not this file's
    business. An index would silently start asserting about a neighbour.
    """
    for line in _screen_text(app).splitlines():
        if "Jobs on port" in line:
            return line
    return ""


def _row_line(app: JobsTuiApp, *needles: str) -> str | None:
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


@pytest.fixture
def control_service() -> typing.Iterator[_JobService]:
    server = _JobService()
    try:
        yield server
    finally:
        server.close()


class TestRenderedRows:
    """What the operator can read off the screen."""

    @pytest.mark.asyncio
    async def test_the_row_shows_the_full_project_path(
        self, control_service: _JobService
    ) -> None:
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        # The basename alone cannot distinguish two worktrees of one repo,
        # and the discriminating part of a root is its tail - so the tail is
        # what must survive when the column cannot show the whole path.
        assert "worktrees/main" in painted

    @pytest.mark.asyncio
    async def test_the_row_shows_elapsed_and_remaining_time(
        self, control_service: _JobService
    ) -> None:
        """The rightmost columns must land inside the table, not past it.

        Column shares are divided from the table's own width, and that width
        settles a layout pass after whatever changed it - the log pane opening
        beside the table, most of all. Dividing on the change rather than on
        the resulting width lays these columns out for a full-width table and
        paints them into a narrower one, so both fall off the right edge.

        Proven able to fail: removing the ``_relayout`` call from
        ``watch_frame_index`` - leaving the division to happen once, on a guess
        about when layout has settled, which is the state before this fix -
        never lets the shares match the table's width, so the run fails in
        ``_ready`` on "the interface never completed its first paint";
        restored, both values are on the row.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "1m15s" in painted, "elapsed runtime must be on the row"
        assert "2m20s left" in painted, "the estimate must be on the row"

    @pytest.mark.asyncio
    async def test_an_absent_estimate_is_not_rendered_as_zero(
        self, control_service: _JobService
    ) -> None:
        app = _app(control_service, [_job("abc123def456", remaining=None, rate=None)])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "left" not in painted, "no estimate must not render as a duration"
        assert "0s" not in painted, "unknown must never be painted as zero"

    @pytest.mark.asyncio
    async def test_the_progress_bar_fits_the_column_it_lands_in(
        self, control_service: _JobService
    ) -> None:
        """The bar is sized from the terminal, not from a constant."""
        narrow = _app(control_service, [_job("abc123def456")])
        async with narrow.run_test(size=(120, 24), notifications=True) as pilot:
            await _ready(pilot, narrow)
            narrow_cells = narrow._bar_cells

        wide = _app(control_service, [_job("abc123def456")])
        async with wide.run_test(size=(260, 24), notifications=True) as pilot:
            await _ready(pilot, wide)
            wide_cells = wide._bar_cells

        assert wide_cells > narrow_cells, (
            "a wider terminal must give the bar more room, not the same room"
        )


class TestResponsiveLayout:
    """One composition, reflowed from the width the terminal reports."""

    @pytest.mark.asyncio
    async def test_a_wide_terminal_shows_the_log_beside_the_table(
        self, control_service: _JobService
    ) -> None:
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = await _await_painted(pilot, app, "a logged line")
            classes = app.screen.classes

        assert "-wide" in classes
        assert "code index" in painted, "a wide terminal shows both panes at once"

    @pytest.mark.asyncio
    async def test_the_log_key_does_something_at_a_wide_size(
        self, control_service: _JobService
    ) -> None:
        """Wide starts with the log open, so the key must close it - and reopen.

        A toggle whose two presses paint the same screen is the defect: it
        reads to an operator as a dead key.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _await_painted(pilot, app, "a logged line")

            await pilot.press("l")
            await _settled_paint(pilot, app)
            closed = _screen_text(app)

            await pilot.press("l")
            await _settled_paint(pilot, app)
            reopened = await _await_painted(pilot, app, "a logged line")

        assert "a logged line" not in closed, "the key must close an open log"
        assert "a logged line" in reopened, "the key must reopen a closed log"
        # The table keeps the whole width once the log gives it back, so the
        # closed frame is not merely the open one with the log blanked out.
        assert closed != reopened

    @pytest.mark.asyncio
    async def test_the_log_key_does_something_at_a_narrow_size(
        self, control_service: _JobService
    ) -> None:
        """Narrow starts with the log closed, so the key must open it - and close."""
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_NARROW, notifications=True) as pilot:
            await _ready(pilot, app)
            assert "-narrow" in app.screen.classes
            assert "a logged line" not in _screen_text(app)

            await pilot.press("l")
            await _settled_paint(pilot, app)
            opened = await _await_painted(pilot, app, "a logged line")

            await pilot.press("l")
            await _settled_paint(pilot, app)
            closed = _screen_text(app)

        assert "a logged line" in opened, "toggling must reveal the log"
        assert "code index" not in opened, (
            "a narrow terminal shows one pane at a time, not two squeezed"
        )
        assert "a logged line" not in closed, "toggling again must give the table back"
        assert "code index" in closed


class TestCapabilityGating:
    """An action the service would refuse is not offered and not sent."""

    @pytest.mark.asyncio
    async def test_a_permitted_action_reaches_the_service(
        self, control_service: _JobService
    ) -> None:
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            await _settle(pilot)

        assert any(
            path.endswith("/desired-state") for path in control_service.control_paths()
        ), "pause is published as permitted, so it must be sent"

    @pytest.mark.asyncio
    async def test_an_unpermitted_action_is_never_sent(
        self, control_service: _JobService
    ) -> None:
        """A denied capability must issue no request, by either route.

        There are two gates and the test drives both, because either one alone
        passing would hide the other's removal. Pressing the key exercises the
        binding gate, which refuses before the action method is ever entered.
        Calling the action method directly exercises the check inside it, which
        is what still has to hold when a binding fires anyway.

        Proven able to fail: deleting the capability check in ``_actionable``
        leaves the key press still blocked but makes the direct call reach the
        service, failing on the empty-requests assertion; restored, it passes.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # ``deletable`` is False on this job.
            await pilot.press("d")
            await pilot.pause()
            app.action_job_delete()
            await pilot.pause()
            await _settle(pilot)

        assert control_service.control_paths() == [], (
            "a capability the service denies must not produce a request"
        )

    @pytest.mark.asyncio
    async def test_the_footer_disables_rather_than_hides_a_denied_action(
        self, control_service: _JobService
    ) -> None:
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # ``None`` greys the key; ``False`` would remove it entirely, and
            # an operator cannot learn a control exists from its absence.
            assert app.check_action("job_delete", ()) is None
            assert app.check_action("job_pause", ()) is True
            painted = _screen_text(app)

        assert "Delete" in painted, "a denied action stays visible, greyed"

    @pytest.mark.asyncio
    async def test_an_unavailable_action_says_why_when_its_key_is_pressed(
        self, control_service: _JobService
    ) -> None:
        """A greyed key that answers nothing reads as a broken interface.

        A disabled binding never invokes its action, so the footer's grey is
        the only signal there was - and an operator whose whole list is
        terminal presses these keys constantly and gets silence every time.

        Proven able to fail: removing the ``on_key`` handler leaves the key
        press with no painted answer and fails on the reason assertion by name;
        restored, it passes.
        """
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # A finished job publishes neither ``pausable`` nor ``cancellable``.
            await pilot.press("p")
            painted = await _await_painted(pilot, app, "Only running work")

            await pilot.press("y")
            await _settle(pilot)

        assert "Only running work can be paused." in painted, (
            "an unavailable action must say why, not do nothing"
        )
        # The reason is not a blanket refusal: the permitted action on the same
        # job still reaches the service.
        assert any(
            path.endswith("/retry") for path in control_service.control_paths()
        ), "greying one action must not disable the ones the job does permit"

    @pytest.mark.asyncio
    async def test_an_unavailable_action_says_why_when_called_directly(
        self, control_service: _JobService
    ) -> None:
        """The refusal holds on the route that bypasses the binding entirely."""
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            app.action_job_stop()
            painted = await _await_painted(pilot, app, "Only running work")

        assert "Only running work can be cancelled." in painted


class TestPendingControl:
    """A requested state is never shown as an observed one."""

    @pytest.mark.asyncio
    async def test_a_requested_control_renders_as_requested(
        self, control_service: _JobService
    ) -> None:
        # The service holds the request rather than answering it, so the test
        # observes the window between asking and acknowledgement.
        control_service.control_delay = 0.5
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            painted = await _await_painted(pilot, app, "pause requested")
            await _settle(pilot)

        assert "pause requested" in painted, (
            "the view must say the control was requested, not that it took effect"
        )

    @pytest.mark.asyncio
    async def test_the_view_converges_on_the_state_the_service_took(
        self, control_service: _JobService
    ) -> None:
        """The requested marker gives way to the service's own answer.

        A marker that never clears is as wrong as one that clears too early:
        it leaves the row permanently claiming a request is outstanding on work
        the service has already accepted.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            painted = await _await_painted(pilot, app, "→ paused")

        assert "→ paused" in painted, (
            "once the service carries the desired state the row must show it"
        )
        assert "pause requested" not in painted, (
            "an acknowledged request must stop being described as pending"
        )
        assert control_service.jobs[0]["desired_state"] == "paused", (
            "the service must actually be holding what the row now claims"
        )


class TestActionOutcomes:
    """Every action outcome is visible, including the ones that worked."""

    @pytest.mark.asyncio
    async def test_a_deletion_converges_the_view_on_the_service(
        self, control_service: _JobService
    ) -> None:
        """The row goes, the freed slot backfills, and the total drops.

        The list the interface shows is one page of a much longer one, so the
        deleted row's slot is immediately refilled from the remainder and the
        table looks untouched. Asserting only that the row went would pass
        against a view that never refreshed at all; the count behind the page
        is what actually moved.
        """
        jobs = [_finished_job(f"job{index:05d}") for index in range(12)]
        app = _app(control_service, jobs, limit=5)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            before = _screen_text(app)
            assert "showing 5 of 12" in before
            # The row's own subtitle, not the bare id: the id also appears in
            # the outcome the action reports, and matching that instead would
            # read a toast as a table row.
            assert "job00000 · tool" in before
            assert "job00005 · tool" not in before, "the sixth job is behind the page"

            await pilot.press("d")
            painted = await _await_painted(pilot, app, "showing 5 of 11")

        assert "job00000" not in control_service.job_ids(), (
            "the service must actually have dropped the job"
        )
        assert "✗ deleted" in painted, (
            "the row the operator acted on must be seen leaving"
        )
        assert "job00005 · tool" in painted, (
            "the freed slot must backfill from behind the page"
        )
        assert "showing 5 of 11" in painted, (
            "the count behind the page is the only place a backfilled "
            "deletion is observable"
        )

    @pytest.mark.asyncio
    async def test_a_deleted_row_is_struck_out_and_then_leaves(
        self, control_service: _JobService
    ) -> None:
        """The operator sees which row went, then it goes.

        A list that silently backfills the freed slot shows nothing having
        happened. Holding the row briefly, struck through, is the only frame
        in which the deletion is legible - but it must not become a permanent
        ghost, so the row has to leave afterwards.

        Proven able to fail: removing the ``_entomb`` call from
        ``_reconcile_pending`` never paints the struck row and fails in
        ``_await_painted`` on the struck-row needle; restored, it passes and
        the row still leaves.
        """
        jobs = [_finished_job(f"job{index:05d}") for index in range(3)]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("d")
            entombed = await _await_painted(pilot, app, "✗ deleted")
            gone = await _await_gone(pilot, app, "✗ deleted")

        assert "job00000 · tool" in entombed, (
            "the deleted row stays legible while it is struck out"
        )
        assert "job00000 · tool" not in gone, (
            "the row must not become a permanent ghost"
        )
        assert "job00001 · tool" in gone, "the rest of the list is untouched"

    @pytest.mark.asyncio
    async def test_a_successful_action_is_reported(
        self, control_service: _JobService
    ) -> None:
        """Silence on success is indistinguishable from an action that vanished.

        Proven able to fail: removing the success branch of ``_after_control``
        leaves nothing painted and fails in ``_await_painted`` on the
        "delete accepted" needle; restored, it passes.
        """
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("d")
            painted = await _await_painted(pilot, app, "delete accepted")

        assert "delete accepted for job00000; awaiting the service." in painted

    @pytest.mark.asyncio
    async def test_the_poll_does_not_cancel_the_control_it_overtakes(
        self, control_service: _JobService
    ) -> None:
        """The poll and the controls must not share a worker group.

        The poll is exclusive by necessity - two answers racing to repaint one
        table is worse than a dropped poll - and an exclusive worker cancels
        every worker sharing its group. With the controls in that same group,
        a poll starting before the control's worker has run its body cancels
        the control outright: no request is ever sent, nothing repaints, and
        no outcome is reported. The key did nothing at all, intermittently,
        depending on where the poll timer happened to land.

        The two callables are driven in one turn rather than through the key,
        because the collision has to be certain: leaving it to the timer's
        arrival gives a test that reproduces the defect some of the time and
        passes over it the rest. They are exactly what the ``d`` binding and
        the poll timer invoke.

        Proven able to fail: putting all five workers back in the default
        group - the state before this fix - sends no request at all and fails
        on the control-paths assertion below by name; restored, it passes.
        """
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            app.action_job_delete()
            app.refresh_jobs()
            await _settle(pilot)
            painted = _screen_text(app)

        assert control_service.control_paths() == ["/jobs/job00000"], (
            "the control must reach the service, not be cancelled before it is sent"
        )
        assert "job00000" not in control_service.job_ids()
        assert "delete accepted for job00000; awaiting the service." in painted

    @pytest.mark.asyncio
    async def test_a_control_aimed_at_a_vanished_job_reports_the_refusal(
        self, control_service: _JobService
    ) -> None:
        """A control naming a dropped id resolves to a sentence and a new list.

        Something else can remove a job between the poll that painted it and
        the key that acts on it: a second operator, or the daemon's own
        retention sweep. The service answers with ``job_not_found``, and that
        is not a generic failure - it says the view is addressing something
        that no longer exists. It must read as that, and the list must be
        corrected, never surfaced as a raw error.
        """
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # Removed behind the interface's back.
            control_service.set_jobs([])
            app.action_job_delete()
            painted = await _await_painted(pilot, app, "no longer on the service")
            await _settle(pilot)
            corrected = _screen_text(app)

        assert "delete: job00000 is no longer on the service - list refreshed." in (
            painted
        ), "a dropped id must be said plainly, not raised as an error"
        assert "job_not_found" not in painted, (
            "the service's code is not operator prose"
        )
        assert "job00000 · tool" not in corrected, (
            "the corrected list must no longer offer the row that was dropped"
        )


class TestMotionMeansSomething:
    """If it moves, something is happening, and the operator can say what."""

    @pytest.mark.asyncio
    async def test_the_header_is_still_when_nothing_is_in_flight(
        self, control_service: _JobService
    ) -> None:
        """A glyph that never stops turning reports nothing at all.

        It says "working" over a view that has been idle for a minute, which
        is worse than saying nothing: an operator reads it as the interface
        being busy and waits.

        Proven able to fail: advancing the frame unconditionally and painting a
        braille glyph regardless of ``_busy`` - the behaviour before this fix -
        leaves a moving header over a settled view and fails on the
        still-glyph assertion by name; restored, it passes.
        """
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            # Several frame intervals, so a glyph that still turns is caught.
            frames = []
            for _ in range(6):
                await asyncio.sleep(_SPINNER_INTERVAL)
                await pilot.pause()
                frames.append(_header_line(app))

        assert all("· Jobs on port" in frame for frame in frames), (
            "a settled view must show a still glyph, not an animation"
        )
        assert not any(char in frame for frame in frames for char in _SPINNER_FRAMES), (
            "nothing may animate while nothing is happening"
        )

    @pytest.mark.asyncio
    async def test_the_header_turns_while_a_request_is_out(
        self, control_service: _JobService
    ) -> None:
        """And it must still move when something genuinely is happening."""
        control_service.control_delay = 0.6
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            await pilot.press("d")
            painted = await _await_painted_when(
                pilot,
                app,
                lambda text: any(
                    char in _line_with(text, "Jobs on port") for char in _SPINNER_FRAMES
                ),
                "an animated header glyph",
            )
            await _settle(pilot)

        assert "Jobs on port" in _line_with(painted, "Jobs on port")

    @pytest.mark.asyncio
    async def test_a_row_whose_progress_has_stalled_does_not_animate(
        self, control_service: _JobService
    ) -> None:
        """``running`` is not the same claim as moving.

        A record can read ``running`` while its progress stopped updating
        minutes ago. Turning a glyph on that row asserts motion the view has
        no evidence for.
        """
        stalled = _job("abc123def456")
        stalled["stalled"] = True
        stalled["last_progress_age_seconds"] = 900.0
        app = _app(control_service, [stalled])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            rows = []
            for _ in range(6):
                await asyncio.sleep(_SPINNER_INTERVAL)
                await pilot.pause()
                rows.append(
                    "\n".join(
                        line
                        for line in _screen_text(app).splitlines()
                        if "abc123de" in line or "active" in line
                    )
                )

        assert not any(char in row for row in rows for char in _SPINNER_FRAMES), (
            "a row whose progress is stale must not claim to be moving"
        )


class TestDurableRequestState:
    """The row carries a control from the keystroke to the service's answer."""

    @pytest.mark.asyncio
    async def test_a_pause_shows_requested_then_sent_then_the_new_state(
        self, control_service: _JobService
    ) -> None:
        """Every stage is on the row, and the intermediate ones are the point.

        The operator's complaint is about the middle of this sequence, not its
        ends: they press a key, a toast flashes for under a second, and the row
        reads exactly as it did before. Asserting only the final state would
        pass against a view that showed nothing until it was over.
        """
        control_service.control_delay = 0.4
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            # The service now answers reads slowly, so the window in which the
            # request is accepted but unconfirmed is observable rather than
            # theoretical.
            control_service.fetch_delay = 0.5

            await pilot.press("p")
            requested = await _await_painted(pilot, app, "pause requested")
            sent = await _await_painted(pilot, app, "pause sent")
            confirmed = await _await_painted(pilot, app, "→ paused")

        assert "pause requested" in requested, (
            "the row must change on the keystroke, before anything is answered"
        )
        assert " pause sent" in sent, (
            "accepted is not done; the row must say it is still waiting"
        )
        assert "pause requested" not in confirmed
        assert "pause sent" not in confirmed
        assert control_service.jobs[0]["desired_state"] == "paused", (
            "the service must actually hold what the row now claims"
        )

    @pytest.mark.asyncio
    async def test_a_settled_row_shows_the_request_without_waiting_for_an_answer(
        self, control_service: _JobService
    ) -> None:
        """The keystroke repaints the row; nothing else is going to.

        A running row is repainted by the frame tick anyway, so it would hide
        this. Most of an operator's list is finished work, which nothing
        animates and nothing else redraws - so if the keystroke does not paint
        the request there, the row sits unchanged until the service answers,
        and on a slow control that is seconds of an interface that looks dead.

        Proven able to fail: removing the repaint from ``_mark_pending`` leaves
        the row on its old state until the answer arrives, and fails in
        ``_await_painted`` on the "delete requested" needle; restored, it
        passes.
        """
        control_service.control_delay = 0.6
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            await pilot.press("d")
            await _await_painted(pilot, app, "delete requested")
            row = _row_line(app, "delete requested", "job00000 · tool")

        assert row is not None, (
            "the row must carry the request before the service has answered"
        )

    @pytest.mark.asyncio
    async def test_a_refusal_stays_on_the_row_and_in_the_header(
        self, control_service: _JobService
    ) -> None:
        """A refusal an operator has to catch inside a toast is one they miss.

        Proven able to fail: clearing the marker in ``_after_control`` instead
        of settling it - the behaviour before this fix - leaves the row
        unchanged and fails on the row-refusal assertion by name; restored, it
        passes and the refusal is still there many frames later.
        """
        control_service.refusal = ("job_not_terminal", "The job is still running.")
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("d")
            await _await_painted(pilot, app, "delete refused")
            await _settle(pilot)
            # Well past the point a toast would have expired on its own.
            for _ in range(10):
                await asyncio.sleep(_SPINNER_INTERVAL)
                await pilot.pause()
            painted = _screen_text(app)
            # Pinned to the row: the toast and the header carry the same words,
            # and outliving those two is the whole point.
            row = _row_line(app, "delete refused", "job00000 · tool")

        assert row is not None, "the row itself must keep saying it was refused"
        assert "delete refused: The job is still running." in painted, (
            "the reason must stay readable in the header, not only in a toast"
        )
        assert "job00000" in control_service.job_ids(), (
            "a refused delete must leave the service's state alone"
        )

    @pytest.mark.asyncio
    async def test_a_poll_that_predates_the_control_cannot_settle_it(
        self, control_service: _JobService
    ) -> None:
        """A marker is settled by evidence, not by the next thing to arrive.

        Several polls are outstanding at once, and cancelling a thread worker
        does not stop the thread - so the answer that lands first is routinely
        one issued before the mutation. Letting it clear the marker makes a
        requested control flash and vanish with nothing having changed, which
        is exactly what "no coupling between state, frontend and backend"
        looks like from the operator's chair.

        Retry is the case that isolates it. A pause is confirmed by a field, so
        a stale payload fails that check anyway; retry sets no desired state at
        all, so the only thing standing between its marker and a payload that
        predates it is the generation stamp.

        Proven able to fail: removing the generation comparison from
        ``_reconcile_pending`` settles the marker against the pre-control
        payload and fails on the marker-survives assertion by name; restored,
        it passes.
        """
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            # Exactly what a poll already in flight when the operator presses
            # the key will eventually deliver.
            stale = _try_http_admin("get_jobs", {"limit": 20}, control_service.port)

            # Every later read is slow, so the poll issued next is still out
            # when the control lands - which is the ordinary case at a
            # two-second interval against a thirty-second timeout.
            control_service.fetch_delay = 1.2
            stale_generation = app._generation + 1
            app.refresh_jobs()

            await pilot.press("y")
            await _await_painted(pilot, app, "retry sent")

            # The poll finally answers, under its own stamp.
            app._apply_result(stale, stale_generation)
            await pilot.pause()
            painted = _screen_text(app)

        assert " retry sent" in painted, (
            "a payload fetched before the control cannot settle it"
        )


class TestServiceHealthIsVisible:
    """A view that cannot hear the service must not sound confident."""

    @pytest.mark.asyncio
    async def test_an_erroring_service_does_not_render_as_an_empty_list(
        self, control_service: _JobService
    ) -> None:
        """The most misleading frame this interface can paint.

        The transport does not raise on a service that answers badly: a
        timeout comes back as an ``ok: false`` envelope, and a non-200 body is
        returned as it stands. Neither carries a ``jobs`` key, so reading the
        payload without checking paints a wedged daemon as "no jobs, refreshed
        just now" - current-looking, confident and false. With a thirty-second
        administrative timeout that is the *normal* rendering of a hung
        service.

        Proven able to fail: dropping the error check in ``_apply_result``
        empties the table and repaints the timestamp, failing on the
        rows-survive assertion by name; restored, it passes.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            healthy = _screen_text(app)
            assert "refreshed" in healthy

            app._apply_result(
                {
                    "ok": False,
                    "error": "admin_timeout",
                    "message": "The service did not answer within 30s.",
                },
                app._generation + 1,
            )
            await pilot.pause()
            painted = _screen_text(app)

        assert "abc123de · tool" in painted, (
            "the last thing the service said stays on screen; it is all there is"
        )
        assert "The service did not answer within 30s." in painted, (
            "the view must say it is not hearing back"
        )
        assert "refreshed" in painted, (
            "the age of the data is exactly what an operator needs when the "
            "service stops answering, so it must survive the error"
        )

    @pytest.mark.asyncio
    async def test_a_payload_without_a_job_list_is_an_error_not_an_empty_list(
        self, control_service: _JobService
    ) -> None:
        """A non-200 body is returned as it stands, and carries no jobs."""
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            app._apply_result({"detail": "Not authenticated"}, app._generation + 1)
            await pilot.pause()
            painted = _screen_text(app)

        assert "did not return a job list" in painted
        assert "abc123de · tool" in painted, "the last known rows stay"

    @pytest.mark.asyncio
    async def test_a_superseded_payload_cannot_revert_the_view(
        self, control_service: _JobService
    ) -> None:
        """Answers are applied newest-first, not in completion order.

        Cancelling a thread worker does not stop the OS thread it runs on, so
        a superseded poll still delivers. With a two-second interval against a
        thirty-second timeout several can be outstanding, and applying them as
        they complete lets a pre-mutation payload land after a post-mutation
        one and silently put the old list back.

        Proven able to fail: removing the generation comparison in
        ``_apply_result`` applies the stale payload and fails on the
        corrected-list assertion by name; restored, it passes.
        """
        jobs = [_finished_job(f"job{index:05d}") for index in range(3)]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # The stamp of the fetch this payload belongs to, captured now
            # rather than derived later: how many generations the refresh below
            # consumes is not this test's business, and counting backwards from
            # the end makes the assertion depend on it.
            stale_generation = app._generation
            stale = _try_http_admin("get_jobs", {"limit": 20}, control_service.port)

            control_service.set_jobs(jobs[1:])
            app.refresh_jobs()
            await _await_painted(pilot, app, "showing 2 of 2")

            # The older fetch finally completes, under its own stamp.
            app._apply_result(stale, stale_generation)
            await pilot.pause()
            painted = _screen_text(app)

        assert "showing 2 of 2" in painted, (
            "a payload older than what is on screen must not be applied"
        )
        assert "job00000 · tool" not in painted


class TestStaleSelection:
    """Selection and pending state reconcile against every refresh."""

    @pytest.mark.asyncio
    async def test_the_selection_follows_the_job_not_the_row_number(
        self, control_service: _JobService
    ) -> None:
        """A job disappearing above the cursor must not move the selection.

        The cursor is what every control key acts on. Restoring it by row index
        after a refresh silently retargets it at whatever slid into that slot,
        so the next press lands on work the operator never chose.

        Proven able to fail: restoring the cursor by index in ``_rebuild_rows``
        moves the selection to ``job00003`` and fails the log-title assertion
        by name; restoring by id keeps it on ``job00002``.
        """
        jobs = [_finished_job(f"job{index:05d}") for index in range(6)]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("down", "down")
            await _await_painted(pilot, app, "Log · job00002")

            # The two jobs above the selection go, out of band.
            control_service.set_jobs(jobs[2:])
            app.refresh_jobs()
            painted = await _await_painted(pilot, app, "showing 4 of 4")

        assert "Log · job00002" in painted, (
            "the selection must stay on the job it was on, not on its old row"
        )
        assert app.selected_id == "job00002"

    @pytest.mark.asyncio
    async def test_a_vanished_selection_moves_to_a_job_that_exists(
        self, control_service: _JobService
    ) -> None:
        """A selection outliving its job would aim every control at a 404."""
        jobs = [_finished_job(f"job{index:05d}") for index in range(4)]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("down")
            await _await_painted(pilot, app, "Log · job00001")

            control_service.set_jobs([jobs[0], jobs[2], jobs[3]])
            app.refresh_jobs()
            await _await_painted(pilot, app, "showing 3 of 3")
            selected = app.selected_id

            # The control that follows must reach a job the service holds.
            app.action_job_delete()
            await _settle(pilot)

        assert selected in {"job00000", "job00002", "job00003"}, (
            "the selection must land on a job the service still holds"
        )
        assert all(
            "job00001" not in path for path in control_service.control_paths()
        ), "no control may be aimed at the id that disappeared"

    @pytest.mark.asyncio
    async def test_a_pending_marker_does_not_outlive_its_job(
        self, control_service: _JobService
    ) -> None:
        """A marker left on a dead id would describe a request forever."""
        control_service.control_delay = 0.4
        jobs = [_job("abc123def456"), _job("def456abc123")]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            await _await_painted(pilot, app, "pause requested")

            control_service.set_jobs([jobs[1]])
            app.refresh_jobs()
            painted = await _await_painted(pilot, app, "showing 1 of 1")
            await _settle(pilot)

        assert "pause requested" not in painted, (
            "a pending marker must not survive the job it describes"
        )
        assert app._pending == {}


class TestHeaderCounts:
    """The header says how much of the service's work is on screen."""

    @pytest.mark.asyncio
    async def test_the_header_shows_the_total_behind_the_page(
        self, control_service: _JobService
    ) -> None:
        jobs = [_finished_job(f"job{index:05d}") for index in range(12)]
        app = _app(control_service, jobs, limit=5)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "showing 5 of 12" in painted, (
            "a page onto a longer list must say so, or every count above it "
            "reads as the whole of the service's work"
        )

    @pytest.mark.asyncio
    async def test_the_counters_describe_the_service_not_the_page(
        self, control_service: _JobService
    ) -> None:
        """Counts tallied from the page move only when the page moves.

        The service tallies every record matching the filter. Re-tallying the
        twenty on screen gives numbers that describe neither the list nor the
        service: deleting one of a hundred and seventy-nine finished jobs
        changes nothing an operator can see, because the page refills and its
        own tally is unchanged.

        Proven able to fail: tallying ``self._jobs`` instead of the published
        summary reports the five rows on the page and fails on the
        succeeded-count assertion by name; restored, it passes.
        """
        jobs = [_finished_job(f"job{index:05d}") for index in range(12)]
        jobs.append(_job("running00"))
        app = _app(control_service, jobs, limit=5)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "succeeded 12" in painted, (
            "the counters must describe every record the service holds, not "
            "the five that happen to be on the page"
        )
        assert "running 1" in painted
        assert "showing 5 of 13" in painted

    @pytest.mark.asyncio
    async def test_a_state_with_no_counter_of_its_own_is_still_counted(
        self, control_service: _JobService
    ) -> None:
        """Numbers that silently drop a state sum to nothing in particular.

        A restored record reads ``interrupted`` and a cancelled one
        ``cancelled``; neither has a counter of its own. Omitting them leaves
        an operator unable to tell a missing state from a zero one.
        """
        jobs = [
            _job("aaaaaaaa0000", phase="interrupted", state="interrupted"),
            _job("bbbbbbbb0000", phase="cancelled", state="cancelled"),
            _finished_job("cccccccc0000"),
        ]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "succeeded 1" in painted
        assert "other 2" in painted, (
            "states without a counter of their own must still be accounted for"
        )

    @pytest.mark.asyncio
    async def test_a_service_publishing_no_total_claims_none(
        self, control_service: _JobService
    ) -> None:
        """Absent is not zero, and must not be painted as a total of zero."""

        def fetch() -> dict[str, object] | None:
            return {"ok": True, "jobs": [_job("abc123def456")]}

        app = JobsTuiApp(fetch=fetch, port=control_service.port, interval=3600.0)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "showing 1" in painted
        assert "of 0" not in painted, "an unpublished total must not read as zero"


class TestLogPane:
    """The log region is scoped to the selected job."""

    @pytest.mark.asyncio
    async def test_the_selected_job_scopes_the_log_request(
        self, control_service: _JobService
    ) -> None:
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            painted = _screen_text(app)

        log_requests = [
            path
            for method, path in control_service.requests
            if method == "GET" and path.startswith("/logs")
        ]
        assert log_requests, "selecting a row must fetch that job's log"
        assert any("abc123def456" in path for path in log_requests), (
            "the log request must carry the selected job id"
        )
        assert "a logged line" in painted, "log lines must reach the screen"

    @pytest.mark.asyncio
    async def test_the_log_follows_the_selection(
        self, control_service: _JobService
    ) -> None:
        """Moving the cursor must move the lines, not only the pane's title.

        The title is set the moment the selection changes; the lines arrive
        from the service. A pane whose title says one job over another job's
        lines is worse than one that says nothing.
        """
        jobs = [_job("abc123def456"), _job("def456abc123")]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _await_painted(pilot, app, "a logged line for abc123def456")
            await pilot.press("down")
            await _await_painted(pilot, app, "a logged line for def456abc123")
            # The frame is read once both fetches have finished, so the
            # assertion below is about where the pane settled rather than
            # about whichever frame happened to be caught mid-swap.
            await _settle(pilot)
            painted = _screen_text(app)

        assert "a logged line for def456abc123" in painted
        assert "Log · def456ab" in painted
        assert "a logged line for abc123def456" not in painted, (
            "the previous job's lines must not survive the selection moving"
        )

    @pytest.mark.asyncio
    async def test_the_poll_does_not_cancel_the_log_it_overtakes(
        self, control_service: _JobService
    ) -> None:
        """The poll and the log fetch must not share a worker group either.

        Same mechanism as the controls: an exclusive poll starting in the turn
        the log fetch was requested cancels it before it runs, and the pane
        keeps the lines it last managed to paint under a title naming a
        different job.

        Proven able to fail: returning ``fetch_logs`` to the default group
        leaves the second job's lines never requested and fails on the
        log-request assertion below by name; restored, it passes.
        """
        jobs = [_job("abc123def456"), _job("def456abc123")]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _await_painted(pilot, app, "a logged line for abc123def456")
            # What pressing "down" does, in one turn: the cursor moves, the
            # selection follows it, and the poll starts alongside the log
            # fetch that follow raised. Through the pilot the fetch would have
            # started a turn earlier and the collision would be a coin toss.
            app.query_one("#jobs", DataTable).move_cursor(row=1)
            app.selected_id = "def456abc123"
            app.refresh_jobs()
            await _settle(pilot)
            painted = _screen_text(app)

        assert any(
            "job_id=def456abc123" in path
            for method, path in control_service.requests
            if method == "GET" and path.startswith("/logs")
        ), "the log request must survive a poll starting alongside it"
        assert "a logged line for def456abc123" in painted


async def _ready(pilot: typing.Any, app: JobsTuiApp) -> None:
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
    """
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    matched_at: float | None = None
    matched_width: int | None = None
    while time.monotonic() < deadline:
        await pilot.pause()
        table = app.query("#jobs")
        if not (
            app._jobs
            and table
            and table.only_one(DataTable).row_count == len(app._jobs)
            and app._bar_cells > 0
            and app._divided_width == table.only_one(DataTable).size.width
            # A row must be selected too. Every control acts on the selection,
            # so a test that starts pressing keys before one exists is testing
            # a frame no operator ever sees.
            and app.selected_id
        ):
            matched_at = None
            await asyncio.sleep(_POLL_INTERVAL)
            continue
        width = table.only_one(DataTable).size.width
        now = time.monotonic()
        if matched_at is None or matched_width != width:
            matched_at, matched_width = now, width
        elif now - matched_at >= _SPINNER_INTERVAL * 1.5:
            return
        await asyncio.sleep(_POLL_INTERVAL)
    raise AssertionError("the interface never completed its first paint")


async def _settle(pilot: typing.Any) -> None:
    """Wait for the interface's worker threads to finish their requests."""
    deadline = time.monotonic() + _HANDOFF_TIMEOUT
    while time.monotonic() < deadline:
        await pilot.pause()
        if not any(worker.is_running for worker in pilot.app.workers):
            return
        await asyncio.sleep(_POLL_INTERVAL)
    raise AssertionError("the interface's workers did not settle")


async def _settled_paint(pilot: typing.Any, app: JobsTuiApp) -> None:
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
        if app._divided_width != width:
            matched_at = None
        elif matched_at is None or matched_width != width:
            matched_at, matched_width = now, width
        elif now - matched_at >= _SPINNER_INTERVAL * 1.5:
            return
        await asyncio.sleep(_POLL_INTERVAL)


async def _await_painted(pilot: typing.Any, app: JobsTuiApp, needle: str) -> str:
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
    app: JobsTuiApp,
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


async def _await_gone(pilot: typing.Any, app: JobsTuiApp, needle: str) -> str:
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


class TestOlderServiceCompatibility:
    """The view is read by operators whose daemon predates it.

    A service is upgraded by restarting it, and nothing forces that to happen
    before the CLI is upgraded. The payload from an older daemon is therefore
    the normal case for a while, not an edge case.
    """

    @pytest.mark.asyncio
    async def test_a_service_without_estimates_says_so_once(
        self, control_service: _JobService
    ) -> None:
        """Absent is a different answer from null, and reads differently.

        A daemon that never publishes the field would otherwise render every
        row's estimate as unknown, which an operator reads as "none of my work
        is measurable" rather than "this service does not measure".
        """
        job = _job("abc123def456")
        del job["estimated_remaining_seconds"]
        del job["progress_rate_per_second"]

        app = _app(control_service, [job])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "does not report time estimates" in painted

    @pytest.mark.asyncio
    async def test_a_service_that_declines_one_estimate_says_nothing(
        self, control_service: _JobService
    ) -> None:
        """Present-and-null is the service declining, and is not a version gap."""
        app = _app(control_service, [_job("abc123def456", remaining=None, rate=None)])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "does not report time estimates" not in painted

    @pytest.mark.asyncio
    async def test_a_restored_job_advertises_no_transition(
        self, control_service: _JobService
    ) -> None:
        """A terminal job carrying a stale desired state is going nowhere.

        A daemon restores jobs its previous life left running as ``interrupted``
        while they still carry ``desired_state: running``. Painting an arrow
        there promises a transition on work that is already over.

        Proven able to fail: dropping the terminal-state test in ``_state_cell``
        renders the arrow and fails the assertion below by name; restored, it
        passes.
        """
        app = _app(
            control_service,
            # The exact shape a daemon restores a job into: dead, but still
            # carrying the desired state it held when the daemon died.
            [
                _job(
                    "abc123def456",
                    phase="interrupted",
                    state="interrupted",
                    desired="running",
                )
            ],
        )
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "interrupted" in painted, "the terminal state itself must show"
        assert "→ running" not in painted, (
            "a terminal job must not advertise a transition it will never make"
        )

    @pytest.mark.asyncio
    async def test_a_record_publishing_no_capabilities_still_offers_its_controls(
        self, control_service: _JobService
    ) -> None:
        """Absent is unknown, and unknown must not read as denied.

        A record restored by a path that predates the capabilities block
        carries none. Reading that as "every control denied" greys every key on
        every row, and an operator whose whole list is in that shape finds an
        interface wired to nothing - which is exactly the report this work
        started from. The service is the authority on what it will accept, so
        the action is offered and its answer is shown.

        Proven able to fail: returning ``False`` for an absent block - the
        reading before this fix - sends no request and fails on the
        control-paths assertion below by name; restored, it passes.
        """
        job = _job("abc123def456")
        del job["capabilities"]

        app = _app(control_service, [job])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("d")
            painted = await _await_painted(pilot, app, "delete accepted")

        assert any(
            path == "/jobs/abc123def456" for path in control_service.control_paths()
        ), "a capability the record does not mention must not be treated as denied"
        assert "delete accepted" in painted

    @pytest.mark.asyncio
    async def test_a_published_denial_is_still_a_denial(
        self, control_service: _JobService
    ) -> None:
        """Only ``false`` denies; the distinction has to survive the change."""
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # ``deletable`` is published as False on this job.
            await pilot.press("d")
            await pilot.pause()
            app.action_job_delete()
            await pilot.pause()
            await _settle(pilot)

        assert control_service.control_paths() == [], (
            "a capability published as false must still block the request"
        )
