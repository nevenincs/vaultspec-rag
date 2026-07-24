"""``server jobs`` collection views and singular ``server job`` controls.

Calls the jobs admin endpoint through the shared HTTP admin client and
typed job-control transport, rendering either human operator output or one
structured JSON envelope. Service-not-running yields exit code 3.
"""

from __future__ import annotations

import functools
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Annotated, Literal, NoReturn, cast

import typer

import vaultspec_rag.cli as _cli

from .._job_errors import (
    STALL_THRESHOLD_SECONDS,
    classify_error_text,
    remediation,
)
from ..serviceclient import (
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)
from ._app import server_app, server_job_app
from ._cli_format import (
    _format_mb,
    _format_milliseconds,
    _format_seconds,
    _path_label,
)
from ._http_search import _try_http_admin
from ._process import _call_interruptibly
from ._render import (
    _display_service_not_running,
    _emit_json,
    _emit_json_error_and_exit,
    _plain,
)
from ._service_status import _default_service_port

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = [
    "_human_progress",
    "_operation_label",
    "_project_label",
    "_stale_progress_label",
    "service_job_delete",
    "service_job_pause",
    "service_job_resume",
    "service_job_retry",
    "service_job_show",
    "service_job_stop",
    "service_jobs",
]

_RESULT_RE = re.compile(
    r"^\+(?P<added>\d+)\s*/(?P<updated>\d+)\s*-(?P<removed>\d+)"
    r"\s*\((?P<duration_ms>\d+)ms\)(?:\s*~(?P<skipped>\d+))?$"
)
# The stall threshold is service-domain: the server computes the
# authoritative ``stalled`` flag; this constant only backs the fallback
# for snapshots from an older service that lacks the flag.
_STALE_PROGRESS_SECONDS = STALL_THRESHOLD_SECONDS
type _DesiredJobState = Literal["running", "paused", "cancelled"]


def _resource_at(job: dict[str, object], key: str) -> dict[str, object] | None:
    resources = job.get("resources")
    if not isinstance(resources, dict):
        return None
    value = cast("dict[str, object]", resources).get(key)
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


def _job_is_waiting(job: dict[str, object]) -> bool:
    if str(job.get("phase", "")) != "running":
        return False
    progress = job.get("progress")
    return (
        isinstance(progress, dict)
        and cast("dict[str, object]", progress).get("step") == "queued"
    )


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
    project_root = cast("dict[str, object]", initiator).get("project_root")
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
    root = cast("dict[str, object]", initiator).get("project_root")
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
        command = str(cast("dict[str, object]", initiator).get("command") or "")
    if source == "maintenance":
        return "storage maintenance cycle"
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
    raw_progress = job.get("progress")
    if not isinstance(raw_progress, dict):
        return ""
    progress = cast("dict[str, object]", raw_progress)
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
    # Prefer the service-computed flag; fall back to the local threshold
    # for snapshots from an older service that lacks it.
    stalled = job.get("stalled")
    if stalled is False:
        return ""
    if stalled is not True and float(raw_age) < _STALE_PROGRESS_SECONDS:
        return ""
    return f"no progress for {_format_seconds(raw_age)}"


def _human_result(raw: object, *, failed: bool = False) -> str:
    if not raw:
        return ""
    result = " ".join(str(raw).split())
    if result == "watcher task cancelled":
        return "automatic update cancelled"
    if failed:
        # One shared taxonomy: the same classification the service
        # stamps as ``error_kind`` drives the friendly remediation here,
        # so the CLI never grows its own error-string matching again.
        # Applied only to failed jobs so a success summary that happens
        # to contain a marker word is never replaced.
        friendly = remediation(classify_error_text(result))
        if friendly is not None:
            return friendly
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
        result = _human_result(job.get("result"), failed=True)
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
    raw_filters = result.get("filters")
    if not isinstance(raw_filters, dict):
        return ""
    filters = cast("dict[str, object]", raw_filters)
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


def _shown_count_text(returned: object, *, filtered: bool) -> str:
    if filtered:
        return _job_count_text(returned, "matching job", "matching jobs")
    return _job_count_text(returned)


