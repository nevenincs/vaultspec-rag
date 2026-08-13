"""Row and detail cells for the jobs watch, and the text they are built from.

Every function here maps one record - a job or a served search - onto what a
single cell or detail line shows. None of them touch the app, the screen or a
transport: given the same record and the same width they return the same
``Text``, which is what lets the watch repaint a row from the record it
already holds.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, NamedTuple, cast

from rich.cells import cell_len
from rich.text import Text

from ..jobs import count, mapping, measurement, text
from ..search._outcomes import FAILED_ACTIVITY_OUTCOMES
from ._cli_format import compact_duration
from ._jobs_tui_constants import (
    ESTIMATE_KEY,
    PILL_CAP_LEFT,
    PILL_CAP_RIGHT,
    PILL_JOINER,
    TERMINAL_STATES,
)
from ._jobs_tui_palette import tone_style
from ._service_jobs_presentation import (
    human_progress,
    operation_label,
    phase_label,
    project_label,
    project_root,
    stale_progress_label,
)
from ._service_jobs_query import job_is_waiting

if TYPE_CHECKING:
    from collections.abc import Callable


def widest_line(line: Text) -> int:
    """The widest row of a possibly multi-row header, in cells."""
    return max(cell_len(part) for part in line.plain.split("\n"))


def append_pill(
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
        line.append(PILL_CAP_LEFT, style=background)
        line.append(
            content.replace(" ", PILL_JOINER),
            style=f"{foreground} on {background}",
        )
        line.append(PILL_CAP_RIGHT, style=background)
        return
    line.append(f" {content} ", style=f"{foreground} on {background}")


# The service-condition pill's vocabulary, worst-last, and its tones.
# ``reachable`` is what an older daemon that stamps no verdicts can claim.
CONDITION_ORDER = ("healthy", "degraded", "stalled")
CONDITION_TONES: dict[str, tuple[str, bool]] = {
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


def find_record(
    records: list[dict[str, object]],
    identity: Callable[[dict[str, object]], str],
    identifier: str,
) -> dict[str, object] | None:
    """Return the record *identity* reads as *identifier*, or ``None``.

    Both lanes resolve a selection the same way - the selected id is a value,
    not an index, so a record that moved or vanished between refreshes simply
    does not match. Which field carries the id is the only difference, and
    that is the reader passed in rather than a field name repeated here.
    """
    for record in records:
        if identity(record) == identifier:
            return record
    return None


def job_id_of(job: dict[str, object]) -> str:
    """Return the id the job publishes; empty means it cannot be addressed."""
    return text(job.get("id"))


def short_id(job: dict[str, object]) -> str:
    return job_id_of(job)[:8] or "unknown"


def search_id(search: dict[str, object]) -> str:
    """Return the request id the served search publishes, or empty."""
    return text(search.get("request_id"))


def search_text(value: object, *, fallback: str = "—") -> str:
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


def capability_flag(job: dict[str, object], flag: str) -> bool:
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


def row_animates(job: dict[str, object]) -> bool:
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


class Pending(NamedTuple):
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


class Tombstone(NamedTuple):
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


class PaintContext(NamedTuple):
    """Per-repaint paint state every row cell shares: frame and tones."""

    frame: str
    tones: dict[str, str]


def state_cell(
    job: dict[str, object],
    paint: PaintContext,
    pending: Pending | None,
    cells: int,
    *,
    deleted: bool = False,
) -> Text:
    """Render the state cell: phase, a live glyph, and any pending request."""
    tones = paint.tones
    label = phase_label(job)
    glyph = f"{paint.frame} " if row_animates(job) else "  "
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
        and str(state) not in TERMINAL_STATES
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


def job_cell(job: dict[str, object], cells: int) -> Text:
    initiator = job.get("initiator")
    kind = ""
    if isinstance(initiator, dict):
        kind = str(cast("dict[str, object]", initiator).get("kind") or "")
    subtitle = f"{short_id(job)} · {kind}" if kind else short_id(job)
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


def path_cell(job: dict[str, object], cells: int) -> Text:
    """Render the project and its root, tail-first when the root is long."""
    root = project_root(job)
    shown = _elide_left(root, cells) if root else "path not reported"
    return _two_line(project_label(job), shown, cells)


def progress_cell(
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


def time_cell(
    job: dict[str, object],
    cells: int,
    *,
    ticked: float | None = None,
) -> Text:
    remaining = measurement(job.get(ESTIMATE_KEY))
    if remaining is not None:
        shown = ticked if ticked is not None else remaining
        # Ceiling, not truncation: the countdown must never read below the
        # value the service just published, and the coarse two-unit
        # rendering already strips any precision the estimate lacks.
        estimate = f"~{compact_duration(math.ceil(shown))} left"
    elif (
        ESTIMATE_KEY in job
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


def search_state_cell(
    search: dict[str, object], cells: int, tones: dict[str, str]
) -> Text:
    """Render lifecycle state and terminal outcome without result bodies."""
    state = search_text(search.get("state"), fallback="unknown")
    outcome = search_text(search.get("outcome"), fallback="serving")
    tone = "good" if state == "active" else "muted"
    if outcome in FAILED_ACTIVITY_OUTCOMES:
        tone = "bad"
    return _two_line(
        state,
        outcome,
        cells,
        top_style=tone_style(tones, tone, bold=state == "active"),
    )


def search_request_cell(search: dict[str, object], cells: int) -> Text:
    """Render stable request identity with type, root, and requested depth."""
    request_id = search_id(search) or "unknown"
    source = search_text(search.get("source"), fallback="source unavailable")
    search_type = search_text(search.get("type"), fallback="type unavailable")
    root = search_text(search.get("root"), fallback="root unavailable")
    top_k = count(search.get("top_k"))
    depth = str(top_k) if top_k is not None else "—"
    return _two_line(
        f"{request_id[:12]} · {source}/{search_type}",
        f"{_elide_left(root, cells)} · top {depth}",
        cells,
    )


def search_query_cell(search: dict[str, object], cells: int) -> Text:
    """Render authenticated in-memory query text, never a result payload.

    A redacted record is shown as redacted rather than as missing: the
    service withheld the text deliberately, and an operator reading
    "query unavailable" would go looking for a fault that is not there.
    """
    fallback = (
        "query redacted"
        if search.get("query_redacted") is True
        else "query unavailable"
    )
    query = search_text(search.get("query"), fallback=fallback)
    availability = search_text(search.get("availability_cause"), fallback="")
    error = search_text(search.get("error_message"), fallback="")
    return _two_line(query, availability or error, cells, top_style="bold")


def search_time_cell(search: dict[str, object], cells: int) -> Text:
    """Render duration, status, and result count from the activity record."""
    total = measurement(search.get("total_seconds"))
    duration = compact_duration(total) if total is not None else "in progress"
    status = count(search.get("status_code"))
    results = count(search.get("result_count"))
    return _two_line(
        duration,
        f"HTTP {status if status is not None else '—'} · "
        f"{results if results is not None else '—'} results",
        cells,
    )


def _search_reading_text(
    value: object,
    reader: Callable[[object], float | int | None],
) -> str:
    """Render one numeric activity field, dashed where none was published.

    The reader is the only thing that varies between the fields this
    renders: a whole-number field narrows through :func:`count`, an
    epoch-second field through :func:`measurement`. Both dash on a value
    the service did not publish, so the rendering itself is shared.
    """
    reading = reader(value)
    return "—" if reading is None else str(reading)


def search_identity_line(search: dict[str, object]) -> str:
    """Name the request, its lane, the corpus it read, and its asked-for depth."""
    source = search_text(search.get("source"), fallback="source unavailable")
    search_type = search_text(search.get("type"), fallback="type unavailable")
    root = search_text(search.get("root"), fallback="root unavailable")
    return (
        f"{search_id(search)} · source {source} · type {search_type}"
        f" · root {root}"
        f" · top_k {_search_reading_text(search.get('top_k'), count)}"
    )


def search_outcome_line(search: dict[str, object]) -> str:
    """Report lifecycle state, verdict, transport status, and result volume."""
    outcome = search_text(search.get("outcome"), fallback="in progress")
    total = measurement(search.get("total_seconds"))
    total_text = compact_duration(total) if total is not None else "—"
    return (
        f"state {search.get('state', '—')} · outcome {outcome}"
        f" · status {_search_reading_text(search.get('status_code'), count)}"
        f" · results {_search_reading_text(search.get('result_count'), count)}"
        f" · total {total_text}"
    )


def search_clock_line(search: dict[str, object]) -> str:
    """Report the wall-clock bounds the service stamped on the request."""
    started = _search_reading_text(search.get("started_at"), measurement)
    finished = _search_reading_text(search.get("finished_at"), measurement)
    return f"started {started} · finished {finished}"


def search_timings_line(search: dict[str, object]) -> str:
    """Break the request down by stage, empty where the service timed none."""
    timings = [
        (str(name), measurement(value))
        for name, value in mapping(search.get("timings")).items()
    ]
    values = [
        f"{name}={compact_duration(seconds)}"
        for name, seconds in sorted(timings, key=lambda item: item[0])
        if seconds is not None
    ]
    return f"timings {' · '.join(values)}" if values else ""


def search_failure_line(search: dict[str, object]) -> str:
    """Name why a request degraded or failed, empty where it did neither."""
    availability = search_text(search.get("availability_cause"), fallback="")
    error_code = search_text(search.get("error_code"), fallback="")
    error_message = search_text(search.get("error_message"), fallback="")
    if not (availability or error_code or error_message):
        return ""
    return (
        f"availability {availability or '—'} · error {error_code or '—'}"
        f" {error_message}"
    ).rstrip()
