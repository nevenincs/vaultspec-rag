"""``server jobs``: list recent index/reindex activity.

Tier-2b observability subcommand (``service-observability`` ADR, plan
P04). Calls the jobs admin endpoint through the shared HTTP admin client
and renders a Rich table (or the JSON envelope). Service-not-running
yields exit code 3.
"""

from __future__ import annotations

import time
from typing import Annotated, NoReturn, cast

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port


def _format_running_job_result(job: dict[str, object]) -> str:
    prog = job.get("progress")
    if not isinstance(prog, dict):
        return ""
    prog_dict = cast("dict[str, object]", prog)
    step = str(prog_dict.get("step", ""))
    completed = prog_dict.get("completed", 0)
    total = prog_dict.get("total")
    started_at = job.get("started_at")
    elapsed_str = ""
    if isinstance(started_at, float | int):
        import time

        elapsed = time.time() - started_at
        elapsed_str = f" ({int(elapsed)}s elapsed)"

    if step == "queued":
        return f"[yellow]queued behind writer lock[/]{elapsed_str}"
    if total is not None:
        return f"[yellow]{step} ({completed}/{total})[/]{elapsed_str}"
    return f"[yellow]{step} ({completed})[/]{elapsed_str}"


def _format_job_age(job: dict[str, object]) -> str:
    timestamp = job.get("finished_at") or job.get("started_at")
    if not isinstance(timestamp, float | int):
        return "?"
    age_s = max(0, int(time.time() - float(timestamp)))
    if age_s < 60:
        return f"{age_s}s"
    if age_s < 3600:
        minutes, seconds = divmod(age_s, 60)
        return f"{minutes}m {seconds}s"
    hours, rem = divmod(age_s, 3600)
    minutes = rem // 60
    return f"{hours}h {minutes}m"


def _job_detail(job: dict[str, object]) -> str:
    phase = str(job.get("phase", "?"))
    result_str = str(job.get("result") or "")
    if phase == "running" and not result_str:
        return _format_running_job_result(job)
    return result_str


def _exit_invalid_jobs_filter(json_mode: bool) -> NoReturn:
    message = "--running cannot be combined with --phase other than running."
    if json_mode:
        _emit_json_error_and_exit(
            "service.jobs",
            "invalid_filter",
            message,
            2,
        )
    _cli.console.print(f"[bold red]Error:[/] {message}")
    raise typer.Exit(2)


def _resolve_jobs_phase(
    phase: str | None,
    running: bool,
    json_mode: bool,
) -> str | None:
    if not running:
        return phase
    if phase is not None and phase.lower() != "running":
        _exit_invalid_jobs_filter(json_mode)
    return "running"


def _jobs_args(
    *,
    limit: int,
    phase: str | None,
    source: str | None,
    trigger: str | None,
    query: str | None,
) -> dict[str, object]:
    args: dict[str, object] = {"limit": limit}
    optional_args = {
        "phase": phase,
        "source": source,
        "trigger": trigger,
        "query": query,
    }
    args.update({key: value for key, value in optional_args.items() if value})
    return args


def _exit_jobs_not_running(json_mode: bool) -> NoReturn:
    message = "Service is not running. Start it with `vaultspec-rag server start`."
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "service_not_running", message, 3)
    _cli.console.print(
        "[red]Service is not running.[/] "
        "Start it with [bold]vaultspec-rag server start[/].",
    )
    raise typer.Exit(3)


def _jobs_from_result(result: dict[str, object]) -> list[object]:
    raw_jobs = result.get("jobs")
    return cast("list[object]", raw_jobs) if isinstance(raw_jobs, list) else []


def _running_count(result: dict[str, object], jobs: list[object]) -> object:
    summary = result.get("summary")
    if isinstance(summary, dict):
        return summary.get("running", 0)
    return sum(
        1
        for entry in jobs
        if isinstance(entry, dict) and entry.get("phase") == "running"
    )


def _render_jobs_table(result: dict[str, object], jobs: list[object]) -> None:
    total = result.get("total", len(jobs))
    returned = result.get("returned", len(jobs))
    running = _running_count(result, jobs)
    table = Table(
        title=f"Jobs ({returned}/{total} shown, {running} running)",
        padding=(0, 1),
    )
    table.add_column("ID", no_wrap=True)
    table.add_column("Source", style="bold", no_wrap=True)
    table.add_column("Trigger", no_wrap=True)
    table.add_column("Phase", no_wrap=True)
    table.add_column("Age", justify="right", no_wrap=True)
    table.add_column("Detail", overflow="fold")
    for entry in jobs:
        job = cast("dict[str, object]", entry) if isinstance(entry, dict) else {}
        table.add_row(
            str(job.get("id", ""))[:8],
            str(job.get("source", "?")),
            str(job.get("trigger", "?")),
            str(job.get("phase", "?")),
            _format_job_age(job),
            _job_detail(job),
        )
    _cli.console.print(table)


@server_app.command("jobs")
def service_jobs(
    limit: Annotated[
        int,
        typer.Option("--limit", help="Max number of matching jobs to show."),
    ] = 20,
    phase: Annotated[
        str | None,
        typer.Option("--phase", help="Filter by job phase, for example running."),
    ] = None,
    source: Annotated[
        str | None,
        typer.Option("--source", help="Filter by source: vault or code."),
    ] = None,
    trigger: Annotated[
        str | None,
        typer.Option("--trigger", help="Filter by trigger: tool or watcher."),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            "-q",
            help="Filter by text in id, result, or progress.",
        ),
    ] = None,
    running: Annotated[
        bool,
        typer.Option("--running", help="Show only running jobs."),
    ] = False,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of a table."),
    ] = False,
) -> None:
    """Show recent index/reindex activity from the running service."""
    phase = _resolve_jobs_phase(phase, running, json_mode)
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin(
        "get_jobs",
        _jobs_args(
            limit=limit,
            phase=phase,
            source=source,
            trigger=trigger,
            query=query,
        ),
        resolved_port,
    )
    if result is None:
        _exit_jobs_not_running(json_mode)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    jobs = _jobs_from_result(result)
    if not jobs:
        _cli.console.print("[dim]No recent jobs.[/]")
        return

    _render_jobs_table(result, jobs)
