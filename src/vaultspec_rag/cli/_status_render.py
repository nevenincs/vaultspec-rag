"""``server status``: gather service signals and render the operator summary.

Computes the derived service state from four independent signals
(``service.json`` present, PID alive, port listening, heartbeat fresh) plus the
warming phase, then renders it as the human summary, the verbose detail, or the
``--json`` envelope - each preserving the documented exit codes (0 running,
3 stopped, 4 crashed/divergent, 5 warming). Never picks one signal as the sole
source of truth: every signal is surfaced and the verdict is derived from all.
"""

from __future__ import annotations

import time
from typing import Annotated, Any, cast

import typer

import vaultspec_rag.cli as _cli

from .._operator_commands import (
    port_option,
    server_jobs_command,
    server_start_command,
    server_status_command,
)
from .._process_probe import pid_alive as _pid_alive
from ..serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_PHASE_WARMING,
    MachineResolution,
    _default_service_port,
    _delete_service_status,
    _read_service_status,
    resolve_machine_service,
)
from ..serviceclient._status import (
    STATUS_STOPPED,
    DiscoveryStatus,
    LivenessSignals,
    compose_discovery_status,
)
from ..serviceclient._transport import _try_http_admin, _try_http_health
from ._app import JSON_OPTION_HELP, server_app
from ._cli_format import NOT_REPORTED
from ._process import (
    _heartbeat_age_seconds,
    _is_our_service,
    _port_is_listening,
)
from ._render import _address_line, _emit_json, _plain
from ._service_jobs import (
    _human_progress,
    _operation_label,
    _project_label,
    _stale_progress_label,
)
from ._service_lifecycle import (
    _print_detail_line,
    _should_unlink_discovery_file,
)
from ._service_status import _service_phase
from ._status_labels import (
    FAILED_JOB_FAMILY,
    DegradedFinding,
    _failed_job_total,
    _format_started_label,
    _format_status_duration,
    _get_token_label,
    _last_failure_label,
    _model_ready_label,
    _network_label,
    _plain_status_label,
    _process_identity_label,
    _status_busy_label,
    _status_env_label,
    _status_health_label,
    _status_jobs_label,
    _status_queue_label,
    _status_uptime_label,
    degradation_findings,
    degradation_lines,
)

__all__ = [
    "_compute_state",
    "_degraded_lines",
    "_evaluate_service_signals",
    "_explicit_port_state",
    "_failure_lines",
    "_liveness_from_resolution",
    "_status_next_action",
    "service_status",
]


def _compute_token_match(
    expected_token: str | None,
    pid_alive: bool,
    port_listening: bool,
    port: int,
) -> bool | None:
    if expected_token is None or not pid_alive:
        return None
    probe_for_token = _try_http_health(port) if port_listening else None
    if probe_for_token is not None and isinstance(
        probe_for_token.get("service_token"),
        str,
    ):
        response_token = probe_for_token["service_token"]
        return bool(response_token) and response_token == expected_token
    return None


def _liveness_from_resolution(resolution: MachineResolution) -> LivenessSignals:
    """Probe the live signals for an address the machine resolution produced."""
    payload = resolution.payload or {}
    pid = resolution.pointer_pid or 0
    port = resolution.port or 0
    token = resolution.service_token
    pid_alive = _pid_alive(pid) if pid > 0 else False
    pid_matches = (
        _is_our_service(pid, port=port, expected_token=token) if pid_alive else False
    )
    port_listening = _port_is_listening(port) if port > 0 else False
    age = resolution.heartbeat_age_s
    window = resolution.stale_after_s
    stale = age is not None and window is not None and age > window
    return LivenessSignals(
        pid=pid,
        pid_alive=pid_alive,
        pid_matches_service=pid_matches,
        port_listening=port_listening,
        heartbeat_age_s=age,
        heartbeat_stale=stale,
        service_token_match=_compute_token_match(
            token, pid_alive, port_listening, port
        ),
        phase=_service_phase(payload),
    )


