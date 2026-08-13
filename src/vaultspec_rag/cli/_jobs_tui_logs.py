"""The watch's two log panes: fetching their lines and titling them.

The job log follows the highlighted row; the managed log follows the service.
Both are fetched off the UI thread and applied back onto it, and both have to
say plainly when they are empty, stale, or closed rather than showing nothing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.text import Text
from textual import work
from textual.widgets import Static

from ..serviceclient._transport import _try_http_admin
from ._jobs_tui_constants import LOG_GROUP, LOG_LINES
from ._jobs_tui_log import JobsLogView
from ._jobs_tui_managed_logs import ManagedLogTankView
from ._jobs_tui_palette import semantic_tones
from ._jobs_tui_payload import log_lines

if TYPE_CHECKING:
    from textual.app import App

    _MixinBase = App[None]
else:
    _MixinBase = object


class LogPanesMixin(_MixinBase):
    """Drives the job-log and managed-log panes."""

    _port: int

    if TYPE_CHECKING:
        from textual.reactive import reactive
        from textual.widget import Widget

        from ._jobs_tui_state import ManagedLogState

        _logs: ManagedLogState
        selected_id: reactive[str]

        def _pane[WidgetT: Widget](
            self, selector: str, kind: type[WidgetT]
        ) -> WidgetT | None: ...

    @work(thread=True, exclusive=True, group=LOG_GROUP)
    def fetch_logs(self, job_id: str) -> None:
        result = _try_http_admin(
            "get_logs",
            {"lines": LOG_LINES, "source": "service", "job_id": job_id},
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