def _job_counts_line(active: int, waiting: int, finished: int, failed: int) -> str:
    return (
        f"Displayed jobs: {active} active, {waiting} waiting, "
        f"{finished} finished, {failed} failed"
    )


def _render_jobs_header(
    *,
    port: int,
    shown_count: str,
    total: object,
    counts_line: str,
) -> None:
    """Print the opening lines both the populated and empty views share."""
    _plain("Jobs")
    _plain(f"Address: http://127.0.0.1:{port}")
    _plain(f"Displayed: {shown_count}")
    _plain(f"Total: {_job_count_text(total)}")
    _plain(counts_line)


def _render_filter_and_watch(
    filter_text: str,
    *,
    monitoring: bool,
    watch_text: str | None,
) -> None:
    """Print the filter line and, while watching, the refresh banner.

    Shared so the two views cannot drift into telling an operator different
    things about the same refresh.
    """
    if filter_text:
        _plain(f"Filter: {filter_text}")
    if not monitoring:
        return
    _plain(f"Refreshed: {time.strftime('%H:%M:%S', time.localtime())}")
    _cli.console.print(watch_text or "Watch: press Ctrl+C to stop.")


def _render_jobs_feed(
    result: dict[str, object],
    jobs: list[object],
    *,
    port: int,
    monitoring: bool = False,
    watch_text: str | None = None,
) -> None:
    sorted_jobs = _human_sorted_jobs(jobs)
    filter_text = _filter_line(result)
    _render_jobs_header(
        port=port,
        shown_count=_shown_count_text(
            result.get("returned", len(jobs)), filtered=bool(filter_text)
        ),
        total=result.get("total", len(jobs)),
        counts_line=_job_counts_line(*_shown_job_counts(sorted_jobs)),
    )
    if not filter_text:
        _plain("Showing: active, waiting, failed, then latest finished")
    _plain("Order: latest job appears last")
    _plain("Legend: * active, ~ waiting, ! failed, - finished")
    # Scripted consumers must use the structured envelope: this human summary
    # always contains the literal words "active"/"waiting", so grepping it for
    # job states self-deadlocks (a waiter that greps "active" always matches).
    _plain("Scripting: use --json (this summary always contains the word 'active')")
    _render_filter_and_watch(filter_text, monitoring=monitoring, watch_text=watch_text)
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
    filter_text = _filter_line(result)
    _render_jobs_header(
        port=port,
        shown_count=_shown_count_text(
            result.get("returned", 0), filtered=bool(filter_text or job_id)
        ),
        total=result.get("total", 0),
        counts_line=_job_counts_line(0, 0, 0, 0),
    )
    _plain("Order: latest job appears last")
    _render_filter_and_watch(filter_text, monitoring=monitoring, watch_text=watch_text)
    _cli.console.print(_empty_jobs_message(result, job_id))
    _plain("Next actions:")
    _plain(f"  vaultspec-rag server status --port {port}")
    _plain(f"  vaultspec-rag server logs --limit 20 --port {port}")


def _exit_invalid_jobs_filter(json_mode: bool, message: str) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            "service.jobs",
            "invalid_filter",
            message,
            2,
        )
    _plain(f"Error: {message}", soft_wrap=True)
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


@dataclass(frozen=True, slots=True)
class _JobsQuery:
    """One resolved ``server jobs`` filter set bound to a service port.

    Carried as a value so the filter names are written once at the command
    boundary instead of being re-listed by every layer that forwards them;
    the watching and one-shot paths are then provably asking the same
    question of the same service.
    """

    port: int
    limit: int
    phase: str | None = None
    source: str | None = None
    trigger: str | None = None
    query: str | None = None
    failed: bool = False
    job_id: str | None = None
    since: float | None = None


