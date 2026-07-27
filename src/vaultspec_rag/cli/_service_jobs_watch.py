"""Interruptible refresh loop for the human ``server jobs --watch`` view."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, NoReturn

import typer

import vaultspec_rag.cli as _cli

from ._process import _call_interruptibly
from ._render import _emit_json_error_and_exit, _plain
from ._service_jobs_presentation import render_jobs_result
from ._service_jobs_query import apply_client_state_filter, exit_jobs_not_running

if TYPE_CHECKING:
    from collections.abc import Callable


@dataclass(frozen=True, slots=True)
class JobsWatchRequest:
    """The resolved query and display settings for a watched jobs view."""

    fetch: Callable[[], dict[str, object] | None]
    job_id: str | None
    port: int
    interval: float
    refresh_count: int | None
    client_state: str | None


def exit_invalid_watch_args(json_mode: bool, interval: float) -> NoReturn:
    message = "--watch is human-only and --interval must be greater than zero."
    if interval > 0:
        message = "--watch cannot be combined with --json."
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "invalid_watch", message, 2)
    _plain(f"Error: {message}")
    raise typer.Exit(2)


def _watch_status_text(refresh_number: int, refresh_count: int | None) -> str:
    if refresh_count is None:
        return "Watch: press Ctrl+C to stop."
    return f"Watch: refresh {refresh_number} of {refresh_count}."


def stop_watching() -> NoReturn:
    """Leave the refreshing view on an operator interrupt.

    Watch only reads, so there is nothing to unwind. Exit on the conventional
    interrupted status rather than reporting the success the operator never
    got, and without a traceback they did not ask for.
    """
    _cli.console.print("\n[dim]Stopped watching jobs.[/]")
    raise typer.Exit(130)


def watch_jobs(request: JobsWatchRequest) -> None:
    """Re-render *fetch*'s result on an interval until interrupted.

    Takes the bound fetch rather than the filter set so the query is spelled
    once in the command and both the one-shot and watching paths are provably
    reading the same thing.
    """
    refreshes = 0
    while request.refresh_count is None or refreshes < request.refresh_count:
        # The refresh is one instance of the general problem of keeping the
        # main thread interruptible across a blocking call, so it shares the
        # process module's helper rather than carrying a second copy of the
        # same threading rationale. A divergence between two copies would be a
        # Ctrl+C that works in one operator view and not the other.
        result = _call_interruptibly(request.fetch)
        if result is None:
            exit_jobs_not_running(False, request.port)
        result = apply_client_state_filter(result, request.client_state)
        _cli.console.clear()
        refresh_number = refreshes + 1
        render_jobs_result(
            result,
            job_id=request.job_id,
            port=request.port,
            monitoring=True,
            watch_text=_watch_status_text(refresh_number, request.refresh_count),
        )
        refreshes += 1
        if request.refresh_count is not None and refreshes >= request.refresh_count:
            return
        time.sleep(request.interval)