def _render_discovery_verdict(
    verdict: DiscoveryStatus,
    *,
    json_mode: bool,
    verbose: bool,
) -> None:
    """Render a verdict derived from machine-global discovery alone.

    Reached when this status directory holds no record of its own, so the
    machine singleton is the only evidence available.
    """
    port = verdict.port or 0
    health = _try_http_health(port) if verdict.signals.port_listening else None
    if json_mode:
        payload = verdict.as_dict()
        payload["service_json_present"] = False
        payload["port"] = verdict.port
        if health is not None:
            payload["health"] = health
        _emit_json(
            verdict.exit_code == 0,
            "service.status",
            data=payload,
            **(
                {"error": verdict.state, "message": verdict.label}
                if verdict.exit_code != 0
                else {}
            ),
        )
        if verdict.exit_code != 0:
            raise typer.Exit(code=verdict.exit_code)
        return

    if verbose:
        _cli.console.print("Service status")
        _print_detail_line("Local record", "not found")
        _print_detail_line("Server", verdict.label)
        _print_detail_line("Discovery", verdict.resolution.evidence())
        if verdict.exit_code != 0:
            raise typer.Exit(code=verdict.exit_code)
        return

    _render_status_summary(
        state_label=verdict.label,
        port=port or _default_service_port() or 8766,
        port_listening=verdict.signals.port_listening,
        health=health,
        operational=None,
        exit_code=verdict.exit_code,
    )


def _compute_state(
    pid_alive: bool,
    pid_is_ours: bool,
    port_listening: bool,
    heartbeat_stale: bool,
    *,
    phase: str | None = None,
) -> tuple[str, str, int]:
    if not pid_alive:
        # Confirmed dead: the only state in which the discovery file may be
        # removed (#204). The ambiguous branches below keep the file and only
        # report a degraded state.
        if _should_unlink_discovery_file(pid_alive):
            _delete_service_status()
        return (
            "crashed_pid_dead",
            "crashed (PID dead, stale service.json cleaned)",
            4,
        )
    if not pid_is_ours:
        return (
            "crashed_pid_reused",
            "crashed (PID reused by unrelated process)",
            4,
        )
    # A live daemon that stamped ``warming`` holds the machine lock but is
    # still loading models: the silent port and the not-yet-started heartbeat
    # are expected, not crash signals. Checked before both so a warming daemon
    # never renders as crashed. An absent phase keeps the pre-phase semantics.
    if phase == SERVICE_PHASE_WARMING:
        return "warming", "warming (loading models, not yet serving)", 5
    if not port_listening:
        return "crashed_port_silent", "crashed (port silent)", 4
    if heartbeat_stale:
        return "crashed_heartbeat_stale", "crashed (heartbeat stale)", 4
    return "running", "running", 0


def _evaluate_service_signals(
    status: dict[str, Any],
) -> tuple[
    int, int, str, bool, bool, bool, float | None, bool, bool | None, str, str, int
]:
    pid = int(status.get("pid", 0))
    port = int(status.get("port", 0))
    started_at = str(status.get("started_at", ""))

    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) and raw_token else None
    pid_alive = _pid_alive(pid)
    pid_is_ours = (
        _is_our_service(pid, port=port, expected_token=expected_token)
        if pid_alive
        else False
    )
    port_listening = _port_is_listening(port) if pid_alive else False
    heartbeat_age = _heartbeat_age_seconds(status)
    heartbeat_stale = (
        pid_alive
        if heartbeat_age is None
        else heartbeat_age > HEARTBEAT_STALENESS_SECONDS
    )

    token_match = _compute_token_match(expected_token, pid_alive, port_listening, port)
    state, state_label, exit_code = _compute_state(
        pid_alive,
        pid_is_ours,
        port_listening,
        heartbeat_stale,
        phase=_service_phase(status),
    )

    return (
        pid,
        port,
        started_at,
        pid_alive,
        pid_is_ours,
        port_listening,
        heartbeat_age,
        heartbeat_stale,
        token_match,
        state,
        state_label,
        exit_code,
    )


