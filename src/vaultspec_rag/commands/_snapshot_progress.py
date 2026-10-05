"""Byte and file counts for a Hugging Face snapshot download, and their line.

Fetching the model repos is the longest wait the CLI has: several gigabytes
across three repos. The hub exposes exactly one reporting seam - a
``tqdm_class`` its download machinery instantiates for its own bars - so this
module adapts that seam into four numbers instead of a drawing. A spinner
would tick here, but the download knows its own byte and file counts, and a
determinate signal is the one an operator can plan around.

The hub builds three bars from the class it is handed: two byte counters and
one file counter. The byte counters describe the SAME payload from two angles -
bytes received from the network, and bytes reconstructed onto disk - and are
seeded with the same total, so summing them would double-count a download that
is only ever one payload. They are collapsed into a single pair of numbers
instead, and the denominator deliberately takes the SMALLEST of the two
declared totals: the network counter inflates its own total as a bar-width
estimate when received bytes overrun the seed, which is display arithmetic and
not a size an operator should be shown.

The counting and the showing happen in different processes. A download runs in
a child that holds the bars and reports the counts; the command that started it
turns the counts into a line. That is why this module sits outside the CLI
package and prints nothing itself.
"""

from __future__ import annotations

import io
import logging
import threading
from dataclasses import dataclass
from typing import Any

from .._units import human_bytes

logger = logging.getLogger(__name__)

__all__ = ["SnapshotBars", "SnapshotCounts", "progress_line"]

# The hub labels both byte bars with this unit and leaves its file bar at
# tqdm's default, which is what separates "bytes moved" from "files done"
# without depending on the prose in either bar's description.
_BYTE_UNIT = "B"


@dataclass(frozen=True, slots=True)
class SnapshotCounts:
    """How far one snapshot download has got.

    Attributes:
        files_done: Files finished so far.
        files_total: Files in the snapshot, or 0 before the hub has said.
        bytes_done: Bytes of payload moved so far.
        bytes_total: The payload's size, or 0 when it is not known - which
            includes the case where the bytes moved have overrun the size the
            hub declared, since a denominator smaller than its numerator
            would tell the operator the file grew.
    """

    files_done: int = 0
    files_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0


def progress_line(prefix: str, counts: SnapshotCounts) -> str:
    """Compose the one operator-facing line for *counts*.

    Args:
        prefix: Leading text naming what is being downloaded.
        counts: The download's current counts.
    """
    parts: list[str] = []
    if counts.files_total:
        parts.append(f"{counts.files_done}/{counts.files_total} files")
    if counts.bytes_total:
        parts.append(
            f"{human_bytes(counts.bytes_done)} of {human_bytes(counts.bytes_total)}"
        )
    elif counts.bytes_done:
        parts.append(human_bytes(counts.bytes_done))
    if not parts:
        return f"{prefix}..."
    return f"{prefix}: {', '.join(parts)}"


class SnapshotBars:
    """Hold the bars the hub builds for one snapshot download, and count them.

    Hand :attr:`tqdm_class` to ``snapshot_download`` and read :meth:`counts`
    while it runs.

    Use it as a context manager. Leaving the block closes every bar the hub
    built, which is load-bearing rather than tidy: the hub abandons its byte
    bars without closing them, so a bar left open is closed by tqdm's
    finaliser during interpreter shutdown, when the modules it would draw
    with have already been torn down.
    """

    def __init__(self) -> None:
        """Build an empty collection."""
        # Reentrant because the hub advances these counters from its download
        # worker threads while another thread reads them, and a decorative
        # path is the last place a lock cycle should be able to hang a
        # download.
        self._lock = threading.RLock()
        self._byte_bars: list[object] = []
        self._file_bars: list[object] = []
        self._tqdm_class: type[Any] | None = None
        self._finished = False

    def __enter__(self) -> SnapshotBars:
        """Begin collecting a download's bars."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close every bar the hub left open."""
        self.finish()

    def finish(self) -> None:
        """Stop collecting and close the bars, idempotently."""
        with self._lock:
            if self._finished:
                return
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
        instead of failing the download.
        """
        with self._lock:
            if self._tqdm_class is None:
                self._tqdm_class = _counting_tqdm_class(self)
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

    def counts(self) -> SnapshotCounts:
        """Return the download's counts as the bars stand now."""
        with self._lock:
            files_done = max((_bar_int(bar, "n") for bar in self._file_bars), default=0)
            files_total = max(
                (_bar_int(bar, "total") for bar in self._file_bars), default=0
            )
            bytes_done = max((_bar_int(bar, "n") for bar in self._byte_bars), default=0)
            declared = [
                total
                for bar in self._byte_bars
                if (total := _bar_int(bar, "total")) > 0
            ]
        bytes_total = min(declared, default=0)
        # A received-byte count above the declared payload size is the network
        # counter's own estimate overrunning, not a bigger download.
        if bytes_done > bytes_total:
            bytes_total = 0
        return SnapshotCounts(files_done, files_total, bytes_done, bytes_total)


def _bar_int(bar: object, attribute: str) -> int:
    """Read one numeric bar attribute, tolerating an absent or unset value."""
    value = getattr(bar, attribute, 0)
    if not isinstance(value, int | float) or isinstance(value, bool):
        return 0
    return int(value)


def _counting_tqdm_class(bars: SnapshotBars) -> type[Any] | None:
    """Build the bar class bound to *bars*, or ``None`` without tqdm.

    Built lazily and per download so nothing loads tqdm until a download
    starts and so no bar outlives the download it was counting.
    """
    try:
        from tqdm.auto import tqdm as _tqdm
    except ImportError as exc:  # tqdm arrives with the hub; absent is survivable
        logger.debug("tqdm unavailable, download progress falls back: %s", exc)
        return None

    # ``tqdm.auto`` picks one of several tqdm variants from the host it finds,
    # so the imported name is a union of classes rather than a single class and
    # cannot be subclassed directly under a type checker. The hub's own base is
    # this same name, so the alias is what makes the real base usable, not a
    # substitute for it.
    base: Any = _tqdm

    class _CountingTqdm(base):
        """A tqdm that is only counted and draws nothing."""

        def __init__(self, *args: object, **kwargs: object) -> None:
            # Pointed at a throwaway buffer rather than a real stream: whoever
            # shows progress owns the terminal, and a second writer would land
            # in its output. ``disable`` is forced OFF because a disabled tqdm
            # returns from ``update`` before touching its counters, and the
            # counters are the entire point here.
            kwargs["file"] = io.StringIO()
            kwargs["disable"] = False
            kwargs["leave"] = False
            super().__init__(*args, **kwargs)  # pyright: ignore[reportUnknownMemberType]
            bars.track(self)

        def display(self, *args: object, **kwargs: object) -> bool:
            """Draw nothing.

            tqdm funnels every frame through this one method, so overriding it
            - rather than the several methods that call it - is what keeps a
            bar off the stream whichever entry point the hub reaches for.
            """
            del args, kwargs
            return True

    return _CountingTqdm
