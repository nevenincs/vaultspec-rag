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

import math
import time
from typing import TYPE_CHECKING, ClassVar, NamedTuple, cast

from rich.cells import cell_len
from rich.text import Text
from textual import events, work
from textual.app import App, ComposeResult, ScreenStackError
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import DataTable, Footer, Static
from textual.widgets.data_table import ColumnKey
from textual.worker import WorkerState

from .._typed_fields import str_or_empty
from ..job_models import DesiredJobState, JobState
from ..jobs import count, measurement
from ..logging_config import MAX_MANAGED_LOG_LINES, validate_managed_log_payload
from ..serviceclient._transport import (
    _try_http_admin,
    _try_http_delete_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)
from ._cli_format import compact_duration
from ._jobs_tui_log import JobsLogView
from ._jobs_tui_managed_logs import ManagedLogTankView
from ._jobs_tui_palette import (
    DARK_THEME_NAME,
    LIGHT_THEME_NAME,
    build_themes,
    pill_fill,
    semantic_tones,
    tone_style,
)
from ._jobs_tui_status import (
    ServiceStatusBar,
    ServiceStatusHeader,
    fetch_service_status,
)
from ._service_jobs_presentation import (
    degradation_evidence_lines,
    degradation_verdict,
    human_progress,
    operation_label,
    phase_label,
    project_label,
    project_root,
    stale_progress_label,
)
from ._service_jobs_query import job_is_waiting, job_revision

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from textual.screen import Screen

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
_GONE_CODES = frozenset({"job_not_found", "not_found"})

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

# The search ledger itself is bounded by the service. This is the bounded
# operator page this screen asks it to project, independent from job and log
# refresh limits.
_SEARCH_ACTIVITY_LIMIT = 100

_SEARCH_COLUMN_WEIGHTS: dict[str, float] = {
    "state": 2.5,
    "request": 3.0,
    "query": 4.0,
    "time": 2.5,
}

# Action name -> (capability flag the service publishes, desired state).
# ``None`` marks an action that is not a desired-state transition.
_STATE_ACTIONS: dict[str, tuple[str, DesiredJobState]] = {
    "pause": ("pausable", DesiredJobState.PAUSED),
    "resume": ("resumable", DesiredJobState.RUNNING),
    "stop": ("cancellable", DesiredJobState.CANCELLED),
}
_PLAIN_ACTIONS: dict[str, str] = {"retry": "retryable", "delete": "deletable"}

# Derived from the canonical enum rather than listed again here, so a state
# added there cannot quietly start reading as non-terminal in this view.
_TERMINAL_STATES = frozenset(state.value for state in JobState if state.is_terminal)

# Estimate fields a service older than this view does not publish at all.
# Absent is not the same answer as present-and-null: null is the service
# declining to estimate this job, absent is a service that never estimates.
# Reading them the same way would tell an operator their jobs are all
# unmeasurable when the truth is that their daemon predates the measurement.
_ESTIMATE_KEY = "estimated_remaining_seconds"

# Key -> action, so a press that lands on an unavailable action can be
# answered. A disabled binding never invokes its action, so without this the
# only signal is a greyed footer entry, and an operator pressing the key gets
# silence - which reads as a broken interface rather than a refused request.
_ACTION_KEYS: dict[str, str] = {
    "p": "job_pause",
    "u": "job_resume",
    "k": "job_stop",
    "y": "job_retry",
    "d": "job_delete",
    "x": "log_noise",
    "n": "log_next_error",
    "N": "log_prev_error",
    "g": "log_top",
    "G": "log_end",
    "f": "log_expand",
}

# Why each action is unavailable, in the operator's terms rather than the
# capability flag's.
_ACTION_REASONS: dict[str, str] = {
    "job_pause": "Only running work can be paused.",
    "job_resume": "Only paused work can be resumed.",
    "job_stop": "Only running work can be cancelled.",
    "job_retry": "Only a finished or failed job can be retried.",
    "job_delete": "Only a finished or failed job can be deleted.",
    "log_next_error": "This log has no error entries.",
    "log_prev_error": "This log has no error entries.",
}

# What every log action answers with while the pane is closed. The keys must
# not go dead just because the pane is not on screen.
_LOG_CLOSED_REASON = "The log pane is closed - press l to open it."

# Header counters, as (label, the canonical state they count). The service
# tallies these over every record matching the filter; the same names index
# both its summary and a record's own ``state``, so the fallback tally of the
# page on screen is the same reading of the same field.
_SUMMARY_BUCKETS: tuple[tuple[str, str], ...] = (
    ("running", "running"),
    ("queued", "queued"),
    ("paused", "paused"),
    ("failed", "failed"),
    ("succeeded", "succeeded"),
)

# Header pills. One anatomy for every pill - glyph, count, then (width
# permitting) a label - so no cell has to be decoded differently from its
# neighbours, and the glyph is never the only signal. Tone is one mapping
# across the whole header: good, attention, bad, neutral, muted - and a
# pill's tone drops to muted at zero so colour always means signal. The
# ASCII fallback carries the same meaning on a terminal that cannot paint
# the glyph, and moves with the glyph whenever one changes.
#
# The glyph families keep the categories apart at a glance: activity states
# use playback marks (▶ run, ⋯ queued, ‖ paused) and outcome marks (✖ ✓),
# while the job-health tallies use an escalating warning-triangle family
# (△ hollow for degraded, ▲ solid for stalled) that cannot be misread as a
# state.
_STATE_PILLS: dict[str, tuple[str, str, str, str, bool]] = {
    # state -> (glyph, ASCII fallback, label, tone, bold)
    "running": ("▶", ">", "running", "good", True),
    "queued": ("⋯", "..", "queued", "neutral", False),
    "paused": ("‖", "||", "paused", "neutral", False),
    "failed": ("✖", "x", "failed", "bad", True),
    "succeeded": ("✓", "v", "succeeded", "good", False),
}
# The residue bucket for states without a pill of their own; the label is
# the state name the tally reported.
_OTHER_PILL_GLYPHS = ("□", "?")

# Job-health tallies the service publishes beside the state counts. Shown
# only when the summary carries the key: a daemon older than the tally is
# absent, not zero.
_HEALTH_PILLS: tuple[tuple[str, str, str, str, str, bool], ...] = (
    # key -> (glyph, ASCII fallback, label, tone, bold)
    ("degraded", "△", "!", "degraded", "attention", False),
    ("stalled", "▲", "!!", "stalled", "bad", True),
)

# The dim divider between header groups: states, health, service, GPU, and
# the page count each read as their own cell run rather than one cramped row.
_GROUP_SEPARATORS = ("│", "|")

# Rounded end-caps for the pills: half-circle glyphs painted in the pill's
# own fill colour, so a background-filled span reads as an actual pill
# rather than a hard-edged block. On a console whose encoding cannot carry
# them, the pill degrades to a space-padded filled span - soft, bracket
# free, and still a pill.
_PILL_CAP_LEFT = "\ue0b6"
_PILL_CAP_RIGHT = "\ue0b4"

# The blank cell that joins a pill's words. It is a glyph, not whitespace:
# both text wrappers on this path break at any Unicode whitespace - the
# no-break space included - so only a non-space blank keeps a pill in one
# piece at every width. It renders as an empty cell in the same braille
# block the busy spinner already draws from.
_PILL_JOINER = "\u2800"


