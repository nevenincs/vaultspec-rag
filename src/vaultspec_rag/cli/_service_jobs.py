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


def _format_progress_text(job: dict[str, object]) -> str:
    prog = job.get("progress")
    if not isinstance(prog, dict):
        return ""
    prog_dict = cast("dict[str, object]", prog)
    step = str(prog_dict.get("step", ""))
    completed = prog_dict.get("completed", 0)
    total = prog_dict.get("total")
    if total is not None:
        return f"{step} ({completed}/{total})"
    return f"{step} ({completed})" if step else str(completed)


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


def _format_seconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "?"
    seconds = max(0, int(float(raw)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {rem}s"
    hours, minutes = divmod(minutes, 60)
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


def _resolve_jobs_filters(
    phase: str | None,
    running: bool,
    failed: bool,
    json_mode: bool,
) -> tuple[str | None, bool]:
    resolved_phase = _resolve_jobs_phase(phase, running, json_mode)
    if (
        failed
        and resolved_phase is not None
        and resolved_phase not in ("error", "failed")
    ):
        message = "--failed cannot be combined with --phase outside error/failed."
        if json_mode:
            _emit_json_error_and_exit("service.jobs", "invalid_filter", message, 2)
        _cli.console.print(f"[bold red]Error:[/] {message}")
        raise typer.Exit(2)
    return resolved_phase, failed


def _jobs_args(
    *,
    limit: int,
    phase: str | None,
    source: str | None,
    trigger: str | None,
    query: str | None,
    failed: bool,
    job_id: str | None,
    since: float | None,
) -> dict[str, object]:
    args: dict[str, object] = {"limit": limit}
    optional_args = {
        "phase": phase,
        "source": source,
        "trigger": trigger,
        "query": query,
        "job_id": job_id,
        "since": since,
    }
    args.update(
        {
            key: value
            for key, value in optional_args.items()
            if value is not None and value != ""
        }
    )
    if failed:
        args["failed"] = True
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


def _render_job_detail(job: dict[str, object]) -> None:
    table = Table(title=f"Job {str(job.get('id', ''))[:12]}", show_header=False)
    table.add_column("Key", style="bold")
    table.add_column("Value")
    table.add_row("ID", str(job.get("id", "")))
    table.add_row("Source", str(job.get("source", "?")))
    table.add_row("Trigger", str(job.get("trigger", "?")))
    table.add_row("Phase", str(job.get("phase", "?")))
    table.add_row("Runtime", _format_seconds(job.get("runtime_seconds")))
    table.add_row(
        "Last progress age",
        _format_seconds(job.get("last_progress_age_seconds")),
    )
    initiator = job.get("initiator")
    if isinstance(initiator, dict):
        table.add_row("Initiator", str(initiator.get("kind", "?")))
        table.add_row("Command", str(initiator.get("command", "?")))
        project_root = initiator.get("project_root")
        if project_root:
            table.add_row("Project root", str(project_root))
    progress = job.get("progress")
    if isinstance(progress, dict):
        table.add_row("Progress", _format_progress_text(job))
    result = job.get("result")
    if result:
        table.add_row("Result", str(result))
    _cli.console.print(table)


def _render_jobs_result(
    result: dict[str, object],
    *,
    job_id: str | None,
) -> None:
    jobs = _jobs_from_result(result)
    if not jobs:
        _cli.console.print(
            "[dim]No matching jobs.[/]" if job_id else "[dim]No recent jobs.[/]"
        )
        return
    if job_id:
        if len(jobs) > 1:
            _cli.console.print(
                f"[bold red]Error:[/] job id prefix [cyan]{job_id}[/] "
                f"matches {len(jobs)} jobs. Use a longer prefix."
            )
            _render_jobs_table(result, jobs)
            raise typer.Exit(2)
        first = jobs[0]
        _render_job_detail(
            cast("dict[str, object]", first) if isinstance(first, dict) else {}
        )
        return
    _render_jobs_table(result, jobs)


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
    failed: Annotated[
        bool,
        typer.Option("--failed", help="Show only failed/error jobs."),
    ] = False,
    job_id: Annotated[
        str | None,
        typer.Option("--job-id", help="Show details for a job id or id prefix."),
    ] = None,
    since: Annotated[
        float | None,
        typer.Option("--since", help="Show jobs updated within the last N seconds."),
    ] = None,
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
    phase, failed = _resolve_jobs_filters(phase, running, failed, json_mode)
    resolved_port = port if port is not None else _default_service_port()
    result = _try_http_admin(
        "get_jobs",
        _jobs_args(
            limit=limit,
            phase=phase,
            source=source,
            trigger=trigger,
            query=query,
            failed=failed,
            job_id=job_id,
            since=since,
        ),
        resolved_port,
    )
    if result is None:
        _exit_jobs_not_running(json_mode)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    _render_jobs_result(result, job_id=job_id)