def _jobs_args(spec: _JobsQuery) -> dict[str, object]:
    args: dict[str, object] = {"limit": spec.limit}
    optional_args = {
        "phase": _jobs_phase_value(spec.phase),
        "source": spec.source,
        "trigger": _jobs_trigger_value(spec.trigger),
        "query": spec.query,
        "job_id": spec.job_id,
        "since": spec.since,
    }
    args.update(
        {
            key: value
            for key, value in optional_args.items()
            if value is not None and value != ""
        }
    )
    if spec.failed:
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
    raw_filters = result.get("filters")
    if not isinstance(raw_filters, dict):
        return "No jobs have been reported by this service yet."
    filters = cast("dict[str, object]", raw_filters)
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


def _resilience_summary_lines(job: dict[str, object]) -> tuple[str, ...]:
    """Return adapter-ready lines from the canonical resilience object."""
    resilience = job.get("resilience")
    if not isinstance(resilience, dict):
        return ()
    data = cast("dict[str, object]", resilience)
    lines: list[str] = []
    if profile := data.get("support_profile"):
        lines.append(f"Index profile: {profile}")
    if generation := data.get("generation_id"):
        lines.append(f"Checkpoint generation: {generation}")
    compatible = data.get("checkpoint_compatible")
    if compatible is not None:
        lines.append(
            "Checkpoint compatible: " + ("yes" if compatible is True else "no")
        )
    lines.append(
        f"Checkpoint units: {data.get('committed_units', 0)} committed, "
        f"{data.get('replayed_units', 0)} resumed"
    )
    deadline = data.get("no_progress_remaining_seconds")
    if deadline is not None:
        lines.append(f"No-progress budget remaining: {_format_seconds(deadline)}")
    if circuit := data.get("circuit_state"):
        lines.append(f"Retry circuit: {circuit}")
    next_retry = data.get("next_retry_at")
    if isinstance(next_retry, int | float):
        lines.append(
            "Next retry: "
            + time.strftime(
                "%Y-%m-%d %H:%M:%S UTC",
                time.gmtime(float(next_retry)),
            )
        )
    peak_rss = data.get("peak_rss_mb")
    rss_ceiling = data.get("rss_ceiling_mb")
    if peak_rss is not None or rss_ceiling is not None:
        lines.append(
            f"RSS high-water / ceiling: {_format_mb(peak_rss)} / "
            f"{_format_mb(rss_ceiling)}"
        )
    peak_allocated = data.get("peak_cuda_allocated_mb")
    if peak_allocated is not None:
        lines.append(f"CUDA allocated high-water: {_format_mb(peak_allocated)}")
    peak_reserved = data.get("peak_cuda_reserved_mb")
    cuda_ceiling = data.get("cuda_ceiling_mb")
    if peak_reserved is not None or cuda_ceiling is not None:
        lines.append(
            f"CUDA reserved high-water / ceiling: {_format_mb(peak_reserved)} / "
            f"{_format_mb(cuda_ceiling)}"
        )
    if terminal := data.get("terminal_outcome"):
        lines.append(f"Index outcome: {terminal}")
    return tuple(lines)


def _render_job_resilience_detail(job: dict[str, object]) -> None:
    for line in _resilience_summary_lines(job):
        _cli.console.print(line)


def _render_job_result_detail(job: dict[str, object]) -> None:
    result = job.get("result")
    if not result:
        return
    is_failed = str(job.get("phase")) in ("error", "failed")
    label = "Error" if is_failed else "Result"
    _cli.console.print(f"{label}: {_human_result(result, failed=is_failed)}")


