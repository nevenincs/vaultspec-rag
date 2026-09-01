"""Startup status reporting for long-running CLI commands.

A command that spends minutes waiting on a daemon, a download, or a model load
has to keep saying so. This module owns the reporter every such command drives.

This is a deliberately separate vocabulary from the indexer's progress reporter
in ``vaultspec_rag.progress``. That one describes determinate work - phases with
known totals, advanced one completed unit at a time - and renders a bar. This
one describes an indeterminate wait, where there is nothing to count and the
only honest signal is which activity is currently blocking and that it is still
going. ``announce`` and ``heartbeat`` have no counterpart there, and a progress
bar has none here; collapsing the two would give either a bar with no
denominator or a spinner that cannot report completion.

Two placement rules keep the output correct, and they are deliberately
asymmetric.

The live region and every human line share ONE console. Rich positions a live
region from what it alone has rendered, so a line printed through a second
console on the same stream is invisible to that bookkeeping: it lands welded
onto the spinner frame, which the region then erases as though it owned it.
Sharing one console is what lets Rich's render hooks erase the frame, emit the
line, and repaint. This is not hypothetical - the start path prints lifecycle
warnings straight to the shared console while a region is open, bypassing this
reporter entirely, so the reporter cannot fix it by routing its own output.

Off a terminal the static lines go to stderr instead. There is no live region in
that mode, so no collision is possible, and keeping progress chatter off stdout
preserves stdout as the parseable result channel. Do not "simplify" these two
rules into one: sending the interactive lines to stderr reintroduces the
collision, and sending the static lines to stdout pollutes the result channel.

Whether the shared console animates at all is decided by the real stdout
terminal rather than by Rich's own detection, and ``--json`` mode is silent on
both streams, because a machine-readable lifecycle verb owes stdout exactly one
structured envelope.
"""

from __future__ import annotations

import threading
import time
from typing import TYPE_CHECKING

from rich.live import Live
from rich.spinner import Spinner

import vaultspec_rag.cli as _cli

from .._rich_console import supports_live
from ._core import _build_console, _stdout_is_tty, logger

if TYPE_CHECKING:
    from collections.abc import Callable

    from rich.console import Console

__all__ = ["StartupStatusReporter"]

# Rich's own default for ``Console.status``; fast enough to read as motion.
_REFRESH_PER_SECOND = 12.5

# A stream can close or be replaced underneath a long-running command (a
# closed pipe, a terminal that went away, a capture buffer torn down). Progress
# is decoration: it degrades to silence rather than failing the command.
_STREAM_GONE = (OSError, ValueError)


