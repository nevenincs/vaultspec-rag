"""Singular ``server job`` CLI controls."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated, NoReturn, cast

import typer

from .._operator_commands import SERVICE_NOT_RUNNING_MESSAGE
from ..job_models import DesiredJobState
from ..serviceclient._discovery import _default_service_port
from ..serviceclient._transport import (
    _try_http_admin,
    _try_http_delete_job,
    _try_http_get_job,
    _try_http_retry_job,
    _try_http_set_job_desired_state,
)
from ._app import JobIdArgument, JsonEnvelopeMode, PortOption, server_job_app
from ._render import _emit_json, _emit_json_error_and_exit, _plain
from ._service_jobs_presentation import render_job_detail
from ._service_jobs_query import jobs_from_result


@dataclass(frozen=True, slots=True)
class _JobStateChangeRequest:
    """One requested desired-state transition for a service job."""

    action: str
    reference: str
    state: DesiredJobState
    port: int | None
    json_mode: bool
    force: bool = False


@dataclass(frozen=True, slots=True)
class _JobControlFailureRequest:
    """One terminal job-control error rendered for humans or JSON clients."""

    command: str
    error: str
    message: str
    json_mode: bool
    exit_code: int
    data: dict[str, object] | None = None


def _job_control_command(action: str) -> str:
    return f"server.job.{action}"


def _job_control_failure(request: _JobControlFailureRequest) -> NoReturn:
    if request.json_mode:
        _emit_json_error_and_exit(
            request.command,
            request.error,
            request.message,
            request.exit_code,
            data=request.data or {},
        )
    _plain(f"Error: {request.message}", soft_wrap=True)
    _plain(f"Code: {request.error}")
    raise typer.Exit(request.exit_code)


def _job_control_port(
    port: int | None,
    *,
    command: str,
    json_mode: bool,
) -> int:
    resolved = port if port is not None else _default_service_port()
    if resolved is None:
        _job_control_failure(
            _JobControlFailureRequest(
                command=command,
                error="service_not_running",
                message=SERVICE_NOT_RUNNING_MESSAGE,
                json_mode=json_mode,
                exit_code=3,
            )
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
        _JobControlFailureRequest(
            command=command,
            error=error,
            message=message,
            json_mode=json_mode,
            exit_code=exit_code,
            data=data,
        )
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
            _JobControlFailureRequest(
                command=command,
                error="service_not_running",
                message=SERVICE_NOT_RUNNING_MESSAGE,
                json_mode=False,
                exit_code=3,
            )
        )
    if result.get("ok") is False:
        _job_control_result_failure(command, result, json_mode=False)
    matches = [
        cast("dict[str, object]", job)
        for job in jobs_from_result(result)
        if isinstance(job, dict)
    ]
    if not matches:
        _job_control_failure(
            _JobControlFailureRequest(
                command=command,
                error="job_not_found",
                message=f'No job matches "{reference}".',
                json_mode=False,
                exit_code=1,
            )
        )
    if len(matches) > 1:
        _job_control_failure(
            _JobControlFailureRequest(
                command=command,
                error="ambiguous_job_id",
                message=(
                    f'Job prefix "{reference}" matches {len(matches)} jobs. '
                    "Use a longer prefix."
                ),
                json_mode=False,
                exit_code=2,
                data={"matches": [job.get("id") for job in matches]},
            )
        )
    exact_id = matches[0].get("id")
    if not isinstance(exact_id, str) or not exact_id:
        _job_control_failure(
            _JobControlFailureRequest(
                command=command,
                error="invalid_job_resource",
                message="The service returned a job without an exact identifier.",
                json_mode=False,
                exit_code=1,
            )
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
            _JobControlFailureRequest(
                command=command,
                error="service_not_running",
                message=SERVICE_NOT_RUNNING_MESSAGE,
                json_mode=json_mode,
                exit_code=3,
            )
        )
    if result.get("ok") is not True:
        _job_control_result_failure(command, result, json_mode=json_mode)
    raw_job = result.get("job")
    if not isinstance(raw_job, dict):
        _job_control_failure(
            _JobControlFailureRequest(
                command=command,
                error="invalid_job_resource",
                message="The service returned an invalid job resource.",
                json_mode=json_mode,
                exit_code=1,
            )
        )
    job = cast("dict[str, object]", raw_job)
    reported_id = job.get("id")
    if reported_id != exact_id:
        _job_control_failure(
            _JobControlFailureRequest(
                command=command,
                error="invalid_job_resource",
                message=(
                    "The service returned a different job identifier than requested."
                ),
                json_mode=json_mode,
                exit_code=1,
            )
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
        _JobControlFailureRequest(
            command=command,
            error="invalid_job_resource",
            message="The service returned a job without a positive revision.",
            json_mode=json_mode,
            exit_code=1,
        )
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
            _JobControlFailureRequest(
                command=command,
                error="service_not_running",
                message=SERVICE_NOT_RUNNING_MESSAGE,
                json_mode=json_mode,
                exit_code=3,
            )
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


def _set_job_state(request: _JobStateChangeRequest) -> None:
    command = _job_control_command(request.action)
    resolved_port = _job_control_port(
        request.port, command=command, json_mode=request.json_mode
    )
    exact_id, job = _exact_job_for_control(
        request.reference,
        resolved_port,
        command=command,
        json_mode=request.json_mode,
    )
    revision = _job_revision(job, command=command, json_mode=request.json_mode)
    result = _try_http_set_job_desired_state(
        exact_id,
        request.state,
        resolved_port,
        expected_revision=revision,
        mode="force" if request.force else "graceful",
    )
    _complete_job_control(command, result, json_mode=request.json_mode)


@server_job_app.command("show")
def service_job_show(
    job_id: JobIdArgument,
    port: PortOption = None,
    json_mode: JsonEnvelopeMode = False,
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
    render_job_detail(job, port=resolved_port)


@server_job_app.command("pause")
def service_job_pause(
    job_id: JobIdArgument,
    port: PortOption = None,
    json_mode: JsonEnvelopeMode = False,
) -> None:
    """Request a cooperative pause for one job."""
    _set_job_state(
        _JobStateChangeRequest(
            action="pause",
            reference=job_id,
            state=DesiredJobState.PAUSED,
            port=port,
            json_mode=json_mode,
        )
    )


@server_job_app.command("resume")
def service_job_resume(
    job_id: JobIdArgument,
    port: PortOption = None,
    json_mode: JsonEnvelopeMode = False,
) -> None:
    """Resume one paused job through reconciliation."""
    _set_job_state(
        _JobStateChangeRequest(
            action="resume",
            reference=job_id,
            state=DesiredJobState.RUNNING,
            port=port,
            json_mode=json_mode,
        )
    )


@server_job_app.command("stop")
def service_job_stop(
    job_id: JobIdArgument,
    port: PortOption = None,
    json_mode: JsonEnvelopeMode = False,
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
        _JobStateChangeRequest(
            action="stop",
            reference=job_id,
            state=DesiredJobState.CANCELLED,
            port=port,
            json_mode=json_mode,
            force=force,
        )
    )


@server_job_app.command("retry")
def service_job_retry(
    job_id: JobIdArgument,
    port: PortOption = None,
    json_mode: JsonEnvelopeMode = False,
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
    job_id: JobIdArgument,
    port: PortOption = None,
    json_mode: JsonEnvelopeMode = False,
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
