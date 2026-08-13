"""Interactive operator interface for the service jobs surface.

Owns the terminal for the duration of the session. Nothing here writes to the
shared console: a live region cannot be hosted on a console configured
non-interactively, and a second console alongside the first corrupts the frame
it is trying to share. The application takes the screen instead.

Every control it issues goes through the same typed transports the singular
job verbs use, carrying the same expected-revision guard. An action is withheld
only where the job's own capabilities publish it as denied; a record that says
nothing about a capability is offered the action, and the service's answer -
including its refusal - is shown on the row that asked for it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, Static
from textual.widgets.data_table import ColumnKey
from textual.worker import WorkerState

from ..jobs import count, measurement
from ..logging_config import MAX_MANAGED_LOG_LINES, validate_managed_log_payload
from ..serviceclient._transport import (
    _try_http_admin,
    _try_http_delete_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)
from ._jobs_tui_cells import (
    PaintContext,
    Pending,
    Tombstone,
    capability_flag,
    find_record,
    job_cell,
    job_id_of,
    path_cell,
    progress_cell,
    row_animates,
    search_clock_line,
    search_failure_line,
    search_id,
    search_identity_line,
    search_outcome_line,
    search_query_cell,
    search_request_cell,
    search_state_cell,
    search_text,
    search_time_cell,
    search_timings_line,
    state_cell,
    time_cell,
)
from ._jobs_tui_constants import (
    ACTION_KEYS,
    ACTION_REASONS,
    COLUMN_WEIGHTS,
    ESTIMATE_KEY,
    LOG_CLOSED_REASON,
    MIN_COLUMN_CELLS,
    SEARCH_ACTIVITY_LIMIT,
    SEARCH_COLUMN_WEIGHTS,
    SPLIT_MIN_CELLS,
    STATE_ACTIONS,
)
from ._jobs_tui_header import HeaderRenderingMixin
from ._jobs_tui_log import JobsLogView
from ._jobs_tui_managed_logs import ManagedLogTankView
from ._jobs_tui_palette import (
    DARK_THEME_NAME,
    LIGHT_THEME_NAME,
    build_themes,
    semantic_tones,
    tone_style,
)
from ._jobs_tui_payload import (
    action_capability,
    canonical_quiesce_block,
    fetch_error_text,
    is_gone,
    log_lines,
    search_activity_error,
    search_records,
)
from ._jobs_tui_state import (
    LaneStamps,
    LayoutMetrics,
    MachineSignals,
    ManagedLogState,
    SearchActivityState,
    ServiceVersion,
)
from ._jobs_tui_status import (
    ServiceStatusBar,
    ServiceStatusHeader,
    fetch_service_status,
)
from ._service_jobs_query import job_revision

if TYPE_CHECKING:
    from collections.abc import Callable

    from textual.screen import Screen
    from textual.widget import Widget

    from ..job_models import DesiredJobState

__all__ = ["ServerWatchApp", "run_server_watch"]

# Braille frames, advanced only while something is actually happening: a
# request this view issued is outstanding, or a row's own work is moving. The
# "last refreshed" stamp beside the glyph is what reports liveness when
# nothing is; motion is reserved for activity an operator can name.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_INTERVAL = 0.1
_LOG_LINES = 200

# What the header shows when nothing is in flight. A glyph that turns whether
# or not anything is happening tells an operator nothing, and a permanently
# animated one actively misleads: it says "working" over a view that has been
# idle for a minute. Motion here means a request is out; stillness means the
# view is settled, and the refreshed-age beside it says how old the data is.
_SETTLED_GLYPH = "·"

# How long a deleted row stays on screen, struck through, before it leaves.
# Long enough to read which row went; the list otherwise backfills the freed
# slot from the remainder and nothing appears to have happened at all.
_TOMBSTONE_SECONDS = 4.0

# The service's answer when the control named a job it no longer holds. This
# is not a generic failure: it means the view is addressing something that has
# been dropped, and the remedy is a corrected list rather than an error.

# Each kind of request runs in a worker group of its own. An exclusive worker
# cancels every worker sharing its group, and the poll that keeps the view
# current is exclusive by necessity - so leaving these in one group means the
# next tick of the refresh timer cancels whatever control the operator just
# issued. The request still reaches the service, because a thread worker
# cannot be interrupted mid-call, but its answer is discarded: the row never
# updates and no outcome is ever reported. That is precisely the shape of "the
# action did nothing".
_REFRESH_GROUP = "jobs-refresh"
_SEARCH_ACTIVITY_GROUP = "search-activity-refresh"
_LOG_GROUP = "jobs-log"
_MANAGED_LOG_GROUP = "managed-log-refresh"
_CONTROL_GROUP = "jobs-control"
# The service header polls on its own group. Textual cancels a whole group
# when an exclusive worker in it starts, so anything sharing a group with the
# controls can destroy a control request before it is ever sent.
_STATUS_GROUP = "jobs-service-status"

_REQUEST_GROUPS = frozenset(
    {
        _REFRESH_GROUP,
        _SEARCH_ACTIVITY_GROUP,
        _LOG_GROUP,
        _MANAGED_LOG_GROUP,
        _CONTROL_GROUP,
    }
)
# The service is far less volatile than the job list, so it is polled at a
# multiple of the job interval rather than on every refresh.
_STATUS_REFRESH_MULTIPLE = 5
_ACTIVE_WORKER_STATES = frozenset({WorkerState.PENDING, WorkerState.RUNNING})


class _LogPane(Vertical):
    """The log pane's container, allowed to fill the screen on request.

    A plain container refuses maximization, and maximizing the log widget
    alone would take it from under its own title bar - the zoom would drop
    the line saying whose log this is and what the noise filter hides.
    """

    ALLOW_MAXIMIZE: ClassVar[bool | None] = True


class ServerWatchApp(HeaderRenderingMixin, App[None]):
    """The canonical live server watch for indexing and served searches."""

    # Every size here is relative: fractional shares for the panes, content
    # height for the bars. Nothing is expressed as a fixed cell count, so the
    # layout follows whatever the terminal reports at any moment.
    #
    # Each pane wears a rounded border, and the border is how focus is told:
    # the pane holding the keyboard lights its frame with the accent colour,
    # every other frame stays muted. The focus ring is the one visual answer
    # to "where will my next keypress land", so it is carried by the pane's
    # own frame rather than by anything inside it.
    CSS = """
    /* The header is a rounded panel like the panes below it, so the whole
       surface reads as one composed set of cards rather than bare bars
       above a framed table. */
    #header { height: auto; border: round $panel-lighten-2; padding: 0 1; }
    #summary { height: auto; padding: 0 1; color: $text; }
    #servicestatus { height: auto; padding: 0 1; color: $text-muted; }
    #body { height: 1fr; width: 1fr; padding: 0 1; }
    #lanes { height: 1fr; width: 1fr; }
    #jobs { width: 1fr; height: 1fr; border: round $panel-lighten-2; }
    #jobs:focus { border: round $accent; }
    #searchpane { width: 1fr; height: 1fr; border: round $panel-lighten-2; }
    #searchpane:focus-within { border: round $accent; }
    #searchtitle { height: auto; padding: 0 1; background: $panel-darken-1; }
    #searches { height: 1fr; }
    #searchdetail {
        height: 6; padding: 0 1; color: $text-muted; overflow-y: auto;
    }
    #logpane { display: none; border: round $panel-lighten-2; }
    #logpane:focus-within { border: round $accent; }
    #logtitle { height: auto; padding: 0 1; background: $panel-darken-1; }
    #joblog { height: 1fr; padding: 0 1; }
    #managedlogpane { display: none; border: round $panel-lighten-2; }
    #managedlogpane:focus-within { border: round $accent; }
    #managedlogtitle { height: auto; padding: 0 1; background: $panel-darken-1; }
    #managedlog { height: 1fr; padding: 0 1; }

    /* One state drives the log in both layouts, so the toggle always does
       something. Width only decides whether showing it splits the screen or
       takes it over. */
    Screen.-showlog #logpane { display: block; }
    Screen.-wide.-showlog #lanes { width: 3fr; }
    Screen.-wide.-showlog #logpane { width: 2fr; margin-left: 1; }
    Screen.-narrow.-showlog #lanes { display: none; }
    Screen.-narrow.-showlog #logpane { width: 1fr; }

    /* A server watch is balanced when there is room. At narrow widths the
       selected lane fills the body, while the header keeps both counts live. */
    Screen.-wide #searchpane { display: block; width: 1fr; margin-left: 1; }
    Screen.-narrow #searchpane { display: none; }
    Screen.-narrow.-showsearch #jobs { display: none; }
    Screen.-narrow.-showsearch #searchpane {
        display: block; width: 1fr; margin-left: 0;
    }

    /* The jobs invocation starts focused on indexing, but its search lane is
       still available through the same owner and preserves its own snapshot. */
    Screen.-jobsfocused #searchpane { display: none; }
    Screen.-jobsfocused.-showsearch #jobs { display: none; }
    Screen.-jobsfocused.-showsearch #searchpane {
        display: block; width: 1fr; margin-left: 0;
    }

    /* The global tank is a review mode, not a third compressed pane. Its
       source groups need the whole body and must never be arranged into an
       inferred cross-source event timeline. */
    Screen.-showmanagedlogs #lanes,
    Screen.-showmanagedlogs #logpane { display: none; }
    Screen.-showmanagedlogs #managedlogpane { display: block; width: 1fr; }
    """

    # Unannotated on purpose: the base declares this class variable, and
    # restating a narrower type here is an invalid override.
    HORIZONTAL_BREAKPOINTS = [  # noqa: RUF012
        (0, "-narrow"),
        (SPLIT_MIN_CELLS, "-wide"),
    ]

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("p", "job_pause", "Pause"),
        Binding("u", "job_resume", "Resume"),
        Binding("k", "job_stop", "Kill"),
        Binding("y", "job_retry", "Retry"),
        Binding("d", "job_delete", "Delete"),
        Binding("l", "toggle_log", "Log"),
        Binding("s", "toggle_search", "Search"),
        Binding("m", "toggle_managed_logs", "Managed logs"),
        Binding("z", "toggle_zoom", "Zoom"),
        Binding("ctrl+t", "toggle_theme", "Dark/light", show=False),
        Binding("x", "log_noise", "Noise"),
        Binding("n", "log_next_error", "Next error"),
        Binding("N", "log_prev_error", "Prev error", show=False),
        Binding("g", "log_top", "Log top", show=False),
        Binding("G", "log_end", "Log end", show=False),
        Binding("f", "log_expand", "Full values", show=False),
    ]

    # ``bindings=True`` re-evaluates ``check_action`` whenever the selection
    # moves, so the footer reflects the newly selected job's capabilities.
    selected_id: reactive[str] = reactive("", bindings=True)
    selected_search_id: reactive[str] = reactive("", bindings=True)

    def __init__(
        self,
        *,
        fetch: Callable[[], dict[str, object] | None],
        port: int,
        interval: float,
        watch_mode: str,
    ) -> None:
        super().__init__()
        if watch_mode not in {"server", "jobs"}:
            raise ValueError("watch_mode must be 'server' or 'jobs'")
        self._fetch = fetch
        self._port = port
        self._interval = interval
        self._watch_mode = watch_mode
        self._jobs: list[dict[str, object]] = []
        self._search = SearchActivityState()
        self._logs = ManagedLogState()
        self._version = ServiceVersion()
        self._signals = MachineSignals()
        self._layout = LayoutMetrics()
        self._pending: dict[str, Pending] = {}
        # Rows the operator deleted, held briefly so the deletion is seen.
        self._tombstones: dict[str, Tombstone] = {}
        # How many jobs the service holds behind the page this view fetches.
        # Without it a deletion is invisible: the next refresh backfills the
        # freed slot from the remainder and the list looks untouched.
        self._total: int | None = None
        # The service's own tally over every record matching the filter, which
        # is the only count that describes more than the page on screen.
        self._summary: object = None
        self._last_refresh: float | None = None
        self._last_error: str | None = None
        # The outcome of the last control, kept in the header until another
        # replaces it. A refusal an operator has to catch inside a toast's
        # lifetime is a refusal they will miss.
        self._last_outcome: tuple[str, str] | None = None
        self._service_estimates = True
        # job id -> (last service estimate in seconds, monotonic stamp of the
        # payload that carried it). Display-side only: between polls the row
        # counts these down linearly, and every applied payload rebuilds the
        # whole map so the countdown snaps to each fresh service value.
        self._estimates: dict[str, tuple[float, float]] = {}
        self._frame = 0
        # Each lane's fetches are stamped and applied newest-first; see
        # ``LaneStamps`` for why completion order cannot be trusted.
        self._job_stamps = LaneStamps()

    def compose(self) -> ComposeResult:
        with Vertical(id="header"):
            yield Static(id="summary")
            yield ServiceStatusBar(id="servicestatus")
        with Horizontal(id="body"):
            with Horizontal(id="lanes"):
                yield DataTable(id="jobs", cursor_type="row", zebra_stripes=True)
                with Vertical(id="searchpane"):
                    yield Static(id="searchtitle")
                    yield DataTable(
                        id="searches", cursor_type="row", zebra_stripes=True
                    )
                    yield Static(id="searchdetail")
            with _LogPane(id="logpane"):
                yield Static("Log", id="logtitle")
                yield JobsLogView(id="joblog")
            with _LogPane(id="managedlogpane"):
                yield Static("Managed logs", id="managedlogtitle")
                yield ManagedLogTankView(id="managedlog")
        yield Footer()

    def on_mount(self) -> None:
        # One palette, two variants. Both are registered and one is active;
        # nothing else is selectable, and no scheme name is ever surfaced.
        for theme in build_themes():
            self.register_theme(theme)
        self.theme = DARK_THEME_NAME
        table = cast("DataTable[Text]", self.query_one("#jobs", DataTable))
        table.border_title = "Indexing jobs"
        for key, label in (
            ("state", "State"),
            ("job", "Job"),
            ("path", "Path"),
            ("progress", "Progress"),
            ("time", "Time"),
        ):
            table.add_column(label, key=key)
        searches = cast("DataTable[Text]", self.query_one("#searches", DataTable))
        searches.border_title = "Served searches"
        for key, label in (
            ("state", "State"),
            ("request", "Request"),
            ("query", "Query"),
            ("time", "Time"),
        ):
            searches.add_column(label, key=key)
        # Status colours resolve from the active theme, so a scheme change
        # must repaint the surfaces that carry them.
        self.theme_changed_signal.subscribe(self, self._on_theme_changed)
        # The table has no width until the first layout pass completes, and
        # dividing zero width would leave every column at its label size.
        self.call_after_refresh(self._relayout)
        # Every beat below reads or paints the screen, so the screen owns
        # them - all of them, including the two later lanes. Shutting down
        # removes the screen and empties the stack behind it before it stops
        # the timers the application itself holds, so a beat owned by the
        # application fires once more with no screen left to read - and an
        # exception raised on a timer callback takes the whole interface down,
        # which reads to an operator as the service having died. Removing a
        # screen stops its timers and waits for them, so ownership here is
        # what makes the beat end with what it paints.
        screen = self.screen
        screen.set_class(self._watch_mode == "jobs", "-jobsfocused")
        screen.set_interval(_SPINNER_INTERVAL, self._tick)
        screen.set_interval(self._interval, self.refresh_jobs)
        screen.set_interval(self._interval, self.refresh_search_activity)
        screen.set_interval(self._interval, self.refresh_managed_logs)
        # The service itself changes far more slowly than its job list, so
        # its beat runs at a multiple of the jobs interval - but the first
        # read happens now, because the header's identity cell is empty
        # until a daemon has answered.
        screen.set_interval(
            self._interval * _STATUS_REFRESH_MULTIPLE, self.refresh_service_status
        )
        self.refresh_service_status()
        self.refresh_jobs()
        self.refresh_search_activity()
        self.refresh_managed_logs()

    def on_resize(self) -> None:
        """Re-divide the columns whenever the terminal changes size."""
        self._relayout()

    def _relayout(self) -> None:
        if self._active_screen() is None:
            return
        self._apply_default_log_visibility()
        if self._layout_columns() and self._jobs:
            self._render_rows()
        if self._layout_search_columns() and self._search.records:
            self._render_searches()

    def _active_screen(self) -> Screen[object] | None:
        """Return the current screen, or ``None`` once teardown removed it.

        Timers may have already queued a callback when Textual clears the
        screen stack.  Those callbacks are presentation work only: they must
        not turn a normal watch shutdown into an operator-visible exception.
        """
        try:
            return self.screen
        except ScreenStackError:
            return None

    def _layout_columns(self) -> bool:
        """Divide the table's own reported width among the column weights.

        Reports whether it re-divided, so a caller only repaints when the
        shares actually moved.

        The width is read from the table rather than taken from whatever
        changed it. A terminal resize, a breakpoint crossing and the log pane
        opening all reach the table a layout pass after the event announcing
        them, so dividing on the event divides the width the table had before -
        which is how the two rightmost columns end up laid out for a full-width
        table and painted into a two-thirds-width one, off the edge of the
        screen. Comparing against the last width divided makes this follow the
        table instead of racing it, at the cost of one integer comparison on
        the frames where nothing moved.
        """
        table = self._table()
        if table is None:
            return False
        padding = table.cell_padding * 2 * len(COLUMN_WEIGHTS)
        # The scrollable content region, not the outer size: the pane's
        # border and any scrollbar come out of the cells the columns can
        # actually paint into, and dividing the outer width lays the last
        # column partly under the frame.
        available = table.scrollable_content_region.width - padding
        # A hidden table reports no width. That is not a new division to
        # record; recording it would skip the real one when it reappears.
        if available <= 0 or table.size.width == self._layout.divided_width:
            return False
        self._layout.divided_width = table.size.width
        total_weight = sum(COLUMN_WEIGHTS.values())
        for key, weight in COLUMN_WEIGHTS.items():
            column = table.columns.get(ColumnKey(key))
            if column is None:
                continue
            column.width = max(MIN_COLUMN_CELLS, int(available * weight / total_weight))
            column.auto_width = False
            self._layout.column_cells[key] = column.width
        # The bar shares its cell with a trailing " 100%", so it takes what
        # the column has left rather than a width of its own.
        self._layout.bar_cells = max(
            0, self._layout.column_cells.get("progress", 0) - len(" 100%")
        )
        return True

    def _cells(self, column: str) -> int:
        """Return the current width of *column*, or zero before layout."""
        return self._layout.column_cells.get(column, 0)

    def _has_screen(self) -> bool:
        """Report whether the interface still has a screen to answer into.

        A widget lookup answers for itself - a query over a torn-down
        composition simply finds nothing - but reading the screen raises
        there, and an exception on a callback delivering an answer is reported
        as the interface having crashed rather than as a request that outlived
        the session that issued it.
        """
        return bool(self.screen_stack)

    def _search_cells(self, column: str) -> int:
        """Return the current width of a served-search column."""
        return self._search.column_cells.get(column, 0)

    def _pane[WidgetT: Widget](
        self, selector: str, kind: type[WidgetT]
    ) -> WidgetT | None:
        """Return the composed widget *selector* names, or ``None``.

        Every pane and table on this screen is reached through here, because
        every one of them needs the same guard. The timers outlive composition
        at both ends: one can fire before the first mount completes and again
        while the screen is being torn down. Composition is likewise not there
        for the whole of a request's life: one issued a moment before the
        session ended is answered after the screen has gone, and that answer
        arrives here.

        The lookup does not raise there. A query issued from the application
        resolves against the screen the application composed on, and that
        screen is held separately from the stack a closing session empties, so
        the lookup comes back empty rather than raising and the empty answer
        is what has to be handled. Reading the screen is the thing that raises,
        which is why nothing on this path does - an exception on a timer
        callback takes the whole interface down, which reads to an operator as
        the service having died. Anything added here that reads the screen
        instead of querying for a widget needs its own answer for the screen
        being gone; a lookup does not.

        Every accessor below binds its own selector and widget type to this
        one rule, so a pane added later cannot acquire a different answer for
        a screen that has gone.
        """
        found = self.query(selector)
        if not found:
            return None
        return found.only_one(kind)

    def _table(self) -> DataTable[Text] | None:
        """Return the indexing table, or ``None`` when it is not mounted."""
        return cast("DataTable[Text] | None", self._pane("#jobs", DataTable))

    def _search_table(self) -> DataTable[Text] | None:
        """Return the served-search table, or ``None`` before composition."""
        return cast("DataTable[Text] | None", self._pane("#searches", DataTable))

    def _layout_search_columns(self) -> bool:
        """Divide the served-search table against its actual current width."""
        table = self._search_table()
        if table is None:
            return False
        padding = table.cell_padding * 2 * len(SEARCH_COLUMN_WEIGHTS)
        available = table.scrollable_content_region.width - padding
        if available <= 0:
            return False
        total_weight = sum(SEARCH_COLUMN_WEIGHTS.values())
        changed = False
        for key, weight in SEARCH_COLUMN_WEIGHTS.items():
            column = table.columns.get(ColumnKey(key))
            if column is None:
                continue
            width = max(MIN_COLUMN_CELLS, int(available * weight / total_weight))
            if column.width != width:
                changed = True
            column.width = width
            column.auto_width = False
            self._search.column_cells[key] = width
        return changed

    def _tick(self) -> None:
        """Advance whatever is genuinely moving, and nothing else.

        Also the one callback guaranteed to run after every layout pass,
        whatever caused it, so it is where the table's width is re-read; see
        ``_layout_columns`` for why the width cannot be taken from the event
        that changed it.
        """
        if self._active_screen() is None:
            return
        self._relayout()
        if self._expire_tombstones():
            self._render_rows()
        elif self._animating():
            self._frame = (self._frame + 1) % len(_SPINNER_FRAMES)
            self._repaint_animated_cells()
        self._render_summary()

    def _busy(self) -> bool:
        """Report whether a request this view issued is still outstanding.

        Read from the worker registry rather than from a counter this code
        raises and lowers. A counter drifts: an exclusive poll cancels the one
        before it, and a worker cancelled before its body ran never reaches the
        callback that would lower the count. The header would then animate for
        the rest of the session over a view where nothing is happening, which
        is the exact defect the still glyph exists to remove.
        """
        return any(
            worker.group in _REQUEST_GROUPS and worker.state in _ACTIVE_WORKER_STATES
            for worker in self.workers
        )

    def _animating(self) -> bool:
        return self._busy() or any(row_animates(job) for job in self._jobs)

    def _header_glyph(self) -> str:
        return _SPINNER_FRAMES[self._frame] if self._busy() else _SETTLED_GLYPH

    def _expire_tombstones(self) -> bool:
        """Drop deleted rows whose time on screen is up."""
        if not self._tombstones:
            return False
        now = time.monotonic()
        expired = [key for key, stone in self._tombstones.items() if stone.until <= now]
        for key in expired:
            del self._tombstones[key]
        return bool(expired)

    def _repaint_animated_cells(self) -> None:
        # Only the animated cells change between frames; repainting every row
        # ten times a second would burn the terminal for a glyph.
        table = self._table()
        if table is None:
            return
        paint = PaintContext(_SPINNER_FRAMES[self._frame], semantic_tones(self.theme))
        for job in self._jobs:
            job_id = job_id_of(job)
            if row_animates(job) and job_id in table.rows:
                table.update_cell(
                    job_id,
                    "state",
                    state_cell(
                        job, paint, self._pending.get(job_id), self._cells("state")
                    ),
                )
                # The countdown only moves between polls if this repaint
                # carries it; the same moving rows the glyph animates are
                # exactly the ones whose estimate is allowed to tick.
                table.update_cell(
                    job_id,
                    "time",
                    time_cell(
                        job, self._cells("time"), ticked=self._ticked_remaining(job)
                    ),
                )

    # -- data ---------------------------------------------------------------

    def refresh_jobs(self) -> None:
        """Issue a stamped fetch. The stamp is what orders the answers."""
        self._fetch_jobs(self._job_stamps.issue())

    @work(thread=True, exclusive=True, group=_REFRESH_GROUP)
    def _fetch_jobs(self, generation: int) -> None:
        """Fetch on a worker thread; the transport is blocking HTTP."""
        result = self._fetch()
        self.call_from_thread(self._apply_result, result, generation)

    def refresh_search_activity(self) -> None:
        """Issue an independent bounded served-search snapshot."""
        self._fetch_search_activity(self._search.stamps.issue())

    @work(thread=True, exclusive=True, group=_SEARCH_ACTIVITY_GROUP)
    def _fetch_search_activity(self, generation: int) -> None:
        """Read active and recent served searches through the admin boundary."""
        result = _try_http_admin(
            "get_search_activity",
            {"limit": SEARCH_ACTIVITY_LIMIT},
            self._port,
        )
        self.call_from_thread(self._apply_search_activity, result, generation)

    def _apply_search_activity(
        self,
        result: dict[str, object] | None,
        generation: int,
    ) -> None:
        """Apply a newer authenticated search projection without touching jobs."""
        if not self._search.stamps.accept(generation):
            return
        error = search_activity_error(result)
        if error is not None:
            self._search.error = error
            self._render_search_title()
            self._render_summary()
            return
        # search_activity_error returns non-None whenever result is None, so
        # reaching here means result is the dict.
        payload = cast("dict[str, object]", result)
        active = search_records(payload.get("active"), "active")
        recent = search_records(payload.get("recent"), "terminal")
        self._search.records = active + recent
        # search_activity_error (via _search_activity_payload_error) already
        # confirmed "counts" is a dict before returning None.
        counts = cast("dict[str, object]", payload["counts"])
        self._search.counts = {
            name: count(counts.get(name)) or 0 for name in ("active", "recent", "total")
        }
        # Counts are computed over every record; the rows are the bounded
        # projection. Keeping the served figure is what lets the title say so.
        self._search.returned = count(payload.get("returned")) or 0
        self._search.error = None
        self._search.last_refresh = time.time()
        self._layout_search_columns()
        self._render_searches()
        self._render_search_title()
        self._render_summary()

    def refresh_managed_logs(self) -> None:
        """Issue an ordered all-source log snapshot on its own worker group."""
        self._fetch_managed_logs(self._logs.stamps.issue())

    @work(thread=True, exclusive=True, group=_MANAGED_LOG_GROUP)
    def _fetch_managed_logs(self, generation: int) -> None:
        """Fetch the bounded raw service and Qdrant log groups independently."""
        result = _try_http_admin(
            "get_logs",
            {"lines": MAX_MANAGED_LOG_LINES, "source": "all"},
            self._port,
        )
        self.call_from_thread(self._apply_managed_logs, result, generation)

    def _apply_managed_logs(
        self,
        result: dict[str, object] | None,
        generation: int,
    ) -> None:
        """Accept only the exact grouped managed-log transport contract."""
        if not self._logs.stamps.accept(generation):
            return
        if result is None or result.get("ok") is False:
            self._logs.error = "the service did not answer"
            self._clear_managed_logs(
                "Managed logs unavailable: the service did not answer."
            )
            return
        groups = validate_managed_log_payload(
            result,
            source="all",
            limit=MAX_MANAGED_LOG_LINES,
            filters={},
        )
        if groups is None:
            self._logs.error = "the service returned an invalid response"
            self._clear_managed_logs(
                "Managed logs unavailable: the service returned an invalid response."
            )
            return
        tank = self._managed_log_view()
        if tank is None:
            return
        tank.show_groups(groups)
        self._logs.error = None
        self._logs.last_refresh = time.time()
        self._refresh_managed_log_title()

    @work(thread=True, exclusive=True, group=_STATUS_GROUP)
    def refresh_service_status(self) -> None:
        """Poll what the service *is*, beside what it is doing.

        Never raises: an unreachable or older service returns a result whose
        unlearnable fields are ``None``, and the header renders those as absent
        rather than as zero.
        """
        result = fetch_service_status(self._port)
        self.call_from_thread(self._apply_service_status, result)

    def _apply_service_status(self, result: ServiceStatusHeader) -> None:
        if result.reachable:
            # Only a daemon that answered can say which daemon it is; an
            # unreachable beat keeps the last learned identity beside the
            # staleness the header already reports.
            self._version.value = result.version
            self._version.checked = True
        bar = self.query("#servicestatus")
        if bar:
            bar.only_one(ServiceStatusBar).show(result)

    def _apply_result(self, result: dict[str, object] | None, generation: int) -> None:
        if not self._has_screen():
            # A poll that was in flight when the session ended. A blocking
            # transport call cannot be cancelled, so its answer arrives
            # whatever became of the interface meanwhile, and there is no
            # longer anything to apply it to.
            return
        if not self._job_stamps.accept(generation):
            # A slower fetch that the newest applied one already superseded.
            # Its payload predates what is on screen.
            return
        error = fetch_error_text(result)
        if error is not None:
            # The rows already on screen are the last thing the service is
            # known to have said, so they stay; what changes is that the view
            # now says it is not hearing back. Overwriting them with the empty
            # list an error envelope carries would render a wedged daemon as
            # "no jobs, refreshed just now" - which is the most misleading
            # frame this interface can paint.
            self._last_error = error
            self._render_summary()
            return
        # fetch_error_text returns non-None whenever result is None, so reaching
        # here means result is the dict.
        payload = cast("dict[str, object]", result)
        raw_jobs = payload.get("jobs")
        previous = self._jobs
        entries = cast("list[object]", raw_jobs) if isinstance(raw_jobs, list) else []
        jobs = [
            cast("dict[str, object]", job)
            for job in entries
            if isinstance(job, dict)
            # A record with no id cannot be addressed, and two of them collide
            # on the table's row key and take the interface down.
            and job_id_of(cast("dict[str, object]", job))
        ]
        self._last_error = None
        self._last_refresh = time.time()
        # A service that publishes the key for no job at all predates the
        # estimate. Saying so once beats every row reading as unmeasurable.
        self._service_estimates = not jobs or any(ESTIMATE_KEY in job for job in jobs)
        self._record_estimates(jobs)
        self._jobs = jobs
        self._total = count(payload.get("total"))
        self._summary = payload.get("summary")
        self._signals.gpu_reported = "gpu" in payload
        raw_gpu = payload.get("gpu")
        self._signals.gpu = (
            cast("dict[str, object]", raw_gpu) if isinstance(raw_gpu, dict) else None
        )
        raw_pressure = payload.get("pressure")
        self._signals.pressure = (
            cast("dict[str, object]", raw_pressure)
            if isinstance(raw_pressure, dict)
            else None
        )
        self._signals.quiesce_reported = "quiesce" in payload
        self._signals.quiesce = canonical_quiesce_block(payload.get("quiesce"))
        self._reconcile_pending(generation, previous)
        self._layout_columns()
        self._render_rows()
        self._render_summary()
        # Capabilities can flip under a refresh, and the footer only
        # re-evaluates when the selection moves.
        self.refresh_bindings()

    def _record_estimates(self, jobs: list[dict[str, object]]) -> None:
        """Stamp each published estimate for display-side tick-down.

        Rebuilt whole from every applied payload: a job whose fresh record
        carries no numeric estimate loses its entry, so a countdown never
        keeps falling from a number the service has stopped standing behind.
        """
        now = time.monotonic()
        estimates: dict[str, tuple[float, float]] = {}
        for job in jobs:
            value = measurement(job.get(ESTIMATE_KEY))
            if value is not None:
                estimates[job_id_of(job)] = (value, now)
        self._estimates = estimates

    def _ticked_remaining(self, job: dict[str, object]) -> float | None:
        """Count the last service estimate down by the seconds since it landed.

        Presentation only: the service owns the estimate; this subtracts wall
        time from it between polls and clamps at zero, and every applied
        payload replaces the entry so the display snaps to each fresh value.
        Gated on the row actually moving - ticking a countdown over stalled
        or waiting work would claim motion the view has no evidence for.
        """
        entry = self._estimates.get(job_id_of(job))
        if entry is None or not row_animates(job):
            return None
        remaining, stamped_at = entry
        return max(0.0, remaining - (time.monotonic() - stamped_at))

    def _reconcile_pending(
        self,
        generation: int,
        previous: list[dict[str, object]],
    ) -> None:
        """Settle each outstanding control against what the service now says.

        A marker survives until a payload *fetched after the control landed*
        carries the transition. Clearing it because any refresh arrived erases
        the request during exactly the window it exists to describe - and with
        several polls outstanding at once, the refresh that arrives first is
        routinely one issued before the mutation, so the marker vanishes
        against state that predates it.

        A refusal is not settled at all. It stays on the row until the operator
        issues another control there or the job leaves the list, because a
        refusal that expires on a timer is one the operator never sees.
        """
        by_id = {job_id_of(job): job for job in self._jobs}
        for job_id, marker in list(self._pending.items()):
            if marker.outcome != "sent":
                # In flight, or an answered failure being held for reading.
                if marker.outcome != "requested" and job_id not in by_id:
                    del self._pending[job_id]
                continue
            if generation <= marker.settled_after:
                continue
            job = by_id.get(job_id)
            if job is None:
                # Absent from a list fetched after the control landed is the
                # service confirming a removal.
                del self._pending[job_id]
                if marker.action == "delete":
                    self._entomb(job_id, previous)
                continue
            if marker.expected is None or job.get("desired_state") == marker.expected:
                del self._pending[job_id]

    def _entomb(self, job_id: str, previous: list[dict[str, object]]) -> None:
        """Hold a deleted row on screen, where it was, long enough to see."""
        for index, job in enumerate(previous):
            if job_id_of(job) == job_id:
                self._tombstones[job_id] = Tombstone(
                    job, index, time.monotonic() + _TOMBSTONE_SECONDS
                )
                return

    def _visible_rows(self) -> list[tuple[dict[str, object], bool]]:
        """Return the rows to paint: the service's list, plus what just left.

        A deleted row keeps its place for a few seconds so the operator sees
        which one went. Reading the list straight from the service instead
        would have the freed slot backfilled from the remainder before the
        next frame, leaving nothing on screen that changed.
        """
        rows: list[tuple[dict[str, object], bool]] = [
            (job, False) for job in self._jobs
        ]
        for stone in sorted(self._tombstones.values(), key=lambda s: s.position):
            rows.insert(min(stone.position, len(rows)), (stone.job, True))
        return rows

    def _render_rows(self) -> None:
        table = self._table()
        if table is None:
            return
        frame = _SPINNER_FRAMES[self._frame]
        rows = self._visible_rows()
        wanted = [job_id_of(job) for job, _deleted in rows]
        if [key.value for key in table.rows] != wanted:
            self._rebuild_rows(table, rows, wanted, frame)
        else:
            for job, deleted in rows:
                self._update_row(table, job, frame, deleted=deleted)
        self._sync_selection(table)

    def _rebuild_rows(
        self,
        table: DataTable[Text],
        rows: list[tuple[dict[str, object], bool]],
        wanted: list[str],
        frame: str,
    ) -> None:
        """Repopulate the table, keeping the cursor on the same job.

        Restoring the cursor to the row *index* it held would move the
        selection onto a different job whenever one above it disappears - and
        because a control key acts on whatever is selected, the next press
        would then be aimed at work the operator never chose. The id is what
        the operator selected, so the id is what is restored; the index is only
        the fallback for a job that is genuinely gone.
        """
        previous = self.selected_id
        cursor = table.cursor_row
        table.clear()
        for job, deleted in rows:
            self._add_row(table, job, frame, deleted=deleted)
        if table.row_count == 0:
            return
        row = (
            wanted.index(previous)
            if previous in wanted
            else min(max(0, cursor), table.row_count - 1)
        )
        table.move_cursor(row=row)

    def _add_row(
        self,
        table: DataTable[Text],
        job: dict[str, object],
        frame: str,
        *,
        deleted: bool = False,
    ) -> None:
        job_id = job_id_of(job)
        tones = semantic_tones(self.theme)
        table.add_row(
            state_cell(
                job,
                PaintContext(frame, tones),
                self._pending.get(job_id),
                self._cells("state"),
                deleted=deleted,
            ),
            job_cell(job, self._cells("job")),
            path_cell(job, self._cells("path")),
            progress_cell(job, self._cells("progress"), self._layout.bar_cells, tones),
            time_cell(job, self._cells("time"), ticked=self._ticked_remaining(job)),
            height=2,
            key=job_id,
        )

    def _update_row(
        self,
        table: DataTable[Text],
        job: dict[str, object],
        frame: str,
        *,
        deleted: bool = False,
    ) -> None:
        job_id = job_id_of(job)
        tones = semantic_tones(self.theme)
        cells = {
            "state": state_cell(
                job,
                PaintContext(frame, tones),
                self._pending.get(job_id),
                self._cells("state"),
                deleted=deleted,
            ),
            "job": job_cell(job, self._cells("job")),
            "path": path_cell(job, self._cells("path")),
            "progress": progress_cell(
                job, self._cells("progress"), self._layout.bar_cells, tones
            ),
            "time": time_cell(
                job, self._cells("time"), ticked=self._ticked_remaining(job)
            ),
        }
        for column, value in cells.items():
            table.update_cell(job_id, column, value)

    def _render_searches(self) -> None:
        """Render the active lane before the recent terminal lane."""
        table = self._search_table()
        if table is None:
            return
        wanted = [search_id(search) for search in self._search.records]
        if [key.value for key in table.rows] != wanted:
            previous = self.selected_search_id
            cursor = table.cursor_row
            table.clear()
            for search in self._search.records:
                self._add_search_row(table, search)
            if table.row_count:
                row = (
                    wanted.index(previous)
                    if previous in wanted
                    else min(max(0, cursor), table.row_count - 1)
                )
                table.move_cursor(row=row)
        else:
            for search in self._search.records:
                self._update_search_row(table, search)
        self._sync_search_selection(table)

    def _add_search_row(
        self, table: DataTable[Text], search: dict[str, object]
    ) -> None:
        tones = semantic_tones(self.theme)
        table.add_row(
            search_state_cell(search, self._search_cells("state"), tones),
            search_request_cell(search, self._search_cells("request")),
            search_query_cell(search, self._search_cells("query")),
            search_time_cell(search, self._search_cells("time")),
            height=2,
            key=search_id(search),
        )

    def _update_search_row(
        self, table: DataTable[Text], search: dict[str, object]
    ) -> None:
        tones = semantic_tones(self.theme)
        cells = {
            "state": search_state_cell(search, self._search_cells("state"), tones),
            "request": search_request_cell(search, self._search_cells("request")),
            "query": search_query_cell(search, self._search_cells("query")),
            "time": search_time_cell(search, self._search_cells("time")),
        }
        for column, value in cells.items():
            table.update_cell(search_id(search), column, value)

    def _sync_search_selection(self, table: DataTable[Text]) -> None:
        if table.row_count == 0:
            self.selected_search_id = ""
            self._render_search_detail()
            return
        row = min(table.cursor_row, table.row_count - 1)
        self.selected_search_id = list(table.rows.keys())[row].value or ""

    def selected_search(self) -> dict[str, object] | None:
        """Return the currently selected served-search activity record."""
        return find_record(self._search.records, search_id, self.selected_search_id)

    def watch_selected_search_id(self, _request_id: str) -> None:
        self._render_search_detail()

    def _render_search_title(self) -> None:
        found = self.query("#searchtitle")
        if not found:
            return
        active = self._search.counts.get("active", 0)
        recent = self._search.counts.get("recent", 0)
        title = Text(f"Served searches · {active} active · {recent} recent")
        # The counts above cover every record the service holds; the table
        # holds the bounded projection. Without this an operator scrolls to
        # the end of 100 rows and concludes they have seen all 300.
        total = self._search.counts.get("total", 0)
        if 0 < self._search.returned < total:
            title.append(
                f" · showing {self._search.returned} of {total}",
                style="dim",
            )
        if self._search.last_refresh is not None:
            stamp = time.strftime("%H:%M:%S", time.localtime(self._search.last_refresh))
            title.append(f" · refreshed {stamp}", style="dim")
        if self._search.error is not None:
            title.append(
                f" · {self._search.error}",
                style=semantic_tones(self.theme)["bad"],
            )
        title.append(" · r refreshes · s switches lane", style="dim")
        found.only_one(Static).update(title)
        self._render_search_detail()

    def _render_search_detail(self) -> None:
        found = self.query("#searchdetail")
        if not found:
            return
        search = self.selected_search()
        if search is None:
            found.only_one(Static).update("No served search selected.")
            return
        query = search_text(search.get("query"), fallback="query unavailable")
        detail = Text(f"query: {query}")
        detail.append(f"\n{search_identity_line(search)}", style="dim")
        detail.append(f"\n{search_outcome_line(search)}", style="dim")
        detail.append(f"\n{search_clock_line(search)}", style="dim")
        timings = search_timings_line(search)
        if timings:
            detail.append(f"\n{timings}", style="dim")
        failure = search_failure_line(search)
        if failure:
            detail.append(
                f"\n{failure}",
                style=tone_style(semantic_tones(self.theme), "bad"),
            )
        found.only_one(Static).update(detail)

    def _sync_selection(self, table: DataTable[Text]) -> None:
        if table.row_count == 0:
            self.selected_id = ""
            # Nothing is selected, so the pane must stop claiming to show a
            # job's log. Leaving the last one there attributes those lines to
            # work that is no longer listed.
            self._clear_log("No job selected.")
            return
        row = min(table.cursor_row, table.row_count - 1)
        # ``str`` on a row key gives its repr, not the id it carries.
        job_id = list(table.rows.keys())[row].value or ""
        if job_id != self.selected_id:
            self.selected_id = job_id

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        # A highlight that named a removed row is superseded rather than
        # filtered: rebuilding the table raises its own highlight afterwards,
        # and ``_sync_selection`` sets the id from the rows that survived. A
        # membership test here would be unreachable, and an id that did somehow
        # go stale is answered by the refusal every action already reports.
        table = cast("DataTable[Text]", event.data_table)
        if table.id == "searches":
            self.selected_search_id = str(event.row_key.value or "")
            return
        if table.id == "jobs":
            self.selected_id = str(event.row_key.value or "")

    def watch_selected_id(self, job_id: str) -> None:
        if not job_id:
            return
        if not self.query("#logtitle"):
            return
        self._refresh_log_title()
        self.fetch_logs(job_id)

    @work(thread=True, exclusive=True, group=_LOG_GROUP)
    def fetch_logs(self, job_id: str) -> None:
        result = _try_http_admin(
            "get_logs",
            {"lines": _LOG_LINES, "source": "service", "job_id": job_id},
            self._port,
        )
        self.call_from_thread(self._apply_logs, job_id, result)

    def _apply_logs(self, job_id: str, result: dict[str, object] | None) -> None:
        if job_id != self.selected_id:
            return
        if result is None or result.get("ok") is False:
            self._clear_log("Logs unavailable: the service did not answer.")
            return
        log = self._log_view()
        if log is None:
            return
        log.show_lines(log_lines(result))
        # The window just changed, so what the noise filter hides and where
        # the errors sit changed with it - both the title's indicator and the
        # error-jump keys in the footer have to follow.
        self._refresh_log_title()
        self.refresh_bindings()

    def _log_view(self) -> JobsLogView | None:
        """Return the log pane's body, or ``None`` when it is not mounted."""
        return self._pane("#joblog", JobsLogView)

    def _refresh_log_title(self) -> None:
        """Repaint the pane's title: whose log, and what is being hidden.

        The noise filter must be visible whenever it is active. Lines
        silently missing from a log pane read as lines that never happened,
        which is precisely the degradation an operator cannot detect.
        """
        found = self.query("#logtitle")
        if not found:
            return
        title = Text(f"Log · {self.selected_id[:8]}" if self.selected_id else "Log")
        log = self._log_view()
        if log is not None:
            hidden = log.hidden_polling_count
            if hidden:
                title.append(
                    f"  ·  {hidden} polling hidden (x shows)",
                    style=semantic_tones(self.theme)["attention"],
                )
            elif log.polling_shown and log.polling_count:
                title.append("  ·  polling shown (x hides)", style="dim")
        found.only_one(Static).update(title)

    def _clear_log(self, message: str) -> None:
        """Replace the log pane's body with *message* and re-title it."""
        self._refresh_log_title()
        log = self._log_view()
        if log is not None:
            log.show_message(message)

    def _managed_log_view(self) -> ManagedLogTankView | None:
        """Return the global raw-log tank, or ``None`` before composition."""
        return self._pane("#managedlog", ManagedLogTankView)

    def _refresh_managed_log_title(self) -> None:
        """Say what the tank holds, when it last refreshed, and how to leave.

        The title is the only place the grouping is stated: records are shown
        exactly as each producer wrote them, never merged into an inferred
        cross-producer timeline.
        """
        found = self.query("#managedlogtitle")
        if not found:
            return
        title = Text("Managed log tank · raw service + qdrant")
        if self._logs.last_refresh is not None:
            stamp = time.strftime("%H:%M:%S", time.localtime(self._logs.last_refresh))
            title.append(f" · refreshed {stamp}", style="dim")
        if self._logs.error is not None:
            title.append(
                f" · {self._logs.error}",
                style=semantic_tones(self.theme)["bad"],
            )
        title.append(" · r refreshes · m returns to watch", style="dim")
        found.only_one(Static).update(title)

    def _clear_managed_logs(self, message: str) -> None:
        """Show a global-log fetch failure without disturbing the jobs pane."""
        tank = self._managed_log_view()
        if tank is not None:
            tank.show_message(message)
        self._refresh_managed_log_title()

    # -- actions ------------------------------------------------------------

    def selected_job(self) -> dict[str, object] | None:
        """Return the currently selected indexing-job record."""
        return find_record(self._jobs, job_id_of, self.selected_id)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Disable a row action the selected job does not permit.

        Returning ``None`` greys the key in the footer rather than hiding it,
        so the operator can see the control exists and that this job cannot
        take it.
        """
        # Named to match the override; these actions take no parameters.
        del parameters
        if action == "toggle_search":
            return True
        if action.startswith("log_"):
            return self._check_log_action(action)
        flag = action_capability(action)
        if flag is None:
            return True
        if not self._job_action_context_available():
            return None
        job = self.selected_job()
        if job is None or not capability_flag(job, flag):
            return None
        return True

    def _job_action_context_available(self) -> bool:
        """Whether a job mutation still names the visible indexing lane.

        A search-row selection intentionally leaves ``selected_id`` intact so
        returning to indexing restores its row. That retained id must not turn
        a served-search keypress into a control request for the now-hidden job.
        The same applies to the full-height managed log tank: it preserves
        selection for return, not for mutation while the jobs lane is absent.
        """
        if self._managed_log_visible():
            return False
        searches = self._search_table()
        if self.focused is searches:
            return False
        # In jobs watch, opening search always replaces the indexing lane. In
        # server watch it does so below the split breakpoint. Check the classes
        # as well as ``display`` because an action may arrive in the layout turn
        # immediately after the switch, before the widget recomputes display.
        if self._search_visible() and (self._watch_mode == "jobs" or not self._wide()):
            return False
        table = self._table()
        return table is not None and table.display

    def _check_log_action(self, action: str) -> bool | None:
        """Disable a log action the pane cannot take right now.

        Every log action needs the pane on screen; the error jumps also need
        an error to jump to. ``None`` greys the key rather than hiding it,
        the same reading the row actions already use.
        """
        if not self._log_visible():
            return None
        if action in ("log_next_error", "log_prev_error"):
            log = self._log_view()
            if log is None or log.error_count == 0:
                return None
        return True

    def on_key(self, event: events.Key) -> None:
        """Answer a press that lands on an action the selected job refuses.

        A disabled binding is never invoked - ``check_action`` returning
        ``None`` greys the footer entry and stops the action there - so without
        this the key produces nothing at all. Silence reads as a broken
        interface; a refusal with its reason reads as an answer. This handler
        runs only once the binding declined the key, so a permitted action is
        untouched.
        """
        action = ACTION_KEYS.get(event.key)
        if action is None or self.check_action(action, ()) is True:
            return
        event.stop()
        event.prevent_default()
        self.notify(self._refusal(action), severity="warning")

    def _refusal(self, action: str) -> str:
        """Say why *action* is unavailable, in the operator's terms."""
        if action.startswith("log_"):
            if not self._log_visible():
                return LOG_CLOSED_REASON
            return ACTION_REASONS.get(
                action, "The log cannot take that action right now."
            )
        if (
            action_capability(action) is not None
            and not self._job_action_context_available()
        ):
            return "Select an indexing job before sending a job action."
        if self.selected_job() is None:
            return "No job is selected."
        return ACTION_REASONS.get(action, "This job cannot take that action.")

    def action_toggle_theme(self) -> None:
        """Flip between the dark and light variants of the one palette."""
        self.theme = (
            LIGHT_THEME_NAME if self.theme == DARK_THEME_NAME else DARK_THEME_NAME
        )

    def _on_theme_changed(self, _theme: object) -> None:
        """Repaint the tone-carrying surfaces under the new variant."""
        self._render_summary()
        self._render_rows()
        self._render_searches()
        self._render_search_title()
        log = self._log_view()
        if log is not None:
            log.repaint_theme()
        tank = self._managed_log_view()
        if tank is not None:
            tank.repaint_theme()

    def action_toggle_zoom(self) -> None:
        """Fill the screen with the focused pane, or restore the split.

        The zoom follows the focus ring: whichever pane's frame is lit is
        the one that grows, so the two answers to "where am I" and "what
        will z do" are the same answer. A pane that cannot be maximized
        answers the press rather than ignoring it.
        """
        if self.screen.maximized is not None:
            self.screen.minimize()
            return
        focused = self.focused
        if focused is None or not self.screen.maximize(focused):
            self.notify("This pane cannot be zoomed.", severity="warning")

    def action_toggle_log(self) -> None:
        # One state, applied the same way in both layouts, so the key always
        # does something: the width decides only whether showing the log
        # splits the screen or takes it over.
        self._logs.show = not self._log_visible()
        self.screen.set_class(self._logs.show, "-showlog")
        # The log keys gate on the pane being on screen, and the footer only
        # re-evaluates them when told to.
        self.refresh_bindings()

    def action_toggle_search(self) -> None:
        """Select the served-search lane without replacing its snapshot."""
        if self._managed_log_visible():
            self.action_toggle_managed_logs()
        if self._watch_mode == "jobs" and self._log_visible():
            self._logs.show = False
            self.screen.set_class(False, "-showlog")
        if self._wide() and self._watch_mode == "server":
            table = self._search_table()
            if table is not None:
                table.focus()
            self.refresh_bindings()
            return
        show_search = not self._search_visible()
        self.screen.set_class(show_search, "-showsearch")
        if show_search:
            table = self._search_table()
            if table is not None:
                table.focus()
        else:
            table = self._table()
            if table is not None:
                table.focus()
        self.refresh_bindings()

    def action_toggle_managed_logs(self) -> None:
        """Move between jobs and the full-height tank of raw grouped records."""
        show_tank = not self._managed_log_visible()
        self.screen.set_class(show_tank, "-showmanagedlogs")
        if show_tank:
            self._refresh_managed_log_title()
            tank = self._managed_log_view()
            if tank is not None:
                tank.focus()
            self.refresh_managed_logs()
        else:
            table = self._table()
            if table is not None:
                table.focus()
        self.refresh_bindings()

    def action_log_noise(self) -> None:
        """Toggle the polling-noise filter, and say so in the title."""
        log = self._log_view()
        if log is None:
            return
        log.toggle_polling()
        self._refresh_log_title()
        self.refresh_bindings()

    def _drive_log(self, drive: Callable[[JobsLogView], object]) -> None:
        """Run one log-view motion when the view exists; refuse silently else."""
        log = self._log_view()
        if log is not None:
            drive(log)

    def action_log_expand(self) -> None:
        """Toggle full values in place of middle-elided ones."""
        self._drive_log(JobsLogView.toggle_expanded)

    def action_log_next_error(self) -> None:
        self._drive_log(JobsLogView.jump_next_error)

    def action_log_prev_error(self) -> None:
        self._drive_log(JobsLogView.jump_previous_error)

    def action_log_top(self) -> None:
        self._drive_log(JobsLogView.jump_top)

    def action_log_end(self) -> None:
        self._drive_log(JobsLogView.jump_end)

    def _log_visible(self) -> bool:
        return self.screen.has_class("-showlog")

    def _search_visible(self) -> bool:
        if self._wide() and self._watch_mode == "server":
            return True
        return self.screen.has_class("-showsearch")

    def _managed_log_visible(self) -> bool:
        return self.screen.has_class("-showmanagedlogs")

    def _apply_default_log_visibility(self) -> None:
        """Show the log by default only where it can sit beside the table.

        A wide terminal has room for both, so the log is there from the start.
        A narrow one does not, and opening over the job list before the
        operator asked for it would hide the thing they came to see. Once they
        have chosen, the choice survives every later resize.
        """
        screen = self._active_screen()
        if self._logs.show is None and screen is not None:
            screen.set_class(self._watch_mode == "jobs" and self._wide(), "-showlog")

    def _wide(self) -> bool:
        return self.screen.has_class("-wide")

    def action_refresh_now(self) -> None:
        self.refresh_jobs()
        self.refresh_search_activity()
        self.refresh_managed_logs()

    def action_job_pause(self) -> None:
        self._request_state("pause")

    def action_job_resume(self) -> None:
        self._request_state("resume")

    def action_job_stop(self) -> None:
        self._request_state("stop")

    def _request_state(self, action: str) -> None:
        job = self._actionable(action)
        if job is None:
            return
        revision = job_revision(job)
        if revision is None:
            self.notify("The service reported no revision for this job.")
            return
        flag, desired = STATE_ACTIONS[action]
        del flag
        self._mark_pending(job, action, expected=desired.value)
        self._send_state(job_id_of(job), desired, revision, action)

    @work(thread=True, group=_CONTROL_GROUP)
    def _send_state(
        self,
        job_id: str,
        desired: DesiredJobState,
        revision: int,
        action: str,
    ) -> None:
        result = _try_http_set_job_desired_state(
            job_id,
            desired,
            self._port,
            expected_revision=revision,
            mode="graceful",
        )
        self.call_from_thread(self._after_control, job_id, action, result)

    def action_job_retry(self) -> None:
        self._request_send("retry", self._send_retry)

    @work(thread=True, group=_CONTROL_GROUP)
    def _send_retry(self, job_id: str) -> None:
        result = _try_http_retry_job(
            job_id,
            self._port,
            initiator_kind="cli",
            command="server_job_retry",
        )
        self.call_from_thread(self._after_control, job_id, "retry", result)

    def action_job_delete(self) -> None:
        self._request_send("delete", self._send_delete)

    @work(thread=True, group=_CONTROL_GROUP)
    def _send_delete(self, job_id: str) -> None:
        result = _try_http_delete_job(job_id, self._port)
        self.call_from_thread(self._after_control, job_id, "delete", result)

    def _request_send(self, action: str, send: Callable[[str], object]) -> None:
        """Mark the selected job pending for *action*, then hand it to *send*.

        The state transitions go through ``_request_state`` instead: they carry
        a revision and an expected state, which this shape has no place for.
        """
        job = self._actionable(action)
        if job is not None:
            self._mark_pending(job, action)
            send(job_id_of(job))

    def _actionable(self, action: str) -> dict[str, object] | None:
        """Return the selected job when it permits *action*, else ``None``.

        The footer already greys a disallowed key, but a binding can still
        fire; this is the check that makes the refusal real rather than
        cosmetic, so no request is sent for a capability the service denies.

        The refusal is reported here as well as at the key, because this is the
        gate an action reaching the method by any other route still meets - and
        a refused request that says nothing is indistinguishable from one that
        was sent and lost.
        """
        flag = action_capability(f"job_{action}")
        if not self._job_action_context_available():
            self.notify(self._refusal(f"job_{action}"), severity="warning")
            return None
        job = self.selected_job()
        if job is None or flag is None or not capability_flag(job, flag):
            self.notify(self._refusal(f"job_{action}"), severity="warning")
            return None
        return job

    def _mark_pending(
        self,
        job: dict[str, object],
        action: str,
        expected: str | None = None,
    ) -> None:
        """Put the request on the row before it leaves the interface.

        The row changes on the keystroke, not on the answer. The gap between
        the two is the whole window in which an operator decides whether
        anything is wired up at all.
        """
        self._pending[job_id_of(job)] = Pending(
            action, expected, "requested", "", self._job_stamps.issued
        )
        self._render_rows()

    def _after_control(
        self,
        job_id: str,
        action: str,
        result: dict[str, object] | None,
    ) -> None:
        short = job_id[:8] or "job"
        if result is None:
            self._settle(
                job_id, "refused", f"{action} failed: the service is not reachable."
            )
        elif is_gone(result):
            # Not a generic failure: the view was addressing a job the service
            # has dropped. The answer is a corrected list and a plain sentence,
            # never a raw error.
            self._settle(
                job_id,
                "gone",
                f"{action}: {short} is no longer on the service - list refreshed.",
            )
        elif result.get("ok") is not True:
            message = result.get("message")
            self._settle(
                job_id,
                "refused",
                f"{action} refused: {message}"
                if isinstance(message, str)
                else f"{action} was refused by the service.",
            )
        else:
            # Accepted is not yet done. The row keeps saying so until the
            # service's own payload carries the transition, because a control
            # that reports success and leaves the row unchanged is exactly what
            # reads as nothing having been wired up.
            self._settle(
                job_id, "sent", f"{action} accepted for {short}; awaiting the service."
            )
        self._render_rows()
        self.refresh_jobs()

    def _settle(self, job_id: str, outcome: str, detail: str) -> None:
        """Record where a control got to, on the row and in the header."""
        marker = self._pending.get(job_id)
        self._pending[job_id] = Pending(
            marker.action if marker is not None else "control",
            marker.expected if marker is not None else None,
            outcome,
            detail,
            # Only a fetch issued after this point can carry the mutation, and
            # ``refresh_jobs`` below takes the next stamp.
            self._job_stamps.issued,
        )
        failed = outcome in {"refused", "gone"}
        # The tone token, not a resolved style: the outcome outlives theme
        # flips, so its colour is resolved at each render, never stored.
        self._last_outcome = (detail, "bad" if failed else "good")
        self.notify(detail, severity="error" if failed else "information")


def run_server_watch(
    fetch: Callable[[], dict[str, object] | None],
    *,
    port: int,
    interval: float,
    watch_mode: str,
) -> None:
    """Run the canonical server-watch application until the operator leaves it."""
    ServerWatchApp(
        fetch=fetch,
        port=port,
        interval=interval,
        watch_mode=watch_mode,
    ).run()
