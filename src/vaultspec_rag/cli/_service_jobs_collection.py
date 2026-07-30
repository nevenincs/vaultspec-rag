"""Collection ``server jobs`` command registration and composition."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

from typer.core import TyperCommand, TyperOption

from ..serviceclient._discovery import _default_service_port
from ._app import (
    JOBS_WATCH_OPTION_HELP,
    JSON_OPTION_HELP,
    PORT_OPTION_HELP,
    WATCH_INTERVAL_OPTION_HELP,
    server_app,
)
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

if TYPE_CHECKING:
    from typer._click import Context as ClickContext


@dataclass(frozen=True, slots=True)
class ServiceJobsOptions:
    limit: int = 20
    state: str | None = None
    index: str | None = None
    started_by: str | None = None
    query: str | None = None
    failed: bool = False
    job_id: str | None = None
    since: float | None = None
    port: int | None = None
    json_mode: bool = False
    watch: bool = False
    interval: float = 2.0
    watch_mode: Literal["server", "jobs"] = "jobs"


class _ServiceJobsCommand(TyperCommand):
    """Parse the jobs collection options into one command request."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.params.extend(
            (
                TyperOption(
                    param_decls=["--limit"],
                    type=int,
                    default=20,
                    help="Maximum number of matching jobs to show.",
                ),
                TyperOption(
                    param_decls=["--state"],
                    type=str,
                    default=None,
                    help=(
                        "Filter by job state: active, waiting, finished, failed, "
                        "or cancelled."
                    ),
                ),
                TyperOption(
                    param_decls=["--index"],
                    type=str,
                    default=None,
                    help="Filter by index type: vault or code.",
                ),
                TyperOption(
                    param_decls=["--started-by"],
                    type=str,
                    default=None,
                    help=(
                        "Filter by who started the job: manual requests or "
                        "automatic updates."
                    ),
                ),
                TyperOption(
                    param_decls=["--query", "-q"],
                    type=str,
                    default=None,
                    help="Filter by text in job id, outcome, or progress.",
                ),
                TyperOption(
                    param_decls=["--failed"],
                    default=False,
                    is_flag=True,
                    help="Show only failed jobs.",
                ),
                TyperOption(
                    param_decls=["--job-id"],
                    type=str,
                    default=None,
                    help="Show details for a job id or prefix.",
                ),
                TyperOption(
                    param_decls=["--since"],
                    type=float,
                    default=None,
                    help="Show jobs updated within the last N seconds.",
                ),
                TyperOption(
                    param_decls=["--port"],
                    type=int,
                    default=None,
                    help=PORT_OPTION_HELP,
                ),
                TyperOption(
                    param_decls=["--json"],
                    default=False,
                    is_flag=True,
                    help=(
                        f"{JSON_OPTION_HELP} Always use this for scripted waits: "
                        "the human summary line unconditionally contains the words "
                        "'active' and 'waiting'."
                    ),
                ),
                TyperOption(
                    param_decls=["--watch"],
                    default=False,
                    is_flag=True,
                    help=JOBS_WATCH_OPTION_HELP,
                ),
                TyperOption(
                    param_decls=["--interval"],
                    type=float,
                    default=2.0,
                    help=WATCH_INTERVAL_OPTION_HELP,
                ),
            )
        )

    def invoke(self, ctx: ClickContext) -> Any:
        params = ctx.params
        return run_service_jobs(
            ServiceJobsOptions(
                limit=cast("int", params["limit"]),
                state=cast("str | None", params["state"]),
                index=cast("str | None", params["index"]),
                started_by=cast("str | None", params["started_by"]),
                query=cast("str | None", params["query"]),
                failed=cast("bool", params["failed"]),
                job_id=cast("str | None", params["job_id"]),
                since=cast("float | None", params["since"]),
                port=cast("int | None", params["port"]),
                json_mode=cast("bool", params["json"]),
                watch=cast("bool", params["watch"]),
                interval=cast("float", params["interval"]),
            )
        )


@server_app.command(
    "jobs",
    cls=_ServiceJobsCommand,
    help="Show recent index update activity from the running service.",
)
def service_jobs() -> None:
    """Register the custom jobs command schema."""


def run_service_jobs(options: ServiceJobsOptions) -> None:
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
                watch_mode=options.watch_mode,
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
