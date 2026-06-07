"""``server service jobs``: list recent index/reindex activity.

Tier-2b observability subcommand (``service-observability`` ADR, plan
P04). Calls the ``get_jobs`` MCP tool over the ``_try_http_admin`` seam
and renders a Rich table (or the JSON envelope). Service-not-running
yields exit code 3.
"""

from __future__ import annotations

from typing import Annotated, cast

import typer
from rich.table import Table

import vaultspec_rag.cli as _cli

from ._app import service_app
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


@service_app.command("jobs")
def service_jobs(
    limit: Annotated[
        int | None,
        typer.Option("--limit", help="Max number of recent jobs to show."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="MCP port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one JSON envelope instead of a table."),
    ] = False,
) -> None:
    """Show recent index/reindex activity from the running service."""
    resolved_port = port if port is not None else _default_service_port()
    args: dict[str, object] = {}
    if limit is not None:
        args["limit"] = limit
    result = _try_http_admin("get_jobs", args, resolved_port)
    if result is None:
        if json_mode:
            _emit_json_error_and_exit(
                "service.jobs",
                "service_not_running",
                "Service is not running. Start it with "
                "`vaultspec-rag server service start`.",
                3,
            )
        _cli.console.print(
            "[red]Service is not running.[/] "
            "Start it with [bold]vaultspec-rag server service start[/].",
        )
        raise typer.Exit(3)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    raw_jobs = result.get("jobs")
    jobs: list[object] = list(raw_jobs) if isinstance(raw_jobs, list) else []
    if not jobs:
        _cli.console.print("[dim]No recent jobs.[/]")
        return

    table = Table(title="Recent jobs", padding=(0, 2))
    table.add_column("Source", style="bold")
    table.add_column("Trigger")
    table.add_column("Phase")
    table.add_column("Result")
    for entry in jobs:
        job = cast("dict[str, object]", entry) if isinstance(entry, dict) else {}
        phase = str(job.get("phase", "?"))
        result_str = str(job.get("result") or "")
        if phase == "running" and not result_str:
            result_str = _format_running_job_result(job)
        table.add_row(
            str(job.get("source", "?")),
            str(job.get("trigger", "?")),
            phase,
            result_str,
        )
    _cli.console.print(table)