def _render_job_detail(job: dict[str, object], *, port: int | None = None) -> None:
    if port is not None:
        _plain(f"Address: http://127.0.0.1:{port}")
    _cli.console.print(f"Job {job.get('id', '')!s}")
    _cli.console.print(f"Operation: {_operation_label(job)}")
    _cli.console.print(f"Project: {_project_label(job)}")
    root = _project_root(job)
    if root:
        _plain(f"Path: {root}")
    _cli.console.print(f"Status: {_phase_label(job)}")
    _cli.console.print(f"Runtime: {_format_seconds(job.get('runtime_seconds'))}")
    _render_job_progress_detail(job)
    _render_job_initiator_detail(job)
    _render_job_runtime_detail(job)
    _render_job_resource_detail(job)
    _render_job_resilience_detail(job)
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
            _plain(
                f"Error: job id prefix {job_id} matches {len(jobs)} jobs. "
                "Use a longer prefix."
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
    _plain(f"Error: {message}")
    raise typer.Exit(2)


def _fetch_jobs_result(spec: _JobsQuery) -> dict[str, object] | None:
    return _try_http_admin("get_jobs", _jobs_args(spec), spec.port)


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


def _stop_watching() -> NoReturn:
    """Leave the refreshing view on an operator interrupt.

    Watch only reads, so there is nothing to unwind. Exit on the conventional
    interrupted status rather than reporting the success the operator never
    got, and without a traceback they did not ask for.
    """
    _cli.console.print("\n[dim]Stopped watching jobs.[/]")
    raise typer.Exit(130)


def _watch_jobs(
    fetch: Callable[[], dict[str, object] | None],
    *,
    job_id: str | None,
    port: int,
    interval: float,
    refresh_count: int | None,
    client_state: str | None,
) -> None:
    """Re-render *fetch*'s result on an interval until interrupted.

    Takes the bound fetch rather than the filter set so the query is spelled
    once in the command and both the one-shot and watching paths are provably
    reading the same thing.
    """
    refreshes = 0
    while refresh_count is None or refreshes < refresh_count:
        # The refresh is one instance of the general problem of keeping the
        # main thread interruptible across a blocking call, so it shares the
        # process module's helper rather than carrying a second copy of the
        # same threading rationale. A divergence between two copies would be a
        # Ctrl+C that works in one operator view and not the other.
        result = _call_interruptibly(fetch)
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


def _job_control_command(action: str) -> str:
    return f"server.job.{action}"


def _job_control_failure(
    command: str,
    error: str,
    message: str,
    *,
    json_mode: bool,
    exit_code: int,
    data: dict[str, object] | None = None,
) -> NoReturn:
    if json_mode:
        _emit_json_error_and_exit(
            command,
            error,
            message,
            exit_code,
            data=data or {},
        )
    _plain(f"Error: {message}", soft_wrap=True)
    _plain(f"Code: {error}")
    raise typer.Exit(exit_code)


def _job_control_port(
    port: int | None,
    *,
    command: str,
    json_mode: bool,
) -> int:
    resolved = port if port is not None else _default_service_port()
    if resolved is None:
        _job_control_failure(
            command,
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            json_mode=json_mode,
            exit_code=3,
        )
    return resolved


def _job_control_result_failure(
    command: str,
    result: dict[str, object],
    *,
    json_mode: bool,
    exit_code: int = 1,
) -> NoReturn:
    error = str(result.get("error") or result.get("code") or "service_error")
    message = str(result.get("message") or "The service rejected the job request.")
    data = {
        key: result[key]
        for key in ("status", "code", "job")
        if result.get(key) is not None
    }
    _job_control_failure(
        command,
        error,
        message,
        json_mode=json_mode,
        exit_code=exit_code,
        data=data,
    )


def _human_exact_job_id(
    reference: str,
    port: int,
    *,
    command: str,
) -> str:
    result = _try_http_admin("get_jobs", {"job_id": reference}, port)
    if result is None:
        _job_control_failure(
            command,
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            json_mode=False,
            exit_code=3,
        )
    if result.get("ok") is False:
        _job_control_result_failure(command, result, json_mode=False)
    matches = [
        cast("dict[str, object]", job)
        for job in _jobs_from_result(result)
        if isinstance(job, dict)
    ]
    if not matches:
        _job_control_failure(
            command,
            "job_not_found",
            f'No job matches "{reference}".',
            json_mode=False,
            exit_code=1,
        )
    if len(matches) > 1:
        _job_control_failure(
            command,
            "ambiguous_job_id",
            f'Job prefix "{reference}" matches {len(matches)} jobs. '
            "Use a longer prefix.",
            json_mode=False,
            exit_code=2,
            data={"matches": [job.get("id") for job in matches]},
        )
    exact_id = matches[0].get("id")
    if not isinstance(exact_id, str) or not exact_id:
        _job_control_failure(
            command,
            "invalid_job_resource",
            "The service returned a job without an exact identifier.",
            json_mode=False,
            exit_code=1,
        )
    return exact_id


def _exact_job_for_control(
    reference: str,
    port: int,
    *,
    command: str,
    json_mode: bool,
) -> tuple[str, dict[str, object]]:
    exact_id = (
        reference
        if json_mode
        else _human_exact_job_id(
            reference,
            port,
            command=command,
        )
    )
    result = _try_http_get_job(exact_id, port)
    if result is None:
        _job_control_failure(
            command,
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            json_mode=json_mode,
            exit_code=3,
        )
    if result.get("ok") is not True:
        _job_control_result_failure(command, result, json_mode=json_mode)
    raw_job = result.get("job")
    if not isinstance(raw_job, dict):
        _job_control_failure(
            command,
            "invalid_job_resource",
            "The service returned an invalid job resource.",
            json_mode=json_mode,
            exit_code=1,
        )
    job = cast("dict[str, object]", raw_job)
    reported_id = job.get("id")
    if reported_id != exact_id:
        _job_control_failure(
            command,
            "invalid_job_resource",
            "The service returned a different job identifier than requested.",
            json_mode=json_mode,
            exit_code=1,
        )
    return exact_id, job


def _job_revision(
    job: dict[str, object],
    *,
    command: str,
    json_mode: bool,
) -> int:
    revision = job.get("revision")
    if isinstance(revision, int) and not isinstance(revision, bool) and revision >= 1:
        return revision
    _job_control_failure(
        command,
        "invalid_job_resource",
        "The service returned a job without a positive revision.",
        json_mode=json_mode,
        exit_code=1,
    )


def _render_job_control_outcome(result: dict[str, object]) -> None:
    message = str(result.get("message") or "Job request completed.")
    _plain(message, soft_wrap=True)
    code = result.get("code")
    if code:
        _plain(f"Outcome: {code}")
    raw_job = result.get("job")
    if not isinstance(raw_job, dict):
        return
    job = cast("dict[str, object]", raw_job)
    _plain(f"Job: {job.get('id', '')}")
    _plain(f"State: {job.get('state', 'not reported')}")
    _plain(f"Desired state: {job.get('desired_state', 'not reported')}")


def _complete_job_control(
    command: str,
    result: dict[str, object] | None,
    *,
    json_mode: bool,
) -> None:
    if result is None:
        _job_control_failure(
            command,
            "service_not_running",
            "Service is not running. Start it with `vaultspec-rag server start`.",
            json_mode=json_mode,
            exit_code=3,
        )
    if result.get("ok") is not True:
        _job_control_result_failure(command, result, json_mode=json_mode)
    data = {
        "status": result.get("code", "ok"),
        "disposition": result.get("status", "ok"),
        "message": result.get("message"),
        "job": result.get("job"),
    }
    if json_mode:
        _emit_json(True, command, data=data)
        return
    _render_job_control_outcome(result)


def _set_job_state(
    action: str,
    reference: str,
    state: _DesiredJobState,
    *,
    port: int | None,
    json_mode: bool,
    force: bool = False,
) -> None:
    command = _job_control_command(action)
    resolved_port = _job_control_port(port, command=command, json_mode=json_mode)
    exact_id, job = _exact_job_for_control(
        reference,
        resolved_port,
        command=command,
        json_mode=json_mode,
    )
    revision = _job_revision(job, command=command, json_mode=json_mode)
    result = _try_http_set_job_desired_state(
        exact_id,
        state,
        resolved_port,
        expected_revision=revision,
        mode="force" if force else "graceful",
    )
    _complete_job_control(command, result, json_mode=json_mode)


@server_job_app.command("show")
def service_job_show(
    job_id: Annotated[str, typer.Argument(help="Exact job id or human-mode prefix.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one structured JSON outcome."),
    ] = False,
) -> None:
    """Show one exact job resource; human output accepts a unique prefix."""
    command = _job_control_command("show")
    resolved_port = _job_control_port(port, command=command, json_mode=json_mode)
    _exact_id, job = _exact_job_for_control(
        job_id,
        resolved_port,
        command=command,
        json_mode=json_mode,
    )
    if json_mode:
        _emit_json(True, command, data={"status": "ok", "job": job})
        return
    _render_job_detail(job, port=resolved_port)


@server_job_app.command("pause")
def service_job_pause(
    job_id: Annotated[str, typer.Argument(help="Exact job id or human-mode prefix.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one structured JSON outcome."),
    ] = False,
) -> None:
    """Request a cooperative pause for one job."""
    _set_job_state("pause", job_id, "paused", port=port, json_mode=json_mode)


@server_job_app.command("resume")
def service_job_resume(
    job_id: Annotated[str, typer.Argument(help="Exact job id or human-mode prefix.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one structured JSON outcome."),
    ] = False,
) -> None:
    """Resume one paused job through reconciliation."""
    _set_job_state("resume", job_id, "running", port=port, json_mode=json_mode)


@server_job_app.command("stop")
def service_job_stop(
    job_id: Annotated[str, typer.Argument(help="Exact job id or human-mode prefix.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one structured JSON outcome."),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help="Request force termination; currently rejected when unsupported.",
        ),
    ] = False,
) -> None:
    """Request cancellation without disabling automatic updates."""
    _set_job_state(
        "stop",
        job_id,
        "cancelled",
        port=port,
        json_mode=json_mode,
        force=force,
    )


