"""Query resolution and service reads for ``server jobs``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import NoReturn, cast

import typer

from .._operator_commands import SERVICE_NOT_RUNNING_MESSAGE
from ..serviceclient._transport import _try_http_admin
from ._render import _display_service_not_running, _emit_json_error_and_exit, _plain


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


def resolve_jobs_filters(
    phase: str | None,
    failed: bool,
    json_mode: bool,
) -> tuple[str | None, bool]:
    if phase == "failed":
        # The service reports a failed job under either of two raw phases
        # depending on which record shape it came from, so no single phase
        # selects them all. Its failed flag is evaluated on lifecycle state.
        return None, True
    if failed and phase is not None:
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
    if value in ("finished", "complete", "completed"):
        return "done"
    if value in ("failed", "failure", "error"):
        return "failed"
    if value in ("cancelled", "canceled"):
        return "cancelled"
    return value


@dataclass(frozen=True, slots=True)
class JobsStateFilter:
    """The service filters one ``--state`` value selects.

    Active and waiting are both the running lifecycle state, told apart by
    the service's own wait verdict; finished, failed and cancelled are
    phases. Every one is evaluated by the service before it cuts the page.
    """

    phase: str | None = None
    state: str | None = None
    waiting: bool | None = None


def jobs_state_filter(
    state: str | None,
    json_mode: bool,
) -> JobsStateFilter:
    if state is None:
        return JobsStateFilter()
    requested = state.strip().lower()
    if requested in ("active", "waiting"):
        return JobsStateFilter(state="running", waiting=requested == "waiting")
    normalized = _jobs_phase_value(state)
    if normalized in ("done", "failed", "cancelled"):
        return JobsStateFilter(phase=normalized)
    _exit_invalid_jobs_filter_value(
        option="--state",
        value=state,
        allowed="active, waiting, finished, failed, or cancelled",
        json_mode=json_mode,
    )


def jobs_started_by_filter(
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


def jobs_index_filter(
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
class JobsQuery:
    """One resolved ``server jobs`` filter set bound to a service port.

    Carried as a value so the filter names are written once at the command
    boundary instead of being re-listed by every layer that forwards them;
    the watching and one-shot paths are then provably asking the same
    question of the same service.
    """

    port: int
    limit: int
    phase: str | None = None
    state: str | None = None
    waiting: bool | None = None
    source: str | None = None
    trigger: str | None = None
    query: str | None = None
    failed: bool = False
    job_id: str | None = None
    since: float | None = None


def _jobs_args(spec: JobsQuery) -> dict[str, object]:
    args: dict[str, object] = {"limit": spec.limit}
    optional_args = {
        "phase": _jobs_phase_value(spec.phase),
        "state": spec.state,
        "waiting": spec.waiting,
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


def exit_jobs_not_running(json_mode: bool, port: int | None = None) -> NoReturn:
    message = SERVICE_NOT_RUNNING_MESSAGE
    if json_mode:
        _emit_json_error_and_exit("service.jobs", "service_not_running", message, 3)
    _display_service_not_running(port)
    raise typer.Exit(3)


def jobs_from_result(result: dict[str, object]) -> list[object]:
    raw_jobs = result.get("jobs")
    return cast("list[object]", raw_jobs) if isinstance(raw_jobs, list) else []


def filter_is_set(value: object) -> bool:
    """Report whether a filter value narrows the job list at all.

    An unset filter arrives three ways - absent as ``None``, empty as ``""``,
    and unticked as ``False`` - and every reader has to treat all three the
    same or it describes a filter nobody applied. The trio was spelled out at
    each site, so a fourth spelling of "unset" would have reached whichever
    sites got remembered.
    """
    return value not in (None, "", False)


def empty_jobs_message(result: dict[str, object], job_id: str | None) -> str:
    message = "No jobs have been reported by this service yet."
    if job_id:
        message = "No job matched that id."
    elif isinstance(raw_filters := result.get("filters"), dict):
        filters = cast("dict[str, object]", raw_filters)
        if filters.get("failed") is True:
            message = "There are no failed jobs."
        elif filters.get("waiting") is False:
            message = "There are no active jobs."
        elif filters.get("waiting") is True:
            message = "There are no waiting jobs."
        elif filters.get("state") == "running":
            message = "There are no active or waiting jobs."
        elif any(
            key != "limit" and filter_is_set(value) for key, value in filters.items()
        ):
            message = "No jobs matched these filters."
    return message


def fetch_jobs_result(spec: JobsQuery) -> dict[str, object] | None:
    return _try_http_admin("get_jobs", _jobs_args(spec), spec.port)
