"""Entry to the jobs-focused canonical server watch for ``server jobs --watch``.

The live view is an application that owns the terminal, not a loop that
reprints. A reprint loop cannot offer selection, per-row control, or a log
pane, and it cannot host a live region on this project's shared console at
all - so ``--watch`` hands the screen to the interface instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, NoReturn

import typer

from ._render import _emit_json_error_and_exit, _plain

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class JobsWatchRequest:
    """The resolved query and display settings for the interactive view."""

    fetch: Callable[[], dict[str, object] | None]
    job_id: str | None
    port: int
    interval: float
    watch_mode: Literal["server", "jobs"]


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

    The interface calls the same fetch the one-shot path does, so both ask
    the same question of the same service.
    """
    # Imported here so the one-shot and structured paths never pay for the
    # interface, and a terminal-less host can still read the plain feed.
    from ._jobs_tui import run_server_watch

    run_server_watch(
        request.fetch,
        port=request.port,
        interval=request.interval,
        watch_mode=request.watch_mode,
    )
