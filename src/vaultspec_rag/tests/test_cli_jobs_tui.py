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
import re
import threading

import pytest

from ..cli._jobs_tui import (
    _SPINNER_FRAMES,
    _SPINNER_INTERVAL,
    ServerWatchApp,
)
from ..cli._jobs_tui_constants import LOG_LINES
from ..serviceclient._transport import _try_http_admin
from ._jobs_tui_harness import (
    _NARROW,
    _WIDE,
    _app,
    _await_painted,
    _await_painted_when,
    _finished_job,
    _header_line,
    _job,
    _JobService,
    _line_with,
    _ready,
    _screen_failure,
    _screen_text,
    _settle,
    _settled_paint,
)

# Declared here rather than inherited: a module-level `pytestmark`
# reaches a suite only if the suite imports that name, so a tier that
# arrives through a helper import disappears the moment the import is
# narrowed - and an untiered test kills its worker at collection.
pytestmark = [pytest.mark.unit]


class TestTeardown:
    """Queued presentation timers are harmless after Textual removes its screen."""

    @pytest.mark.asyncio
    async def test_jobs_focused_timer_tick_survives_screen_teardown(self) -> None:
        """The normal jobs watch may close between a timer queue and its callback.

        Proven able to fail: without the screen-presence guard, leaving the
        real Textual ``run_test`` context clears its screen stack and this
        direct production timer callback raises ``ScreenStackError`` from
        ``_apply_default_log_visibility``. Restored, it is a no-op.
        """

        def fetch() -> dict[str, object] | None:
            return {"ok": True, "jobs": [_job("teardown-watch-job")]}

        app = ServerWatchApp(
            fetch=fetch,
            port=0,
            interval=3600.0,
            watch_mode="jobs",
        )
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            assert app.screen.has_class("-jobsfocused")

        assert not app.is_running
        app._tick()


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
        # The row counts the service's 140s estimate down between polls, so
        # the painted value depends on how long the first paint took; any
        # value within a few ticked seconds proves the estimate is on the row.
        assert re.search(r"2m(?:1[5-9]|20)s left", painted), (
            "the estimate must be on the row"
        )

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
            narrow_cells = narrow._layout.bar_cells

        wide = _app(control_service, [_job("abc123def456")])
        async with wide.run_test(size=(260, 24), notifications=True) as pilot:
            await _ready(pilot, wide)
            wide_cells = wide._layout.bar_cells

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
            frames: list[str] = []
            for _ in range(6):
                await asyncio.sleep(_SPINNER_INTERVAL)
                await pilot.pause()
                frames.append(_header_line(app))

        assert all("· vaultspec-rag" in frame for frame in frames), (
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
                    char in _line_with(text, "vaultspec-rag")
                    for char in _SPINNER_FRAMES
                ),
                "an animated header glyph",
            )
            await _settle(pilot)

        assert "vaultspec-rag" in _line_with(painted, "vaultspec-rag")

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
            rows: list[str] = []
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
        """A marker left on a dead id would describe a request forever.

        The service answers the held control with ``job_not_found``, because
        the job left the list while the control was in flight, so the marker
        settles as ``gone`` rather than ``sent``. A gone marker for a job the
        service no longer lists must be dropped.

        The claim is carried by ``app._pending``, not by the frame: the row
        itself is gone, so nothing paints for it either way. The painted wait
        below is a synchronisation point, and ``_settle`` is what guarantees
        the control has actually resolved before the assertions run.

        Proven able to fail: made the gone-marker branch of
        ``_reconcile_pending`` skip its delete; this fails on
        ``app._pending == {}``, carrying the surviving marker. Restored, it
        passes.
        """
        # The control is held rather than merely slowed. The requested stage
        # lasts exactly as long as the service takes to answer, so a delay
        # makes the whole assertion a bet that this box paints and reads a
        # frame inside it - and a loaded shard loses that bet, after which the
        # wait sits out its full bound hunting a stage that is already over.
        # Held on an event, the stage ends on the observation that proves it.
        control_service.control_gate = threading.Event()
        jobs = [_job("abc123def456"), _job("def456abc123")]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            await _await_painted(pilot, app, "pause requested")

            # The job leaves the service while its control is still in flight,
            # which is the situation this test is about.
            control_service.set_jobs([jobs[1]])
            app.refresh_jobs()
            await _await_painted(pilot, app, "showing 1 of 1")

            # Only now may the control answer, against a job the service no
            # longer holds. The marker must not outlive that.
            control_service.control_gate.set()
            # Every painted form of the marker, not just the requested one:
            # the outcome flips to "sent" the moment the service answers, so
            # waiting for "pause requested" alone would be satisfied by the
            # stage advancing rather than by the marker actually going.
            painted = await _await_painted_when(
                pilot,
                app,
                lambda frame: (
                    "pause requested" not in frame and "pause sent" not in frame
                ),
                "the pause marker leaving the row",
            )
            await _settle(pilot)

        assert "pause requested" not in painted, (
            "a pending marker must not survive the job it describes"
        )
        assert app._pending == {}


