"""Collection ``server jobs`` command registration and composition."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Annotated, Literal

import typer

from ..serviceclient._discovery import _default_service_port
from ._app import (
    JOBS_WATCH_OPTION_HELP,
    JSON_OPTION_HELP,
    WATCH_INTERVAL_OPTION_HELP,
    PortOption,
    server_root_app,
)
from ._option_groups import with_option_group
from ._render import _emit_json
from ._service_jobs_presentation import render_jobs_result
from ._service_jobs_query import (
    JobsQuery,
    apply_client_state_filter,
    exit_jobs_not_running,
    fetch_jobs_result,
    jobs_index_filter,
    jobs_started_by_filter,
    jobs_state_filter,
    resolve_jobs_filters,
)
from ._service_jobs_watch import (
    JobsWatchRequest,
    exit_invalid_watch_args,
    watch_jobs,
)


@dataclass(frozen=True, slots=True)
class ServiceJobsOptions:
    limit: Annotated[
        int, typer.Option("--limit", help="Maximum number of matching jobs to show.")
    ] = 20
    state: Annotated[
        str | None,
        typer.Option(
            "--state",
            help=(
                "Filter by job state: active, waiting, finished, failed, or cancelled."
            ),
        ),
    ] = None
    index: Annotated[
        str | None,
        typer.Option("--index", help="Filter by index type: vault or code."),
    ] = None
    started_by: Annotated[
        str | None,
        typer.Option(
            "--started-by",
            help=(
                "Filter by who started the job: manual requests or automatic updates."
            ),
        ),
    ] = None
    query: Annotated[
        str | None,
        typer.Option(
            "--query", "-q", help="Filter by text in job id, outcome, or progress."
        ),
    ] = None
    failed: Annotated[bool, typer.Option("--failed", help="Show only failed jobs.")] = (
        False
    )
    job_id: Annotated[
        str | None,
        typer.Option("--job-id", help="Show details for a job id or prefix."),
    ] = None
    since: Annotated[
        float | None,
        typer.Option("--since", help="Show jobs updated within the last N seconds."),
    ] = None
    port: PortOption = None
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                f"{JSON_OPTION_HELP} Always use this for scripted waits: "
                "the human summary line unconditionally contains the words "
                "'active' and 'waiting'."
            ),
        ),
    ] = False
    watch: Annotated[bool, typer.Option("--watch", help=JOBS_WATCH_OPTION_HELP)] = False
    interval: Annotated[
        float, typer.Option("--interval", help=WATCH_INTERVAL_OPTION_HELP)
    ] = 2.0


@server_root_app.command(
    "jobs",
    help="Show recent index update activity from the running service.",
)
@with_option_group
def service_jobs(options: ServiceJobsOptions) -> None:
    """Show recent index update activity from the running service."""
    run_service_jobs(options)


def run_service_jobs(
    options: ServiceJobsOptions, *, watch_mode: Literal["server", "jobs"] = "jobs"
) -> None:
    """Show recent index update activity from the running service."""
    json_mode = options.json_mode
    interval = options.interval
    phase, client_state = jobs_state_filter(options.state, json_mode)
    source = jobs_index_filter(options.index, json_mode)
    trigger = jobs_started_by_filter(options.started_by, json_mode)
    phase, failed = resolve_jobs_filters(phase, options.failed, json_mode)
    resolved_port = (
        options.port if options.port is not None else _default_service_port()
    )
    if resolved_port is None:
        exit_jobs_not_running(json_mode)
    if interval <= 0:
        exit_invalid_watch_args(json_mode, interval)
    if options.watch and json_mode:
        exit_invalid_watch_args(json_mode, interval)
    spec = JobsQuery(
        port=resolved_port,
        limit=options.limit,
        phase=phase,
        source=source,
        trigger=trigger,
        query=options.query,
        failed=failed,
        job_id=options.job_id,
        since=options.since,
    )
    fetch = functools.partial(fetch_jobs_result, spec)
    if options.watch:
        watch_jobs(
            JobsWatchRequest(
                fetch=fetch,
                job_id=options.job_id,
                port=resolved_port,
                interval=interval,
                client_state=client_state,
                watch_mode=watch_mode,
            )
        )
        return

    result = fetch()
    if result is None:
        exit_jobs_not_running(json_mode, resolved_port)
    result = apply_client_state_filter(result, client_state)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    render_jobs_result(result, job_id=options.job_id, port=resolved_port)
