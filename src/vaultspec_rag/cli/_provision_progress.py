"""Report a provisioning run through a command's status reporter.

The provisioning front door reports to a sink it defines and knows nothing
about consoles. This is that sink for the CLI: every command that fetches the
models or the Qdrant server - ``install``, ``server start``, ``server warmup``
- hands the front door one of these, so the same fetch is reported in the same
words whichever command started it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..commands._snapshot_progress import progress_line

if TYPE_CHECKING:
    from ..commands._snapshot_progress import SnapshotCounts
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

    def downloading(self, heading: str, counts: SnapshotCounts) -> None:
        """Show how far one model snapshot download has got.

        A heartbeat rather than a stage: the counts change several times a
        second, and off a terminal the reporter thins heartbeats to one line
        every few seconds instead of printing each.
        """
        self._open()
        self._reporter.heartbeat(progress_line(heading, counts))

    def _open(self) -> None:
        if not self._opened:
            self._opened = True
            self._reporter.__enter__()