def _widest_line(line: Text) -> int:
    """The widest row of a possibly multi-row header, in cells."""
    return max(cell_len(part) for part in line.plain.split("\n"))


def _append_pill(
    line: Text,
    content: str,
    fill: tuple[str, str],
    *,
    unicode_ok: bool,
) -> None:
    """Append one rounded pill: *content* on its fill, capped or padded.

    The content's spaces become blank joiner cells, so a pill wraps as one
    unit: a line break inside a filled span would tear the pill across two
    rows. The ASCII degradation keeps plain spaces - it carries no glyphs
    at all, by definition.
    """
    background, foreground = fill
    if unicode_ok:
        line.append(_PILL_CAP_LEFT, style=background)
        line.append(
            content.replace(" ", _PILL_JOINER),
            style=f"{foreground} on {background}",
        )
        line.append(_PILL_CAP_RIGHT, style=background)
        return
    line.append(f" {content} ", style=f"{foreground} on {background}")


# The service-condition pill's vocabulary, worst-last, and its tones.
# ``reachable`` is what an older daemon that stamps no verdicts can claim.
_CONDITION_ORDER = ("healthy", "degraded", "stalled")
_CONDITION_TONES: dict[str, tuple[str, bool]] = {
    "healthy": ("good", False),
    "degraded": ("attention", False),
    "stalled": ("bad", True),
    "unreachable": ("bad", True),
    "reachable": ("muted", False),
}

# Row phase-label tones: motion and success are good, waiting is attention,
# failure is bad, every deliberate operator state (paused, cancelled and the
# transitions into them) is neutral, and finished work recedes to muted.
_STATE_TONES: dict[str, tuple[str, bool]] = {
    "active": ("good", True),
    "waiting": ("attention", False),
    "failed": ("bad", True),
    "paused": ("neutral", False),
    "pausing": ("neutral", False),
    "cancelling": ("neutral", False),
    "cancelled": ("neutral", False),
    "finished": ("muted", False),
}


def _record_with_id(
    records: list[dict[str, object]],
    key: str,
    wanted: str,
) -> dict[str, object] | None:
    """Return the record whose *key* equals *wanted*, or ``None``.

    Both lanes resolve a selection the same way - the selected id is a value,
    not an index, so a record that moved or vanished between refreshes simply
    does not match. Which field carries the id is the only difference.
    """
    for record in records:
        if str_or_empty(record.get(key)) == wanted:
            return record
    return None


def _job_id(job: dict[str, object]) -> str:
    return str_or_empty(job.get("id"))


def _short_id(job: dict[str, object]) -> str:
    return _job_id(job)[:8] or "unknown"


def _search_id(search: dict[str, object]) -> str:
    return str_or_empty(search.get("request_id"))


def _search_text(value: object, *, fallback: str = "—") -> str:
    """Return one printable line from an authenticated activity field."""
    if not isinstance(value, str) or not value:
        return fallback
    return (
        " ".join(
            "".join(
                character if character.isprintable() else " " for character in value
            ).split()
        )
        or fallback
    )


def _capability(job: dict[str, object], flag: str) -> bool:
    """Report whether *job* may take the action *flag* names.

    Only a published ``false`` denies. Absent is unknown, and unknown keeps
    today's reading rather than inventing a more specific one - the same
    distinction the jobs surface already draws between a field the service
    declined to fill and one it does not publish at all.

    Reading absent as denied is what makes a whole list of restored records
    silently inert: every key greys, every press does nothing, and the
    interface looks wired to no backend at all. The service is the authority
    on what it will accept, so an unknown capability is offered and its
    refusal, if it comes, is shown on the row.
    """
    capabilities = job.get("capabilities")
    if not isinstance(capabilities, dict):
        return True
    return cast("dict[str, object]", capabilities).get(flag) is not False


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


def _row_animates(job: dict[str, object]) -> bool:
    """Report whether this row's work is actually moving.

    A glyph that turns for every record whose phase reads ``running`` turns for
    work queued behind admission and for work whose progress stopped updating
    minutes ago. Both are stopped from the operator's side, and a turning glyph
    over them is a claim the view cannot support.
    """
    return (
        str(job.get("phase", "")) == "running"
        and not job_is_waiting(job)
        and not stale_progress_label(job)
    )


class _Pending(NamedTuple):
    """One control the operator issued, and how far it has got.

    The row carries this until the service's own payload settles it. A toast
    that expires in seconds is not acknowledgement: the operator looks back at
    the row, sees the state it always had, and concludes nothing was wired up.
    """

    action: str
    # The ``desired_state`` whose arrival confirms the transition, or ``None``
    # for a control that sets none - retry and delete are confirmed by the
    # service's list changing, not by a field.
    expected: str | None
    # ``requested`` in flight, ``sent`` accepted and awaiting the payload that
    # proves it, ``refused`` rejected, ``gone`` aimed at a dropped id.
    outcome: str
    detail: str
    # Only a fetch issued after this generation can confirm the control. A
    # poll already in flight when the control landed carries pre-mutation
    # state, and letting it clear the marker is what makes a requested control
    # flash and vanish without anything having changed.
    settled_after: int


class _Tombstone(NamedTuple):
    """A deleted row, and where it sat before it went."""

    job: dict[str, object]
    position: int
    until: float


# Each line is kept inside the state column's share, which is set by the
# widest of them. A longer phrase is not more informative here: it is trimmed
# to a width that cuts the distinguishing word off, and every stage of a
# control then paints the same truncated stem. The header carries the full
# sentence, where there is room for one.
_PENDING_LINES: dict[str, tuple[str, str, bool, bool]] = {
    # outcome -> (template, tone, bold, italic)
    "requested": (" {action} requested", "attention", False, True),
    "sent": (" {action} sent", "attention", False, True),
    "refused": (" {action} refused", "bad", True, False),
    "gone": (" no longer listed", "bad", True, False),
}


class _PaintContext(NamedTuple):
    """Per-repaint paint state every row cell shares: frame and tones."""

    frame: str
    tones: dict[str, str]


def _state_cell(
    job: dict[str, object],
    paint: _PaintContext,
    pending: _Pending | None,
    cells: int,
    *,
    deleted: bool = False,
) -> Text:
    """Render the state cell: phase, a live glyph, and any pending request."""
    tones = paint.tones
    label = phase_label(job)
    glyph = f"{paint.frame} " if _row_animates(job) else "  "
    if deleted:
        # The row the operator acted on, held on screen long enough to be seen
        # leaving. Without this the freed slot is backfilled from the
        # remainder on the next poll and the list looks untouched.
        return _two_line(
            f"  {label}",
            " ✗ deleted",
            cells,
            top_style="strike dim",
            bottom_style=tone_style(tones, "bad", bold=True),
        )
    desired = job.get("desired_state")
    state = job.get("state")
    if pending is not None:
        # A requested control is not an observed one. Saying so keeps the
        # view honest across the window where the service has not yet
        # acknowledged the request.
        template, tone, bold, italic = _PENDING_LINES[pending.outcome]
        second = template.format(action=pending.action)
        second_style = tone_style(tones, tone, bold=bold, italic=italic)
    elif (
        isinstance(desired, str)
        and desired
        and desired != state
        # A terminal job is not transitioning anywhere. Restored jobs in
        # particular carry the desired state they held when the daemon died -
        # an interrupted job still reads ``desired_state: running`` - and
        # painting an arrow there advertises a transition that will never
        # happen, on work that is already over.
        and str(state) not in _TERMINAL_STATES
    ):
        second = f" → {desired}"
        second_style = tone_style(tones, "attention", italic=True)
    else:
        second, second_style = "", "dim"
    top_tone, top_bold = _STATE_TONES.get(label, ("", False))
    return _two_line(
        f"{glyph}{label}",
        second,
        cells,
        top_style=tone_style(tones, top_tone, bold=top_bold),
        bottom_style=second_style,
    )