class TestRemainingTimeOnTheRow:
    """The row answers "how much longer", or says plainly that it cannot."""

    @pytest.mark.asyncio
    async def test_a_declined_estimate_is_said_on_the_row(
        self, control_service: _JobService
    ) -> None:
        """Published null on working work reads as unknown, not as nothing.

        A bare dash on a running row reads as "nothing to know here", when
        the truth is the service measured and declined. Saying so is what
        stops an operator refreshing forever waiting for a dash to change.

        Proven able to fail: collapsing the published-null branch of
        ``time_cell`` into the dash - the rendering before this change -
        never paints the marker and fails on the assertion below by name;
        restored, it passes.
        """
        app = _app(control_service, [_job("abc123def456", remaining=None, rate=None)])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "ETA unknown" in painted, (
            "a published null on a running row must read as an explicit unknown"
        )

    @pytest.mark.asyncio
    async def test_a_pre_estimate_daemon_row_does_not_claim_unknown(
        self, control_service: _JobService
    ) -> None:
        """Absent stays a different answer from null on the row itself.

        Proven able to fail: making ``time_cell`` treat an absent key the
        same as a published null paints the marker on every row of an older
        daemon and fails on the not-painted assertion below by name;
        restored, it passes and the header note carries the version gap.
        """
        job = _job("abc123def456")
        del job["estimated_remaining_seconds"]
        del job["progress_rate_per_second"]

        app = _app(control_service, [job])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "ETA unknown" not in painted, (
            "a daemon that never estimates must not read as declining each job"
        )
        assert "does not report time estimates" in painted

    @pytest.mark.asyncio
    async def test_inert_work_does_not_claim_unknown(
        self, control_service: _JobService
    ) -> None:
        """Finished work has no remaining time to be unsure about."""
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "ETA unknown" not in painted, (
            "an unknown marker on finished work claims a question it never had"
        )

    @pytest.mark.asyncio
    async def test_the_countdown_ticks_between_polls_and_snaps_to_the_service(
        self, control_service: _JobService
    ) -> None:
        """Between polls the row counts down; each poll re-anchors it.

        The refresh interval here is an hour, so every movement below is the
        display ticking the last service value down locally - and the manual
        refresh proves a fresh payload snaps the row back to what the
        service says rather than continuing from the local count.

        Proven able to fail two ways, each on its own assertion: removing
        the time-cell update from ``_repaint_animated_cells`` leaves the row
        frozen on the applied value and fails awaiting the ticked-down
        paint; stamping entries only when absent in ``_record_estimates``
        (instead of rebuilding the map) keeps the countdown falling through
        the refresh and fails on the snapped-back assertion. Restored, both
        pass.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # The service said 140s; a strictly lower painted value can only
            # come from the local tick-down.
            await _await_painted_when(
                pilot,
                app,
                lambda text: re.search(r"2m1[0-8]s left", text) is not None,
                "a countdown ticked below the service estimate",
            )

            app.refresh_jobs()
            snapped = await _await_painted(pilot, app, "2m20s left")

        assert "2m20s left" in snapped, (
            "a fresh service payload must snap the countdown back to its value"
        )


class TestClosingTheSession:
    """Nothing the interface set in motion outlives the screen it paints.

    A session ends by removing the screen, and the stack is empty from that
    moment on. Anything still beating or still answering reads the screen,
    raises there, and is reported as the interface having crashed rather than
    closed - on whichever unrelated thing happened to be in progress. Every
    test below drives the removal directly, because the window it opens is
    microseconds wide on an idle machine and a loaded one lands in it about
    once in several hundred sessions.
    """

    @pytest.mark.asyncio
    async def test_no_beat_survives_the_screen_it_paints(
        self, control_service: _JobService
    ) -> None:
        """Removing the screen stops every one of the interface's beats.

        The removal empties the screen stack before the timers an application
        owns are stopped, so a beat owned there fires once more with no screen
        left to read.

        Proven able to fail two ways, each on its own assertion: registering
        the frame beat on the application - the ownership before this change -
        fires it against the empty stack and fails on the outlived assertion;
        registering the jobs beat there instead leaves a beat running without
        firing one, and fails on the ownership assertion. Restored, both pass.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            with control_service._lock:
                polls_before_close = sum(
                    method == "GET" and path.startswith("/jobs")
                    for method, path in control_service.requests
                )
            # The step that removes the interface's screen.
            await app._close_all()
            # Several frames' worth, so a beat that survived has to fire.
            await asyncio.sleep(_SPINNER_INTERVAL * 4)
            # Read and cleared here so the assertion below is what fails,
            # rather than the session's own close re-raising it.
            recorded = app._exception
            app._exception = None
            # The job interval is an hour, so a misplaced application-owned
            # timer remains live here without firing during this bounded
            # window. Its presence is therefore distinct from the real
            # transport observation below: together they prove teardown
            # stopped the timer, rather than merely that it happened not to
            # poll yet.
            beats = {app._tick, app.refresh_jobs, app.refresh_service_status}
            timer_names = {
                timer.name for timer in app._timers if timer._callback in beats
            }
            left_running = [
                task.get_name()
                for task in asyncio.all_tasks()
                if task.get_name() in timer_names and not task.done()
            ]
            with control_service._lock:
                polls_after_close = sum(
                    method == "GET" and path.startswith("/jobs")
                    for method, path in control_service.requests
                )

        assert recorded is None, f"a beat outlived the screen it paints: {recorded!r}"
        assert not left_running, (
            "the beats must end with the screen they paint, not with the "
            f"application: {left_running}"
        )
        assert polls_after_close == polls_before_close, (
            "the jobs refresh beat outlived the screen without raising"
        )

    @pytest.mark.asyncio
    async def test_an_answer_that_outlives_the_session_is_dropped(
        self, control_service: _JobService
    ) -> None:
        """A poll answering after the screen has gone is dropped, not applied.

        A blocking transport call cannot be cancelled, so a request issued a
        moment before the session ended answers into an interface that no
        longer has a screen to paint onto.

        Proven able to fail two ways, each on its own assertion: removing the
        screen check from ``_apply_result`` raises out of the binding refresh
        at the end of it and fails on the dropped assertion; removing both
        that check and the binding refresh applies a payload no operator can
        see and fails on the not-applied assertion. Restored, both pass.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # An answer that differs from what the interface holds, so applying
            # it is visible rather than indistinguishable from dropping it.
            control_service.set_jobs([_job("999999999999")])
            answer = _try_http_admin("get_jobs", {"limit": 20}, control_service.port)
            await app._close_all()
            failure = _screen_failure(
                lambda: app._apply_result(answer, app._job_stamps.issued + 1)
            )
            held = [str(job.get("id")) for job in app._jobs]

        assert failure is None, (
            f"an answer arriving after the screen went must be dropped: {failure!r}"
        )
        assert held == ["abc123def456"], (
            "an answer arriving after the screen went must not be applied either"
        )

    @pytest.mark.asyncio
    async def test_a_log_answer_that_outlives_the_session_is_dropped(
        self, control_service: _JobService
    ) -> None:
        """A log window answering after the screen has gone is dropped as well.

        Pinned separately from its neighbour for two reasons, neither of which
        the code itself records.

        First, this one is protected by accident rather than on purpose: the
        pane's absence is noticed before anything reads the screen, so what
        stops the read is a lookup that happens to sit in front of it. Hoisting
        the binding refresh above that lookup is an ordinary-looking tidy-up
        which removes the protection with nothing else in the file to notice -
        so the two tests are not the duplicates they resemble, and neither
        covers the other.

        Second, that lookup comes back empty rather than raising only because
        a query issued from the application resolves against the screen the
        application composed on, held separately from the screen stack that
        teardown empties (``App._compose_screen``, assigned once at compose
        time). Nothing here governs that. Were it to stop being held, every
        callback answering after the screen has gone would begin raising at its
        first lookup, and this test is the only tripwire that says so - the
        failures otherwise surface as an unexplained intermittent crash in
        whatever else happened to be running.

        Proven able to fail: moving the binding refresh above the absent-pane
        return raises out of it and fails on the assertion below by name, while
        the neighbouring poll test still passes; restored, it passes.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            selected = app.selected_id
            # The same window the interface asks for, from the same transport.
            answer = _try_http_admin(
                "get_logs",
                {"lines": LOG_LINES, "source": "service", "job_id": selected},
                control_service.port,
            )
            assert answer is not None and answer.get("ok") is True, (
                "the delivery below has to carry an answer the interface would act on"
            )
            await app._close_all()
            failure = _screen_failure(lambda: app._apply_logs(selected, answer))

        assert failure is None, (
            f"a log answer arriving after the screen went must be dropped: {failure!r}"
        )
