"""Server-watch controls: the behaviour of that half of the interface."""

from __future__ import annotations

import asyncio
import threading

import pytest

from ..cli._jobs_tui import (
    _SPINNER_INTERVAL,
)
from ..serviceclient._transport import _try_http_admin
from ._jobs_tui_harness import (
    _WIDE,
    _app,
    _await_gone,
    _await_painted,
    _finished_job,
    _job,
    _JobService,
    _ready,
    _row_line,
    _screen_text,
    _settle,
)

# Declared here rather than inherited: a module-level `pytestmark`
# reaches a suite only if the suite imports that name, so a tier that
# arrives through a helper import disappears the moment the import is
# narrowed - and an untiered test kills its worker at collection.
pytestmark = [pytest.mark.unit]


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
        # observes the window between asking and acknowledgement. The hold is
        # an event, not a delay: a window that lasts a fixed half second is one
        # the test loses on a loaded machine, because delivering the keystroke
        # pumps the event loop hard enough to outrun it and the stage is over
        # before the first readable frame. Released on the observation that
        # proves it, the window cannot close early however busy the box is.
        answered = threading.Event()
        control_service.control_gate = answered
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("p")
            painted = await _await_painted(pilot, app, "pause requested")
            answered.set()
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

        The wait is on the whole sentence the assertion needs, not on a phrase
        inside it. A fragment is already satisfied by the toast, which is
        narrow enough to wrap the sentence across two lines; the unwrapped copy
        is the header's, and the header picks the outcome up on its next beat.
        Waiting on the fragment therefore returns a frame that can carry only
        the wrapped copy, and the assertion fails on a sentence that is on the
        screen and about to be on it whole.
        """
        app = _app(control_service, [_finished_job("job00000")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # Removed behind the interface's back.
            control_service.set_jobs([])
            app.action_job_delete()
            painted = await _await_painted(
                pilot,
                app,
                "delete: job00000 is no longer on the service - list refreshed.",
            )
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

        Each intermediate stage is held open by the observation that ends it,
        never by a delay. The service cannot answer the control until the
        requested row has been read, and cannot answer the confirming poll
        until the sent row has been read, so the sequence this asserts is the
        one the service enforced rather than one the machine happened to allow.

        Proven able to fail: marking the keystroke ``sent`` rather than
        ``requested`` in ``_mark_pending`` - the view collapsing the two stages
        into the one it can prove - paints no requested row at all and fails on
        the "pause requested" needle by name; restored, it passes. The repaint
        in ``_mark_pending`` is not what this one holds: a running row is
        repainted by the frame tick regardless, and the sibling test over a
        finished row is what pins that.
        """
        answered = threading.Event()
        confirming_poll = threading.Event()
        control_service.control_gate = answered
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await _settle(pilot)
            # From here the only read left is the one the answered control
            # triggers, so holding reads holds exactly the window in which the
            # request is accepted but unconfirmed.
            control_service.fetch_gate = confirming_poll

            await pilot.press("p")
            requested = await _await_painted(pilot, app, "pause requested")
            answered.set()
            sent = await _await_painted(pilot, app, "pause sent")
            confirming_poll.set()
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
        # The window this test observes is the gap between the keystroke and
        # the service's answer, so the simulated control has to stay slow for
        # longer than a loaded runner's scheduling jitter. At 0.6s the answer
        # landed first on a twelve-worker CI host and the row had already
        # settled, reported as `pending markers=[none]` - the transient state
        # was gone before any frame sampled it, which says nothing about the
        # repaint being absent. A wider gap makes the same assertion, and
        # costs nothing: the test waits on pixels, not on this delay.
        control_service.control_delay = 5.0
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

            # The next poll is held open rather than merely made slow, so it
            # is still out when the control lands - the ordinary case at a
            # two-second interval against a thirty-second timeout. Held on an
            # event, because the reads that could settle the marker are the
            # ones this test needs never to answer until it has read the
            # frame: the control's own follow-up refresh is issued the moment
            # the service accepts, and a delay only bets that the marker is
            # painted and observed before that refresh returns. That bet is
            # the whole of the margin, and a loaded shard loses it - the
            # marker is settled before any frame carries it, and the wait then
            # sits out its full bound looking for a needle nothing will paint
            # again. Released below, once the frame has been read.
            control_service.fetch_gate = threading.Event()
            stale_generation = app._job_stamps.issued + 1
            app.refresh_jobs()

            await pilot.press("y")
            await _await_painted(pilot, app, "retry sent")

            # The poll finally answers, under its own stamp.
            app._apply_result(stale, stale_generation)
            await pilot.pause()
            painted = _screen_text(app)
            # Freed here rather than left to the service's teardown: the reads
            # are held on worker threads the interface joins as it closes, and
            # every one still parked is a full hold bound paid by the session
            # that ends.
            control_service.fetch_gate.set()
            await _settle(pilot)

        assert " retry sent" in painted, (
            "a payload fetched before the control cannot settle it"
        )
