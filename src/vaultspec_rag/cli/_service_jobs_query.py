"""Query resolution and service reads for ``server jobs``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, cast

import typer

from .._operator_commands import SERVICE_NOT_RUNNING_MESSAGE
from ..serviceclient._transport import _try_http_admin
from ._render import _display_service_not_running, _emit_json_error_and_exit, _plain


def _job_awaiting_admission(job: dict[str, object]) -> bool:
    """Report whether a running job has not yet won its admission slot.

    Only one encode-bearing index job may execute at a time, because a single
    GPU gains nothing from job-level concurrency. Jobs beyond that one are
    dispatched and hold the ``running`` phase while parked on the admission
    limiter, having done no work at all.

    ``admission_acquired_at`` is stamped the moment the attempt's worker
    actually begins, so a null value is the service's own statement that the
    job is still waiting. Reporting such a job as active - with a runtime that
    is really its queue wait - tells an operator that four jobs are competing
    when three of them have not started.

    The field must be PRESENT and null. A payload that omits it entirely is an
    older daemon, or a projection that does not carry it, and says nothing
    either way; inferring a wait from silence would relabel every running job
    on that daemon as queued. Absent means unknown, and unknown keeps today's
    reading rather than inventing a more specific one.
    """
    if str(job.get("phase", "")) != "running":
        return False
    if "admission_acquired_at" not in job:
        return False
    return job["admission_acquired_at"] is None


def _job_is_waiting(job: dict[str, object]) -> bool:
    """Report whether a running job is waiting rather than working.

    Covers both waits, which are distinct and both invisible in the phase:
    queued behind the store writer, and queued for the admission slot.
    """
    if str(job.get("phase", "")) != "running":
        return False
    if _job_awaiting_admission(job):
        return True
    progress = job.get("progress")
    return (
        isinstance(progress, dict)
        and cast("dict[str, object]", progress).get("step") == "queued"
    )


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
    message = SERVICE_NOT_RUNNING_MESSAGE
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "service_not_running", message, 3)
    _display_service_not_running(port)
    raise typer.Exit(3)


def _jobs_from_result(result: dict[str, object]) -> list[object]:
    raw_jobs = result.get("jobs")
    return cast("list[object]", raw_jobs) if isinstance(raw_jobs, list) else []


def _empty_jobs_message(result: dict[str, object], job_id: str | None) -> str:
    message = "No jobs have been reported by this service yet."
    if job_id:
        message = "No job matched that id."
    elif isinstance(raw_filters := result.get("filters"), dict):
        filters = cast("dict[str, object]", raw_filters)
        if filters.get("failed") is True:
            message = "There are no failed jobs."
        elif filters.get("state") == "active":
            message = "There are no active jobs."
        elif filters.get("state") == "waiting":
            message = "There are no waiting jobs."
        elif (
            isinstance(phase := filters.get("phase"), str)
            and phase.lower() == "running"
        ):
            message = "There are no active or waiting jobs."
        elif any(
            key != "limit" and value not in (None, "", False)
            for key, value in filters.items()
        ):
            message = "No jobs matched these filters."
    return message


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