def _job_cell(job: dict[str, object], cells: int) -> Text:
    initiator = job.get("initiator")
    kind = ""
    if isinstance(initiator, dict):
        kind = str(cast("dict[str, object]", initiator).get("kind") or "")
    subtitle = f"{_short_id(job)} · {kind}" if kind else _short_id(job)
    return _two_line(operation_label(job), subtitle, cells, top_style="bold")


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
    root = project_root(job)
    shown = _elide_left(root, cells) if root else "path not reported"
    return _two_line(project_label(job), shown, cells)


def _progress_cell(
    job: dict[str, object],
    cells: int,
    bar_cells: int,
    tones: dict[str, str],
) -> Text:
    """Render the progress cell, sizing the bar to the column it lands in."""
    detail = human_progress(job) or "—"
    stale = stale_progress_label(job)
    if stale:
        return _two_line(
            detail, stale, cells, bottom_style=tone_style(tones, "bad", bold=True)
        )
    progress = job.get("progress")
    bar = ""
    if isinstance(progress, dict) and bar_cells > 0:
        data = cast("dict[str, object]", progress)
        completed = count(data.get("completed"))
        total = count(data.get("total"))
        if completed is not None and total is not None and total > 0:
            ratio = min(1.0, completed / total)
            filled = round(bar_cells * ratio)
            bar = f"{'█' * filled}{'░' * (bar_cells - filled)} {round(100 * ratio)}%"
    return _two_line(detail, bar, cells)


def _time_cell(
    job: dict[str, object],
    cells: int,
    *,
    ticked: float | None = None,
) -> Text:
    remaining = measurement(job.get(_ESTIMATE_KEY))
    if remaining is not None:
        shown = ticked if ticked is not None else remaining
        # Ceiling, not truncation: the countdown must never read below the
        # value the service just published, and the coarse two-unit
        # rendering already strips any precision the estimate lacks.
        estimate = f"~{compact_duration(math.ceil(shown))} left"
    elif (
        _ESTIMATE_KEY in job
        and str(job.get("phase", "")) == "running"
        and not job_is_waiting(job)
    ):
        # Published null on working work is the service declining to
        # estimate this job - said on the row, because a bare dash there
        # reads as "nothing to know" rather than "measured and unknown".
        estimate = "ETA unknown"
    else:
        # No estimate is not a zero estimate: the key is absent (a daemon
        # that predates it; the header says so once) or the work is inert.
        estimate = "—"
    return _two_line(compact_duration(job.get("runtime_seconds")), estimate, cells)


def _search_state_cell(
    search: dict[str, object], cells: int, tones: dict[str, str]
) -> Text:
    """Render lifecycle state and terminal outcome without result bodies."""
    state = _search_text(search.get("state"), fallback="unknown")
    outcome = _search_text(search.get("outcome"), fallback="serving")
    tone = "good" if state == "active" else "muted"
    if outcome in {"failed", "unavailable", "validation_rejected"}:
        tone = "bad"
    return _two_line(
        state,
        outcome,
        cells,
        top_style=tone_style(tones, tone, bold=state == "active"),
    )


def _search_request_cell(search: dict[str, object], cells: int) -> Text:
    """Render stable request identity with type, root, and requested depth."""
    request_id = _search_id(search) or "unknown"
    source = _search_text(search.get("source"), fallback="source unavailable")
    search_type = _search_text(search.get("type"), fallback="type unavailable")
    root = _search_text(search.get("root"), fallback="root unavailable")
    top_k = count(search.get("top_k"))
    depth = "—" if top_k is None else str(top_k)
    return _two_line(
        f"{request_id[:12]} · {source}/{search_type}",
        f"{_elide_left(root, cells)} · top {depth}",
        cells,
    )


def _search_query_cell(search: dict[str, object], cells: int) -> Text:
    """Render authenticated in-memory query text, never a result payload."""
    query = _search_text(search.get("query"), fallback="query unavailable")
    availability = _search_text(search.get("availability_cause"), fallback="")
    error = _search_text(search.get("error_message"), fallback="")
    return _two_line(query, availability or error, cells, top_style="bold")


def _search_time_cell(search: dict[str, object], cells: int) -> Text:
    """Render duration, status, and result count from the activity record."""
    total = measurement(search.get("total_seconds"))
    duration = "in progress" if total is None else compact_duration(total)
    status = count(search.get("status_code"))
    results = count(search.get("result_count"))
    return _two_line(
        duration,
        f"HTTP {'—' if status is None else status} · "
        f"{'—' if results is None else results} results",
        cells,
    )


class _LogPane(Vertical):
    """The log pane's container, allowed to fill the screen on request.

    A plain container refuses maximization, and maximizing the log widget
    alone would take it from under its own title bar - the zoom would drop
    the line saying whose log this is and what the noise filter hides.
    """

    ALLOW_MAXIMIZE: ClassVar[bool | None] = True


