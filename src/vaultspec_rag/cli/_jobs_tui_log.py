"""Structured rendering for the jobs interface's log pane.

The service's log window interleaves three dialects: the application's own
structured events (``timestamp LEVEL logger: message key=value ...``), the
HTTP server's access lines (``INFO:     client - "GET /path HTTP/1.1" 200``),
and the vector backend's request lines (an ISO UTC stamp, a level, an actix
target, then the request in quotes). Each is parsed into fields and rendered
as a formatted block: a level badge, a local-time stamp, the event or request
prominent, and the key=value detail wrapped beneath it.

Two rules hold throughout:

* Parsing never invents content. A field a line did not carry is absent -
  never defaulted to a zero, an empty status, or a stamp that looks reported.
* No line is dropped silently and none is rendered raw. A line matching no
  dialect is sanitized - ANSI escapes stripped, control characters removed,
  length bounded - and shown as it stands. Log content is adversarial input:
  an escape sequence must be inert on this screen, not replayed into it.

Most of the window is the interface's own polling reflected back: the access
lines its jobs and log fetches produce. Those collapse by default behind a
counted marker in the pane, and the pane's title says the filter is active -
hidden lines with no indicator would be silent degradation, which is exactly
what this view exists to remove.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast

from rich.text import Text
from textual.widgets import RichLog

from ._jobs_tui_palette import semantic_tones

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from textual.app import App
    from textual.events import Resize

__all__ = [
    "JobsLogView",
    "LogEntry",
    "parse_log_line",
    "sanitize_log_text",
]

# Terminal escape sequences, in every shape a hostile line can carry them:
# CSI (colours, cursor movement), OSC (titles, hyperlinks), and the remaining
# single-character C1 escapes. Stripped before anything else looks at the
# line, so no rendered field can replay one into the operator's terminal.
_ANSI_RE = re.compile(
    r"\x1b\[[0-9;:?]*[ -/]*[@-~]"  # CSI sequences
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?"  # OSC sequences
    r"|\x1b[@-_]"  # other C1 escapes
)

# Every remaining C0 control character and DEL is deleted; a tab becomes a
# space so tab-separated content stays word-separated rather than fused.
_CONTROL_TRANSLATION: dict[int, int | None] = dict.fromkeys((*range(32), 127))
_CONTROL_TRANSLATION[0x09] = 0x20

# A line longer than this is truncated with a visible mark. The bound exists
# for the pathological line - a traceback fused onto one line, a megabyte of
# base64 - whose full text would make the pane unusable; the mark keeps the
# truncation honest.
_MAX_LINE_CHARS = 2000

# The application's own structured lines: local timestamp, level, logger.
_APP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})[ T]"
    r"(?P<time>\d{2}:\d{2}:\d{2})(?:[.,]\d+)?\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<logger>[A-Za-z_][\w.]*):\s?(?P<rest>.*)$"
)

# The HTTP server's access lines. They carry no timestamp at all.
_ACCESS_RE = re.compile(
    r"^(?P<level>[A-Z]+):\s+(?P<client>\S+) - "
    r'"(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[0-9.]+" '
    r"(?P<status>\d{3})(?: (?P<reason>.+))?$"
)

# The vector backend's lines: an ISO UTC stamp, a level, an actix target.
_QDRANT_RE = re.compile(
    r"^(?P<stamp>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z)\s+"
    r"(?P<level>[A-Z]+)\s+"
    r"(?P<target>[\w:]+):\s?(?P<rest>.*)$"
)

# The request inside a backend line: client, quoted request, status, size,
# referer, agent, then the duration in seconds.
_QDRANT_REQUEST_RE = re.compile(
    r'^(?P<client>\S+) "(?P<method>[A-Z]+) (?P<path>\S+) HTTP/[0-9.]+" '
    r'(?P<status>\d{3}) (?P<size>\d+) "[^"]*" "[^"]*" '
    r"(?P<duration>\d+(?:\.\d+)?)$"
)

_PAIR_RE = re.compile(r"^(?P<key>[A-Za-z_][\w.\-]*)=(?P<value>.*)$")

# Routes this interface (and the watch loop behind it) polls on a timer. A
# GET reflected back from one of these says nothing an operator cannot see on
# the screen already; everything else - mutations, other clients, errors - is
# signal and stays visible.
_POLLING_ROUTES = (
    "/jobs",
    "/logs",
    "/health",
    "/metrics",
    "/projects",
    "/watcher",
    "/storage/survey",
)

_ERROR_LEVELS = frozenset({"ERROR", "CRITICAL", "FATAL"})

# Level -> (semantic tone, bold). Tones, not colours: every status colour on
# this surface resolves from the active theme's palette so the same badge is
# right in the dark and the light scheme alike.
_LEVEL_TONES: dict[str, tuple[str, bool]] = {
    "ERROR": ("bad", True),
    "CRITICAL": ("bad", True),
    "FATAL": ("bad", True),
    "WARNING": ("attention", False),
    "WARN": ("attention", False),
    "INFO": ("muted", False),
    "DEBUG": ("muted", False),
    "TRACE": ("muted", False),
}


# Fixed leading columns, so every entry's content starts on the same cell:
# an eight-cell local time, a space, then an eight-cell level badge.
_TIME_CELLS = 8
_BADGE_CELLS = 8
_DETAIL_INDENT = "    "

# A value longer than this is middle-elided - the head names the thing and
# the tail discriminates it, so both survive - unless the operator has asked
# for full values. The full entry is always one keypress away.
_VALUE_CELLS = 48


def sanitize_log_text(text: str) -> str:
    """Return *text* safe to paint: escapes stripped, length bounded.

    Order matters: escapes are stripped before control characters are
    deleted, because deleting the ESC first would leave the printable body
    of a CSI sequence (``[31m``) behind as visible garbage.
    """
    cleaned = _ANSI_RE.sub("", text).translate(_CONTROL_TRANSLATION)
    if len(cleaned) > _MAX_LINE_CHARS:
        cleaned = cleaned[: _MAX_LINE_CHARS - 1] + "…"
    return cleaned


@dataclass(frozen=True, slots=True)
class LogEntry:
    """One log line, parsed as far as its dialect allows.

    A field the line did not carry is ``None`` - absent, not defaulted to
    something that looks reported. ``raw`` always holds the whole sanitized
    line, so nothing a parse discarded is unrecoverable.
    """

    kind: str  # "app" | "access" | "qdrant" | "raw"
    raw: str
    level: str | None = None
    timestamp: str | None = None
    origin: str | None = None
    event: str | None = None
    message: str | None = None
    pairs: tuple[tuple[str, str], ...] = ()
    method: str | None = None
    path: str | None = None
    status: str | None = None
    reason: str | None = None
    duration_ms: float | None = None

    @property
    def is_error(self) -> bool:
        """Whether this entry is an error an operator would jump to."""
        if (self.level or "").upper() in _ERROR_LEVELS:
            return True
        return self.status is not None and self.status.startswith("5")

    @property
    def is_polling(self) -> bool:
        """Whether this is the interface's own polling reflected back."""
        if self.kind != "access" or self.method != "GET" or self.path is None:
            return False
        base = self.path.partition("?")[0]
        return any(
            base == route or base.startswith(route + "/") for route in _POLLING_ROUTES
        )


def _split_pairs(rest: str) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Split a message tail into leading prose and trailing key=value pairs.

    A word that is not a pair but follows one is a continuation of the
    previous pair's value (``error=CUDA out of memory``), not new prose:
    reattaching it keeps spaced values whole without inventing a delimiter
    the line never had.
    """
    prose: list[str] = []
    pairs: list[list[str]] = []
    for word in rest.split():
        match = _PAIR_RE.match(word)
        if match is not None:
            pairs.append([match.group("key"), match.group("value")])
        elif pairs:
            pairs[-1][1] = f"{pairs[-1][1]} {word}"
        else:
            prose.append(word)
    return " ".join(prose), tuple((key, value) for key, value in pairs)


def _local_time(stamp: str) -> str | None:
    """Convert an ISO UTC stamp to local wall-clock, or ``None`` unparsed."""
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    return parsed.astimezone().strftime("%H:%M:%S")


def _parse_app_line(match: re.Match[str], raw: str) -> LogEntry:
    prose, pairs = _split_pairs(match.group("rest"))
    event = None
    kept: list[tuple[str, str]] = []
    for key, value in pairs:
        if key == "event" and event is None:
            event = value
        else:
            kept.append((key, value))
    return LogEntry(
        kind="app",
        raw=raw,
        level=match.group("level"),
        timestamp=match.group("time"),
        origin=match.group("logger"),
        event=event,
        message=prose or None,
        pairs=tuple(kept),
    )


def _parse_qdrant_line(match: re.Match[str], raw: str) -> LogEntry:
    rest = match.group("rest")
    request = _QDRANT_REQUEST_RE.match(rest)
    if request is None:
        return LogEntry(
            kind="qdrant",
            raw=raw,
            level=match.group("level"),
            timestamp=_local_time(match.group("stamp")),
            origin=match.group("target"),
            message=rest or None,
        )
    return LogEntry(
        kind="qdrant",
        raw=raw,
        level=match.group("level"),
        timestamp=_local_time(match.group("stamp")),
        origin=request.group("client"),
        method=request.group("method"),
        path=request.group("path"),
        status=request.group("status"),
        duration_ms=float(request.group("duration")) * 1000.0,
    )


def parse_log_line(line: str) -> LogEntry:
    """Parse one sanitized line into the dialect it matches, or raw."""
    cleaned = sanitize_log_text(line).rstrip()
    access = _ACCESS_RE.match(cleaned)
    if access is not None:
        return LogEntry(
            kind="access",
            raw=cleaned,
            level=access.group("level"),
            origin=access.group("client"),
            method=access.group("method"),
            path=access.group("path"),
            status=access.group("status"),
            reason=access.group("reason"),
        )
    qdrant = _QDRANT_RE.match(cleaned)
    if qdrant is not None:
        return _parse_qdrant_line(qdrant, cleaned)
    app = _APP_RE.match(cleaned)
    if app is not None:
        return _parse_app_line(app, cleaned)
    return LogEntry(kind="raw", raw=cleaned)


def _elide_middle(value: str, cells: int) -> str:
    """Trim *value* to *cells*, keeping its head and tail.

    The head of a path or an id names the thing; the tail discriminates it
    from its siblings. The middle is the part an operator can spare.
    """
    if cells <= 1 or len(value) <= cells:
        return value
    head = (cells - 1 + 1) // 2
    tail = cells - 1 - head
    return f"{value[:head]}…{value[-tail:]}" if tail else f"{value[:head]}…"


def _status_style(status: str, tones: Mapping[str, str]) -> str:
    if status.startswith("5"):
        return f"bold {tones['bad']}"
    if status.startswith("4"):
        return tones["attention"]
    return tones["good"]


def _duration_label(duration_ms: float) -> str:
    if duration_ms >= 1000.0:
        return f"{duration_ms / 1000.0:.2f}s"
    return f"{duration_ms:.0f}ms"


def _lead(entry: LogEntry, tones: Mapping[str, str]) -> Text:
    """The fixed columns every entry starts with: time, then a level badge."""
    line = Text()
    line.append(f"{entry.timestamp or '':<{_TIME_CELLS}}", style="dim")
    line.append(" ")
    level = entry.level or ""
    tone, bold = _LEVEL_TONES.get(level.upper(), ("", False))
    colour = tones.get(tone, "") if tone else ""
    style = f"bold {colour}".strip() if bold else colour
    line.append(f"{level:<{_BADGE_CELLS}}"[:_BADGE_CELLS], style=style)
    return line


def _append_request(
    line: Text,
    entry: LogEntry,
    tones: Mapping[str, str],
    *,
    width: int,
    expanded: bool,
) -> None:
    """Append the request summary: method, path, status, timing."""
    if entry.method is not None:
        line.append(entry.method, style="bold")
        line.append(" ")
    if entry.path is not None:
        # Capped to what the pane leaves after the lead columns and the
        # status tail, so the one line an operator scans stays one line.
        cap = min(_VALUE_CELLS, max(12, width - 30))
        shown = entry.path if expanded else _elide_middle(entry.path, cap)
        line.append(shown)
    if entry.status is not None:
        line.append(" → ", style="dim")
        line.append(entry.status, style=_status_style(entry.status, tones))
    if entry.reason is not None:
        line.append(f" {entry.reason}", style="dim")
    if entry.duration_ms is not None:
        line.append(f"  {_duration_label(entry.duration_ms)}", style="dim")
    if entry.origin is not None:
        line.append(f"  · {entry.origin}", style="dim")


def _header_line(
    entry: LogEntry,
    tones: Mapping[str, str],
    *,
    width: int,
    expanded: bool,
) -> Text:
    line = _lead(entry, tones)
    line.append(" ")
    if entry.method is not None or entry.status is not None:
        _append_request(line, entry, tones, width=width, expanded=expanded)
        return line
    prominent = entry.event or entry.message
    if prominent is not None:
        line.append(
            prominent,
            style=f"bold {tones['bad']}" if entry.is_error else "bold",
        )
    if entry.origin is not None:
        line.append(f"  · {entry.origin}", style="dim")
    return line


def _pair_lines(
    pairs: tuple[tuple[str, str], ...],
    *,
    width: int,
    expanded: bool,
) -> list[Text]:
    """Pack key=value pairs into indented lines that fit *width*."""
    if not pairs:
        return []
    room = max(20, width - len(_DETAIL_INDENT))
    lines: list[Text] = []
    current = Text(_DETAIL_INDENT)
    used = 0
    for key, value in pairs:
        # The cap is the narrower of the standing bound and what this pane
        # can actually show beside the key, so a lone pair fits its line
        # instead of folding awkwardly mid-value on a narrow pane.
        cap = min(_VALUE_CELLS, max(8, room - len(key) - 1))
        shown = value if expanded else _elide_middle(value, cap)
        cost = len(key) + 1 + len(shown) + (2 if used else 0)
        if used and used + cost > room:
            lines.append(current)
            current = Text(_DETAIL_INDENT)
            used = 0
            cost = len(key) + 1 + len(shown)
        if used:
            current.append("  ")
        current.append(key, style="dim")
        current.append("=", style="dim")
        current.append(shown)
        used += cost
    lines.append(current)
    return lines


def render_entry(
    entry: LogEntry,
    *,
    width: int,
    expanded: bool = False,
    quiet: bool = False,
    tones: Mapping[str, str] | None = None,
) -> list[Text]:
    """Render one entry as its formatted lines.

    Args:
        entry: The parsed entry.
        width: Cells available to a line; detail pairs are packed to it.
        expanded: Show values whole instead of middle-elided.
        quiet: Dim the whole entry - polling noise an operator chose to see.
        tones: The active theme's semantic tones; ``None`` resolves the
            no-theme fallbacks, for a render outside a running app.

    Returns:
        The lines to write, at least one. A raw entry is its sanitized text.
    """
    resolved = tones if tones is not None else semantic_tones("")
    if entry.kind == "raw":
        lines = [Text(entry.raw or " ")]
    else:
        lines = [_header_line(entry, resolved, width=width, expanded=expanded)]
        lines.extend(_pair_lines(entry.pairs, width=width, expanded=expanded))
    if quiet:
        for line in lines:
            line.stylize("dim")
    return lines


class JobsLogView(RichLog):
    """The log pane: parsed entries, collapsed polling noise, error jumps.

    Content arrives as raw lines through :meth:`show_lines` and is kept as
    parsed entries, so the same window can be re-rendered when the pane's
    width changes, when the noise filter toggles, and when full values are
    asked for - without refetching anything.
    """

    def __init__(self, *, id: str | None = None) -> None:
        # Named to match the base widget's parameter.
        #
        # ``min_width=1``: the base widget's default floor is wider than a
        # split pane, and a line rendered at the floor is cropped by the
        # compositor instead of wrapped by the widget - the tail of every
        # long line would silently vanish off the pane's edge.
        super().__init__(wrap=True, markup=False, auto_scroll=True, min_width=1, id=id)
        # Focusable, so the pane can take the keyboard: focus lights the
        # pane's frame, gives the arrow keys to the scroll view, and makes
        # this pane the target of the zoom key.
        self.can_focus = True
        self._entries: list[LogEntry] = []
        self._message: str | None = None
        self._show_polling = False
        self._expanded = False
        # Rendered line offset of each error entry, in written order, and
        # which of them the last jump landed on.
        self._error_offsets: list[int] = []
        self._error_cursor = -1
        self._rendered_width = 0

    # -- content ------------------------------------------------------------

    def show_lines(self, lines: Iterable[str]) -> None:
        """Replace the pane's content with *lines*, parsed and rendered."""
        self._entries = [parse_log_line(line) for line in lines]
        self._message = None
        self._render_entries()

    def show_message(self, message: str) -> None:
        """Replace the pane's content with a single plain sentence."""
        self._entries = []
        self._message = message
        self._render_entries()

    # -- filter state -------------------------------------------------------

    @property
    def polling_count(self) -> int:
        """How many entries in the window are polling reflections."""
        return sum(1 for entry in self._entries if entry.is_polling)

    @property
    def hidden_polling_count(self) -> int:
        """How many entries the noise filter is currently hiding."""
        return 0 if self._show_polling else self.polling_count

    @property
    def polling_shown(self) -> bool:
        return self._show_polling

    @property
    def error_count(self) -> int:
        """How many rendered entries are errors (level or 5xx status)."""
        return len(self._error_offsets)

    def toggle_polling(self) -> bool:
        """Flip the noise filter and repaint. Returns the new shown-state."""
        self._show_polling = not self._show_polling
        self._render_entries()
        return self._show_polling

    def toggle_expanded(self) -> bool:
        """Flip full-value rendering and repaint. Returns the new state."""
        self._expanded = not self._expanded
        self._render_entries()
        return self._expanded

    # -- navigation ---------------------------------------------------------

    def jump_top(self) -> None:
        self.scroll_home(animate=False)

    def jump_end(self) -> None:
        self.scroll_end(animate=False)

    def jump_next_error(self) -> bool:
        """Scroll to the error after the last one jumped to, wrapping."""
        if not self._error_offsets:
            return False
        self._error_cursor = (self._error_cursor + 1) % len(self._error_offsets)
        self.scroll_to(y=self._error_offsets[self._error_cursor], animate=False)
        return True

    def jump_previous_error(self) -> bool:
        """Scroll to the error before the last one jumped to, wrapping."""
        if not self._error_offsets:
            return False
        self._error_cursor = (self._error_cursor - 1) % len(self._error_offsets)
        self.scroll_to(y=self._error_offsets[self._error_cursor], animate=False)
        return True

    # -- rendering ----------------------------------------------------------

    def on_resize(self, event: Resize) -> None:
        """Re-pack the detail lines when the pane's width changes.

        The base handler flushes writes deferred while the size was unknown,
        so it runs first; the re-render then replaces them at the width the
        pane actually has.
        """
        super().on_resize(event)
        if (self._entries or self._message is not None) and (
            self._content_width() != self._rendered_width
        ):
            self._render_entries()

    def on_show(self) -> None:
        """Render for real once the pane is actually on screen.

        Writes issued while the widget is hidden are deferred with no line
        accounting, so the error offsets recorded then describe nothing.
        """
        if self._entries or self._message is not None:
            self._render_entries()

    def _content_width(self) -> int:
        width = self.scrollable_content_region.width or self.content_size.width
        return max(24, width)

    def repaint_theme(self) -> None:
        """Re-render the held window under the active theme's tones."""
        if self._entries or self._message is not None:
            self._render_entries()

    def _tones(self) -> dict[str, str]:
        """The active palette variant's tones, resolved fresh per render."""
        app = cast("App[object]", self.app)
        return semantic_tones(app.theme)

    def _render_entries(self) -> None:
        self.clear()
        self._error_offsets = []
        self._error_cursor = -1
        width = self._content_width()
        self._rendered_width = width
        if self._message is not None:
            self.write(Text(self._message))
            return
        tones = self._tones()
        hidden = 0
        for entry in self._entries:
            if entry.is_polling and not self._show_polling:
                hidden += 1
                continue
            hidden = self._flush_hidden(hidden)
            if entry.is_error:
                self._error_offsets.append(len(self.lines))
            for line in render_entry(
                entry,
                width=width,
                expanded=self._expanded,
                quiet=entry.is_polling,
                tones=tones,
            ):
                self.write(line)
        self._flush_hidden(hidden)

    def _flush_hidden(self, hidden: int) -> int:
        """Mark a collapsed run of polling lines where it sat. Returns 0."""
        if hidden:
            noun = "polling line" if hidden == 1 else "polling lines"
            self.write(
                Text(f"· {hidden} {noun} hidden — x shows them", style="dim italic")
            )
        return 0