class StartupStatusReporter:
    """Report the progress of one long-running command to its operator.

    Used as a context manager wrapping the command body. On an interactive
    stream the block is covered by an animated live region whose caption tracks
    the current activity; otherwise the same activity is reported as plain
    rate-limited lines on stderr. In ``--json`` mode nothing is emitted at all,
    because a machine-readable lifecycle verb must put exactly one structured
    envelope on stdout and any progress text would corrupt it.

    Entering is re-entrant: nested blocks share the one live region, which is
    torn down when the outermost block exits.
    """

    def __init__(
        self,
        *,
        json_mode: bool,
        console: Console | None = None,
        interactive: bool | None = None,
        static_interval_s: float = 5.0,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Build a reporter.

        Args:
            json_mode: Suppress every emission, for machine-readable output.
            console: Console driving both the live region and the lines,
                overriding the default stream choice entirely. Defaults to the
                shared CLI console when animating, and to a stderr console
                otherwise.
            interactive: Force animated or plain reporting. ``None`` decides
                from the real stdout terminal, which is the production path and
                the same decision the shared console was built from; passing a
                value drives either mode deterministically.
            static_interval_s: Minimum seconds between plain heartbeat lines.
            now: Monotonic clock used for that rate limit.
        """
        self._json_mode = json_mode
        self._console_override = console
        self._interactive = _stdout_is_tty() if interactive is None else interactive
        self._static_interval_s = static_interval_s
        self._now = now
        self._lock = threading.RLock()
        self._depth = 0
        self._live: Live | None = None
        self._live_console: Console | None = None
        self._spinner: Spinner | None = None
        self._stderr_console: Console | None = None
        self._label: str | None = None
        self._last_static_emit: float | None = None

    def __enter__(self) -> StartupStatusReporter:
        """Open the live region on the outermost entry."""
        with self._lock:
            self._depth += 1
            if (
                self._depth == 1
                and not self._json_mode
                and self._interactive
                and supports_live(self._target_console())
            ):
                self._start_live()
        return self

    def __exit__(self, *exc: object) -> None:
        """Tear the live region down once the outermost block exits."""
        with self._lock:
            self._depth = max(0, self._depth - 1)
            if self._depth == 0:
                self._stop_live()

    def announce(self, line: str) -> None:
        """Print one line immediately, whatever the stream is.

        This is the guarantee that the command has visibly started, so it is
        never deduped, never rate limited, and never conditional on a terminal.
        """
        if self._json_mode:
            return
        with self._lock:
            self._emit(line)

    def stage(self, label: str) -> None:
        """Declare the current activity.

        Animated: becomes the live caption, rendered at once. Plain: printed as
        a line, skipping a label identical to the one already showing.
        """
        if self._json_mode:
            return
        with self._lock:
            if self._render_live(label):
                return
            if label == self._label:
                return
            self._emit_static(label)

    def heartbeat(self, label: str) -> None:
        """Refresh the current activity even when nothing has changed.

        An idle wait still has to tick visibly. Animated: repaints the live
        caption. Plain: prints at most one line per ``static_interval_s``, so a
        piped log shows liveness without flooding.
        """
        if self._json_mode:
            return
        with self._lock:
            if self._render_live(label):
                return
            last = self._last_static_emit
            if last is not None and self._now() - last < self._static_interval_s:
                return
            self._emit_static(label)

    def _target_console(self) -> Console:
        """Resolve the console to write through, at call time.

        Late binding is required rather than stylistic: tests substitute
        ``vaultspec_rag.cli.console`` at runtime, and a module-scope import of
        the console object would bind past every such substitution and silently
        render it inert.

        While a live region is open its console is returned unconditionally,
        even if the package namespace has since been repointed. The region and
        the lines printed around it must be the same console object, or Rich
        cannot erase the frame before the line lands.
        """
        if self._live_console is not None:
            return self._live_console
        if self._console_override is not None:
            return self._console_override
        if self._interactive:
            return _cli.console
        if self._stderr_console is None:
            self._stderr_console = _build_console(interactive=False, stderr=True)
        return self._stderr_console

    def _emit_static(self, label: str) -> None:
        """Print a progress line and arm the rate limit against it."""
        self._label = label
        self._last_static_emit = self._now()
        self._emit(label)

    def _emit(self, line: str) -> None:
        """Write one line through the console that currently owns the stream."""
        console = self._target_console()
        try:
            console.print(line)
            console.file.flush()
        except _STREAM_GONE as exc:
            logger.debug("progress line dropped: %s", exc)

    def _render_live(self, label: str) -> bool:
        """Repaint the live caption; report whether the region took the update.

        A ``False`` return sends the caller down the plain-line path, which is
        also how a failed or torn-down live region degrades.
        """
        live = self._live
        spinner = self._spinner
        if live is None or spinner is None:
            return False
        self._label = label
        try:
            # Updating the spinner alone only changes what the next frame will
            # say, and Rich repaints a spinner on its own timer, so an activity
            # change would not appear until the next tick without this explicit
            # refresh through the Live.
            spinner.update(text=label)
            live.update(spinner, refresh=True)
        except _STREAM_GONE as exc:
            logger.debug("progress live region lost its stream: %s", exc)
            self._stop_live()
            return False
        return True

    def _start_live(self) -> None:
        """Open the animated region on the console the lines also use."""
        console = self._target_console()
        spinner = Spinner("dots", text=self._label or "", style="status.spinner")
        live = Live(
            spinner,
            console=console,
            refresh_per_second=_REFRESH_PER_SECOND,
            transient=True,
        )
        try:
            live.start()
        except _STREAM_GONE as exc:
            logger.debug("progress live region could not start: %s", exc)
            return
        self._spinner = spinner
        self._live = live
        self._live_console = console

    def _stop_live(self) -> None:
        """Close the live region, restoring the cursor, and forget it."""
        live = self._live
        self._live = None
        self._spinner = None
        self._live_console = None
        if live is None:
            return
        try:
            live.stop()
        except _STREAM_GONE as exc:
            logger.debug("progress live region did not stop cleanly: %s", exc)
