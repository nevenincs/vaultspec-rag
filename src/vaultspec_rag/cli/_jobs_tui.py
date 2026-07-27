"""Interactive operator interface for the service jobs surface.

Owns the terminal for the duration of the session. Nothing here writes to the
shared console: a live region cannot be hosted on a console configured
non-interactively, and a second console alongside the first corrupts the frame
it is trying to share. The application takes the screen instead.

Every control it issues goes through the same typed transports the singular
job verbs use, carrying the same expected-revision guard, and every action is
offered only where the job's own published capability flags permit it.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, ClassVar, cast

from rich.text import Text
from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import DataTable, Footer, RichLog, Static

from ..job_models import DesiredJobState
from ..serviceclient._transport import (
    _try_http_admin,
    _try_http_delete_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)
from ._cli_format import _compact_duration
from ._service_jobs import (
    _human_progress,
    _job_is_waiting,
    _operation_label,
    _phase_label,
    _project_label,
    _project_root,
    _stale_progress_label,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

__all__ = ["JobsTuiApp", "run_jobs_tui"]

# Braille frames advance on a timer of their own. A view that repaints only on
# a successful fetch is indistinguishable from one whose service has stopped
# answering; the moving glyph says the interface is alive, and the "last
# refreshed" stamp beside it says whether the data is.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
_SPINNER_INTERVAL = 0.1
_LOG_LINES = 200

# Columns are laid out by relative weight, never by a fixed size: the table
# divides whatever width the terminal reports among these shares, so the same
# composition fills an 80-column shell and a 300-column one. The path column
# carries the largest share because it holds the longest value and is the one
# an operator most needs to read whole.
_COLUMN_WEIGHTS: dict[str, float] = {
    # The state column carries the widest short string the view can show -
    # a pending control such as "pause requested" - so its share is set by
    # that, not by the header word.
    "state": 3.0,
    "job": 3.0,
    "path": 4.5,
    "progress": 3.5,
    "time": 2.0,
}
# A column narrower than this cannot show even a truncated value, so the
# division floors here rather than collapsing a column to nothing.
_MIN_COLUMN_CELLS = 8
# The width at or above which two panes side by side are both still readable.
# Below it the layout shows one at a time instead of shrinking both.
_SPLIT_MIN_CELLS = 110

# Action name -> (capability flag the service publishes, desired state).
# ``None`` marks an action that is not a desired-state transition.
_STATE_ACTIONS: dict[str, tuple[str, DesiredJobState]] = {
    "pause": ("pausable", DesiredJobState.PAUSED),
    "resume": ("resumable", DesiredJobState.RUNNING),
    "stop": ("cancellable", DesiredJobState.CANCELLED),
}
_PLAIN_ACTIONS: dict[str, str] = {"retry": "retryable", "delete": "deletable"}

_STATE_STYLES: dict[str, str] = {
    "active": "bold green",
    "waiting": "yellow",
    "failed": "bold red",
    "paused": "cyan",
    "pausing": "cyan",
    "cancelling": "magenta",
    "cancelled": "magenta",
    "finished": "dim",
}


def _job_id(job: dict[str, object]) -> str:
    identifier = job.get("id")
    return identifier if isinstance(identifier, str) else ""


def _short_id(job: dict[str, object]) -> str:
    return _job_id(job)[:8] or "unknown"


def _capability(job: dict[str, object], flag: str) -> bool:
    """Report whether the service published *flag* as permitted for *job*.

    Absent capabilities are read as not permitted. An action the service would
    reject is better shown as unavailable than offered and refused.
    """
    capabilities = job.get("capabilities")
    if not isinstance(capabilities, dict):
        return False
    return cast("dict[str, object]", capabilities).get(flag) is True


def _job_revision(job: dict[str, object]) -> int | None:
    revision = job.get("revision")
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return None
    return revision


def _fit(value: str, cells: int) -> str:
    """Trim *value* to *cells*, marking the trim.

    Every cell in this table is exactly two lines tall. A value wider than its
    column would otherwise wrap onto the second line and push that line's own
    content out of the row entirely - which is how a progress bar, a job id and
    an initiator all silently disappear at moderate widths. Truncating keeps
    each line in its place; losing the tail of one label is far cheaper than
    losing a whole line of the row.
    """
    if cells <= 0 or len(value) <= cells:
        return value
    return value[: max(0, cells - 1)] + "…"


def _two_line(
    top: str,
    bottom: str,
    cells: int,
    *,
    top_style: str = "",
    bottom_style: str = "dim",
) -> Text:
    """Compose one fixed two-line cell, each line trimmed to *cells*."""
    text = Text(_fit(top, cells), style=top_style)
    text.append("\n")
    text.append(_fit(bottom, cells), style=bottom_style)
    return text


def _state_cell(
    job: dict[str, object],
    frame: str,
    pending: str | None,
    cells: int,
) -> Text:
    """Render the state cell: phase, a live glyph, and any pending request."""
    label = _phase_label(job)
    running = str(job.get("phase", "")) == "running" and not _job_is_waiting(job)
    glyph = f"{frame} " if running else "  "
    desired = job.get("desired_state")
    if pending is not None:
        # A requested control is not an observed one. Saying so keeps the
        # view honest across the window where the service has not yet
        # acknowledged the request.
        second, second_style = f" {pending} requested", "italic yellow"
    elif isinstance(desired, str) and desired and desired != job.get("state"):
        second, second_style = f" → {desired}", "italic yellow"
    else:
        second, second_style = "", "dim"
    return _two_line(
        f"{glyph}{label}",
        second,
        cells,
        top_style=_STATE_STYLES.get(label, ""),
        bottom_style=second_style,
    )


def _job_cell(job: dict[str, object], cells: int) -> Text:
    initiator = job.get("initiator")
    kind = ""
    if isinstance(initiator, dict):
        kind = str(cast("dict[str, object]", initiator).get("kind") or "")
    subtitle = f"{_short_id(job)} · {kind}" if kind else _short_id(job)
    return _two_line(_operation_label(job), subtitle, cells, top_style="bold")


def _elide_left(value: str, cells: int) -> str:
    """Trim *value* to *cells*, keeping its tail.

    A path that does not fit must lose its head, not its tail. The leading
    segments of these roots are identical across every checkout on a machine;
    everything that says which one this is sits at the end, so trimming from
    the right would discard the only part worth showing.
    """
    if cells <= 0 or len(value) <= cells:
        return value
    return "…" + value[-(cells - 1) :]


def _path_cell(job: dict[str, object], cells: int) -> Text:
    """Render the project and its root, tail-first when the root is long."""
    root = _project_root(job)
    shown = _elide_left(root, cells) if root else "path not reported"
    return _two_line(_project_label(job), shown, cells)


def _progress_cell(job: dict[str, object], cells: int, bar_cells: int) -> Text:
    """Render the progress cell, sizing the bar to the column it lands in."""
    detail = _human_progress(job) or "—"
    stale = _stale_progress_label(job)
    if stale:
        return _two_line(detail, stale, cells, bottom_style="bold red")
    progress = job.get("progress")
    bar = ""
    if isinstance(progress, dict) and bar_cells > 0:
        data = cast("dict[str, object]", progress)
        completed = data.get("completed")
        total = data.get("total")
        if (
            isinstance(completed, int)
            and not isinstance(completed, bool)
            and isinstance(total, int)
            and not isinstance(total, bool)
            and total > 0
        ):
            ratio = min(1.0, max(0.0, completed / total))
            filled = round(bar_cells * ratio)
            bar = f"{'█' * filled}{'░' * (bar_cells - filled)} {round(100 * ratio)}%"
    return _two_line(detail, bar, cells)


def _time_cell(job: dict[str, object], cells: int) -> Text:
    remaining = job.get("estimated_remaining_seconds")
    estimate = (
        f"~{_compact_duration(remaining)} left"
        if isinstance(remaining, int | float) and not isinstance(remaining, bool)
        # No estimate is not a zero estimate.
        else "—"
    )
    return _two_line(_compact_duration(job.get("runtime_seconds")), estimate, cells)


class JobsTuiApp(App[None]):
    """The live jobs interface."""

    # Every size here is relative: fractional shares for the panes, content
    # height for the bars. Nothing is expressed as a fixed cell count, so the
    # layout follows whatever the terminal reports at any moment.
    CSS = """
    #summary { height: auto; padding: 0 1; background: $panel; color: $text; }
    #body { height: 1fr; width: 1fr; }
    #jobs { width: 1fr; height: 1fr; }
    #logpane { display: none; }
    #logtitle { height: auto; padding: 0 1; background: $panel-darken-1; }
    #joblog { height: 1fr; }

    /* Wide: the log sits beside the table and both are visible at once. */
    Screen.-wide #logpane { width: 2fr; display: block; }
    Screen.-wide #jobs { width: 3fr; }

    /* Narrow: one pane at a time, toggled - the same composition, reflowed. */
    Screen.-narrow.-showlog #logpane { width: 1fr; display: block; }
    Screen.-narrow.-showlog #jobs { display: none; }
    """

    # Unannotated on purpose: the base declares this class variable, and
    # restating a narrower type here is an invalid override.
    HORIZONTAL_BREAKPOINTS = [  # noqa: RUF012
        (0, "-narrow"),
        (_SPLIT_MIN_CELLS, "-wide"),
    ]

    BINDINGS: ClassVar[list[Binding]] = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh_now", "Refresh"),
        Binding("p", "job_pause", "Pause"),
        Binding("u", "job_resume", "Resume"),
        Binding("k", "job_stop", "Kill"),
        Binding("y", "job_retry", "Retry"),
        Binding("d", "job_delete", "Delete"),
        Binding("l", "toggle_log", "Log"),
    ]

    frame_index: reactive[int] = reactive(0)
    # ``bindings=True`` re-evaluates ``check_action`` whenever the selection
    # moves, so the footer reflects the newly selected job's capabilities.
    selected_id: reactive[str] = reactive("", bindings=True)

    def __init__(
        self,
        *,
        fetch: Callable[[], dict[str, object] | None],
        port: int,
        interval: float,
    ) -> None:
        super().__init__()
        self._fetch = fetch
        self._port = port
        self._interval = interval
        self._jobs: list[dict[str, object]] = []
        self._pending: dict[str, tuple[str, str | None]] = {}
        self._last_refresh: float | None = None
        self._last_error: str | None = None
        self._show_log = False
        self._bar_cells = 0
        self._column_cells: dict[str, int] = {}

    def compose(self) -> ComposeResult:
        yield Static(id="summary")
        with Horizontal(id="body"):
            yield DataTable(id="jobs", cursor_type="row", zebra_stripes=True)
            with Vertical(id="logpane"):
                yield Static("Log", id="logtitle")
                yield RichLog(
                    id="joblog", wrap=True, markup=False, max_lines=_LOG_LINES
                )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#jobs", DataTable)
        for key, label in (
            ("state", "State"),
            ("job", "Job"),
            ("path", "Path"),
            ("progress", "Progress"),
            ("time", "Time"),
        ):
            table.add_column(label, key=key)
        # The table has no width until the first layout pass completes, and
        # dividing zero width would leave every column at its label size.
        self.call_after_refresh(self._relayout)
        self.set_interval(_SPINNER_INTERVAL, self._advance_frame)
        self.set_interval(self._interval, self.refresh_jobs)
        self.refresh_jobs()

    def on_resize(self) -> None:
        """Re-divide the columns whenever the terminal changes size."""
        self.call_after_refresh(self._relayout)

    def _relayout(self) -> None:
        self._layout_columns()
        if self._jobs:
            self._render_rows()

    def _layout_columns(self) -> None:
        """Divide the table's reported width among the column weights.

        Called on mount and on every resize, so column widths are always a
        function of the current terminal rather than a value chosen once.
        """
        table = self._table()
        if table is None:
            return
        padding = table.cell_padding * 2 * len(_COLUMN_WEIGHTS)
        available = table.size.width - padding
        if available <= 0:
            return
        total_weight = sum(_COLUMN_WEIGHTS.values())
        for key, weight in _COLUMN_WEIGHTS.items():
            column = table.columns.get(key)
            if column is None:
                continue
            column.width = max(
                _MIN_COLUMN_CELLS, int(available * weight / total_weight)
            )
            column.auto_width = False
            self._column_cells[key] = column.width
        # The bar shares its cell with a trailing " 100%", so it takes what
        # the column has left rather than a width of its own.
        self._bar_cells = max(0, self._column_cells.get("progress", 0) - len(" 100%"))

    def _cells(self, column: str) -> int:
        """Return the current width of *column*, or zero before layout."""
        return self._column_cells.get(column, 0)

    def _table(self) -> DataTable | None:
        """Return the table, or ``None`` when it is not mounted.

        The timers outlive composition at both ends: one can fire before the
        first mount completes and again while the screen is being torn down.
        An unguarded query raises there, and an exception on a timer callback
        takes the whole interface down - which reads to an operator as the
        service having died.
        """
        found = self.query("#jobs")
        return found.only_one(DataTable) if found else None

    def _advance_frame(self) -> None:
        self.frame_index = (self.frame_index + 1) % len(_SPINNER_FRAMES)

    def watch_frame_index(self) -> None:
        # Only the animated cells and the summary change between frames;
        # repainting every row ten times a second would burn the terminal
        # for a glyph.
        table = self._table()
        if table is not None:
            frame = _SPINNER_FRAMES[self.frame_index]
            for job in self._jobs:
                job_id = _job_id(job)
                if job_id in table.rows:
                    table.update_cell(
                        job_id,
                        "state",
                        _state_cell(
                            job,
                            frame,
                            _pending_label(self._pending, job_id),
                            self._cells("state"),
                        ),
                    )
        self._render_summary()

    # -- data ---------------------------------------------------------------

    @work(thread=True, exclusive=True)
    def refresh_jobs(self) -> None:
        """Fetch on a worker thread; the transport is blocking HTTP."""
        result = self._fetch()
        self.call_from_thread(self._apply_result, result)

    def _apply_result(self, result: dict[str, object] | None) -> None:
        if result is None:
            self._last_error = "service not reachable"
            self._render_summary()
            return
        raw_jobs = result.get("jobs")
        jobs = [
            cast("dict[str, object]", job)
            for job in (raw_jobs if isinstance(raw_jobs, list) else [])
            if isinstance(job, dict)
        ]
        self._last_error = None
        self._last_refresh = time.time()
        self._jobs = jobs
        self._reconcile_pending()
        self._layout_columns()
        self._render_rows()
        self._render_summary()

    def _reconcile_pending(self) -> None:
        """Drop a pending marker once the service has taken the request.

        The marker must survive until the service's own ``desired_state``
        carries what was asked for. Clearing it merely because a refresh
        arrived would erase the request during exactly the window it exists to
        describe - the gap between asking and acknowledgement, which for a
        cooperative pause is the interesting part.

        Retry and delete set no desired state, so they clear on the first
        refresh that follows: by then the job has been removed, relinked, or
        the request was refused and already reported.
        """
        by_id = {_job_id(job): job for job in self._jobs}
        for job_id, (_action, expected) in list(self._pending.items()):
            job = by_id.get(job_id)
            if job is None or expected is None:
                del self._pending[job_id]
                continue
            if job.get("desired_state") == expected:
                del self._pending[job_id]

    def _render_rows(self) -> None:
        table = self._table()
        if table is None:
            return
        frame = _SPINNER_FRAMES[self.frame_index]
        wanted = [_job_id(job) for job in self._jobs]
        if [key.value for key in table.rows] != wanted:
            cursor = table.cursor_row
            table.clear()
            for job in self._jobs:
                self._add_row(table, job, frame)
            if cursor < table.row_count:
                table.move_cursor(row=cursor)
        else:
            for job in self._jobs:
                self._update_row(table, job, frame)
        self._sync_selection(table)

    def _add_row(self, table: DataTable, job: dict[str, object], frame: str) -> None:
        table.add_row(
            _state_cell(
                job,
                frame,
                _pending_label(self._pending, _job_id(job)),
                self._cells("state"),
            ),
            _job_cell(job, self._cells("job")),
            _path_cell(job, self._cells("path")),
            _progress_cell(job, self._cells("progress"), self._bar_cells),
            _time_cell(job, self._cells("time")),
            height=2,
            key=_job_id(job),
        )

    def _update_row(self, table: DataTable, job: dict[str, object], frame: str) -> None:
        job_id = _job_id(job)
        cells = {
            "state": _state_cell(
                job, frame, _pending_label(self._pending, job_id), self._cells("state")
            ),
            "job": _job_cell(job, self._cells("job")),
            "path": _path_cell(job, self._cells("path")),
            "progress": _progress_cell(job, self._cells("progress"), self._bar_cells),
            "time": _time_cell(job, self._cells("time")),
        }
        for column, value in cells.items():
            table.update_cell(job_id, column, value)

    def _sync_selection(self, table: DataTable) -> None:
        if table.row_count == 0:
            self.selected_id = ""
            return
        row = min(table.cursor_row, table.row_count - 1)
        # ``str`` on a row key gives its repr, not the id it carries.
        job_id = list(table.rows.keys())[row].value or ""
        if job_id != self.selected_id:
            self.selected_id = job_id

    def _render_summary(self) -> None:
        frame = _SPINNER_FRAMES[self.frame_index]
        counts = {"active": 0, "waiting": 0, "failed": 0, "finished": 0}
        for job in self._jobs:
            label = _phase_label(job)
            if label in counts:
                counts[label] += 1
        line = Text(f"{frame} Jobs on port {self._port}", style="bold")
        line.append(
            f"   active {counts['active']}  waiting {counts['waiting']}"
            f"  failed {counts['failed']}  finished {counts['finished']}"
        )
        if self._last_error is not None:
            line.append(f"\n{self._last_error}", style="bold red")
        elif self._last_refresh is not None:
            stamp = time.strftime("%H:%M:%S", time.localtime(self._last_refresh))
            age = time.time() - self._last_refresh
            line.append(f"\nrefreshed {stamp}", style="dim")
            if age > max(5.0, self._interval * 3):
                line.append(f" ({_compact_duration(age)} ago)", style="bold yellow")
        else:
            line.append("\nloading", style="dim")
        summary = self.query("#summary")
        if summary:
            summary.only_one(Static).update(line)

    # -- selection and logs -------------------------------------------------

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self.selected_id = str(event.row_key.value or "")

    def watch_selected_id(self, job_id: str) -> None:
        if not job_id:
            return
        title = self.query("#logtitle")
        if not title:
            return
        title.only_one(Static).update(f"Log · {job_id[:8]}")
        self.fetch_logs(job_id)

    @work(thread=True, exclusive=True)
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
        found = self.query("#joblog")
        if not found:
            return
        log = found.only_one(RichLog)
        log.clear()
        if result is None or result.get("ok") is False:
            log.write("Logs unavailable: the service did not answer.")
            return
        for line in _log_lines(result):
            log.write(line)

    # -- actions ------------------------------------------------------------

    def selected_job(self) -> dict[str, object] | None:
        for job in self._jobs:
            if _job_id(job) == self.selected_id:
                return job
        return None

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Disable a row action the selected job does not permit.

        Returning ``None`` greys the key in the footer rather than hiding it,
        so the operator can see the control exists and that this job cannot
        take it.
        """
        # Named to match the override; these actions take no parameters.
        del parameters
        flag = _action_capability(action)
        if flag is None:
            return True
        job = self.selected_job()
        if job is None or not _capability(job, flag):
            return None
        return True

    def action_toggle_log(self) -> None:
        self._show_log = not self._show_log
        self.screen.set_class(self._show_log, "-showlog")

    def action_refresh_now(self) -> None:
        self.refresh_jobs()

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
        revision = _job_revision(job)
        if revision is None:
            self.notify("The service reported no revision for this job.")
            return
        flag, desired = _STATE_ACTIONS[action]
        del flag
        self._mark_pending(job, action, expected=desired.value)
        self._send_state(_job_id(job), desired, revision, action)

    @work(thread=True)
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
        job = self._actionable("retry")
        if job is not None:
            self._mark_pending(job, "retry")
            self._send_retry(_job_id(job))

    @work(thread=True)
    def _send_retry(self, job_id: str) -> None:
        result = _try_http_retry_job(
            job_id,
            self._port,
            initiator_kind="cli",
            command="server_job_retry",
        )
        self.call_from_thread(self._after_control, job_id, "retry", result)

    def action_job_delete(self) -> None:
        job = self._actionable("delete")
        if job is not None:
            self._mark_pending(job, "delete")
            self._send_delete(_job_id(job))

    @work(thread=True)
    def _send_delete(self, job_id: str) -> None:
        result = _try_http_delete_job(job_id, self._port)
        self.call_from_thread(self._after_control, job_id, "delete", result)

    def _actionable(self, action: str) -> dict[str, object] | None:
        """Return the selected job when it permits *action*, else ``None``.

        The footer already greys a disallowed key, but a binding can still
        fire; this is the check that makes the refusal real rather than
        cosmetic, so no request is sent for a capability the service denies.
        """
        job = self.selected_job()
        flag = _action_capability(f"job_{action}")
        if job is None or flag is None or not _capability(job, flag):
            return None
        return job

    def _mark_pending(
        self,
        job: dict[str, object],
        action: str,
        expected: str | None = None,
    ) -> None:
        self._pending[_job_id(job)] = (action, expected)
        self._render_rows()

    def _after_control(
        self,
        job_id: str,
        action: str,
        result: dict[str, object] | None,
    ) -> None:
        if result is None:
            self._pending.pop(job_id, None)
            self.notify(f"{action} failed: the service is not reachable.")
        elif result.get("ok") is not True:
            self._pending.pop(job_id, None)
            message = result.get("message")
            self.notify(
                f"{action} refused: {message}"
                if isinstance(message, str)
                else f"{action} was refused by the service."
            )
        self._render_rows()
        self.refresh_jobs()


def _pending_label(
    pending: dict[str, tuple[str, str | None]],
    job_id: str,
) -> str | None:
    marker = pending.get(job_id)
    return None if marker is None else marker[0]


def _action_capability(action: str) -> str | None:
    """Map a binding action name to the capability flag that permits it."""
    name = action.removeprefix("job_")
    if name in _STATE_ACTIONS:
        return _STATE_ACTIONS[name][0]
    return _PLAIN_ACTIONS.get(name)


def _log_lines(result: dict[str, object]) -> Iterable[str]:
    """Yield raw log lines from a managed-log payload, group order preserved."""
    groups = result.get("groups")
    if not isinstance(groups, list):
        return []
    lines: list[str] = []
    for group in cast("list[object]", groups):
        if not isinstance(group, dict):
            continue
        raw = cast("dict[str, object]", group).get("lines")
        if isinstance(raw, list):
            lines.extend(str(line) for line in cast("list[object]", raw))
    return lines or ["No log lines matched this job."]


def run_jobs_tui(
    fetch: Callable[[], dict[str, object] | None],
    *,
    port: int,
    interval: float,
) -> None:
    """Run the interface until the operator leaves it."""
    JobsTuiApp(fetch=fetch, port=port, interval=interval).run()
