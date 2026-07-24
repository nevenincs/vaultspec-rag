"""Real byte-and-file progress for a HuggingFace snapshot download.

Fetching the model repos is the longest unbounded wait the CLI has: several
gigabytes across three repos, with a per-request timeout that bounds no total.
The hub exposes exactly one reporting seam - a ``tqdm_class`` its download
machinery instantiates for its own bars - so this module adapts that seam onto
the CLI's status reporter rather than onto a terminal. A spinner would tick
here, but the download knows its own byte and file counts, and a determinate
signal is the one an operator can plan around.

The hub builds three bars from the class it is handed: two byte counters and
one file counter. The byte counters describe the SAME payload from two angles -
bytes received from the network, and bytes reconstructed onto disk - and are
seeded with the same total, so summing them would double-count a download that
is only ever one payload. They are collapsed into a single pair of numbers
instead, and the denominator deliberately takes the SMALLEST of the two
declared totals: the network counter inflates its own total as a bar-width
estimate when received bytes overrun the seed, which is display arithmetic and
not a size an operator should be shown.
"""

from __future__ import annotations

import io
import threading
import time
from typing import TYPE_CHECKING, Any

from .._units import human_bytes
from ._core import logger

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["SnapshotProgress"]

# The hub labels both byte bars with this unit and leaves its file bar at
# tqdm's default, which is what separates "bytes moved" from "files done"
# without depending on the prose in either bar's description.
_BYTE_UNIT = "B"

# The reporter repaints a live region on every update, so an unthrottled byte
# counter would repaint per network chunk. Fast enough to read as motion.
_MIN_EMIT_INTERVAL_S = 0.2


class SnapshotProgress:
    """Collapse one snapshot download's bars into one operator-facing line.

    Hand :attr:`tqdm_class` to ``snapshot_download``; the aggregated label is
    pushed to the ``report`` callable - in practice a
    :meth:`~._progress.StartupStatusReporter.heartbeat` - as the download
    advances.

    Use it as a context manager. Leaving the block closes every bar the hub
    built and stops reporting for good, which is load-bearing rather than
    tidy: the hub abandons its byte bars without closing them, so a bar left
    open is closed by tqdm's finaliser during interpreter shutdown, and the
    report it emits from there reaches a console whose modules have already
    been torn down.
    """

    def __init__(
        self,
        report: Callable[[str], None],
        *,
        prefix: str,
        min_interval_s: float = _MIN_EMIT_INTERVAL_S,
        now: Callable[[], float] = time.monotonic,
    ) -> None:
        """Build a tracker.

        Args:
            report: Sink for each rendered progress line.
            prefix: Leading text naming what is being downloaded.
            min_interval_s: Minimum seconds between reported lines.
            now: Monotonic clock backing that rate limit.
        """
        self._report = report
        self._prefix = prefix
        self._min_interval_s = min_interval_s
        self._now = now
        # Reentrant to match the reporter it feeds: the hub advances these
        # counters from its download worker threads, and a decorative path is
        # the last place a lock cycle should be able to hang a command.
        self._lock = threading.RLock()
        self._byte_bars: list[object] = []
        self._file_bars: list[object] = []
        self._last_emit: float | None = None
        self._tqdm_class: type[Any] | None = None
        self._finished = False

    def __enter__(self) -> SnapshotProgress:
        """Begin tracking a download."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Stop reporting and close every bar the hub left open."""
        self.finish()

    def finish(self) -> None:
        """Silence the tracker and close its bars, idempotently."""
        with self._lock:
            if self._finished:
                return
            # Set BEFORE closing: closing a bar renders a final frame, which
            # arrives back here as a report the caller no longer wants.
            self._finished = True
            bars = [*self._byte_bars, *self._file_bars]
            self._byte_bars.clear()
            self._file_bars.clear()
        for bar in bars:
            closer = getattr(bar, "close", None)
            if closer is None:
                continue
            try:
                closer()
            except (OSError, ValueError, RuntimeError) as exc:
                logger.debug("download bar did not close cleanly: %s", exc)

    @property
    def tqdm_class(self) -> type[Any] | None:
        """The bar class to hand the hub, or ``None`` when tqdm is absent.

        ``None`` is a supported argument: the hub then draws its own bars, so
        an environment without tqdm degrades to the hub's default reporting
        instead of failing the warmup.
        """
        with self._lock:
            if self._tqdm_class is None:
                self._tqdm_class = _reporting_tqdm_class(self)
            return self._tqdm_class

    def track(self, bar: object) -> None:
        """Register a bar the hub just constructed."""
        with self._lock:
            if self._finished:
                return
            unit = getattr(bar, "unit", "")
            if unit == _BYTE_UNIT:
                self._byte_bars.append(bar)
            else:
                self._file_bars.append(bar)

    def refresh(self) -> None:
        """Render the current aggregate and report it, subject to the rate limit."""
        with self._lock:
            if self._finished:
                return
            moment = self._now()
            last = self._last_emit
            if last is not None and moment - last < self._min_interval_s:
                return
            self._last_emit = moment
            line = self._render()
        self._report(line)

    def _render(self) -> str:
        """Compose the one line describing every bar's current state."""
        parts: list[str] = []
        files_done, files_total = _file_counts(self._file_bars)
        if files_total:
            parts.append(f"{files_done}/{files_total} files")
        parts.extend(_byte_parts(self._byte_bars))
        if not parts:
            return f"{self._prefix}..."
        return f"{self._prefix}: {', '.join(parts)}"