@server_job_app.command("retry")
def service_job_retry(
    job_id: Annotated[str, typer.Argument(help="Exact job id or human-mode prefix.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one structured JSON outcome."),
    ] = False,
) -> None:
    """Create a linked retry for one retryable terminal job."""
    command = _job_control_command("retry")
    resolved_port = _job_control_port(port, command=command, json_mode=json_mode)
    exact_id, _job = _exact_job_for_control(
        job_id,
        resolved_port,
        command=command,
        json_mode=json_mode,
    )
    result = _try_http_retry_job(
        exact_id,
        resolved_port,
        initiator_kind="cli",
        command="server_job_retry",
    )
    _complete_job_control(command, result, json_mode=json_mode)


@server_job_app.command("delete")
def service_job_delete(
    job_id: Annotated[str, typer.Argument(help="Exact job id or human-mode prefix.")],
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit one structured JSON outcome."),
    ] = False,
) -> None:
    """Delete one terminal job from retained history."""
    command = _job_control_command("delete")
    resolved_port = _job_control_port(port, command=command, json_mode=json_mode)
    exact_id, _job = _exact_job_for_control(
        job_id,
        resolved_port,
        command=command,
        json_mode=json_mode,
    )
    result = _try_http_delete_job(exact_id, resolved_port)
    _complete_job_control(command, result, json_mode=json_mode)


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
        typer.Option(
            "--json",
            help=(
                "Emit JSON for scripts instead of human text. Always use this "
                "for scripted waits: the human summary line unconditionally "
                "contains the words 'active' and 'waiting'."
            ),
        ),
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
    spec = _JobsQuery(
        port=resolved_port,
        limit=limit,
        phase=phase,
        source=source,
        trigger=trigger,
        query=query,
        failed=failed,
        job_id=job_id,
        since=since,
    )
    fetch = functools.partial(_fetch_jobs_result, spec)
    if watch:
        try:
            _watch_jobs(
                fetch,
                job_id=job_id,
                port=resolved_port,
                interval=interval,
                refresh_count=refresh_count,
                client_state=client_state,
            )
        except KeyboardInterrupt:
            _stop_watching()
        return

    result = fetch()
    if result is None:
        _exit_jobs_not_running(json_mode, resolved_port)
    result = _apply_client_state_filter(result, client_state)

    if json_mode:
        _emit_json(True, "service.jobs", data=result)
        return

    _render_jobs_result(result, job_id=job_id, port=resolved_port)
