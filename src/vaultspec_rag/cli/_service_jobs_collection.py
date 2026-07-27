"""Collection ``server jobs`` command registration and composition."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from typer.core import TyperCommand, TyperOption

from ..serviceclient._discovery import _default_service_port
from ._app import JSON_OPTION_HELP, server_app
from ._render import _emit_json
from ._service_jobs_presentation import _render_jobs_result
from ._service_jobs_query import (
    _apply_client_state_filter,
    _exit_jobs_not_running,
    _fetch_jobs_result,
    _jobs_index_filter,
    _jobs_started_by_filter,
    _jobs_state_filter,
    _JobsQuery,
    _resolve_jobs_filters,
)
from ._service_jobs_watch import (
    _exit_invalid_watch_args,
    _JobsWatchRequest,
    _watch_jobs,
)

if TYPE_CHECKING:
    from typer._click import Context as ClickContext


@dataclass(frozen=True, slots=True)
class _ServiceJobsOptions:
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
                    help="Service port (defaults to running service).",
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
                    help="Open the interactive jobs interface with per-job controls.",
                ),
                TyperOption(
                    param_decls=["--interval"],
                    type=float,
                    default=2.0,
                    help="Seconds between refreshes in the interactive interface.",
                ),
            )
        )

    def invoke(self, ctx: ClickContext) -> Any:
        params = ctx.params
        return _run_service_jobs(
            _ServiceJobsOptions(
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


def _run_service_jobs(options: _ServiceJobsOptions) -> None:
    """Show recent index update activity from the running service."""
    json_mode = options.json_mode
    interval = options.interval
    phase, client_state = _jobs_state_filter(options.state, json_mode)
    source = _jobs_index_filter(options.index, json_mode)
    trigger = _jobs_started_by_filter(options.started_by, json_mode)
    phase, failed = _resolve_jobs_filters(phase, options.failed, json_mode)
    resolved_port = (
        options.port if options.port is not None else _default_service_port()
    )
    if resolved_port is None:
        _exit_jobs_not_running(json_mode)
    if interval <= 0:
        _exit_invalid_watch_args(json_mode, interval)
    if options.watch and json_mode:
        _exit_invalid_watch_args(json_mode, interval)
    spec = _JobsQuery(
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
    fetch = functools.partial(_fetch_jobs_result, spec)
    if options.watch:
        _watch_jobs(
            _JobsWatchRequest(
                fetch=fetch,
                job_id=options.job_id,
                port=resolved_port,
                interval=interval,
                client_state=client_state,
            )
        )
        return

    result = fetch()
    if result is None:
        _exit_jobs_not_running(json_mode, resolved_port)
    result = _apply_client_state_filter(result, client_state)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    _render_jobs_result(result, job_id=options.job_id, port=resolved_port)