class ServerWatchApp(App[None]):
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
        (_SPLIT_MIN_CELLS, "-wide"),
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
        self._searches: list[dict[str, object]] = []
        self._search_counts: dict[str, int] = {}
        self._pending: dict[str, _Pending] = {}
        # Rows the operator deleted, held briefly so the deletion is seen.
        self._tombstones: dict[str, _Tombstone] = {}
        # How many jobs the service holds behind the page this view fetches.
        # Without it a deletion is invisible: the next refresh backfills the
        # freed slot from the remainder and the list looks untouched.
        self._total: int | None = None
        # The service's own tally over every record matching the filter, which
        # is the only count that describes more than the page on screen.
        self._summary: object = None
        # The machine-wide GPU pressure block riding the jobs payload.
        # Absent-vs-null matters: a daemon older than the field never sends
        # it, a daemon on a host that cannot measure sends null measurements.
        self._gpu: dict[str, object] | None = None
        self._gpu_reported = False
        # The machine pressure tier riding the jobs payload. A daemon that
        # predates the tier sends no key, and must not be rendered as if it
        # had computed one.
        self._pressure: dict[str, object] | None = None
        # The release the connected daemon reports, never the local
        # package's own: the two differ exactly when the difference matters.
        # ``checked`` separates "no daemon has answered yet" from "the
        # daemon answered and predates version reporting".
        self._service_version: str | None = None
        self._service_version_checked = False
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
        # Fetches are stamped and applied newest-first. Cancelling a thread
        # worker does not stop the OS thread it is running on, so a poll the
        # next one superseded still delivers its answer - and with a two-second
        # interval against a thirty-second timeout, several can be outstanding
        # at once. Applying them in completion order lets a pre-mutation
        # payload land after a post-mutation one and silently revert the view.
        self._generation = 0
        self._applied_generation = 0
        self._search_activity_last_refresh: float | None = None
        self._search_activity_error: str | None = None
        self._search_activity_generation = 0
        self._applied_search_activity_generation = 0
        # ``None`` until the operator chooses; the width decides until then.
        self._show_log: bool | None = None
        self._managed_logs_last_refresh: float | None = None
        self._managed_logs_error: str | None = None
        # The managed-log worker is independent from jobs, but it has the
        # same late-thread-answer hazard: a cancelled older HTTP call can
        # still return after its replacement. Its snapshot must therefore be
        # ordered by issue generation, not completion order.
        self._managed_log_generation = 0
        self._applied_managed_log_generation = 0
        self._bar_cells = 0
        self._column_cells: dict[str, int] = {}
        self._search_column_cells: dict[str, int] = {}
        # The table width the current column shares were divided from.
        self._divided_width = 0

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
        if self._layout_search_columns() and self._searches:
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
        padding = table.cell_padding * 2 * len(_COLUMN_WEIGHTS)
        # The scrollable content region, not the outer size: the pane's
        # border and any scrollbar come out of the cells the columns can
        # actually paint into, and dividing the outer width lays the last
        # column partly under the frame.
        available = table.scrollable_content_region.width - padding
        # A hidden table reports no width. That is not a new division to
        # record; recording it would skip the real one when it reappears.
        if available <= 0 or table.size.width == self._divided_width:
            return False
        self._divided_width = table.size.width
        total_weight = sum(_COLUMN_WEIGHTS.values())
        for key, weight in _COLUMN_WEIGHTS.items():
            column = table.columns.get(ColumnKey(key))
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
        return True

    def _cells(self, column: str) -> int:
        """Return the current width of *column*, or zero before layout."""
        return self._column_cells.get(column, 0)

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
        return self._search_column_cells.get(column, 0)

    def _mounted[WidgetT: Widget](
        self,
        selector: str,
        kind: type[WidgetT],
    ) -> WidgetT | None:
        """Return a composed widget, or ``None`` when it is not mounted.

        Every pane and table on this screen is reached through here, because
        every one of them needs the same guard, and it is needed at both ends
        of composition. A timer can fire before the first mount completes; and
        composition is not there for the whole of a request's life either - one
        issued a moment before the session ended is answered after the screen
        has gone, and that answer arrives here. An unguarded query raises in
        both cases, and an exception on the callback takes the whole interface
        down - which reads to an operator as the service having died.

        """
        found = self.query(selector)
        if not found:
            return None
        return found.only_one(kind)

    def _table(self) -> DataTable[Text] | None:
        """Return the jobs table, or ``None`` when it is not mounted."""
        return cast("DataTable[Text] | None", self._mounted("#jobs", DataTable))

    def _search_table(self) -> DataTable[Text] | None:
        """Return the served-search table, or ``None`` before composition."""
        return cast("DataTable[Text] | None", self._mounted("#searches", DataTable))

    def _layout_search_columns(self) -> bool:
        """Divide the served-search table against its actual current width."""
        table = self._search_table()
        if table is None:
            return False
        padding = table.cell_padding * 2 * len(_SEARCH_COLUMN_WEIGHTS)
        available = table.scrollable_content_region.width - padding
        if available <= 0:
            return False
        total_weight = sum(_SEARCH_COLUMN_WEIGHTS.values())
        changed = False
        for key, weight in _SEARCH_COLUMN_WEIGHTS.items():
            column = table.columns.get(ColumnKey(key))
            if column is None:
                continue
            width = max(_MIN_COLUMN_CELLS, int(available * weight / total_weight))
            if column.width != width:
                changed = True
            column.width = width
            column.auto_width = False
            self._search_column_cells[key] = width
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
        return self._busy() or any(_row_animates(job) for job in self._jobs)

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
        paint = _PaintContext(_SPINNER_FRAMES[self._frame], semantic_tones(self.theme))
        for job in self._jobs:
            job_id = _job_id(job)
            if _row_animates(job) and job_id in table.rows:
                table.update_cell(
                    job_id,
                    "state",
                    _state_cell(
                        job, paint, self._pending.get(job_id), self._cells("state")
                    ),
                )
                # The countdown only moves between polls if this repaint
                # carries it; the same moving rows the glyph animates are
                # exactly the ones whose estimate is allowed to tick.
                table.update_cell(
                    job_id,
                    "time",
                    _time_cell(
                        job, self._cells("time"), ticked=self._ticked_remaining(job)
                    ),
                )

    # -- data ---------------------------------------------------------------

    def refresh_jobs(self) -> None:
        """Issue a stamped fetch. The stamp is what orders the answers."""
        self._generation += 1
        self._fetch_jobs(self._generation)

    @work(thread=True, exclusive=True, group=_REFRESH_GROUP)
    def _fetch_jobs(self, generation: int) -> None:
        """Fetch on a worker thread; the transport is blocking HTTP."""
        result = self._fetch()
        self.call_from_thread(self._apply_result, result, generation)

    def refresh_search_activity(self) -> None:
        """Issue an independent bounded served-search snapshot."""
        self._search_activity_generation += 1
        self._fetch_search_activity(self._search_activity_generation)

    @work(thread=True, exclusive=True, group=_SEARCH_ACTIVITY_GROUP)
    def _fetch_search_activity(self, generation: int) -> None:
        """Read active and recent served searches through the admin boundary."""
        result = _try_http_admin(
            "get_search_activity",
            {"limit": _SEARCH_ACTIVITY_LIMIT},
            self._port,
        )
        self.call_from_thread(self._apply_search_activity, result, generation)

    def _apply_search_activity(
        self,
        result: dict[str, object] | None,
        generation: int,
    ) -> None:
        """Apply a newer authenticated search projection without touching jobs."""
        if generation <= self._applied_search_activity_generation:
            return
        self._applied_search_activity_generation = generation
        error = _search_activity_error(result)
        if error is not None:
            self._search_activity_error = error
            self._render_search_title()
            self._render_summary()
            return
        payload = cast("dict[str, object]", result)
        active = _search_records(payload.get("active"), "active")
        recent = _search_records(payload.get("recent"), "terminal")
        self._searches = active + recent
        counts = cast("dict[str, object]", payload["counts"])
        self._search_counts = {
            name: count(counts.get(name)) or 0 for name in ("active", "recent", "total")
        }
        self._search_activity_error = None
        self._search_activity_last_refresh = time.time()
        self._layout_search_columns()
        self._render_searches()
        self._render_search_title()
        self._render_summary()

    def refresh_managed_logs(self) -> None:
        """Issue an ordered all-source log snapshot on its own worker group."""
        self._managed_log_generation += 1
        self._fetch_managed_logs(self._managed_log_generation)

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
        if generation <= self._applied_managed_log_generation:
            return
        self._applied_managed_log_generation = generation
        if result is None or result.get("ok") is False:
            self._managed_logs_error = "the service did not answer"
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
            self._managed_logs_error = "the service returned an invalid response"
            self._clear_managed_logs(
                "Managed logs unavailable: the service returned an invalid response."
            )
            return
        tank = self._managed_log_view()
        if tank is None:
            return
        tank.show_groups(groups)
        self._managed_logs_error = None
        self._managed_logs_last_refresh = time.time()
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
            self._service_version = result.version
            self._service_version_checked = True
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
        if generation <= self._applied_generation:
            # A slower fetch that the newest applied one already superseded.
            # Its payload predates what is on screen.
            return
        self._applied_generation = generation
        error = _fetch_error(result)
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
            and _job_id(cast("dict[str, object]", job))
        ]
        self._last_error = None
        self._last_refresh = time.time()
        # A service that publishes the key for no job at all predates the
        # estimate. Saying so once beats every row reading as unmeasurable.
        self._service_estimates = not jobs or any(_ESTIMATE_KEY in job for job in jobs)
        self._record_estimates(jobs)
        self._jobs = jobs
        self._total = count(payload.get("total"))
        self._summary = payload.get("summary")
        self._gpu_reported = "gpu" in payload
        raw_gpu = payload.get("gpu")
        self._gpu = (
            cast("dict[str, object]", raw_gpu) if isinstance(raw_gpu, dict) else None
        )
        raw_pressure = payload.get("pressure")
        self._pressure = (
            cast("dict[str, object]", raw_pressure)
            if isinstance(raw_pressure, dict)
            else None
        )
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
            value = measurement(job.get(_ESTIMATE_KEY))
            if value is not None:
                estimates[_job_id(job)] = (value, now)
        self._estimates = estimates

    def _ticked_remaining(self, job: dict[str, object]) -> float | None:
        """Count the last service estimate down by the seconds since it landed.

        Presentation only: the service owns the estimate; this subtracts wall
        time from it between polls and clamps at zero, and every applied
        payload replaces the entry so the display snaps to each fresh value.
        Gated on the row actually moving - ticking a countdown over stalled
        or waiting work would claim motion the view has no evidence for.
        """
        entry = self._estimates.get(_job_id(job))
        if entry is None or not _row_animates(job):
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
        by_id = {_job_id(job): job for job in self._jobs}
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
            if _job_id(job) == job_id:
                self._tombstones[job_id] = _Tombstone(
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
        wanted = [_job_id(job) for job, _deleted in rows]
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
        job_id = _job_id(job)
        tones = semantic_tones(self.theme)
        table.add_row(
            _state_cell(
                job,
                _PaintContext(frame, tones),
                self._pending.get(job_id),
                self._cells("state"),
                deleted=deleted,
            ),
            _job_cell(job, self._cells("job")),
            _path_cell(job, self._cells("path")),
            _progress_cell(job, self._cells("progress"), self._bar_cells, tones),
            _time_cell(job, self._cells("time"), ticked=self._ticked_remaining(job)),
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
        job_id = _job_id(job)
        tones = semantic_tones(self.theme)
        cells = {
            "state": _state_cell(
                job,
                _PaintContext(frame, tones),
                self._pending.get(job_id),
                self._cells("state"),
                deleted=deleted,
            ),
            "job": _job_cell(job, self._cells("job")),
            "path": _path_cell(job, self._cells("path")),
            "progress": _progress_cell(
                job, self._cells("progress"), self._bar_cells, tones
            ),
            "time": _time_cell(
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
        wanted = [_search_id(search) for search in self._searches]
        if [key.value for key in table.rows] != wanted:
            previous = self.selected_search_id
            cursor = table.cursor_row
            table.clear()
            for search in self._searches:
                self._add_search_row(table, search)
            if table.row_count:
                row = (
                    wanted.index(previous)
                    if previous in wanted
                    else min(max(0, cursor), table.row_count - 1)
                )
                table.move_cursor(row=row)
        else:
            for search in self._searches:
                self._update_search_row(table, search)
        self._sync_search_selection(table)

    def _add_search_row(
        self, table: DataTable[Text], search: dict[str, object]
    ) -> None:
        tones = semantic_tones(self.theme)
        table.add_row(
            _search_state_cell(search, self._search_cells("state"), tones),
            _search_request_cell(search, self._search_cells("request")),
            _search_query_cell(search, self._search_cells("query")),
            _search_time_cell(search, self._search_cells("time")),
            height=2,
            key=_search_id(search),
        )

    def _update_search_row(
        self, table: DataTable[Text], search: dict[str, object]
    ) -> None:
        tones = semantic_tones(self.theme)
        cells = {
            "state": _search_state_cell(search, self._search_cells("state"), tones),
            "request": _search_request_cell(search, self._search_cells("request")),
            "query": _search_query_cell(search, self._search_cells("query")),
            "time": _search_time_cell(search, self._search_cells("time")),
        }
        for column, value in cells.items():
            table.update_cell(_search_id(search), column, value)

    def _sync_search_selection(self, table: DataTable[Text]) -> None:
        if table.row_count == 0:
            self.selected_search_id = ""
            self._render_search_detail()
            return
        row = min(table.cursor_row, table.row_count - 1)
        self.selected_search_id = list(table.rows.keys())[row].value or ""

    def selected_search(self) -> dict[str, object] | None:
        """Return the currently selected served-search activity record."""
        return _record_with_id(self._searches, "request_id", self.selected_search_id)

    def watch_selected_search_id(self, _request_id: str) -> None:
        self._render_search_detail()

    def _render_search_title(self) -> None:
        found = self.query("#searchtitle")
        if not found:
            return
        active = self._search_counts.get("active", 0)
        recent = self._search_counts.get("recent", 0)
        title = Text(f"Served searches · {active} active · {recent} recent")
        if self._search_activity_last_refresh is not None:
            stamp = time.strftime(
                "%H:%M:%S", time.localtime(self._search_activity_last_refresh)
            )
            title.append(f" · refreshed {stamp}", style="dim")
        if self._search_activity_error is not None:
            title.append(
                f" · {self._search_activity_error}",
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
        query = _search_text(search.get("query"), fallback="query unavailable")
        detail = Text(f"query: {query}")
        source = _search_text(search.get("source"), fallback="source unavailable")
        search_type = _search_text(search.get("type"), fallback="type unavailable")
        root = _search_text(search.get("root"), fallback="root unavailable")
        top_k = count(search.get("top_k"))
        top_k_text = "—" if top_k is None else str(top_k)
        detail.append(
            f"\n{_search_id(search)} · source {source} · type {search_type}"
            f" · root {root}"
            f" · top_k {top_k_text}",
            style="dim",
        )
        status = count(search.get("status_code"))
        outcome = _search_text(search.get("outcome"), fallback="in progress")
        result_count = count(search.get("result_count"))
        status_text = "—" if status is None else str(status)
        result_count_text = "—" if result_count is None else str(result_count)
        total = measurement(search.get("total_seconds"))
        total_text = "—" if total is None else compact_duration(total)
        detail.append(
            f"\nstate {search.get('state', '—')} · outcome {outcome}"
            f" · status {status_text} · results {result_count_text}"
            f" · total {total_text}",
            style="dim",
        )
        started = measurement(search.get("started_at"))
        finished = measurement(search.get("finished_at"))
        started_text = "—" if started is None else str(started)
        finished_text = "—" if finished is None else str(finished)
        detail.append(
            f"\nstarted {started_text} · finished {finished_text}",
            style="dim",
        )
        timings = search.get("timings")
        if isinstance(timings, dict) and timings:
            measured = [
                (str(name), measurement(value))
                for name, value in sorted(
                    cast("dict[object, object]", timings).items(),
                    key=lambda item: str(item[0]),
                )
            ]
            values = [
                f"{name}={compact_duration(seconds)}"
                for name, seconds in measured
                if seconds is not None
            ]
            if values:
                detail.append(f"\ntimings {' · '.join(values)}", style="dim")
        availability = _search_text(search.get("availability_cause"), fallback="")
        error_code = _search_text(search.get("error_code"), fallback="")
        error_message = _search_text(search.get("error_message"), fallback="")
        if availability or error_code or error_message:
            detail.append(
                f"\navailability {availability or '—'} · error {error_code or '—'}"
                f" {error_message}".rstrip(),
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

    def _header_counts(self) -> list[tuple[str, int]]:
        """Count what the service holds, not what fits on the page.

        The service tallies every record matching the filter; the page is at
        most twenty of them. Re-tallying the page produces numbers that
        describe neither the list nor the service and that do not move when
        anything outside the page changes - so a deletion from a
        two-hundred-record history shows nowhere at all.

        The residue is named rather than dropped. Counters that quietly omit
        every state they have no bucket for sum to nothing in particular, and
        an operator cannot tell a missing state from a zero one.
        """
        summary = self._summary
        if isinstance(summary, dict):
            counted = cast("dict[str, object]", summary)
            counts = [
                (label, count(counted.get(key)) or 0) for label, key in _SUMMARY_BUCKETS
            ]
            tallied = sum(tally for _label, tally in counts)
            scope = self._total if self._total is not None else tallied
        else:
            states = [str(job.get("state", "")) for job in self._jobs]
            counts = [(label, states.count(key)) for label, key in _SUMMARY_BUCKETS]
            scope = len(self._jobs)
        other = scope - sum(tally for _label, tally in counts)
        if other > 0:
            counts.append(("other", other))
        return counts

    def _unicode_glyphs(self) -> bool:
        """Whether the console's encoding can carry the pill glyphs."""
        encoding = str(getattr(self.console, "encoding", "") or "")
        return "utf" in encoding.lower()

    def _append_separator(self, line: Text, *, unicode_ok: bool) -> None:
        """A dim divider, so each header group reads as its own cell run."""
        glyph, fallback = _GROUP_SEPARATORS
        line.append("  ")
        line.append(glyph if unicode_ok else fallback, style="dim")
        line.append(" ")

    def _append_state_pills(
        self,
        line: Text,
        fills: dict[str, tuple[str, str]],
        *,
        labelled: bool,
        unicode_ok: bool,
    ) -> None:
        """One pill per state bucket: glyph, count, and (wide) its label.

        A pill with work in it wears its token's solid fill; an empty one
        wears the muted fill so colour always means signal.
        """
        for key, tally in self._header_counts():
            spec = _STATE_PILLS.get(key)
            if spec is None:
                # The residue bucket, in the same anatomy as its neighbours.
                glyph, fallback = _OTHER_PILL_GLYPHS
                label, tone = key, "muted"
            else:
                glyph, fallback, label, tone, _bold = spec
            content = f"{glyph if unicode_ok else fallback} {tally}"
            if labelled:
                content += f" {label}"
            # One cell of air: the caps already separate pill from pill.
            line.append(" ")
            _append_pill(
                line,
                content,
                fills[tone if tally else "muted"],
                unicode_ok=unicode_ok,
            )

    def _append_health_pills(
        self,
        line: Text,
        fills: dict[str, tuple[str, str]],
        *,
        labelled: bool,
        unicode_ok: bool,
        lead_separator: bool = True,
    ) -> None:
        """The service's job-health tallies, in their own group."""
        summary = self._summary
        if not isinstance(summary, dict):
            return
        counted = cast("dict[str, object]", summary)
        present = [spec for spec in _HEALTH_PILLS if spec[0] in counted]
        if not present:
            # A daemon older than the tally; absent is not zero.
            return
        if lead_separator:
            self._append_separator(line, unicode_ok=unicode_ok)
        for index, (key, glyph, fallback, label, tone, _bold) in enumerate(present):
            tally = count(counted.get(key)) or 0
            content = f"{glyph if unicode_ok else fallback} {tally}"
            if labelled:
                content += f" {label}"
            if index:
                line.append(" ")
            _append_pill(
                line,
                content,
                fills[tone if tally else "muted"],
                unicode_ok=unicode_ok,
            )

    def _append_search_activity(self, line: Text, tones: dict[str, str]) -> None:
        """Keep served-search lane counts visible even when narrow hides its table."""
        self._append_separator(line, unicode_ok=self._unicode_glyphs())
        if self._search_activity_error is not None:
            line.append("search unavailable", style=tone_style(tones, "bad", bold=True))
            return
        if self._search_activity_last_refresh is None:
            line.append("search loading", style="dim")
            return
        active = self._search_counts.get("active", 0)
        recent = self._search_counts.get("recent", 0)
        line.append(
            f"search {active} active · {recent} recent",
            style=tone_style(tones, "good", bold=active > 0),
        )

    def _service_condition(self) -> str:
        """The service's condition verdict for the header pill.

        Reachability first, then the worst active degradation verdict the
        service has stamped - taken from the service's own tally where the
        summary carries one, from the stamped records on the page otherwise.
        Nothing is computed here; the service is the authority on both.
        """
        if self._last_error is not None:
            return "unreachable"
        summary = self._summary
        if isinstance(summary, dict):
            counted = cast("dict[str, object]", summary)
            if "stalled" in counted or "degraded" in counted:
                if count(counted.get("stalled")):
                    return "stalled"
                if count(counted.get("degraded")):
                    return "degraded"
                return "healthy"
        stamped = [
            verdict
            for verdict in (degradation_verdict(job) for job in self._jobs)
            if isinstance(verdict, str) and verdict in _CONDITION_ORDER
        ]
        if not stamped:
            # An older daemon stamps no verdicts; reachable is all it claims.
            return "reachable"
        return max(stamped, key=_CONDITION_ORDER.index)

    def _gpu_cell(self) -> tuple[str, str, bool]:
        """The GPU pressure cell as (text, tone, bold), honest about absence.

        Never fake numbers: a daemon that does not send the block renders as
        a muted dash, and one that probed an unmeasurable host as ``n/a``.
        The tone shift at high pressure is presentation only; any verdict
        about what the pressure means stays with the service.
        """
        if not self._gpu_reported:
            return "gpu —", "muted", False
        gpu = self._gpu or {}
        utilization = measurement(gpu.get("utilization_percent"))
        used = measurement(gpu.get("memory_used_mib"))
        total = measurement(gpu.get("memory_total_mib"))
        parts: list[str] = []
        pressure = 0.0
        if utilization is not None:
            parts.append(f"{utilization:.0f}%")
            pressure = max(pressure, utilization / 100.0)
        if used is not None and total is not None and total > 0:
            parts.append(f"{used / 1024:.1f}/{total / 1024:.1f}G")
            pressure = max(pressure, used / total)
        if not parts:
            return "gpu n/a", "muted", False
        if pressure >= 0.9:
            return f"gpu {' '.join(parts)}", "bad", True
        if pressure >= 0.75:
            return f"gpu {' '.join(parts)}", "attention", False
        return f"gpu {' '.join(parts)}", "good", False

    def _pressure_cell(self) -> tuple[str, str] | None:
        """The machine pressure pill as (text, tone), or nothing to show.

        Three answers, the same three the plain feed gives, so the two
        surfaces can never disagree: a daemon that sends no tier says
        nothing, a nominal tier is the healthy steady state and says
        nothing either, and any other tier is a verdict an operator must
        see. Silence is not a claim of health - the condition and GPU cells
        still report - and it keeps the steady-state header at the width it
        already had, so a pill nobody needs never costs a label somebody
        does. The tier is rendered verbatim: a tier this build has no tone
        for is still shown, because a newer daemon naming a worse state
        must never be swallowed.
        """
        tier = (self._pressure or {}).get("tier")
        if not isinstance(tier, str) or tier in ("", "nominal"):
            return None
        return f"pressure {tier}", "bad" if tier == "critical" else "attention"

    def _compose_header_line(
        self,
        tones: dict[str, str],
        *,
        state_labels: bool,
        health_labels: bool,
        split_before_service: bool = False,
        split_before_health: bool = False,
    ) -> Text:
        """Build the header row: grouped pills, condition, GPU, page count.

        The groups - state pills, health tallies, service condition, GPU,
        and the page count - are divided by dim separators so the row reads
        as cells rather than one cramped run. Labels are a width decision
        made by the caller; the condition and GPU cells are never dropped.
        ``split_before_service`` is the last width fallback: the row breaks
        deliberately at the service-group boundary instead of wherever the
        wrapper would land - never through the middle of a pill.
        """
        unicode_ok = self._unicode_glyphs()
        # The leading cell is identity: which daemon, at which release, on
        # which port. Identity is not signal, so it carries no semantic
        # tone - the version is the connected daemon's own report, and an
        # answering daemon that predates the field reads as unknown rather
        # than being filled from the local package.
        line = Text(f"{self._header_glyph()} vaultspec-rag", style="bold")
        if self._service_version:
            line.append(f" {self._service_version}")
        elif self._service_version_checked:
            line.append(" v?", style=tone_style(tones, "muted"))
        line.append(" · ", style="dim")
        line.append(f"port {self._port}", style="bold")
        fills = pill_fill(self.theme)
        self._append_state_pills(
            line, fills, labelled=state_labels, unicode_ok=unicode_ok
        )
        if split_before_health:
            line.append("\n")
        self._append_health_pills(
            line,
            fills,
            labelled=health_labels,
            unicode_ok=unicode_ok,
            lead_separator=not split_before_health,
        )
        if self._watch_mode == "server":
            self._append_search_activity(line, tones)
        if split_before_service:
            line.append("\n")
        else:
            self._append_separator(line, unicode_ok=unicode_ok)
        verdict = self._service_condition()
        condition_tone, _bold = _CONDITION_TONES[verdict]
        _append_pill(
            line,
            f"{'●' if unicode_ok else '*'} svc {verdict}",
            fills[condition_tone],
            unicode_ok=unicode_ok,
        )
        self._append_separator(line, unicode_ok=unicode_ok)
        gpu_text, gpu_tone, _gpu_bold = self._gpu_cell()
        _append_pill(line, gpu_text, fills[gpu_tone], unicode_ok=unicode_ok)
        pressure_cell = self._pressure_cell()
        if pressure_cell is not None:
            pressure_text, pressure_tone = pressure_cell
            self._append_separator(line, unicode_ok=unicode_ok)
            _append_pill(
                line, pressure_text, fills[pressure_tone], unicode_ok=unicode_ok
            )
        self._append_separator(line, unicode_ok=unicode_ok)
        shown = len(self._jobs)
        if self._total is None:
            line.append(f"showing {shown}")
        else:
            # A page onto a longer list is marked, because every count above
            # is a count of the page rather than of the service's work - and
            # because it is the only place a deletion shows when the freed
            # slot is immediately backfilled from the remainder.
            line.append(
                f"showing {shown} of {self._total}",
                style=tone_style(tones, "attention", bold=True)
                if self._total > shown
                else "",
            )
        return line

    def _summary_width(self) -> int:
        """The header bar's content width, or zero before its first layout."""
        found = self.query("#summary")
        if not found:
            return 0
        return found.only_one(Static).content_size.width

    def _render_summary(self) -> None:
        tones = semantic_tones(self.theme)
        width = self._summary_width()
        # Widest fitting form wins: labels leave the state pills first, then
        # the health tallies. Counts, the condition and the GPU cell are
        # never shed, and neither is the pressure pill on the occasions it
        # is painted at all; past the narrowest form the bar wraps.
        line = self._compose_header_line(tones, state_labels=True, health_labels=True)
        if 0 < width < _widest_line(line):
            line = self._compose_header_line(
                tones, state_labels=False, health_labels=True
            )
        if 0 < width < _widest_line(line):
            line = self._compose_header_line(
                tones, state_labels=False, health_labels=False
            )
        if 0 < width < _widest_line(line):
            # Narrower than even the unlabelled row: break it deliberately
            # at the service-group boundary, never through a pill.
            line = self._compose_header_line(
                tones,
                state_labels=False,
                health_labels=False,
                split_before_service=True,
            )
        if 0 < width < _widest_line(line):
            # Still too narrow: the health group takes its own row too, so
            # every row of the header holds whole groups of whole pills.
            line = self._compose_header_line(
                tones,
                state_labels=False,
                health_labels=False,
                split_before_service=True,
                split_before_health=True,
            )
        # The age of the data is reported whether or not the last fetch
        # failed - it is exactly when the service stops answering that an
        # operator needs to know how old what they are reading is. Suppressing
        # it on the error branch leaves stale rows on screen with nothing
        # saying they are stale.
        if self._last_refresh is None:
            line.append("\nloading", style="dim")
        else:
            stamp = time.strftime("%H:%M:%S", time.localtime(self._last_refresh))
            age = time.time() - self._last_refresh
            line.append(f"\nrefreshed {stamp}", style="dim")
            if age > max(5.0, self._interval * 3):
                line.append(
                    f" ({compact_duration(age)} ago)",
                    style=tone_style(tones, "attention", bold=True),
                )
        if self._last_error is not None:
            line.append(
                f"  ·  {self._last_error}",
                style=tone_style(tones, "bad", bold=True),
            )
        if not self._service_estimates:
            # Said once in the header rather than implied by every row's
            # empty estimate, which reads as unmeasurable work instead of
            # an older daemon.
            line.append("  ·  this service does not report time estimates", style="dim")
        if self._last_outcome is not None:
            text, token = self._last_outcome
            line.append(f"\n{text}", style=tone_style(tones, token, bold=True))
        self._append_selected_degradation(line, tones)
        summary = self.query("#summary")
        if summary:
            summary.only_one(Static).update(line)

    def _append_selected_degradation(self, line: Text, tones: dict[str, str]) -> None:
        """Show the selected job's unhealthy verdict and evidence in the header.

        The verdict and every finding come verbatim from the service payload
        through the same presentation helpers the CLI detail view renders -
        the header is the one place this view has room for whole sentences,
        and the row's own progress cell already carries the short form.
        """
        job = self.selected_job()
        if job is None:
            return
        verdict = degradation_verdict(job)
        if verdict is None or verdict == "healthy":
            return
        line.append(
            f"\n{_short_id(job)} {verdict}", style=tone_style(tones, "bad", bold=True)
        )
        evidence = "  ·  ".join(degradation_evidence_lines(job))
        if evidence:
            line.append(f"  ·  {evidence}", style=tone_style(tones, "bad"))

    # -- selection and logs -------------------------------------------------

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
        log.show_lines(_log_lines(result))
        # The window just changed, so what the noise filter hides and where
        # the errors sit changed with it - both the title's indicator and the
        # error-jump keys in the footer have to follow.
        self._refresh_log_title()
        self.refresh_bindings()

    def _log_view(self) -> JobsLogView | None:
        """Return the log pane's body, or ``None`` when it is not mounted."""
        return self._mounted("#joblog", JobsLogView)

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
        return self._mounted("#managedlog", ManagedLogTankView)

    def _refresh_managed_log_title(self) -> None:
        """Name the raw, source-grouped view mode and its refresh contract."""
        found = self.query("#managedlogtitle")
        if not found:
            return
        title = Text("Managed log tank · raw service + qdrant")
        if self._managed_logs_last_refresh is not None:
            stamp = time.strftime(
                "%H:%M:%S", time.localtime(self._managed_logs_last_refresh)
            )
            title.append(f" · refreshed {stamp}", style="dim")
        if self._managed_logs_error is not None:
            title.append(
                f" · {self._managed_logs_error}",
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
        return _record_with_id(self._jobs, "id", self.selected_id)

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
        flag = _action_capability(action)
        if flag is None:
            return True
        if not self._job_action_context_available():
            return None
        job = self.selected_job()
        if job is None or not _capability(job, flag):
            return None
        return True

    def _job_action_context_available(self) -> bool:
        """Whether a job mutation still names the visible indexing lane.

        A search-row selection intentionally leaves ``selected_id`` intact so
        returning to indexing restores its row. That retained id must not turn
        a served-search keypress into a control request for the now-hidden job.
        The same applies to the full-height managed-log view: it preserves
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
        action = _ACTION_KEYS.get(event.key)
        if action is None or self.check_action(action, ()) is True:
            return
        event.stop()
        event.prevent_default()
        self.notify(self._refusal(action), severity="warning")

    def _refusal(self, action: str) -> str:
        """Say why *action* is unavailable, in the operator's terms."""
        if action.startswith("log_"):
            if not self._log_visible():
                return _LOG_CLOSED_REASON
            return _ACTION_REASONS.get(
                action, "The log cannot take that action right now."
            )
        if (
            _action_capability(action) is not None
            and not self._job_action_context_available()
        ):
            return "Select an indexing job before sending a job action."
        if self.selected_job() is None:
            return "No job is selected."
        return _ACTION_REASONS.get(action, "This job cannot take that action.")

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
        self._show_log = not self._log_visible()
        self.screen.set_class(self._show_log, "-showlog")
        # The log keys gate on the pane being on screen, and the footer only
        # re-evaluates them when told to.
        self.refresh_bindings()

    def action_toggle_search(self) -> None:
        """Select the served-search lane without replacing its snapshot."""
        if self._managed_log_visible():
            self.action_toggle_managed_logs()
        if self._watch_mode == "jobs" and self._log_visible():
            self._show_log = False
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
        """Move between jobs and the full-height grouped raw-log view."""
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
        if self._show_log is None and screen is not None:
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
        flag, desired = _STATE_ACTIONS[action]
        del flag
        self._mark_pending(job, action, expected=desired.value)
        self._send_state(_job_id(job), desired, revision, action)

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
            send(_job_id(job))

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
        flag = _action_capability(f"job_{action}")
        if not self._job_action_context_available():
            self.notify(self._refusal(f"job_{action}"), severity="warning")
            return None
        job = self.selected_job()
        if job is None or flag is None or not _capability(job, flag):
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
        self._pending[_job_id(job)] = _Pending(
            action, expected, "requested", "", self._generation
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
        elif _is_gone(result):
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
        self._pending[job_id] = _Pending(
            marker.action if marker is not None else "control",
            marker.expected if marker is not None else None,
            outcome,
            detail,
            # Only a fetch issued after this point can carry the mutation, and
            # ``refresh_jobs`` below takes the next stamp.
            self._generation,
        )
        failed = outcome in {"refused", "gone"}
        # The tone token, not a resolved style: the outcome outlives theme
        # flips, so its colour is resolved at each render, never stored.
        self._last_outcome = (detail, "bad" if failed else "good")
        self.notify(detail, severity="error" if failed else "information")


def _fetch_error(result: dict[str, object] | None) -> str | None:
    """Return why a fetch cannot be believed, or ``None`` when it can.

    The transport does not raise on a service that answers badly: a timeout
    comes back as an ``ok: false`` envelope and a non-200 body is returned as
    it stands. Neither carries a ``jobs`` key, so reading the payload without
    checking would paint a wedged, erroring or unauthenticated daemon as "no
    jobs, refreshed just now" - a confident, current-looking, entirely false
    frame, and with a thirty-second administrative timeout it is the *normal*
    rendering of a hung service.
    """
    if result is None:
        return "service not reachable"
    if result.get("ok") is False:
        message = result.get("message")
        if isinstance(message, str) and message:
            return message
        error = result.get("error")
        return f"service error: {error}" if error else "the service reported an error"
    if not isinstance(result.get("jobs"), list):
        return "the service did not return a job list"
    return None


def _search_activity_error(result: dict[str, object] | None) -> str | None:
    """Return why an activity response cannot be rendered truthfully."""
    if result is None:
        return "served-search activity unavailable: service not reachable"
    if result.get("ok") is False:
        message = result.get("message")
        return (
            f"served-search activity unavailable: {message}"
            if isinstance(message, str) and message
            else "served-search activity unavailable: service reported an error"
        )
    return _search_activity_payload_error(result)


def _search_activity_payload_error(result: dict[str, object]) -> str | None:
    """Validate the bounded active/recent response envelope."""
    active = result.get("active")
    recent = result.get("recent")
    counts = result.get("counts")
    returned = result.get("returned")
    filters = result.get("filters")
    if not isinstance(active, list) or not isinstance(recent, list):
        return "served-search activity unavailable: invalid record lists"
    if not isinstance(counts, dict) or not isinstance(filters, dict):
        return "served-search activity unavailable: invalid summary"
    if count(returned) is None:
        return "served-search activity unavailable: invalid returned count"
    for name in ("active", "recent", "total"):
        if count(cast("dict[str, object]", counts).get(name)) is None:
            return "served-search activity unavailable: invalid counts"
    return _search_activity_records_error(
        cast("list[object]", active), cast("list[object]", recent)
    )


def _search_activity_records_error(
    active: list[object], recent: list[object]
) -> str | None:
    """Validate record identity, lane, and query privacy invariants."""
    seen: set[str] = set()
    for records, state in ((active, "active"), (recent, "terminal")):
        for record in records:
            if not isinstance(record, dict):
                return "served-search activity unavailable: invalid record"
            entry = cast("dict[str, object]", record)
            request_id = _search_id(entry)
            if (
                not request_id
                or request_id in seen
                or entry.get("state") != state
                or not isinstance(entry.get("query"), str)
            ):
                return "served-search activity unavailable: invalid record"
            seen.add(request_id)
    return None


def _search_records(raw: object, state: str) -> list[dict[str, object]]:
    """Narrow a validated activity lane to production records."""
    return [
        cast("dict[str, object]", record)
        for record in cast("list[object]", raw)
        if isinstance(record, dict)
        and cast("dict[str, object]", record).get("state") == state
    ]


def _is_gone(result: dict[str, object]) -> bool:
    """Report whether the service says the job the control named is absent."""
    return any(
        isinstance(value, str) and value in _GONE_CODES
        for value in (result.get("code"), result.get("error"))
    )


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
