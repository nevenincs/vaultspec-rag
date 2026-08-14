"""Server-watch header: the behaviour of that half of the interface."""

from __future__ import annotations

import asyncio

import pytest

from ..cli._jobs_tui import (
    _SPINNER_INTERVAL,
    ServerWatchApp,
)
from ..cli._jobs_tui_palette import DARK_THEME_NAME, LIGHT_THEME_NAME
from ..service_quiesce import QuiesceState
from ..serviceclient._transport import _try_http_admin
from ._jobs_tui_harness import (
    _NARROW,
    _WIDE,
    _app,
    _await_painted,
    _await_painted_when,
    _finished_job,
    _job,
    _JobService,
    _line_with,
    _quiesce_block,
    _ready,
    _screen_text,
    _settle,
)

# Declared here rather than inherited: a module-level `pytestmark`
# reaches a suite only if the suite imports that name, so a tier that
# arrives through a helper import disappears the moment the import is
# narrowed - and an untiered test kills its worker at collection.
pytestmark = [pytest.mark.unit]


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
                app._job_stamps.issued + 1,
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
            app._apply_result(
                {"detail": "Not authenticated"}, app._job_stamps.issued + 1
            )
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
            stale_generation = app._job_stamps.issued
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

        assert "✓ 12" in painted, (
            "the counters must describe every record the service holds, not "
            "the five that happen to be on the page"
        )
        assert "▶ 1" in painted
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

        assert "✓ 1" in painted
        assert "□ 2 other" in painted, (
            "states without a counter of their own must still be accounted for"
        )

    @pytest.mark.asyncio
    async def test_state_pills_pair_glyph_count_and_recede_at_zero(
        self, control_service: _JobService
    ) -> None:
        """Every pill is a glyph AND a count; an empty bucket goes dim.

        The glyph is never the only signal, so the count must be painted
        beside it - including the zero, which is a different claim from the
        bucket not existing at all.
        """
        jobs = [
            _job("abc123def456"),
            _job("dddd0000eeee", phase="error", state="failed"),
            _finished_job("job00001aaaa"),
            _finished_job("job00002aaaa"),
        ]
        app = _app(control_service, jobs)
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        # At this width the uniform anatomy is glyph, count, label - every
        # state pill alike, so no cell is decoded differently from its
        # neighbours.
        assert "▶ 1 running" in painted, "running renders as its full pill"
        assert "✖ 1 failed" in painted, "failed renders as its full pill"
        assert "✓ 2 succeeded" in painted, "succeeded renders as its full pill"
        assert "⋯ 0 queued" in painted, "an empty bucket is still accounted for"

    @pytest.mark.asyncio
    async def test_the_condition_pill_reports_the_worst_stamped_verdict(
        self, control_service: _JobService
    ) -> None:
        """The header says what the service is, not only what it is doing."""
        stalled = _job("abc123def456")
        stalled["degradation"] = "stalled"
        app = _app(control_service, [stalled, _finished_job("job00001aaaa")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "● svc stalled" in painted, (
            "the worst service-stamped verdict must sit in the header"
        )
        assert "▲ 1 stalled" in painted, "the stalled tally rides beside the states"

    @pytest.mark.asyncio
    async def test_a_healthy_service_says_so_in_the_header(
        self, control_service: _JobService
    ) -> None:
        app = _app(control_service, [_finished_job("job00001aaaa")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "● svc healthy" in painted

    @pytest.mark.asyncio
    async def test_gpu_pressure_renders_from_the_payload(
        self, control_service: _JobService
    ) -> None:
        control_service.gpu = {
            "available": True,
            "utilization_percent": 97.0,
            "memory_used_mib": 15770.0,
            "memory_total_mib": 16384.0,
        }
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "gpu 97% 15.4/16.0G" in painted, (
            "the card's pressure must be readable in the header at all times"
        )

    @pytest.mark.asyncio
    async def test_an_absent_gpu_block_renders_a_dash_not_numbers(
        self, control_service: _JobService
    ) -> None:
        """A daemon older than the field must never be given fake numbers.

        Proven able to fail: making the absent branch of ``_gpu_cell``
        return a zeroed reading - the shape inventing a default would take -
        paints ``gpu 0%`` and fails both assertions below by name; restored,
        it passes.
        """
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "gpu —" in painted, "an unreported card reads as a dim dash"
        assert "gpu 0" not in painted, "absence must never be painted as a zero reading"

    @pytest.mark.asyncio
    async def test_a_probed_but_unmeasurable_host_reads_na(
        self, control_service: _JobService
    ) -> None:
        """Present-and-null is the daemon probing a host it cannot measure."""
        control_service.gpu = {
            "available": False,
            "utilization_percent": None,
            "memory_used_mib": None,
            "memory_total_mib": None,
        }
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "gpu n/a" in painted
        assert "gpu —" not in painted, (
            "a probed host is a different answer from an unreporting daemon"
        )

    @pytest.mark.asyncio
    async def test_a_pressured_machine_is_named_in_the_header(
        self, control_service: _JobService
    ) -> None:
        control_service.pressure = {
            "tier": "critical",
            "entered_at": 1_000.0,
            "evidence": {},
        }
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "pressure critical" in painted, (
            "the machine tier must be readable in the header while it is not nominal"
        )

    @pytest.mark.asyncio
    async def test_a_nominal_machine_spends_no_header_width(
        self, control_service: _JobService
    ) -> None:
        """The healthy steady state is the one that must stay silent.

        Proven able to fail: dropping ``nominal`` from the silent set in
        ``_pressure_cell`` - so the steady state claims a pill - paints
        ``pressure nominal`` and fails the assertion below by name;
        restored, it passes. The pill is not free: the header is already
        at its widest fitting form, so a cell nobody needs sheds the state
        labels somebody does.
        """
        control_service.pressure = {
            "tier": "nominal",
            "entered_at": 1_000.0,
            "evidence": {},
        }
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "pressure" not in painted, (
            "a nominal machine must not spend header width saying so"
        )
        assert "▶ 1 running" in painted, (
            "and the labels the pill would have cost must still be painted"
        )

    @pytest.mark.asyncio
    async def test_a_daemon_without_the_tier_paints_no_pressure_cell(
        self, control_service: _JobService
    ) -> None:
        """Absent is not a verdict, and must not be painted as any tier."""
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "pressure" not in painted, (
            "a daemon that predates the tier must not grow a pressure cell"
        )

    @pytest.mark.asyncio
    async def test_a_tier_this_build_does_not_know_is_still_painted(
        self, control_service: _JobService
    ) -> None:
        """A newer daemon naming a worse state must not be swallowed.

        Proven able to fail: matching ``_pressure_cell`` against a fixed set
        of known tiers instead of rendering verbatim - the silence this
        guards against - paints nothing and fails the assertion below by
        name; restored, it passes.
        """
        control_service.pressure = {
            "tier": "catastrophic",
            "entered_at": 1_000.0,
            "evidence": {},
        }
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "pressure catastrophic" in painted, (
            "an unrecognised tier is the service's verdict and is shown as given"
        )

    @pytest.mark.asyncio
    async def test_a_running_controller_spends_no_header_width(
        self, control_service: _JobService
    ) -> None:
        """The controller's steady state is the one that must stay silent.

        A running controller holding its VRAM with no borrower admitted is
        what an operator already assumes, and it is what every healthy daemon
        publishes on every refresh. Spending the widest cell in the bar on it
        sheds the state labels for a claim nobody was waiting on - and the
        evidence is not lost by the silence, because the detail row carries
        the whole block whatever the pill decides.

        Proven able to fail: returning the evidence pill for the running
        steady state - the shape that renders every observation alike -
        paints ``borrower safety unsafe`` and fails the first two assertions
        below by name; restored, it passes.
        """
        control_service.quiesce = _quiesce_block(
            state=QuiesceState.RUNNING,
            vram_released=False,
            safe_to_borrow_gpu=False,
        )
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "borrower safety" not in painted, (
            "a controller in its steady state must not spend header width saying so"
        )
        assert "▶ 1 running" in painted, (
            "and the labels the pill would have cost must still be painted"
        )
        assert "quiesce details:" in painted, (
            "silence in the header is not silence on screen: the detail row "
            "still carries the block the service published"
        )

    @pytest.mark.asyncio
    async def test_a_quiesced_controller_keeps_its_cell_over_the_labels(
        self, control_service: _JobService
    ) -> None:
        """Controller news outranks every label the bar could have kept.

        A controller past running is the window in which an operator needs
        all three facts at once, so the cell is painted whole and the labels
        go instead - the reverse of the steady-state case, from the same
        header width.
        """
        control_service.quiesce = _quiesce_block(
            state=QuiesceState.QUIESCED,
            vram_released=True,
            safe_to_borrow_gpu=True,
        )
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "quiesce quiesced" in painted
        assert "vram released" in painted
        assert "borrower safety safe" in painted, (
            "the borrower's own answer is the reason the cell exists"
        )
        assert "▶ 1 running" not in painted, (
            "reported controller evidence is never shed; the labels are"
        )

    @pytest.mark.asyncio
    async def test_a_narrow_bar_sheds_labels_before_counts_or_cells(
        self, control_service: _JobService
    ) -> None:
        """Width takes the pill labels first; nothing else is ever shed."""
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_NARROW, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "▶ 1" in painted, "the count survives every width"
        assert "▶ 1 running" not in painted, "labels are the first thing shed"
        assert "svc" in painted, "the condition cell is never shed"
        assert "gpu" in painted, "the GPU cell is never shed"

    @pytest.mark.asyncio
    async def test_a_service_publishing_no_total_claims_none(
        self, control_service: _JobService
    ) -> None:
        """Absent is not zero, and must not be painted as a total of zero."""

        def fetch() -> dict[str, object] | None:
            return {"ok": True, "jobs": [_job("abc123def456")]}

        app = ServerWatchApp(
            fetch=fetch,
            port=control_service.port,
            interval=3600.0,
            watch_mode="jobs",
        )
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "showing 1" in painted
        assert "of 0" not in painted, "an unpublished total must not read as zero"


class TestServiceIdentity:
    """The header leads with which daemon this is, at which release."""

    @pytest.mark.asyncio
    async def test_the_daemons_own_version_leads_the_header(
        self, control_service: _JobService
    ) -> None:
        """The version shown is the connected daemon's report, never local.

        A stale daemon beside a fresh client is exactly when the number
        matters, so the fixture reports a release the local package cannot
        be - the assertion fails if the cell is filled from the client.
        """
        from ..serviceclient._compat import local_package_version

        control_service.package_version = "9.9.9"
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = await _await_painted(pilot, app, "vaultspec-rag 9.9.9")

        assert "vaultspec-rag 9.9.9" in painted, (
            "the running daemon's release must lead the header"
        )
        assert f"vaultspec-rag {local_package_version()}" not in painted, (
            "the cell must never be filled from the local package"
        )
        assert "port" in _line_with(painted, "vaultspec-rag 9.9.9"), (
            "identity and port share the leading cell"
        )

    @pytest.mark.asyncio
    async def test_an_unversioned_daemon_reads_unknown_not_a_number(
        self, control_service: _JobService
    ) -> None:
        """A daemon that predates version reporting is said to be unknown.

        Proven able to fail: filling the absent branch from the local
        package - the fabrication this guards against - paints the local
        release and fails both assertions below by name; restored, it
        passes.
        """
        from ..serviceclient._compat import local_package_version

        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            # Wait on the fact, not the rendering, so a mutation that paints
            # the wrong thing fails on the assertions below by name rather
            # than timing out the wait.
            await _await_painted_when(
                pilot,
                app,
                lambda _text: app._version.checked,
                "the daemon's identity answer",
            )
            await asyncio.sleep(_SPINNER_INTERVAL)
            await pilot.pause()
            painted = _screen_text(app)

        assert "vaultspec-rag v?" in painted, (
            "an answering daemon without a version reads as unknown"
        )
        assert f"vaultspec-rag {local_package_version()}" not in painted, (
            "unknown must never be papered over with the local release"
        )


class TestPillShape:
    """Pills are rounded, background-filled spans, not coloured text runs."""

    _FILL = ("#123456", "#654321")

    def test_a_pill_is_capped_in_its_own_fill_colour(self) -> None:
        from rich.text import Text

        from ..cli._jobs_tui_cells import append_pill
        from ..cli._jobs_tui_constants import PILL_CAP_LEFT, PILL_CAP_RIGHT

        line = Text()
        append_pill(line, "> 2 running", self._FILL, unicode_ok=True)
        spans = [(line.plain[s.start : s.end], str(s.style)) for s in line.spans]

        background, foreground = self._FILL
        assert spans[0] == (PILL_CAP_LEFT, background), (
            "the left cap's foreground is the pill's background, so the "
            "half-circle completes the fill"
        )
        assert spans[-1] == (PILL_CAP_RIGHT, background)
        # Interior spaces are non-breaking, so the pill wraps as one unit.
        assert spans[1] == (
            "> 2 running".replace(" ", "\u2800"),
            f"{foreground} on {background}",
        ), "the span between the caps is background-filled"

    def test_the_ascii_degradation_is_a_soft_filled_span(self) -> None:
        """No caps a font cannot carry, and no brackets pretending to be.

        Proven able to fail: making the ASCII branch emit the cap glyphs
        anyway - the degradation this guards - fails the no-cap assertion
        by name; restored, it passes.
        """
        from rich.text import Text

        from ..cli._jobs_tui_cells import append_pill
        from ..cli._jobs_tui_constants import PILL_CAP_LEFT, PILL_CAP_RIGHT

        line = Text()
        append_pill(line, "> 2 running", self._FILL, unicode_ok=False)

        assert PILL_CAP_LEFT not in line.plain, (
            "an ASCII console must never be sent the cap glyphs"
        )
        assert PILL_CAP_RIGHT not in line.plain
        assert "[" not in line.plain and "]" not in line.plain, (
            "the degradation is padding, not brackets"
        )
        # Non-breaking padding throughout, so the pill wraps as one unit.
        assert line.plain == " > 2 running ", (
            "the filled span is space-padded so it still reads as a pill"
        )
        background, foreground = self._FILL
        assert str(line.spans[0].style) == f"{foreground} on {background}"


class TestColourScheme:
    """One palette, two variants; nothing else is selectable."""

    @pytest.mark.asyncio
    async def test_the_variants_toggle_between_the_palette_themes(
        self, control_service: _JobService
    ) -> None:
        """Dark by default, the light variant one keypress away."""
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            default_theme = app.theme
            await pilot.press("ctrl+t")
            await pilot.pause()
            toggled = app.theme
            await pilot.press("ctrl+t")
            await pilot.pause()
            restored = app.theme

        assert default_theme == DARK_THEME_NAME, "the dark variant is the default"
        assert toggled == LIGHT_THEME_NAME, "the toggle flips to the light variant"
        assert restored == DARK_THEME_NAME


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

        Proven able to fail: dropping the terminal-state test in ``state_cell``
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