def _render_status_json(
    pid: int,
    port: int,
    started_at: str,
    pid_alive: bool,
    pid_is_ours: bool,
    port_listening: bool,
    heartbeat_age: float | None,
    heartbeat_stale: bool,
    token_match: bool | None,
    state: str,
    exit_code: int,
    health: dict[str, object] | None,
    operational: dict[str, object] | None,
) -> None:
    payload: dict[str, object] = {
        "service_json_present": True,
        "pid": pid,
        "port": port,
        "started_at": started_at,
        "pid_alive": pid_alive,
        "pid_matches_service": pid_is_ours,
        "port_listening": port_listening,
        "heartbeat_age_seconds": heartbeat_age,
        "heartbeat_stale": heartbeat_stale,
        "service_token_match": token_match,
        "state": state,
    }
    if isinstance(health, dict):
        payload["health"] = health
    if isinstance(operational, dict):
        payload["operational"] = operational
    _emit_json(
        exit_code == 0,
        "service.status",
        data=payload,
        **(
            {"error": state, "message": f"Service status: {state}"}
            if exit_code != 0
            else {}
        ),
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _job_progress_summary(job: dict[str, object]) -> str:
    parts: list[str] = []
    progress = _human_progress(job)
    if progress:
        parts.append(progress)
    stale_progress = _stale_progress_label(job)
    if stale_progress:
        parts.append(stale_progress)
    return f", {', '.join(parts)}" if parts else ""


def _job_project(job: dict[str, object]) -> str:
    """Return the job's project, or an empty string when it reported none.

    The project label carries its own absence sentinel, so every caller would
    otherwise repeat the comparison against that exact phrase - and a reword of
    the sentinel would silently start printing it as if it were a project name.
    """
    project = _project_label(job)
    return "" if project == "project not reported" else project


def _job_runtime_label(job: dict[str, object]) -> str:
    """Return how long the job has been running, from its start stamp."""
    started_at = job.get("started_at")
    if not isinstance(started_at, int | float):
        return NOT_REPORTED
    return _format_status_duration(time.time() - float(started_at))


def _job_command_name(job: dict[str, object]) -> str:
    operation = _operation_label(job)
    project = _job_project(job)
    return f"{operation} for {project}" if project else operation


def _current_job_summary(job: dict[str, object] | None) -> str:
    if job is None:
        return "none"
    runtime = _job_runtime_label(job)
    return f"{_job_command_name(job)} ({runtime}{_job_progress_summary(job)})"


def _active_job_records(
    job_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    active: list[dict[str, object]] = []
    for entry in job_records:
        if entry.get("phase") != "running":
            continue
        progress = entry.get("progress")
        if (
            isinstance(progress, dict)
            and cast("dict[str, object]", progress).get("step") == "queued"
        ):
            continue
        active.append(entry)
    return sorted(active, key=_job_started_timestamp)


def _job_started_timestamp(job: dict[str, object]) -> float:
    started_at = job.get("started_at")
    return float(started_at) if isinstance(started_at, int | float) else 0.0


def _running_job_line(job: dict[str, object]) -> str:
    return f"  * {_current_job_summary(job)}"


def _current_job_detail_lines(jobs: dict[str, object] | None) -> list[str]:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return [f"Current job: {NOT_REPORTED}"]
    raw_current_jobs = jobs.get("current_jobs")
    current_jobs = (
        cast("list[object]", raw_current_jobs)
        if isinstance(raw_current_jobs, list)
        else None
    )
    if current_jobs is not None and len(current_jobs) > 1:
        return [
            "Active jobs:",
            *[
                _running_job_line(cast("dict[str, object]", job))
                for job in current_jobs
                if isinstance(job, dict)
            ],
        ]
    current_job = jobs.get("current_job")
    if not isinstance(current_job, dict):
        return ["Current job: none active"]
    return _single_job_detail_lines(cast("dict[str, object]", current_job))


def _single_job_detail_lines(job: dict[str, object]) -> list[str]:
    lines = ["Current job:", f"  Operation: {_operation_label(job)}"]
    project = _job_project(job)
    if project:
        lines.append(f"  Project: {project}")
    lines.append(f"  Runtime: {_job_runtime_label(job)}")
    for label, value in (
        ("Progress", _human_progress(job)),
        ("Warning", _stale_progress_label(job)),
    ):
        if value:
            lines.append(f"  {label}: {value}")
    return lines


def _print_status_lines(lines: list[str]) -> None:
    """Write already-shaped operator lines, soft-wrapped and unstyled.

    Status output is data an operator reads and copies - paths, commands, job
    ids - so it goes out without markup or highlighting, and that decision is
    made once here rather than at each print site.
    """
    for line in lines:
        _plain(line, soft_wrap=True)


def _print_current_job_detail(jobs: dict[str, object] | None) -> None:
    _print_status_lines(_current_job_detail_lines(jobs))


def _degraded_findings_for_render(
    operational: dict[str, object] | None,
    health: dict[str, object] | None,
) -> list[DegradedFinding]:
    """Return the findings to render, computing them when none were passed.

    The summary path carries findings on ``operational`` because that is where
    the port qualifier is known, so those are rebuilt rather than re-derived.
    The discovery fallback has no operational summary and would otherwise print
    a bare severity word, so it derives them from the health payload it holds.
    """
    if not isinstance(operational, dict):
        return degradation_findings(health)
    raw = operational.get("degraded")
    entries = cast("list[object]", raw) if isinstance(raw, list) else []
    return [
        DegradedFinding.from_dict(cast("dict[str, object]", entry))
        for entry in entries
        if isinstance(entry, dict)
    ]


def _service_release_lines(health: dict[str, object]) -> list[str]:
    """Render the running service's release, and the mismatch when there is one.

    The release is shown unconditionally - an operator diagnosing odd behaviour
    should not have to guess which build answered - and an incompatible one adds
    the reason and its remediation, because a version the operator cannot act on
    is one more number on the screen.
    """
    from ..serviceclient._compat import classify_service_version

    verdict = classify_service_version(health)
    lines = [f"Service release: {verdict.service_version or NOT_REPORTED}"]
    if not verdict.is_compatible:
        lines.append(f"Incompatible: {verdict.reason()}.")
        lines.extend(verdict.remediation())
    return lines


def _degraded_lines(
    operational: dict[str, object] | None,
    health: dict[str, object] | None,
) -> list[str]:
    """Render each reported cause above the command that inspects it."""
    return degradation_lines(
        _degraded_findings_for_render(operational, health),
        header="Degraded because:",
    )


def _failure_lines(operational: dict[str, object] | None) -> list[str]:
    """Render the failed-job follow-up that hangs off the processed-jobs line."""
    if not isinstance(operational, dict):
        return []
    failure = operational.get("failure")
    if not isinstance(failure, dict):
        return []
    entry = cast("dict[str, object]", failure)
    lines: list[str] = []
    summary = entry.get("summary")
    if summary:
        lines.append(f"  Last failure: {summary}")
    command = entry.get("command")
    if command:
        lines.append(f"  Review failures: {command}")
    return lines


def _print_health_detail(
    health: dict[str, object] | None,
    port_listening: bool,
    operational: dict[str, object] | None = None,
) -> None:
    if isinstance(health, dict):
        _print_detail_line(
            "Requests",
            _status_health_label(health, port_listening=port_listening),
        )
        _print_status_lines(_degraded_lines(operational, health))
        compute = (
            "GPU available"
            if health.get("cuda") is True
            else "no supported GPU detected"
            if health.get("cuda") is False
            else NOT_REPORTED
        )
        _print_detail_line("Compute", compute)
        env_exe = health.get("executable")
        if isinstance(env_exe, str) and env_exe:
            _print_detail_line("Service env", env_exe)
        _print_status_lines(_service_release_lines(health))
        _print_detail_line(
            "Search models", _model_ready_label(health.get("models_loaded"))
        )
        _print_detail_line(
            "Reranking", _model_ready_label(health.get("reranker_loaded"))
        )
        _print_detail_line(
            "Loaded projects",
            health.get("project_count", NOT_REPORTED),
        )
        _print_detail_line("Uptime", _format_status_duration(health.get("uptime_s")))
    elif port_listening:
        _print_detail_line("Requests", "not reachable")


def _job_records_from_result(result: dict[str, object]) -> list[dict[str, object]]:
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        return []
    return [
        cast("dict[str, object]", entry)
        for entry in cast("list[object]", jobs)
        if isinstance(entry, dict)
    ]


def _queued_job_count(job_records: list[dict[str, object]]) -> int:
    queued = 0
    for entry in job_records:
        progress = entry.get("progress")
        if entry.get("phase") == "running" and isinstance(progress, dict):
            queued += int(cast("dict[str, object]", progress).get("step") == "queued")
    return queued


def _summary_count(
    value: object,
    *,
    fallback: int = 0,
) -> int:
    return value if isinstance(value, int) and value > 0 else fallback


def _running_job_count(
    summary: dict[str, object],
    job_records: list[dict[str, object]],
) -> int:
    fallback = sum(1 for entry in job_records if entry.get("phase") == "running")
    return _summary_count(summary.get("running"), fallback=fallback)


def _jobs_summary_from_result(result: dict[str, object] | None) -> dict[str, object]:
    if not isinstance(result, dict):
        return {"available": False}
    if result.get("ok") is False:
        return {
            "available": False,
            "error": result.get("error", "service_error"),
            "message": result.get("message", "Jobs route returned an error."),
        }
    summary = result.get("summary")
    summary_dict = (
        cast("dict[str, object]", summary) if isinstance(summary, dict) else {}
    )
    job_records = _job_records_from_result(result)
    active_job_records = _active_job_records(job_records)
    total_count = _summary_count(result.get("total"), fallback=len(job_records))
    returned_count = _summary_count(result.get("returned"), fallback=len(job_records))
    return {
        "available": True,
        "running": _running_job_count(summary_dict, job_records),
        "total": total_count,
        "returned": returned_count,
        "queued": _queued_job_count(job_records),
        "current_job": next(iter(active_job_records), None),
        "current_jobs": active_job_records,
        "phases": summary_dict.get("phases", {}),
        "sources": summary_dict.get("sources", {}),
        "triggers": summary_dict.get("triggers", {}),
        "initiators": summary_dict.get("initiators", {}),
        "active_initiators": summary_dict.get("active_initiators", {}),
        "users": summary_dict.get("users", {}),
    }


def _status_jobs_summary(port: int, port_listening: bool) -> dict[str, object]:
    if not port_listening:
        return {"available": False}
    try:
        return _jobs_summary_from_result(
            _try_http_admin("get_jobs", {"limit": 5}, port),
        )
    except Exception as exc:
        return {
            "available": False,
            "error": exc.__class__.__name__,
            "message": str(exc),
        }


def _status_next_action(
    state: str,
    health: dict[str, object] | None,
    jobs: dict[str, object],
    *,
    findings: list[DegradedFinding] | None = None,
    port: int | None = None,
) -> str:
    port_arg = port_option(port)
    if state == "stopped":
        return server_start_command(port)
    if state == "warming":
        return f"{server_status_command(port)}  (models loading; retry shortly)"
    if state != "running":
        return f"vaultspec-rag server logs --limit 80{port_arg}"
    return _running_service_next_action(
        health,
        jobs,
        findings or [],
        port=port,
    )


def _running_service_next_action(
    health: dict[str, object] | None,
    jobs: dict[str, object],
    findings: list[DegradedFinding],
    *,
    port: object | None,
) -> str:
    """Choose the follow-up for a service that is up, degraded or not."""
    port_arg = port_option(port)
    # A named cause outranks every generic follow-up: the operator's next move
    # is whatever inspects the thing that is actually broken.
    remediation = next((finding.command for finding in findings if finding.command), "")
    if remediation:
        return f"{remediation}{port_arg}"
    if not isinstance(health, dict) or health.get("status") != "ready":
        # Degraded for reasons this build cannot pair with a verb: the logs are
        # a sharper move than re-running status with more rows.
        if findings:
            return f"vaultspec-rag server logs --limit 80{port_arg}"
        return server_status_command(port, verbose=True)
    running_jobs = jobs.get("running")
    if isinstance(running_jobs, int) and running_jobs > 0:
        return server_jobs_command(port)
    return f'vaultspec-rag search "<query>" --type code{port_arg} --timeout 120'


def _failure_followup(
    health: dict[str, object] | None,
    jobs: dict[str, object],
    findings: list[DegradedFinding],
    *,
    port: object | None,
) -> dict[str, str] | None:
    """Turn a non-zero failed-job count into something the operator can run.

    The latest failure is named here only when the degraded block did not
    already name it, so the same job is never reported twice.
    """
    failed_total = _failed_job_total(jobs)
    already_reported = any(finding.family == FAILED_JOB_FAMILY for finding in findings)
    summary = "" if already_reported else _last_failure_label(health)
    if failed_total <= 0 and not summary:
        return None
    followup = {"command": server_jobs_command(port, failed=True)}
    if summary:
        followup["summary"] = summary
    return followup


def _status_operational_summary(
    state: str,
    port: int,
    port_listening: bool,
    health: dict[str, object] | None,
    *,
    explicit_port: bool = False,
) -> dict[str, object]:
    jobs = _status_jobs_summary(port, port_listening)
    port_arg = port_option(port if explicit_port else None)
    findings = degradation_findings(health)
    operational: dict[str, object] = {
        "jobs": jobs,
        "degraded": [finding.as_dict(port_arg=port_arg) for finding in findings],
        "next_action": _status_next_action(
            state,
            health,
            jobs,
            findings=findings,
            port=port if explicit_port else None,
        ),
    }
    failure = _failure_followup(
        health, jobs, findings, port=port if explicit_port else None
    )
    if failure is not None:
        operational["failure"] = failure
    return operational


def _print_operational_detail(
    operational: dict[str, object] | None,
) -> None:
    if operational is None:
        return
    status_file_port = operational.get("status_file_port")
    if status_file_port:
        _print_detail_line("Status file port", status_file_port)
    jobs = operational.get("jobs")
    if isinstance(jobs, dict):
        jobs_dict = cast("dict[str, object]", jobs)
        if jobs_dict.get("available") is True:
            _print_detail_line("Busy", _status_busy_label(jobs_dict))
            _print_detail_line("Queue", _status_queue_label(jobs_dict))
            _print_detail_line("Processed jobs", _status_jobs_label(jobs_dict))
            _print_status_lines(_failure_lines(operational))
            _print_current_job_detail(jobs_dict)
        else:
            _print_detail_line("Processed jobs", NOT_REPORTED)
    next_action = operational.get("next_action")
    if next_action:
        _print_next_action(next_action)


def _print_next_action(next_action: object) -> None:
    if next_action:
        _print_status_lines(["Next action:", f"  {next_action}"])


def _render_status_summary(
    *,
    state_label: str,
    port: int,
    port_listening: bool,
    health: dict[str, object] | None,
    operational: dict[str, object] | None,
    exit_code: int,
) -> None:
    jobs = operational.get("jobs") if isinstance(operational, dict) else None
    jobs_dict = cast("dict[str, object]", jobs) if isinstance(jobs, dict) else None
    lines = [
        f"Server: {_plain_status_label(state_label)}",
        f"Requests: {_status_health_label(health, port_listening=port_listening)}",
        *_degraded_lines(operational, health),
        f"Busy: {_status_busy_label(jobs_dict)}",
        _address_line(port),
        f"Service env: {_status_env_label(health)}",
        f"Uptime: {_status_uptime_label(health)}",
        f"Queue: {_status_queue_label(jobs_dict)}",
        f"Processed jobs: {_status_jobs_label(jobs_dict)}",
        *_failure_lines(operational),
    ]
    _print_status_lines(lines)
    _print_current_job_detail(jobs_dict)
    if isinstance(operational, dict):
        _print_next_action(operational.get("next_action"))
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _render_status_detail(
    pid: int,
    port: int,
    started_at: str,
    pid_alive: bool,
    pid_is_ours: bool,
    port_listening: bool,
    heartbeat_age: float | None,
    heartbeat_stale: bool,
    token_match: bool | None,
    state_label: str,
    exit_code: int,
    health: dict[str, object] | None,
    operational: dict[str, object] | None,
) -> None:
    _cli.console.print("Service status")
    _print_detail_line("Local record", "found")
    _print_detail_line("Process ID", pid)
    _print_status_lines([_address_line(port)])
    _print_detail_line("Started", _format_started_label(started_at))
    _print_detail_line("Process", "running" if pid_alive else "not running")
    _print_detail_line(
        "Process check",
        _process_identity_label(pid_alive, pid_is_ours),
    )
    _print_detail_line("Identity check", _get_token_label(token_match))
    _print_detail_line("Network", _network_label(port_listening, pid_alive))
    if heartbeat_age is None:
        _print_detail_line("Heartbeat", "absent")
    else:
        suffix = " (stale)" if heartbeat_stale else ""
        _print_detail_line("Heartbeat", f"{heartbeat_age:.0f}s ago{suffix}")
    _print_detail_line("Server", _plain_status_label(state_label))

    _print_health_detail(health, port_listening, operational)
    _print_operational_detail(operational)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _render_port_only_status(
    port: int,
    *,
    json_mode: bool,
    verbose: bool = False,
) -> None:
    port_listening = _port_is_listening(port)
    health = _try_http_health(port) if port_listening else None
    state = (
        "running"
        if isinstance(health, dict) and health.get("status") == "ready"
        else "stopped"
        if not port_listening
        else "unreachable"
    )
    exit_code = 0 if state == "running" else 3 if state == "stopped" else 4
    operational = _status_operational_summary(
        state,
        port,
        port_listening,
        health,
        explicit_port=True,
    )
    payload: dict[str, object] = {
        "service_json_present": False,
        "pid": None,
        "port": port,
        "pid_alive": None,
        "pid_matches_service": None,
        "port_listening": port_listening,
        "heartbeat_age_seconds": None,
        "heartbeat_stale": None,
        "service_token_match": None,
        "state": state,
    }
    if isinstance(health, dict):
        payload["health"] = health
    payload["operational"] = operational

    if json_mode:
        _emit_json(
            exit_code == 0,
            "service.status",
            data=payload,
            **(
                {"error": state, "message": f"Service status: {state}"}
                if exit_code != 0
                else {}
            ),
        )
        if exit_code != 0:
            raise typer.Exit(code=exit_code)
        return

    if not verbose:
        rendered_state = "running" if state == "running" else state
        _render_status_summary(
            state_label=rendered_state,
            port=port,
            port_listening=port_listening,
            health=health,
            operational=operational,
            exit_code=exit_code,
        )
        return

    _cli.console.print("Service status")
    _print_detail_line("Local record", "not found")
    _print_detail_line("Process", "not reported")
    _print_status_lines([_address_line(port)])
    _print_detail_line(
        "Network",
        "accepting connections" if port_listening else "not accepting connections",
    )
    _print_detail_line("Server", state)
    _print_health_detail(health, port_listening, operational)
    _print_operational_detail(operational)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _explicit_port_state(
    port_listening: bool,
    health: dict[str, object] | None,
    *,
    phase: str | None = None,
    pid_alive: bool = False,
    pid_is_ours: bool = False,
) -> tuple[str, str, int, bool]:
    if isinstance(health, dict) and health.get("status") == "ready":
        return "running", "running", 0, False
    if port_listening:
        return "unreachable", "unreachable", 4, False
    # Silent port + a live, identity-confirmed daemon that stamped ``warming``:
    # report the warmup window instead of a contradictory "stopped" (the
    # machine lock is held). A reused pid must not resurrect a stale stamp.
    if phase == SERVICE_PHASE_WARMING and pid_alive and pid_is_ours:
        return "warming", "warming (loading models, not yet serving)", 5, False
    return "stopped", "stopped", 3, False


def _status_response_token_match(
    expected_token: str | None,
    health: dict[str, object] | None,
) -> bool | None:
    response_token = health.get("service_token") if isinstance(health, dict) else None
    if isinstance(response_token, str) and expected_token:
        return bool(response_token) and response_token == expected_token
    return None


def _render_explicit_port_status(
    status: dict[str, Any],
    target_port: int,
    *,
    json_mode: bool,
    verbose: bool = False,
) -> None:
    pid = int(status.get("pid", 0))
    status_file_port = int(status.get("port", 0))
    started_at = str(status.get("started_at", "unknown"))
    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) else None
    pid_alive = _pid_alive(pid)
    pid_is_ours = (
        _is_our_service(pid, port=status_file_port, expected_token=expected_token)
        if pid_alive
        else False
    )
    heartbeat_age = _heartbeat_age_seconds(status)
    port_listening = _port_is_listening(target_port)
    health = _try_http_health(target_port) if port_listening else None
    state, state_label, exit_code, heartbeat_stale = _explicit_port_state(
        port_listening,
        health,
        phase=_service_phase(status),
        pid_alive=pid_alive,
        pid_is_ours=pid_is_ours,
    )
    token_match = _status_response_token_match(expected_token, health)
    operational = _status_operational_summary(
        state,
        target_port,
        port_listening,
        health,
        explicit_port=True,
    )
    if target_port != status_file_port:
        operational["status_file_port"] = status_file_port

    if json_mode:
        _render_status_json(
            pid,
            target_port,
            started_at,
            pid_alive,
            pid_is_ours,
            port_listening,
            heartbeat_age,
            heartbeat_stale,
            token_match,
            state,
            exit_code,
            health,
            operational,
        )
        return

    if target_port != status_file_port:
        _plain(
            "Local record points to "
            f"http://127.0.0.1:{status_file_port}; "
            f"checking http://127.0.0.1:{target_port}."
        )
    if verbose:
        _render_status_detail(
            pid,
            target_port,
            started_at,
            pid_alive,
            pid_is_ours,
            port_listening,
            heartbeat_age,
            heartbeat_stale,
            token_match,
            state_label,
            exit_code,
            health,
            operational,
        )
        return
    _render_status_summary(
        state_label=state_label,
        port=target_port,
        port_listening=port_listening,
        health=health,
        operational=operational,
        exit_code=exit_code,
    )


@server_app.command(
    "status",
    help=(
        "Show the human operator summary for server readiness, work, and next checks."
    ),
)
def service_status(
    requested_port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help=(
                f"{JSON_OPTION_HELP} Preserves exit "
                "codes 0 (running), 3 (stopped), 4 (crashed or divergent), "
                "and 5 (warming: models loading, not yet serving)."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help=(
                "Show process, heartbeat, service identity, model, and extra "
                "diagnostic details in the human output."
            ),
        ),
    ] = False,
) -> None:
    """Display the current status of the background search service.

    Gathers four signals before rendering - ``service.json`` present,
    PID alive, port listening, heartbeat fresh - and surfaces each as
    its own row plus a derived ``Server`` row. Avoids the previous
    "pick one source of truth" behaviour where conflicting signals
    rendered as a misleading verdict.

    Exit codes:
      - 0: ``running`` (all signals green).
      - 3: ``stopped`` (no ``service.json``).
      - 4: ``divergent`` or ``crashed-*`` (file present but at least
        one signal contradicts the others). Lets scripts branch on
        "known-bad state" without parsing the prose.
      - 5: ``warming`` (a live daemon holds the machine lock and is
        loading models; it is not yet accepting connections). Retry
        shortly rather than treating it as crashed.
    """
    status = _read_service_status()

    if status is None:
        if requested_port is not None:
            _render_port_only_status(
                requested_port,
                json_mode=json_mode,
                verbose=verbose,
            )
            return
        # This status directory holds no record, but the machine singleton is
        # machine-global: a consumer that does not share the daemon's status
        # directory still shares the singleton. Consult it before declaring
        # anything stopped, so a live holder - whether it is serving or has
        # merely failed to publish a trustworthy address - is never rendered
        # as an absent service. Only a genuinely unheld singleton falls
        # through to the stopped contract below.
        verdict = compose_discovery_status(
            (resolution := resolve_machine_service()),
            _liveness_from_resolution(resolution),
        )
        if verdict.state != STATUS_STOPPED:
            _render_discovery_verdict(verdict, json_mode=json_mode, verbose=verbose)
            return
        # Nothing holds the singleton => this config's service is stopped
        # (exit 3), per the documented contract (exit 4 is reserved for a
        # *present* service.json that diverges). We do NOT probe the port
        # here: on the shared default port another project's healthy service
        # would otherwise be misreported as this config's orphan/divergent
        # state (a multi-project false positive). `server start` keeps its own
        # port guard against double-starts.
        if json_mode:
            _emit_json(
                False,
                "service.status",
                error="stopped",
                message="No service.json - service is not running.",
                data={"service_json_present": False, "state": "stopped"},
            )
            raise typer.Exit(code=3)
        if verbose:
            _cli.console.print("Service status")
            _print_detail_line("Local record", "not found")
            _print_detail_line("Server", "stopped")
        else:
            _render_status_summary(
                state_label="stopped",
                port=_default_service_port() or 8766,
                port_listening=False,
                health=None,
                operational=None,
                exit_code=3,
            )
            return
        raise typer.Exit(code=3)

    if requested_port is not None:
        _render_explicit_port_status(
            status,
            requested_port,
            json_mode=json_mode,
            verbose=verbose,
        )
        return

    (
        pid,
        status_file_port,
        started_at,
        pid_alive,
        pid_is_ours,
        port_listening,
        heartbeat_age,
        heartbeat_stale,
        token_match,
        state,
        state_label,
        exit_code,
    ) = _evaluate_service_signals(status)

    target_port = status_file_port
    health = _try_http_health(target_port) if port_listening else None
    operational = _status_operational_summary(
        state,
        target_port,
        port_listening,
        health,
        explicit_port=False,
    )

    if json_mode:
        _render_status_json(
            pid,
            target_port,
            started_at,
            pid_alive,
            pid_is_ours,
            port_listening,
            heartbeat_age,
            heartbeat_stale,
            token_match,
            state,
            exit_code,
            health,
            operational,
        )
        return

    if verbose:
        _render_status_detail(
            pid,
            target_port,
            started_at,
            pid_alive,
            pid_is_ours,
            port_listening,
            heartbeat_age,
            heartbeat_stale,
            token_match,
            state_label,
            exit_code,
            health,
            operational,
        )
        return
    _render_status_summary(
        state_label=state_label,
        port=target_port,
        port_listening=port_listening,
        health=health,
        operational=operational,
        exit_code=exit_code,
    )
