"""Entry to the interactive jobs interface for ``server jobs --watch``.

The live view is an application that owns the terminal, not a loop that
reprints. A reprint loop cannot offer selection, per-row control, or a log
pane, and it cannot host a live region on this project's shared console at
all - so ``--watch`` hands the screen to the interface instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

import typer

from ._render import _emit_json_error_and_exit, _plain
from ._service_jobs_query import apply_client_state_filter

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class JobsWatchRequest:
    """The resolved query and display settings for the interactive view."""

    fetch: Callable[[], dict[str, object] | None]
    job_id: str | None
    port: int
    interval: float
    client_state: str | None


def exit_invalid_watch_args(json_mode: bool, interval: float) -> NoReturn:
    message = "--watch is human-only and --interval must be greater than zero."
    if interval > 0:
        message = "--watch cannot be combined with --json."
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "invalid_watch", message, 2)
    _plain(f"Error: {message}")
    raise typer.Exit(2)


def watch_jobs(request: JobsWatchRequest) -> None:
    """Run the interactive interface until the operator leaves it.

    The client-side state filter is applied to every fetch here rather than
    inside the interface, so the interactive and one-shot paths are provably
    asking the same question of the same service.
    """
    # Imported here so the one-shot and structured paths never pay for the
    # interface, and a terminal-less host can still read the plain feed.
    from ._jobs_tui import run_jobs_tui

    def watched_fetch() -> dict[str, object] | None:
        result = request.fetch()
        if result is None:
            return None
        return apply_client_state_filter(result, request.client_state)

    run_jobs_tui(watched_fetch, port=request.port, interval=request.interval)
