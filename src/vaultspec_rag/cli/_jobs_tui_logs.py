"""The watch's two log panes: fetching their lines and titling them.

The focused log follows the highlighted work; the managed log follows the service.
Both are fetched off the UI thread and applied back onto it, and both have to
say plainly when they are empty, stale, or closed rather than showing nothing.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from rich.text import Text
from textual import work
from textual.widgets import Static

from ..logging_config import validate_managed_log_payload
from ..serviceclient._transport import _try_http_admin
from ._jobs_tui_constants import LOG_GROUP, LOG_LINES
from ._jobs_tui_log import JobsLogView
from ._jobs_tui_managed_logs import ManagedLogTankView, managed_log_group_metadata
from ._jobs_tui_palette import semantic_tones

if TYPE_CHECKING:
    from textual.app import App

    _MixinBase = App[None]
else:
    _MixinBase = object


class LogPanesMixin(_MixinBase):
    """Drives the focused-work and managed-log panes."""

    _port: int

    if TYPE_CHECKING:
        from typing import Literal

        from textual.reactive import reactive
        from textual.widget import Widget

        from ._jobs_tui_state import FocusedLogState, ManagedLogState

        _logs: ManagedLogState
        _focused_log: FocusedLogState
        _interval: float
        selected_id: reactive[str]
        selected_search_id: reactive[str]

        def _pane[WidgetT: Widget](
            self, selector: str, kind: type[WidgetT]
        ) -> WidgetT | None: ...

    def refresh_focused_logs(self) -> None:
        """Poll the current inspection without cancelling its own in-flight read."""
        state = self._focused_log
        identity = self.selected_id if state.kind == "job" else self.selected_search_id
        subject = (state.kind, identity) if identity else None
        changed = subject != state.subject
        if changed:
            state.subject = subject
            state.last_refresh = None
            state.error = None
            state.metadata = ""
            self._clear_log(
                "Loading selected logs…" if subject else "No work selected."
            )
        if subject is None:
            return
        if not changed and any(
            worker.group == LOG_GROUP and not worker.is_finished
            for worker in self.workers
        ):
            return
        self.fetch_logs(subject, state.stamps.issue())

    @work(thread=True, exclusive=True, group=LOG_GROUP)
    def fetch_logs(
        self, subject: tuple[Literal["job", "request"], str], generation: int
    ) -> None:
        kind, identity = subject
        filters = {"job_id": identity} if kind == "job" else {"contains": identity}
        result = _try_http_admin(
            "get_logs",
            {"lines": LOG_LINES, "source": "service", **filters},
            self._port,
            timeout=min(5.0, self._interval),
        )
        self.call_from_thread(self._apply_logs, subject, result, generation)

    def _apply_logs(
        self,
        subject: tuple[Literal["job", "request"], str],
        result: dict[str, object] | None,
        generation: int,
    ) -> None:
        state = self._focused_log
        if subject != state.subject or not state.stamps.accept(generation):
            return
        log = self._log_view()
        if log is None:
            return
        if result is None or result.get("ok") is False:
            state.error = "logs unavailable: the service did not answer"
            self._refresh_log_title()
            return
        kind, identity = subject
        filters = {"job_id": identity} if kind == "job" else {"contains": identity}
        groups = validate_managed_log_payload(
            result,
            source="service",
            limit=LOG_LINES,
            filters=filters,
        )
        if groups is None:
            state.error = "logs unavailable: invalid service response"
            self._refresh_log_title()
            return
        group = groups[0]
        follow_tail = state.last_refresh is None or log.is_vertical_scroll_end
        position = log.scroll_offset.y
        log.auto_scroll = follow_tail
        state.metadata = managed_log_group_metadata(group)
        state.last_refresh = time.time()
        state.error = None
        if group["lines"]:
            log.show_lines(group["lines"])
        else:
            log.show_message(f"No log lines matched this {kind} in the bounded window.")
        # The window just changed, so what the noise filter hides and where
        # the errors sit changed with it - both the title's indicator and the
        # error-jump keys in the footer have to follow.
        self._refresh_log_title()
        if follow_tail:
            self.call_after_refresh(log.scroll_followed_tail)
        else:
            self.call_after_refresh(log.scroll_to, y=position, animate=False)
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
        state = self._focused_log
        subject = state.subject
        if subject is None:
            title = Text("Log · no work selected")
        else:
            kind, identity = subject
            label = "indexing job" if kind == "job" else "served request"
            title = Text(f"Log · {identity} · {label} · service source")
        if state.last_refresh is not None:
            stamp = time.strftime("%H:%M:%S", time.localtime(state.last_refresh))
            title.append(f" · refreshed {stamp}", style="dim")
            age = time.time() - state.last_refresh
            if age > max(5.0, self._interval * 3):
                title.append(" · stale", style=semantic_tones(self.theme)["attention"])
        if state.error:
            title.append(f" · {state.error}", style=semantic_tones(self.theme)["bad"])
        if state.metadata:
            title.append(f"\n{state.metadata} · tail {LOG_LINES}", style="dim")
        log = self._log_view()
        if log is not None:
            hidden = log.hidden_polling_count
            if hidden:
                title.append(
                    f"\n{hidden} polling hidden (x shows)",
                    style=semantic_tones(self.theme)["attention"],
                )
            elif log.polling_shown and log.polling_count:
                title.append("\npolling shown (x hides)", style="dim")
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
