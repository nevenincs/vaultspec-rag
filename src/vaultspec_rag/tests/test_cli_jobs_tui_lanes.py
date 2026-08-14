"""Server-watch lanes: the behaviour of that half of the interface."""

from __future__ import annotations

import typing

import pytest
from textual.widgets import DataTable

from ._jobs_tui_harness import (  # noqa: F401
    _HANDOFF_TIMEOUT,
    _NARROW,
    _POLL_INTERVAL,
    _READY_RETRIES,
    _WIDE,
    _app,
    _await_gone,
    _await_painted,
    _await_painted_when,
    _finished_job,
    _header_line,
    _health_payload,
    _hold,
    _job,
    _jobs_payload,
    _JobService,
    _line_with,
    _log_payload,
    _quiesce_block,
    _ready,
    _requested_state,
    _row_line,
    _screen_failure,
    _screen_text,
    _search_activity_payload,
    _served_search,
    _settle,
    _settled_paint,
    _summarise,
    _unpainted,
    pytestmark,
)


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


class TestDualLaneServerWatch:
    """The root watch presents indexing and served searches as equal lanes."""

    @pytest.mark.asyncio
    async def test_wide_server_watch_shows_both_lanes_and_global_logs(
        self, control_service: _JobService
    ) -> None:
        control_service.set_search_activity(
            active=[
                _served_search(
                    "search-active-001",
                    query="where is the active indexing work",
                )
            ],
            recent=[
                _served_search(
                    "search-recent-001",
                    state="terminal",
                    query="which documents changed",
                    outcome="succeeded",
                )
            ],
        )
        app = _app(
            control_service,
            [_job("abc123def456")],
            watch_mode="server",
        )
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = await _await_painted(
                pilot, app, "where is the active indexing work"
            )
            await pilot.press("m")
            tank = await _await_painted(pilot, app, "Managed log tank")

        assert "code index" in painted, "indexing remains visible beside searches"
        assert "which documents changed" in painted, (
            "recent served searches remain visible"
        )
        assert "search 1 active · 1 recent" in painted, (
            "the header must expose both served-search counts"
        )
        assert "a qdrant log line" in tank, (
            "the canonical global log tank remains reachable from server watch"
        )
        assert "where is the active indexing work" not in tank, (
            "query text is reviewable from activity only, never injected into raw logs"
        )

    @pytest.mark.asyncio
    async def test_narrow_server_watch_keeps_counts_and_switches_to_search(
        self, control_service: _JobService
    ) -> None:
        control_service.set_search_activity(
            active=[
                _served_search(
                    "search-active-001",
                    query="show the served search query",
                )
            ],
            recent=[],
        )
        app = _app(
            control_service,
            [_job("abc123def456")],
            watch_mode="server",
        )
        async with app.run_test(size=_NARROW, notifications=True) as pilot:
            await _ready(pilot, app)
            jobs = await _await_painted(pilot, app, "search 1 active · 0 recent")
            await pilot.press("s")
            searches = await _await_painted(pilot, app, "show the served search query")
            await pilot.press("s")
            returned = await _await_painted(pilot, app, "code index")

        assert "show the served search query" not in jobs, (
            "narrow mode starts on indexing rather than squeezing both lanes"
        )
        assert "code index" not in searches, (
            "the selected narrow search lane must occupy the usable body"
        )
        assert "show the served search query" not in returned

    @pytest.mark.asyncio
    async def test_jobs_watch_starts_focused_and_keeps_search_review_access(
        self, control_service: _JobService
    ) -> None:
        control_service.set_search_activity(
            active=[
                _served_search(
                    "search-active-001",
                    query="find the query from jobs watch",
                )
            ],
            recent=[],
        )
        app = _app(control_service, [_job("abc123def456")])
        async with app.run_test(size=_NARROW, notifications=True) as pilot:
            await _ready(pilot, app)
            assert "-jobsfocused" in app.screen.classes
            await pilot.press("s")
            painted = await _await_painted(pilot, app, "find the query from jobs watch")

        assert "Served searches · 1 active · 0 recent" in painted

    @pytest.mark.asyncio
    async def test_search_focus_cannot_mutate_the_retained_job_selection(
        self, control_service: _JobService
    ) -> None:
        """A search-focused key must not reuse the indexing table's old row.

        The test drives the real search widget, all five job bindings, and the
        action methods that could otherwise bypass a disabled binding. It then
        focuses the real jobs table and proves the same pause control reaches
        the loopback service. Removing either action-context gate makes a
        request appear while search holds the keyboard.
        """
        control_service.set_search_activity(
            active=[_served_search("search-active-001")], recent=[]
        )
        job = _job(
            "abc123def456",
            capabilities={
                "pausable": True,
                "resumable": True,
                "cancellable": True,
                "retryable": True,
                "deletable": True,
                "force_killable": False,
            },
        )
        app = _app(control_service, [job], watch_mode="server")
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("s")
            await _await_painted(pilot, app, "why is the index behind")
            searches = typing.cast(
                "DataTable[object]", app.query_one("#searches", DataTable)
            )
            assert app.focused is searches, (
                "s gives the served-search lane the keyboard"
            )
            assert app.selected_id == "abc123def456", (
                "the retained id makes this the stale-selection regression"
            )
            for key in ("p", "u", "k", "y", "d"):
                await pilot.press(key)
                await pilot.pause()
            app.action_job_pause()
            app.action_job_resume()
            app.action_job_stop()
            app.action_job_retry()
            app.action_job_delete()
            await _settle(pilot)
            blocked = _screen_text(app)

            jobs = typing.cast("DataTable[object]", app.query_one("#jobs", DataTable))
            jobs.focus()
            await pilot.pause()
            await pilot.press("p")
            await _settle(pilot)

        assert "Select an indexing job before sending a job action." in blocked
        assert control_service.control_paths() == [
            "/jobs/abc123def456/desired-state"
        ], "only a job-focused pause may reach the service"

    @pytest.mark.asyncio
    async def test_global_log_focus_cannot_mutate_the_retained_job_selection(
        self, control_service: _JobService
    ) -> None:
        """The global raw-log tank keeps a job selection for return, not control.

        This drives the real full-height managed-log widget, every mutation
        binding, and the direct action methods that must not bypass the focus
        guard. Removing the managed-log branch of
        ``_job_action_context_available`` makes one of the named job-control
        requests reach the loopback service; restored, only refocusing the
        real jobs table permits the final pause.
        """
        job = _job(
            "abc123def456",
            capabilities={
                "pausable": True,
                "resumable": True,
                "cancellable": True,
                "retryable": True,
                "deletable": True,
                "force_killable": False,
            },
        )
        app = _app(control_service, [job], watch_mode="server")
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("m")
            await _await_painted(pilot, app, "Managed log tank")
            tank = app.query_one("#managedlog")
            assert app.focused is tank, "m gives the global raw-log tank the keyboard"
            assert app.selected_id == "abc123def456", (
                "the retained id makes this the stale-selection regression"
            )
            for key in ("p", "u", "k", "y", "d"):
                await pilot.press(key)
                await pilot.pause()
            app.action_job_pause()
            app.action_job_resume()
            app.action_job_stop()
            app.action_job_retry()
            app.action_job_delete()
            await _settle(pilot)
            blocked = _screen_text(app)

            await pilot.press("m")
            await _await_painted(pilot, app, "code index")
            jobs = typing.cast("DataTable[object]", app.query_one("#jobs", DataTable))
            jobs.focus()
            await pilot.pause()
            await pilot.press("p")
            await _settle(pilot)

        assert "Select an indexing job before sending a job action." in blocked
        assert control_service.control_paths() == [
            "/jobs/abc123def456/desired-state"
        ], "only a job-focused pause may reach the service"

    @pytest.mark.asyncio
    async def test_narrow_search_view_cannot_mutate_a_hidden_job_selection(
        self, control_service: _JobService
    ) -> None:
        """A lane switch hides jobs, so a direct action must refuse as well."""
        control_service.set_search_activity(
            active=[_served_search("search-active-001")], recent=[]
        )
        app = _app(
            control_service,
            [_job("abc123def456")],
            watch_mode="server",
        )
        async with app.run_test(size=_NARROW, notifications=True) as pilot:
            await _ready(pilot, app)
            await pilot.press("s")
            await _await_painted(pilot, app, "why is the index behind")
            jobs = typing.cast("DataTable[object]", app.query_one("#jobs", DataTable))
            assert not jobs.display, "narrow search replaces the indexing table"
            assert app.check_action("job_pause", ()) is None
            await pilot.press("p")
            await pilot.pause()
            app.action_job_pause()
            await _settle(pilot)

        assert control_service.control_paths() == []


