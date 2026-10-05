"""Report a provisioning run through a command's status reporter.

The provisioning front door reports to a sink it defines and knows nothing
about consoles. This is that sink for the CLI: every command that fetches the
models or the Qdrant server - ``install``, ``server start``, ``server warmup``
- hands the front door one of these, so the same fetch is reported in the same
words whichever command started it.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import TYPE_CHECKING, Any

from ._hf_progress import SnapshotProgress

if TYPE_CHECKING:
    from collections.abc import Generator

    from ._progress import StartupStatusReporter

__all__ = ["ReporterProvisionProgress"]


class ReporterProvisionProgress:
    """Render provisioning stages and downloads on one status reporter.

    Use it as a context manager around the provisioning call. The reporter's
    live region is opened on the first thing reported rather than on entry:
    ``install`` asks its questions before it provisions, and a region already
    animating would be drawn over the prompt. A command whose reporter is
    already open simply shares it, because entering a reporter is re-entrant.
    """

    def __init__(self, reporter: StartupStatusReporter) -> None:
        """Build a sink reporting through *reporter*."""
        self._reporter = reporter
        self._opened = False

    def __enter__(self) -> ReporterProvisionProgress:
        """Begin a provisioning run; nothing is drawn until it reports."""
        return self

    def __exit__(self, *exc: object) -> None:
        """Close the live region this sink opened, if it opened one."""
        if self._opened:
            self._opened = False
            self._reporter.__exit__(*exc)

    def stage(self, label: str) -> None:
        """Declare the current provisioning activity."""
        self._open()
        self._reporter.stage(label)

    @contextmanager
    def download(self, heading: str) -> Generator[type[Any] | None]:
        """Report one snapshot download; yield the bar class to hand the hub.

        The hub exposes its byte and file counts only through the bar class it
        is given, so the block yields that class and collapses what the hub
        does with it into one line under *heading*.
        """
        self._open()
        self._reporter.stage(f"{heading}...")
        with SnapshotProgress(self._reporter.heartbeat, prefix=heading) as tracker:
            yield tracker.tqdm_class

    def _open(self) -> None:
        if not self._opened:
            self._opened = True
            self._reporter.__enter__()
