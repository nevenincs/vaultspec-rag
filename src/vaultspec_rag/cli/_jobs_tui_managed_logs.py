"""Raw, source-grouped managed-log view for the server watch interface.

This view deliberately does not share the selected-job renderer's structured
parsing, polling suppression, or per-record display cap. Its only record
transformation is neutralizing terminal control bytes before Rich receives the
text. The service contract supplies one stable group per producer; displaying
those groups separately avoids inventing a cross-producer chronology.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.text import Text
from textual.widgets import RichLog

from ..logging_config import (
    MAX_MANAGED_LOG_LINES,
    MAX_MANAGED_LOG_SOURCE_BYTES,
    ManagedLogGroup,
)
from ._jobs_tui_log import sanitize_log_text

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = [
    "ManagedLogTankView",
    "managed_log_group_metadata",
    "managed_log_safe_text",
]


def managed_log_safe_text(record: str) -> str:
    """Keep one managed record whole while making terminal controls inert."""
    return sanitize_log_text(record, max_chars=None)


def managed_log_group_metadata(group: ManagedLogGroup) -> str:
    """Describe the server bounds and any server-declared truncation."""
    source = group["source"]
    records = len(group["lines"])
    source_limit_mib = MAX_MANAGED_LOG_SOURCE_BYTES // (1024 * 1024)
    summary = (
        f"{source}: {records:,} records · server cap "
        f"{MAX_MANAGED_LOG_LINES:,} records / {source_limit_mib} MiB"
    )
    if group.get("truncated") is not True:
        return summary

    truncation = group.get("truncation") or {}
    details = ["TRUNCATED by server"]
    returned = truncation.get("returned_content_bytes")
    if isinstance(returned, int):
        details.append(f"returned {returned:,} bytes")
    omitted_bytes = truncation.get("omitted_bytes_at_least")
    if isinstance(omitted_bytes, int) and omitted_bytes:
        details.append(f"omitted at least {omitted_bytes:,} bytes")
    shortened = truncation.get("record_truncations")
    if isinstance(shortened, int) and shortened:
        details.append(f"shortened {shortened:,} records")
    if truncation.get("source_budget_exhausted") is True:
        details.append("source byte budget exhausted")
    if truncation.get("response_budget_exhausted") is True:
        omitted_records = truncation.get("omitted_response_records")
        suffix = (
            f" ({omitted_records:,} records omitted)"
            if isinstance(omitted_records, int)
            else ""
        )
        details.append(f"response byte budget exhausted{suffix}")
    return f"{summary} · {'; '.join(details)}"


class ManagedLogTankView(RichLog):
    """Render the bounded service and Qdrant records as independent raw groups."""

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(
            wrap=True,
            markup=False,
            auto_scroll=True,
            max_lines=None,
            min_width=1,
            id=id,
        )
        self.can_focus = True
        self._groups: list[ManagedLogGroup] = []
        self._message: str | None = None

    def show_groups(self, groups: Sequence[ManagedLogGroup]) -> None:
        """Replace the tank with the exact source-grouped server response."""
        self._groups = list(groups)
        self._message = None
        self._paint_groups()

    def show_message(self, message: str) -> None:
        """Replace the tank with a fetch or validation failure."""
        self._groups = []
        self._message = message
        self._paint_groups()

    def on_show(self) -> None:
        """Write held content once the full-height pane becomes visible."""
        self._repaint_if_held()

    def repaint_theme(self) -> None:
        """Repaint the held groups after the interface palette changes."""
        self._repaint_if_held()

    def _repaint_if_held(self) -> None:
        """Repaint only when something is actually held for display.

        Two distinct events need this and neither can stand in for the other:
        the framework calls ``on_show`` when the pane becomes visible, and the
        app calls ``repaint_theme`` when the palette changes. Painting an empty
        tank would clear a message the operator has not read yet, so both go
        through the same guard rather than each carrying a copy of it.
        """
        if self._groups or self._message is not None:
            self._paint_groups()

    def _paint_groups(self) -> None:
        self.clear()
        if self._message is not None:
            self.write(Text(self._message))
            return
        for index, group in enumerate(self._groups):
            if index:
                self.write(Text(""))
            self.write(Text(f"[{group['source']}]", style="bold"))
            self.write(Text(managed_log_group_metadata(group), style="dim"))
            marker = group.get("marker")
            if isinstance(marker, str) and marker:
                self.write(Text(managed_log_safe_text(marker), style="bold"))
            for record in group["lines"]:
                self.write(Text(managed_log_safe_text(record)))