class TestRedactedSearchActivity:
    """A service that withholds query text is serving, not broken.

    The ledger's serializer omits ``query`` and publishes ``query_redacted``
    whenever it is asked not to disclose the text, and a test pins that
    contract. The console required the text outright, so a supported service
    mode made the whole lane read as an invalid response - counts, rows and
    detail all replaced by an error string.
    """

    def test_a_redacted_record_is_accepted(self) -> None:
        """Mutation: requiring ``query`` again fails this on the returned error."""
        from ..cli._jobs_tui_payload import search_activity_records_error

        redacted: dict[str, object] = {
            "request_id": "r-1",
            "state": "active",
            "query_redacted": True,
        }
        assert search_activity_records_error([redacted], []) is None

    def test_a_record_carrying_neither_query_nor_redaction_is_rejected(self) -> None:
        """Silence about the text is not the same as a declared redaction.

        A record that simply lost the field must still fail: the check is that
        exactly one of the two is present, not that the strict one was relaxed.
        """
        from ..cli._jobs_tui_payload import search_activity_records_error

        silent: dict[str, object] = {"request_id": "r-2", "state": "active"}
        assert search_activity_records_error([silent], []) is not None

    def test_a_record_claiming_both_is_rejected(self) -> None:
        """Disclosed and redacted at once describes no service state."""
        from ..cli._jobs_tui_payload import search_activity_records_error

        both: dict[str, object] = {
            "request_id": "r-3",
            "state": "active",
            "query": "vector search",
            "query_redacted": True,
        }
        assert search_activity_records_error([both], []) is not None

    def test_the_cell_says_redacted_rather_than_unavailable(self) -> None:
        """An operator must not go looking for a fault that is not there."""
        from ..cli._jobs_tui import search_query_cell

        rendered = search_query_cell({"query_redacted": True}, 40).plain
        assert "redacted" in rendered
        assert "unavailable" not in rendered