def _file_counts(bars: list[object]) -> tuple[int, int]:
    """Return ``(done, total)`` across the file-counting bars."""
    done = max((_bar_int(bar, "n") for bar in bars), default=0)
    total = max((_bar_int(bar, "total") for bar in bars), default=0)
    return done, total


def _byte_parts(bars: list[object]) -> list[str]:
    """Render the byte counters as at most one ``x of y`` fragment."""
    done = max((_bar_int(bar, "n") for bar in bars), default=0)
    declared = [total for bar in bars if (total := _bar_int(bar, "total")) > 0]
    total = min(declared, default=0)
    if not done and not total:
        return []
    # A received-byte count above the declared payload size is the network
    # counter's own estimate overrunning, not a bigger download; showing it as
    # a denominator would tell the operator the file grew.
    if total and done <= total:
        return [f"{human_bytes(done)} of {human_bytes(total)}"]
    return [human_bytes(done)]


def _bar_int(bar: object, attribute: str) -> int:
    """Read one numeric bar attribute, tolerating an absent or unset value."""
    value = getattr(bar, attribute, 0)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return 0
    return int(value)


def _reporting_tqdm_class(tracker: SnapshotProgress) -> type[Any] | None:
    """Build the bar class bound to *tracker*, or ``None`` without tqdm.

    Built lazily and per download so the CLI import path never loads tqdm and
    so no bar outlives the download it was counting.
    """
    try:
        from tqdm.auto import tqdm as _tqdm  # pyright: ignore[reportMissingTypeStubs]
    except ImportError as exc:  # tqdm arrives with the hub; absent is survivable
        logger.debug("tqdm unavailable, download progress falls back: %s", exc)
        return None

    # ``tqdm.auto`` picks one of several tqdm variants from the host it finds,
    # so the imported name is a union of classes rather than a single class and
    # cannot be subclassed directly under a type checker. The hub's own base is
    # this same name, so the alias is what makes the real base usable, not a
    # substitute for it.
    base: Any = _tqdm

    class _ReportingTqdm(base):
        """A tqdm that reports through the tracker and draws nothing."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            # Pointed at a throwaway buffer rather than a real stream: the
            # reporter owns the terminal, and a second writer would land
            # inside its live frame. ``disable`` is forced OFF because a
            # disabled tqdm returns from ``update`` before touching its
            # counters, and the counters are the entire point here.
            kwargs["file"] = io.StringIO()
            kwargs["disable"] = False
            kwargs["leave"] = False
            super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownMemberType]
            tracker.track(self)

        def display(self, *args: Any, **kwargs: Any) -> bool:
            """Report instead of drawing.

            tqdm funnels every frame through this one method, so overriding it
            - rather than the several methods that call it - is what keeps a
            bar off the stream whichever entry point the hub reaches for.
            """
            del args, kwargs
            tracker.refresh()
            return True

    return _ReportingTqdm
