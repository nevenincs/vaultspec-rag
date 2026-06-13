"""``server jobs``: list recent index update activity.

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
from ._render import (
    _display_service_not_running,
    _emit_json,
    _emit_json_error_and_exit,
)
from ._service_status import _default_service_port

_RESULT_RE = re.compile(
    r"^\+(?P<added>\d+)\s*/(?P<updated>\d+)\s*-(?P<removed>\d+)"
    r"\s*\((?P<duration_ms>\d+)ms\)(?:\s*~(?P<skipped>\d+))?$"
)
_STALE_PROGRESS_SECONDS = 300.0


def _counted_unit(value: int, singular: str, plural: str | None = None) -> str:
    unit = singular if value == 1 else plural or f"{singular}s"
    return f"{value} {unit}"


def _format_seconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    raw_seconds = max(0.0, float(raw))
    if raw_seconds < 1:
        return "less than 1 second"
    seconds = int(raw_seconds)
    if seconds < 60:
        return _counted_unit(seconds, "second")
    minutes, rem = divmod(seconds, 60)
    if minutes < 60:
        if rem:
            return f"{_counted_unit(minutes, 'minute')} {_counted_unit(rem, 'second')}"
        return _counted_unit(minutes, "minute")
    hours, minutes = divmod(minutes, 60)
    if minutes:
        return f"{_counted_unit(hours, 'hour')} {_counted_unit(minutes, 'minute')}"
    return _counted_unit(hours, "hour")


def _format_milliseconds(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
    return _format_seconds(float(raw) / 1000.0)


def _format_mb(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported"
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
    parts: list[str] = []
    if "rss_mb" in snapshot:
        parts.append(f"process {_format_mb(snapshot.get('rss_mb'))}")
    if "cuda_allocated_mb" in snapshot:
        parts.append(f"GPU used {_format_mb(snapshot.get('cuda_allocated_mb'))}")
    if "cuda_reserved_mb" in snapshot:
        parts.append(f"GPU reserved {_format_mb(snapshot.get('cuda_reserved_mb'))}")
    return ", ".join(parts)


def _initiator_label(raw: object) -> str:
    value = str(raw or "not reported")
    if value == "watcher":
        return "automatic updates"
    if value in ("cli", "tool"):
        return "manual request"
    return value.replace("_", " ")


def _command_label(raw: object) -> str:
    value = str(raw or "request not reported")
    if value == "watcher_code_index":
        return "automatic code index update"
    if value == "watcher_vault_index":
        return "automatic vault index update"
    if value == "reindex_codebase":
        return "code index refresh"
    if value == "reindex_vault":
        return "vault index refresh"
    return value.replace("_", " ")


def _path_label(raw: object) -> str:
    value = str(raw or "")
    if not value:
        return "path not reported"
    parts = value.replace("\\", "/").rstrip("/").split("/")
    if ".venv" in parts:
        return "/".join(parts[parts.index(".venv") :])
    if len(parts) > 3:
        return ".../" + "/".join(parts[-3:])
    return value


def _job_is_waiting(job: dict[str, object]) -> bool:
    if str(job.get("phase", "")) != "running":
        return False
    progress = job.get("progress")
    return isinstance(progress, dict) and progress.get("step") == "queued"


def _phase_label(job: dict[str, object]) -> str:
    phase = str(job.get("phase", "not-reported"))
    if phase in ("error", "failed"):
        return "failed"
    if _job_is_waiting(job):
        return "waiting"
    if phase == "running":
        return "active"
    if phase == "done":
        return "finished"
    return phase


def _job_prefix(job: dict[str, object]) -> str:
    phase = str(job.get("phase", ""))
    if _job_is_waiting(job):
        return "~"
    if phase == "running":
        return "*"
    if phase in ("error", "failed"):
        return "!"
    return "-"


def _job_timestamp(job: dict[str, object]) -> float:
    timestamp = job.get("finished_at") or job.get("started_at")
    return float(timestamp) if isinstance(timestamp, int | float) else 0.0


def _job_time_label(job: dict[str, object]) -> str:
    timestamp = _job_timestamp(job)
    if timestamp <= 0:
        return "time not reported"
    return time.strftime("%H:%M:%S", time.localtime(timestamp))


def _project_label(job: dict[str, object]) -> str:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return "project not reported"
    project_root = initiator.get("project_root")
    if not project_root:
        return "project not reported"
    parts = str(project_root).replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else str(project_root)


def _project_phrase(job: dict[str, object]) -> str:
    project = _project_label(job)
    if project == "project not reported":
        return ""
    return f" for {project}"


def _project_root(job: dict[str, object]) -> str | None:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return None
    root = initiator.get("project_root")
    return str(root) if root else None


def _source_label(job: dict[str, object]) -> str:
    source = str(job.get("source", "index"))
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


def _progress_step_label(step: str, source: str) -> str:
    section = (
        "source code section"
        if source == "code"
        else "document section"
        if source == "vault"
        else "section"
    )
    sections = f"{section}s"
    labels = {
        "queued": "waiting to write the index",
        "discover": "discovering items",
        "chunk": "preparing files",
        "delete removed": (
            "removing stale source files"
            if source == "code"
            else "removing deleted vault documents"
            if source == "vault"
            else "removing stale index entries"
        ),
        "embed": f"embedding {sections}",
        "embed + upsert chunks": f"embedding and writing {sections}",
        "embed + upsert documents": "embedding and writing documents",
        "index": "writing index",
        "chunk + embed": "preparing and embedding files",
        "upsert": "writing vectors",
    }
    return labels.get(step, step.replace("_", " "))


def _human_progress(job: dict[str, object]) -> str:
    progress = job.get("progress")
    if not isinstance(progress, dict):
        return ""
    step = str(progress.get("step", ""))
    label = _progress_step_label(step, _source_label(job))
    completed = progress.get("completed")
    total = progress.get("total")
    if step == "queued":
        return label
    if isinstance(completed, int | float) and isinstance(total, int | float):
        return f"{label} {int(completed)} of {int(total)}"
    if isinstance(completed, int | float) and step:
        return f"{label} {int(completed)}"
    return label


def _stale_progress_label(job: dict[str, object]) -> str:
    if str(job.get("phase", "")) != "running" or _job_is_waiting(job):
        return ""
    raw_age = job.get("last_progress_age_seconds")
    if not isinstance(raw_age, int | float):
        return ""
    if float(raw_age) < _STALE_PROGRESS_SECONDS:
        return ""
    return f"no progress for {_format_seconds(raw_age)}"


def _human_result(raw: object) -> str:
    if not raw:
        return ""
    result = " ".join(str(raw).split())
    if result == "watcher task cancelled":
        return "automatic update cancelled"
    if "[Errno 28]" in result or "No space left on device" in result:
        return "not enough disk space; free disk space and retry"
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


def _waiting_job_detail(detail: str, raw_runtime: object) -> str:
    has_runtime = isinstance(raw_runtime, int | float)
    if detail:
        return (
            f"{detail} for {_format_seconds(raw_runtime)}"
            if has_runtime
            else f"{detail}; runtime not reported"
        )
    return (
        f"waiting for {_format_seconds(raw_runtime)}"
        if has_runtime
        else "waiting; runtime not reported"
    )


def _running_job_detail(job: dict[str, object]) -> str:
    detail = _human_progress(job)
    raw_runtime = job.get("runtime_seconds")
    if _job_is_waiting(job):
        return _waiting_job_detail(detail, raw_runtime)
    runtime_detail = (
        f"running for {_format_seconds(raw_runtime)}"
        if isinstance(raw_runtime, int | float)
        else "runtime not reported"
    )
    stale_progress = _stale_progress_label(job)
    parts = [p for p in (detail, runtime_detail, stale_progress) if p]
    return "; ".join(parts) if parts else runtime_detail


def _job_summary_detail(job: dict[str, object]) -> str:
    phase = str(job.get("phase", ""))
    if phase == "running":
        return _running_job_detail(job)
    if phase in ("error", "failed"):
        result = _human_result(job.get("result"))
        return f"error: {result}" if result else "error reported"
    result = _human_result(job.get("result"))
    if result:
        return result
    return _human_progress(job)


def _human_sorted_jobs(jobs: list[object]) -> list[dict[str, object]]:
    normalised = [
        cast("dict[str, object]", entry) if isinstance(entry, dict) else {}
        for entry in jobs
    ]
    return sorted(normalised, key=_job_timestamp)


def _job_id_labels(jobs: list[dict[str, object]]) -> dict[int, str]:
    raw_ids = [str(job.get("id", "")) for job in jobs]
    labels: dict[int, str] = {}
    for index, raw_id in enumerate(raw_ids):
        if not raw_id:
            labels[index] = "not reported"
            continue
        min_length = min(8, len(raw_id))
        label = raw_id[:min_length]
        for length in range(min_length, len(raw_id) + 1):
            prefix = raw_id[:length]
            matches = [other for other in raw_ids if other and other.startswith(prefix)]
            if len(matches) == 1:
                label = prefix
                break
        labels[index] = label
    return labels


def _shown_job_counts(jobs: list[dict[str, object]]) -> tuple[int, int, int, int]:
    active = 0
    waiting = 0
    finished = 0
    failed = 0
    for job in jobs:
        phase = str(job.get("phase", ""))
        if phase in ("error", "failed"):
            failed += 1
        elif phase == "done":
            finished += 1
        elif _job_is_waiting(job):
            waiting += 1
        elif phase == "running":
            active += 1
    return active, waiting, finished, failed


def _filters_label(result: dict[str, object]) -> str:
    filters = result.get("filters")
    if not isinstance(filters, dict):
        return ""
    visible: list[str] = []
    labels = {
        "phase": "state",
        "source": "index",
        "trigger": "started by",
        "query": "text",
        "job_id": "job",
        "since": "updated within",
    }
    values = {
        "running": "active or waiting",
        "done": "finished",
        "watcher": "automatic updates",
        "tool": "manual request",
    }
    state = filters.get("state")
    if state == "active":
        visible.append("state active")
    elif state == "waiting":
        visible.append("state waiting")
    elif state not in (None, "", False):
        visible.append(f"state {state}")

    for key in ("phase", "source", "trigger", "query", "job_id", "since"):
        if key == "phase" and state in ("active", "waiting"):
            continue
        value = filters.get(key)
        if value not in (None, "", False):
            value_text = values.get(str(value), str(value))
            visible.append(f"{labels[key]} {value_text}")
    if filters.get("failed") is True:
        visible.append("failed only")
    return f" Filtered by {'; '.join(visible)}." if visible else ""


def _filter_line(result: dict[str, object]) -> str:
    text = _filters_label(result).strip()
    if not text:
        return ""
    prefix = "Filtered by "
    if text.startswith(prefix):
        text = text[len(prefix) :]
    return text.removesuffix(".")


def _job_count_text(
    count: object,
    singular: str = "job",
    plural: str | None = None,
) -> str:
    value = count if isinstance(count, int) else 0
    word = singular if value == 1 else (plural or f"{singular}s")
    return f"{value} {word}"


def _render_jobs_feed(
    result: dict[str, object],
    jobs: list[object],
    *,
    port: int,
    monitoring: bool = False,
    watch_text: str | None = None,
) -> None:
    total = result.get("total", len(jobs))
    returned = result.get("returned", len(jobs))
    sorted_jobs = _human_sorted_jobs(jobs)
    active, waiting, finished, failed = _shown_job_counts(sorted_jobs)
    _cli.console.print("Jobs", markup=False, highlight=False)
    _cli.console.print(
        f"Address: http://127.0.0.1:{port}",
        markup=False,
        highlight=False,
    )
    filter_text = _filter_line(result)
    shown_count = (
        _job_count_text(returned, "matching job", "matching jobs")
        if filter_text
        else _job_count_text(returned)
    )
    _cli.console.print(
        f"Displayed: {shown_count}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Total: {_job_count_text(total)}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"Displayed jobs: {active} active, {waiting} waiting, "
        f"{finished} finished, {failed} failed",
        markup=False,
        highlight=False,
    )
    if not filter_text:
        _cli.console.print(
            "Showing: active, waiting, failed, then latest finished",
            markup=False,
            highlight=False,
        )
    _cli.console.print("Order: latest job appears last", markup=False, highlight=False)
    _cli.console.print(
        "Legend: * active, ~ waiting, ! failed, - finished",
        markup=False,
        highlight=False,
    )
    if filter_text:
        _cli.console.print(f"Filter: {filter_text}", markup=False, highlight=False)
    if monitoring:
        _cli.console.print(
            f"Refreshed: {time.strftime('%H:%M:%S', time.localtime())}",
            markup=False,
            highlight=False,
        )
        _cli.console.print(watch_text or "Watch: press Ctrl+C to stop.")
    job_id_labels = _job_id_labels(sorted_jobs)
    for index, job in enumerate(sorted_jobs):
        job_id = job_id_labels[index]
        _cli.console.print(
            f"{_job_prefix(job)} {_job_time_label(job)} {_phase_label(job)} "
            f"{_operation_label(job)}{_project_phrase(job)} (job {job_id}) - "
            f"{_job_summary_detail(job)}",
            soft_wrap=True,
        )


def _render_empty_jobs_result(
    result: dict[str, object],
    *,
    job_id: str | None,
    port: int,
    monitoring: bool,
    watch_text: str | None = None,
) -> None:
    total = result.get("total", 0)
    returned = result.get("returned", 0)
    filter_text = _filter_line(result)
    shown_count = (
        _job_count_text(returned, "matching job", "matching jobs")
        if filter_text or job_id
        else _job_count_text(returned)
    )
    _cli.console.print("Jobs", markup=False, highlight=False)
    _cli.console.print(
        f"Address: http://127.0.0.1:{port}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(f"Displayed: {shown_count}", markup=False, highlight=False)
    _cli.console.print(
        f"Total: {_job_count_text(total)}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        "Displayed jobs: 0 active, 0 waiting, 0 finished, 0 failed",
        markup=False,
        highlight=False,
    )
    _cli.console.print("Order: latest job appears last", markup=False, highlight=False)
    if filter_text:
        _cli.console.print(f"Filter: {filter_text}", markup=False, highlight=False)
    if monitoring:
        _cli.console.print(
            f"Refreshed: {time.strftime('%H:%M:%S', time.localtime())}",
            markup=False,
            highlight=False,
        )
        _cli.console.print(watch_text or "Watch: press Ctrl+C to stop.")
    _cli.console.print(_empty_jobs_message(result, job_id))
    _cli.console.print("Next actions:", markup=False, highlight=False)
    _cli.console.print(
        f"  vaultspec-rag server status --port {port}",
        markup=False,
        highlight=False,
    )
    _cli.console.print(
        f"  vaultspec-rag server logs --limit 20 --port {port}",
        markup=False,
        highlight=False,
    )


def _exit_invalid_jobs_filter(json_mode: bool, message: str) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            "service.jobs",
            "invalid_filter",
            message,
            2,
        )
    _cli.console.print(
        f"Error: {message}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    raise typer.Exit(2)


def _exit_invalid_jobs_filter_value(
    *,
    option: str,
    value: str,
    allowed: str,
    json_mode: bool,
) -> NoReturn:
    message = f'Invalid {option} "{value}". Use {allowed}.'
    _exit_invalid_jobs_filter(json_mode, message)


def _resolve_jobs_filters(
    phase: str | None,
    failed: bool,
    json_mode: bool,
) -> tuple[str | None, bool]:
    if failed and phase is not None and phase not in ("error", "failed"):
        message = "--failed can only be combined with --state failed."
        _exit_invalid_jobs_filter(json_mode, message)
    return phase, failed


def _jobs_trigger_value(trigger: str | None) -> str | None:
    if trigger is None:
        return None
    value = trigger.strip().lower()
    if value in ("automatic", "automatic-updates", "updates"):
        return "watcher"
    if value in ("manual", "manual-request", "manual-requests"):
        return "tool"
    return trigger


def _jobs_phase_value(phase: str | None) -> str | None:
    if phase is None:
        return None
    value = phase.strip().lower()
    if value in ("running", "active", "waiting"):
        return "running"
    if value in ("finished", "complete", "completed"):
        return "done"
    if value in ("failed", "failure", "error"):
        return "error"
    if value in ("cancelled", "canceled"):
        return "cancelled"
    return value


def _jobs_state_filter(
    state: str | None,
    json_mode: bool,
) -> tuple[str | None, str | None]:
    if state is None:
        return None, None
    normalized = _jobs_phase_value(state)
    requested = state.strip().lower()
    if requested in ("active", "waiting"):
        return "running", requested
    if normalized in ("done", "error", "cancelled"):
        return normalized, None
    _exit_invalid_jobs_filter_value(
        option="--state",
        value=state,
        allowed="active, waiting, finished, failed, or cancelled",
        json_mode=json_mode,
    )


def _jobs_started_by_filter(
    started_by: str | None,
    json_mode: bool,
) -> str | None:
    if started_by is None:
        return None
    normalized = _jobs_trigger_value(started_by)
    if normalized in ("watcher", "tool"):
        return normalized
    _exit_invalid_jobs_filter_value(
        option="--started-by",
        value=started_by,
        allowed="manual or automatic",
        json_mode=json_mode,
    )


def _jobs_index_filter(
    index: str | None,
    json_mode: bool,
) -> str | None:
    if index is None:
        return None
    normalized = index.strip().lower()
    if normalized in ("code", "source-code", "source code", "codebase"):
        return "code"
    if normalized == "vault":
        return "vault"
    _exit_invalid_jobs_filter_value(
        option="--index",
        value=index,
        allowed="vault or code",
        json_mode=json_mode,
    )


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
    normalized_phase = _jobs_phase_value(phase)
    normalized_trigger = _jobs_trigger_value(trigger)
    optional_args = {
        "phase": normalized_phase,
        "source": source,
        "trigger": normalized_trigger,
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


def _exit_jobs_not_running(json_mode: bool, port: int | None = None) -> NoReturn:
    message = "Service is not running. Start it with `vaultspec-rag server start`."
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "service_not_running", message, 3)
    _display_service_not_running(port)
    raise typer.Exit(3)


def _jobs_from_result(result: dict[str, object]) -> list[object]:
    raw_jobs = result.get("jobs")
    return cast("list[object]", raw_jobs) if isinstance(raw_jobs, list) else []


def _empty_jobs_message(result: dict[str, object], job_id: str | None) -> str:
    if job_id:
        return "No job matched that id."
    filters = result.get("filters")
    if not isinstance(filters, dict):
        return "No jobs have been reported by this service yet."
    if filters.get("failed") is True:
        return "There are no failed jobs."
    state = filters.get("state")
    if state == "active":
        return "There are no active jobs."
    if state == "waiting":
        return "There are no waiting jobs."
    phase = filters.get("phase")
    if isinstance(phase, str) and phase.lower() == "running":
        return "There are no active or waiting jobs."
    active_filters = [
        key
        for key, value in filters.items()
        if key != "limit" and value not in (None, "", False)
    ]
    if active_filters:
        return "No jobs matched these filters."
    return "No jobs have been reported by this service yet."


def _render_job_progress_detail(job: dict[str, object]) -> None:
    if str(job.get("phase", "")) == "running":
        _cli.console.print(
            "Last progress update: "
            f"{_format_seconds(job.get('last_progress_age_seconds'))} ago"
        )
    stale_progress = _stale_progress_label(job)
    if stale_progress:
        _cli.console.print(f"Progress warning: {stale_progress}")
    if isinstance(job.get("progress"), dict):
        _cli.console.print(f"Progress: {_human_progress(job)}")


def _render_job_initiator_detail(job: dict[str, object]) -> None:
    initiator = job.get("initiator")
    if not isinstance(initiator, dict):
        return
    initiator_data = cast("dict[str, object]", initiator)
    _cli.console.print(f"Started by: {_initiator_label(initiator_data.get('kind'))}")
    _cli.console.print(f"Request: {_command_label(initiator_data.get('command'))}")


def _render_job_runtime_detail(job: dict[str, object]) -> None:
    runtime = job.get("runtime")
    if not isinstance(runtime, dict):
        return
    runtime_data = cast("dict[str, object]", runtime)
    pid = runtime_data.get("pid")
    if pid is not None:
        _cli.console.print(f"Job process id: {pid}")
    user = runtime_data.get("user")
    if user:
        _cli.console.print(f"User: {user}")
    executable = runtime_data.get("executable")
    if executable:
        _cli.console.print(f"Python: {_path_label(executable)}")
    virtual_env = runtime_data.get("virtual_env") or runtime_data.get("prefix")
    if virtual_env:
        _cli.console.print(f"Python environment: {_path_label(virtual_env)}")


def _render_job_resource_detail(job: dict[str, object]) -> None:
    resource_summary = _resource_summary(job)
    if resource_summary:
        _cli.console.print(f"Memory: {resource_summary}")


def _render_job_result_detail(job: dict[str, object]) -> None:
    result = job.get("result")
    if not result:
        return
    label = "Error" if str(job.get("phase")) in ("error", "failed") else "Result"
    _cli.console.print(f"{label}: {_human_result(result)}")


def _render_job_detail(job: dict[str, object], *, port: int | None = None) -> None:
    if port is not None:
        _cli.console.print(
            f"Address: http://127.0.0.1:{port}",
            markup=False,
            highlight=False,
        )
    _cli.console.print(f"Job {job.get('id', '')!s}")
    _cli.console.print(f"Operation: {_operation_label(job)}")
    _cli.console.print(f"Project: {_project_label(job)}")
    root = _project_root(job)
    if root:
        _cli.console.print(f"Path: {root}", markup=False, highlight=False)
    _cli.console.print(f"Status: {_phase_label(job)}")
    _cli.console.print(f"Runtime: {_format_seconds(job.get('runtime_seconds'))}")
    _render_job_progress_detail(job)
    _render_job_initiator_detail(job)
    _render_job_runtime_detail(job)
    _render_job_resource_detail(job)
    _render_job_result_detail(job)


def _render_jobs_result(
    result: dict[str, object],
    *,
    job_id: str | None,
    port: int,
    monitoring: bool = False,
    watch_text: str | None = None,
) -> None:
    jobs = _jobs_from_result(result)
    if not jobs:
        _render_empty_jobs_result(
            result,
            job_id=job_id,
            port=port,
            monitoring=monitoring,
            watch_text=watch_text,
        )
        return
    if job_id:
        if len(jobs) > 1:
            _cli.console.print(
                f"Error: job id prefix {job_id} matches {len(jobs)} jobs. "
                "Use a longer prefix.",
                markup=False,
                highlight=False,
            )
            _render_jobs_feed(result, jobs, port=port)
            raise typer.Exit(2)
        first = jobs[0]
        _render_job_detail(
            cast("dict[str, object]", first) if isinstance(first, dict) else {},
            port=port,
        )
        return
    _render_jobs_feed(
        result, jobs, port=port, monitoring=monitoring, watch_text=watch_text
    )


def _exit_invalid_watch_args(json_mode: bool, interval: float) -> NoReturn:
    message = "--watch is human-only and --interval must be greater than zero."
    if interval > 0:
        message = "--watch cannot be combined with --json."
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "invalid_watch", message, 2)
    _cli.console.print(f"Error: {message}", markup=False, highlight=False)
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


def _client_state_matches(job: dict[str, object], state: str | None) -> bool:
    if state == "active":
        return str(job.get("phase", "")) == "running" and not _job_is_waiting(job)
    if state == "waiting":
        return _job_is_waiting(job)
    return True


def _apply_client_state_filter(
    result: dict[str, object],
    state: str | None,
) -> dict[str, object]:
    if state not in ("active", "waiting"):
        return result
    jobs: list[dict[str, object]] = []
    for job in _jobs_from_result(result):
        if not isinstance(job, dict):
            continue
        job_dict = cast("dict[str, object]", job)
        if _client_state_matches(job_dict, state):
            jobs.append(job_dict)
    filtered = dict(result)
    filtered["jobs"] = jobs
    filtered["returned"] = len(jobs)
    filters = result.get("filters")
    filter_dict = (
        cast("dict[str, object]", filters) if isinstance(filters, dict) else {}
    )
    filtered["filters"] = {**filter_dict, "state": state}
    return filtered


def _watch_status_text(refresh_number: int, refresh_count: int | None) -> str:
    if refresh_count is None:
        return "Watch: press Ctrl+C to stop."
    return f"Watch: refresh {refresh_number} of {refresh_count}."


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
    client_state: str | None,
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
            _exit_jobs_not_running(False, port)
        result = _apply_client_state_filter(result, client_state)
        _cli.console.clear()
        refresh_number = refreshes + 1
        _render_jobs_result(
            result,
            job_id=job_id,
            port=port,
            monitoring=True,
            watch_text=_watch_status_text(refresh_number, refresh_count),
        )
        refreshes += 1
        if refresh_count is not None and refreshes >= refresh_count:
            return
        time.sleep(interval)


@server_app.command("jobs")
def service_jobs(
    limit: Annotated[
        int,
        typer.Option("--limit", help="Maximum number of matching jobs to show."),
    ] = 20,
    state: Annotated[
        str | None,
        typer.Option(
            "--state",
            help=(
                "Filter by job state: active, waiting, finished, failed, or cancelled."
            ),
        ),
    ] = None,
    index: Annotated[
        str | None,
        typer.Option("--index", help="Filter by index type: vault or code."),
    ] = None,
    started_by: Annotated[
        str | None,
        typer.Option(
            "--started-by",
            help="Filter by who started the job: manual requests or automatic updates.",
        ),
    ] = None,
    query: Annotated[
        str | None,
        typer.Option(
            "--query",
            "-q",
            help="Filter by text in job id, outcome, or progress.",
        ),
    ] = None,
    failed: Annotated[
        bool,
        typer.Option("--failed", help="Show only failed jobs."),
    ] = False,
    job_id: Annotated[
        str | None,
        typer.Option("--job-id", help="Show details for a job id or prefix."),
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
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
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
            help="Stop --watch after this many refreshes.",
        ),
    ] = None,
) -> None:
    """Show recent index update activity from the running service."""
    phase, client_state = _jobs_state_filter(state, json_mode)
    source = _jobs_index_filter(index, json_mode)
    trigger = _jobs_started_by_filter(started_by, json_mode)
    phase, failed = _resolve_jobs_filters(phase, failed, json_mode)
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
                client_state=client_state,
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
        _exit_jobs_not_running(json_mode, resolved_port)
    result = _apply_client_state_filter(result, client_state)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    _render_jobs_result(result, job_id=job_id, port=resolved_port)