class TestBoundedSearchProjectionAnnouncesItself:
    """A limited row set beside an unlimited count must say so.

    The counts are computed over every retained record; the rows are the
    bounded projection the route returned. Rendering the first beside the
    second with nothing between them lets an operator scroll to the end of
    the table and conclude they have seen everything.
    """

    @pytest.mark.asyncio
    async def test_a_truncated_projection_renders_its_served_figure(
        self, control_service: _JobService
    ) -> None:
        """Mutation: dropping the marker leaves only the unqualified counts.

        Removing the ``showing`` append in ``_render_search_title`` fails this
        on the membership assertion below, not on a count.
        """
        control_service.set_search_activity(
            active=[_served_search("search-active-001", query="a served query")],
            recent=[],
        )
        control_service.search_total_override = 300
        app = _app(control_service, [_job("abc123def456")], watch_mode="server")
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "showing 1 of 300" in painted, (
            "a bounded projection must name what it served against what exists"
        )

    @pytest.mark.asyncio
    async def test_an_untruncated_projection_spends_no_width_saying_so(
        self, control_service: _JobService
    ) -> None:
        """Every record served is the ordinary case and stays silent.

        Asserted on a two-record figure rather than the bare phrase: the jobs
        header carries its own ``showing N of M`` for the work list, so a
        looser matcher passes on that one and proves nothing about this lane.
        """
        control_service.set_search_activity(
            active=[
                _served_search("search-active-002", query="a served query"),
                _served_search("search-active-003", query="another served query"),
            ],
            recent=[],
        )
        app = _app(control_service, [_job("abc123def456")], watch_mode="server")
        async with app.run_test(size=_WIDE, notifications=True) as pilot:
            await _ready(pilot, app)
            painted = _screen_text(app)

        assert "showing 2 of 2" not in painted
