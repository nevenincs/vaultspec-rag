"""``server jobs``: list recent index/reindex activity.

Calls the jobs admin endpoint through the shared HTTP admin client and
renders either a line-oriented operator feed or the JSON envelope.
Service-not-running yields exit code 3.
"""

from __future__ import annotations

import re
import time
from typing import Annotated, NoReturn, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port

_RESULT_RE = re.compile(
    r"^\+(?P<added>\d+)\s*/(?P<updated>\d+)\s*-(?P<removed>\d+)"
    r"\s*\((?P<duration_ms>\d+)ms\)(?:\s*~(?P<skipped>\d+))?$"
)


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


def _format_milliseconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "?"
    return _format_seconds(float(raw) / 1000.0)


def _format_mb(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "?"
    return f"{float(raw):.1f} MB"


def _resource_at(job: dict[str, object], key: str) -> dict[str, object] | None:
    resources = job.get("resources")
    if not isinstance(resources, dict):
        return None
    value = resources.get(key)
    return cast("dict[str, object]", value) if isinstance(value, dict) else None


def _preferred_resource_snapshot(job: dict[str, object]) -> dict[str, object] | None:
    for key in ("current", "finished", "started"):
        snapshot = _resource_at(job, key)
        if snapshot is not None:
            return snapshot
    return None


def _resource_summary(job: dict[str, object]) -> str:
    snapshot = _preferred_resource_snapshot(job)
    if snapshot is None:
        return ""
    return (
        f"rss {_format_mb(snapshot.get('rss_mb'))}, "
        f"cuda alloc {_format_mb(snapshot.get('cuda_allocated_mb'))}, "
        f"cuda reserved {_format_mb(snapshot.get('cuda_reserved_mb'))}"
    )


def _phase_label(job: dict[str, object]) -> str:
    phase = str(job.get("phase", "?"))
    if phase in ("error", "failed"):
        return "FAILED"
    if phase == "running":
        return "running"
    return phase


def _job_prefix(job: dict[str, object]) -> str:
    phase = str(job.get("phase", ""))
    if phase == "running":
        return "*"
    if phase in ("error", "failed"):
        return "!"
    return " "


def _job_timestamp(job: dict[str, object]) -> float:
    timestamp = job.get("finished_at") or job.get("started_at")
    return float(timestamp) if isinstance(timestamp, int | float) else 0.0


def _job_time_label(job: dict[str, object]) -> str:
    timestamp = _job_timestamp(job)
    if timestamp <= 0:
        return "time unknown"
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


def _project_label(job: dict[str, object]) -> str:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return "project unknown"
    project_root = initiator.get("project_root")
    if not project_root:
        return "project unknown"
    parts = str(project_root).replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else str(project_root)


def _project_root(job: dict[str, object]) -> str | None:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return None
    root = initiator.get("project_root")
    return str(root) if root else None


def _source_label(job: dict[str, object]) -> str:
    source = str(job.get("source", "?"))
    if source == "code":
        return "code"
    if source == "vault":
        return "vault"
    return source


def _operation_label(job: dict[str, object]) -> str:
    source = _source_label(job)
    trigger = str(job.get("trigger", ""))
    initiator = job.get("initiator")
    command = ""
    if isinstance(initiator, dict):
        command = str(initiator.get("command") or "")
    if trigger == "watcher":
        return f"{source} index update"
    if command.startswith("reindex_"):
        return f"{source} index refresh"
    return f"{source} index operation"


def _progress_step_label(step: str) -> str:
    labels = {
        "queued": "waiting for writer lock",
        "discover": "discovering items",
        "chunk": "chunking files",
        "embed": "embedding chunks",
        "index": "writing index",
        "upsert": "writing vectors",
    }
    return labels.get(step, step.replace("_", " "))


def _human_progress(job: dict[str, object]) -> str:
    progress = job.get("progress")
    if not isinstance(progress, dict):
        return ""
    step = str(progress.get("step", ""))
    label = _progress_step_label(step)
    completed = progress.get("completed")
    total = progress.get("total")
    if isinstance(completed, int | float) and isinstance(total, int | float):
        return f"{label} {int(completed)} of {int(total)}"
    if isinstance(completed, int | float) and step:
        return f"{label} {int(completed)}"
    return label


def _human_result(raw: object) -> str:
    if not raw:
        return ""
    result = str(raw)
    match = _RESULT_RE.match(result.strip())
    if match is None:
        return result
    added = int(match.group("added"))
    updated = int(match.group("updated"))
    removed = int(match.group("removed"))
    duration_ms = int(match.group("duration_ms"))
    parts = [
        f"added {added}",
        f"updated {updated}",
        f"removed {removed}",
        f"finished in {_format_milliseconds(duration_ms)}",
    ]
    skipped = match.group("skipped")
    if skipped is not None:
        parts.append(f"skipped {int(skipped)}")
    return ", ".join(parts)


def _job_summary_detail(job: dict[str, object]) -> str:
    phase = str(job.get("phase", ""))
    if phase == "running":
        detail = _human_progress(job)
        runtime = _format_seconds(job.get("runtime_seconds"))
        if detail:
            return f"{detail}; running for {runtime}"
        return f"running for {runtime}"
    if phase in ("error", "failed"):
        result = _human_result(job.get("result"))
        return f"error: {result}" if result else "error reported"
    result = _human_result(job.get("result"))
    if result:
        return result
    progress = _human_progress(job)
    return progress


def _human_sorted_jobs(jobs: list[object]) -> list[dict[str, object]]:
    normalised = [
        cast("dict[str, object]", entry) if isinstance(entry, dict) else {}
        for entry in jobs
    ]
    return sorted(normalised, key=_job_timestamp)


def _summary_count(summary: object, key: str) -> int:
    if not isinstance(summary, dict):
        return 0
    value = summary.get(key)
    return int(value) if isinstance(value, int | float) else 0


def _summary_phase_count(summary: object, *phases: str) -> int:
    if not isinstance(summary, dict):
        return 0
    phase_counts = summary.get("phases")
    if not isinstance(phase_counts, dict):
        return 0
    total = 0
    for phase in phases:
        value = phase_counts.get(phase, 0)
        if isinstance(value, int | float):
            total += int(value)
    return total


def _filters_label(result: dict[str, object]) -> str:
    filters = result.get("filters")
    if not isinstance(filters, dict):
        return ""
    visible: list[str] = []
    for key in ("phase", "source", "trigger", "query", "job_id", "since"):
        value = filters.get(key)
        if value not in (None, "", False):
            visible.append(f"{key}={value}")
    if filters.get("failed") is True:
        visible.append("failed=true")
    return f" filters: {', '.join(visible)}" if visible else ""


def _render_jobs_feed(
    result: dict[str, object],
    jobs: list[object],
    *,
    port: int,
    monitoring: bool = False,
) -> None:
    total = result.get("total", len(jobs))
    returned = result.get("returned", len(jobs))
    summary = result.get("summary")
    running = _summary_count(summary, "running")
    failed = _summary_phase_count(summary, "error", "failed")
    filter_text = _filters_label(result)
    monitor_text = ""
    if monitoring:
        monitor_text = f" refreshed {time.strftime('%H:%M:%S', time.localtime())}"
    _cli.console.print(
        f"Jobs on service port {port}: {returned}/{total} shown, "
        f"{running} running, {failed} failed. Latest shown last.{filter_text}"
        f"{monitor_text}",
        soft_wrap=True,
    )
    if monitoring:
        _cli.console.print("[dim]Watching; press Ctrl+C to stop.[/]")
    for job in _human_sorted_jobs(jobs):
        job_id = str(job.get("id", ""))[:8]
        _cli.console.print(
            f"{_job_prefix(job)} {_job_time_label(job)} {_phase_label(job)} "
            f"{_operation_label(job)} project={_project_label(job)} id={job_id} - "
            f"{_job_summary_detail(job)}",
            soft_wrap=True,
        )


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


def _render_job_detail(job: dict[str, object]) -> None:
    _cli.console.print(f"Job {job.get('id', '')!s}")
    _cli.console.print(f"Operation: {_operation_label(job)}")
    _cli.console.print(f"Project: {_project_label(job)}")
    root = _project_root(job)
    if root:
        _cli.console.print(f"Project root: {root}")
    _cli.console.print(f"State: {_phase_label(job)}")
    _cli.console.print(f"Runtime: {_format_seconds(job.get('runtime_seconds'))}")
    _cli.console.print(
        "Last progress update: "
        f"{_format_seconds(job.get('last_progress_age_seconds'))} ago"
    )
    initiator = job.get("initiator")
    if isinstance(initiator, dict):
        _cli.console.print(f"Initiator: {initiator.get('kind', '?')}")
        _cli.console.print(f"Command: {initiator.get('command', '?')}")
    runtime = job.get("runtime")
    if isinstance(runtime, dict):
        pid = runtime.get("pid")
        user = runtime.get("user")
        if pid is not None:
            _cli.console.print(f"PID: {pid}")
        if user:
            _cli.console.print(f"OS user: {user}")
        executable = runtime.get("executable")
        if executable:
            _cli.console.print(f"Executable: {executable}")
        virtual_env = runtime.get("virtual_env") or runtime.get("prefix")
        if virtual_env:
            _cli.console.print(f"Virtual env: {virtual_env}")
    progress = job.get("progress")
    if isinstance(progress, dict):
        _cli.console.print(f"Progress: {_human_progress(job)}")
    resource_summary = _resource_summary(job)
    if resource_summary:
        _cli.console.print(f"Resources: {resource_summary}")
    result = job.get("result")
    if result:
        label = "Error" if str(job.get("phase")) in ("error", "failed") else "Result"
        _cli.console.print(f"{label}: {_human_result(result)}")


def _render_jobs_result(
    result: dict[str, object],
    *,
    job_id: str | None,
    port: int,
    monitoring: bool = False,
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
            _render_jobs_feed(result, jobs, port=port)
            raise typer.Exit(2)
        first = jobs[0]
        _render_job_detail(
            cast("dict[str, object]", first) if isinstance(first, dict) else {}
        )
        return
    _render_jobs_feed(result, jobs, port=port, monitoring=monitoring)


def _exit_invalid_watch_args(json_mode: bool, interval: float) -> NoReturn:
    message = "--watch is human-only and --interval must be greater than zero."
    if interval > 0:
        message = "--watch cannot be combined with --json."
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "invalid_watch", message, 2)
    _cli.console.print(f"[bold red]Error:[/] {message}")
    raise typer.Exit(2)


def _fetch_jobs_result(
    *,
    limit: int,
    phase: str | None,
    source: str | None,
    trigger: str | None,
    query: str | None,
    failed: bool,
    job_id: str | None,
    since: float | None,
    port: int,
) -> dict[str, object] | None:
    return _try_http_admin(
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
        port,
    )


def _watch_jobs(
    *,
    limit: int,
    phase: str | None,
    source: str | None,
    trigger: str | None,
    query: str | None,
    failed: bool,
    job_id: str | None,
    since: float | None,
    port: int,
    interval: float,
    refresh_count: int | None,
) -> None:
    refreshes = 0
    while refresh_count is None or refreshes < refresh_count:
        result = _fetch_jobs_result(
            limit=limit,
            phase=phase,
            source=source,
            trigger=trigger,
            query=query,
            failed=failed,
            job_id=job_id,
            since=since,
            port=port,
        )
        if result is None:
            _exit_jobs_not_running(False)
        _cli.console.clear()
        _render_jobs_result(
            result,
            job_id=job_id,
            port=port,
            monitoring=True,
        )
        refreshes += 1
        if refresh_count is not None and refreshes >= refresh_count:
            return
        time.sleep(interval)


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
        typer.Option("--json", help="Emit one JSON envelope instead of human output."),
    ] = False,
    watch: Annotated[
        bool,
        typer.Option("--watch", help="Continuously refresh the human jobs view."),
    ] = False,
    interval: Annotated[
        float,
        typer.Option("--interval", help="Seconds between --watch refreshes."),
    ] = 2.0,
    refresh_count: Annotated[
        int | None,
        typer.Option(
            "--refresh-count",
            help="Stop --watch after N refreshes.",
            hidden=True,
        ),
    ] = None,
) -> None:
    """Show recent index/reindex activity from the running service."""
    phase, failed = _resolve_jobs_filters(phase, running, failed, json_mode)
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        _exit_jobs_not_running(json_mode)
    if interval <= 0:
        _exit_invalid_watch_args(json_mode, interval)
    if watch and json_mode:
        _exit_invalid_watch_args(json_mode, interval)
    if watch:
        try:
            _watch_jobs(
                limit=limit,
                phase=phase,
                source=source,
                trigger=trigger,
                query=query,
                failed=failed,
                job_id=job_id,
                since=since,
                port=resolved_port,
                interval=interval,
                refresh_count=refresh_count,
            )
        except KeyboardInterrupt:
            _cli.console.print("\n[dim]Stopped watching jobs.[/]")
        return

    result = _fetch_jobs_result(
        limit=limit,
        phase=phase,
        source=source,
        trigger=trigger,
        query=query,
        failed=failed,
        job_id=job_id,
        since=since,
        port=resolved_port,
    )
    if result is None:
        _exit_jobs_not_running(json_mode)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    _render_jobs_result(result, job_id=job_id, port=resolved_port)
