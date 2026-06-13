"""``server`` lifecycle commands: start, stop, status, warmup."""

from __future__ import annotations

import os
import re
import sys
import time
from datetime import datetime
from typing import Annotated, Any, cast

import typer

import vaultspec_rag.cli as _cli

from ..config import EnvVar, get_config
from ._app import server_app
from ._gpu_errors import _handle_gpu_error
from ._http_search import _try_http_admin
from ._process import (
    _HEARTBEAT_STALENESS_SECONDS,
    _health_probe,
    _heartbeat_age_seconds,
    _port_is_available,
    _port_is_listening,
    _spawn_service,
)
from ._render import _emit_json
from ._service_jobs import (
    _human_progress,
    _operation_label,
    _project_label,
    _stale_progress_label,
)
from ._service_status import (
    _default_service_port,
    _log_file,
    _read_service_status,
    _status_file,
    _update_service_metadata,
    _update_service_token,
    _write_service_status,
)


def _ensure_qdrant_binary(*, auto_provision: bool) -> None:
    """Fail fast (or provision with consent) before a server-mode start.

    Server mode is the default backend, so this guard runs by default and
    only ``--local-only`` (or an explicit ``--no-qdrant``) skips it. Never
    downloads silently: an absent executable without ``auto_provision``
    prints the exact install command and exits non-zero.
    """
    from ..qdrant_runtime import QdrantProvisionAction, provision, resolve_binary

    if resolve_binary() is not None:
        return
    if not auto_provision:
        _print_lifecycle_lines(
            "Service start failed",
            (
                "Qdrant server mode needs the managed Qdrant server, "
                "which is not installed."
            ),
            "Run: vaultspec-rag server qdrant install",
            "(or re-run with --qdrant-auto-provision to consent to the download)",
            "Local-only option: vaultspec-rag server start --local-only",
        )
        raise typer.Exit(code=1)
    report = provision()
    if report.action == QdrantProvisionAction.FAILED or resolve_binary() is None:
        _print_lifecycle_lines(
            "Service start failed",
            f"Qdrant install failed: {report.message}",
        )
        raise typer.Exit(code=1)
    _print_lifecycle_lines(
        "Installed Qdrant server",
        f"Version: {report.version}",
        f"Install: {report.binary}",
    )


def _health_service_pid(health: dict[str, object], fallback_pid: int) -> int:
    serving_pid = health.get("pid")
    if isinstance(serving_pid, int) and serving_pid > 0:
        return serving_pid
    return fallback_pid


def _status_metadata_from_health(
    health: dict[str, object],
    *,
    pid: int,
) -> dict[str, object]:
    return {
        "pid": pid,
        "parent_pid": health.get("parent_pid"),
        "executable": health.get("executable"),
        "prefix": health.get("prefix"),
        "base_prefix": health.get("base_prefix"),
        "virtual_env": health.get("virtual_env"),
    }


def _print_lifecycle_lines(title: str, *lines: str) -> None:
    _cli.console.print(title, markup=False, highlight=False)
    for line in lines:
        _cli.console.print(line, markup=False, highlight=False, soft_wrap=True)


def _print_lifecycle_next_actions(*commands: str) -> None:
    _cli.console.print("Next actions:", markup=False, highlight=False)
    for command in commands:
        _cli.console.print(f"  {command}", markup=False, highlight=False)


def _process_line(pid: object) -> str:
    return f"Process ID: {pid}"


def _address_line(port: object) -> str:
    return f"Address: http://127.0.0.1:{port}"


def _existing_service_running() -> bool:
    """Report a live service and clean up stale state.

    Returns True when a healthy service we own is already running (the
    caller should not spawn another); removes a stale status file and
    returns False otherwise.
    """
    status = _read_service_status()
    if status is None:
        return False
    existing_pid = int(status["pid"])
    existing_port = int(status["port"])
    existing_token = status.get("service_token")
    existing_token_str = existing_token if isinstance(existing_token, str) else None
    if _cli._is_our_service(
        existing_pid,
        port=existing_port,
        expected_token=existing_token_str,
    ):
        health = _health_probe(existing_port)
        if health is not None:
            _print_lifecycle_lines(
                "Service already running",
                _process_line(existing_pid),
                _address_line(existing_port),
            )
            return True
    # Stale PID -- remove status file
    _status_file().unlink(missing_ok=True)
    return False


@server_app.command(
    "start",
    help=(
        "Start the background search service. Waits until it is ready "
        "and records how the CLI can reach it."
    ),
)
def service_start(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help="Port for the background search service.",
            envvar=EnvVar.PORT,
        ),
    ] = 8766,
    updates: Annotated[
        bool | None,
        typer.Option(
            "--updates/--no-updates",
            help=(
                "Enable or disable automatic index updates when files change "
                "(default: enabled)."
            ),
        ),
    ] = None,
    update_delay_ms: Annotated[
        int | None,
        typer.Option(
            "--update-delay-ms",
            help="Delay before indexing a burst of file changes, in milliseconds.",
        ),
    ] = None,
    same_project_delay_s: Annotated[
        float | None,
        typer.Option(
            "--same-project-delay-s",
            help="Minimum wait before indexing the same project again, in seconds.",
        ),
    ] = None,
    local_only: Annotated[
        bool,
        typer.Option(
            "--local-only",
            help=(
                "Use the on-disk local store instead of the default managed "
                "Qdrant server. This is the first-class opt-out for CI, "
                "offline, and small-project hosts."
            ),
        ),
    ] = False,
    qdrant: Annotated[
        bool | None,
        typer.Option(
            "--qdrant/--no-qdrant",
            help=(
                "Explicitly opt in to (or out of) the managed Qdrant server. "
                "Server mode is already the default, so --qdrant is redundant; "
                "use --local-only to select the on-disk store. Unset leaves "
                "the current Qdrant setting unchanged."
            ),
        ),
    ] = None,
    qdrant_auto_provision: Annotated[
        bool,
        typer.Option(
            "--qdrant-auto-provision",
            help=(
                "Download the managed Qdrant server if it is missing. "
                "Without this flag, start prints the install command."
            ),
        ),
    ] = False,
) -> None:
    """Start the background search service."""
    # Port-level guard: prevents concurrent start races (ADR D1)
    if not _port_is_available(port):
        _print_lifecycle_lines(
            "Service start failed",
            f"Port {port} is already in use.",
            "Another process is already using this service address.",
        )
        _print_lifecycle_next_actions(
            f"vaultspec-rag server status --port {port}",
            f"vaultspec-rag server jobs --state active --port {port}",
            "vaultspec-rag server start --port <free-port>",
        )
        raise typer.Exit(code=1)

    # Server mode is the default backend, so the qdrant-binary guard runs
    # by default. --local-only (and an explicit --no-qdrant) select the
    # on-disk store and skip it, so a default start fails fast on a missing
    # binary while the local opt-out never touches the server.
    if not local_only and qdrant is not False:
        _ensure_qdrant_binary(auto_provision=qdrant_auto_provision)

    if _existing_service_running():
        return

    log_path = _log_file()
    t0 = time.perf_counter()
    pid = _spawn_service(
        port,
        log_path,
        watch=updates,
        watch_debounce_ms=update_delay_ms,
        watch_cooldown_s=same_project_delay_s,
        qdrant=qdrant,
        local_only=local_only,
    )
    _write_service_status(pid, port)

    # Poll health with exponential backoff
    delay = 0.1
    deadline = 300.0
    elapsed = 0.0
    with _cli.console.status("Starting service..."):
        while elapsed < deadline:
            time.sleep(delay)
            elapsed = time.perf_counter() - t0

            # Check if process died (port conflict, etc.)
            if not _cli._is_pid_alive(pid):
                _status_file().unlink(missing_ok=True)
                _print_lifecycle_lines(
                    "Service start failed",
                    _process_line(pid),
                    _address_line(port),
                    f"Log: {log_path}",
                )
                raise typer.Exit(code=1)

            health = _health_probe(port)
            if health is not None and health.get("status") == "ready":
                # Persist the token from /health into service.json so
                # auto-delegation auth works before the first heartbeat
                # tick overwrites the file (S10 / #181 A5).
                token_from_health = health.get("service_token")
                if isinstance(token_from_health, str) and token_from_health:
                    _update_service_token(token_from_health)
                pid = _health_service_pid(health, pid)
                _update_service_metadata(_status_metadata_from_health(health, pid=pid))
                startup_s = time.perf_counter() - t0
                _print_lifecycle_lines(
                    "Service started",
                    _process_line(pid),
                    _address_line(port),
                    f"Startup: {startup_s:.1f}s",
                    f"Log: {log_path}",
                )
                return

            delay = min(delay * 2, 5.0)

    _print_lifecycle_lines(
        "Service start timed out",
        f"Waited: {deadline:.0f}s",
        _process_line(pid),
        "Server: process is running but not ready",
        f"Log: {log_path}",
    )
    raise typer.Exit(code=1)


@server_app.command("stop", help="Stop the background search service.")
def service_stop() -> None:
    """Stop the background search service.

    Reads the status file from ``~/.vaultspec-rag/service.json``, verifies
    the PID is still alive and belongs to a vaultspec-rag process, sends
    a graceful termination signal (SIGTERM on Unix, CTRL_BREAK_EVENT on
    Windows), waits briefly for graceful shutdown, and removes the status file.
    Force-kills (SIGKILL/TerminateProcess) if graceful shutdown fails.
    """
    status = _read_service_status()
    if status is None:
        # No service.json => nothing to stop for this config. We do NOT probe
        # the port: on the shared default port another project's healthy
        # service would otherwise be misreported as this config's orphan.
        _cli.console.print("Service is not running.")
        return

    pid = int(status["pid"])
    port = int(status["port"])
    raw_token = status.get("service_token")
    expected_token = raw_token if isinstance(raw_token, str) else None
    if not _cli._is_our_service(pid, port=port, expected_token=expected_token):
        _status_file().unlink(missing_ok=True)
        _print_lifecycle_lines(
            "Service status cleaned",
            f"Recorded process {pid} is no longer running.",
        )
        return

    _cli._terminate_pid(pid)

    # Wait briefly for process to exit
    for _ in range(50):
        if not _cli._is_pid_alive(pid):
            break
        time.sleep(0.1)

    _status_file().unlink(missing_ok=True)
    if sys.platform == "win32":
        # On Windows, os.kill(SIGTERM) is TerminateProcess so the
        # daemon's atexit handler and lifespan ``finally`` never
        # fire. POSIX flows through uvicorn's signal handler →
        # lifespan finally → ``_record_shutdown("clean")`` which
        # emits ``service.lifecycle event=shutdown reason=clean``.
        # The CLI parent emits a mirror line here so Windows
        # operators get the same audit trail.
        _cli._append_lifecycle_shutdown_log(
            "cli_terminate",
            pid=pid,
            platform="win32",
        )
    _print_lifecycle_lines("Service stopped", _process_line(pid))


def _compute_token_match(
    expected_token: str | None,
    pid_alive: bool,
    port_listening: bool,
    port: int,
) -> bool | None:
    if expected_token is None or not pid_alive:
        return None
    probe_for_token = _health_probe(port) if port_listening else None
    if probe_for_token is not None and isinstance(
        probe_for_token.get("service_token"),
        str,
    ):
        response_token = probe_for_token["service_token"]
        return bool(response_token) and response_token == expected_token
    return None


def _compute_state(
    pid_alive: bool,
    pid_is_ours: bool,
    port_listening: bool,
    heartbeat_stale: bool,
) -> tuple[str, str, int]:
    if not pid_alive:
        _status_file().unlink(missing_ok=True)
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
    pid_alive = _cli._is_pid_alive(pid)
    pid_is_ours = (
        _cli._is_our_service(pid, port=port, expected_token=expected_token)
        if pid_alive
        else False
    )
    port_listening = _port_is_listening(port) if pid_alive else False
    heartbeat_age = _heartbeat_age_seconds(status)
    heartbeat_stale = (
        pid_alive
        if heartbeat_age is None
        else heartbeat_age > _HEARTBEAT_STALENESS_SECONDS
    )

    token_match = _compute_token_match(expected_token, pid_alive, port_listening, port)
    state, state_label, exit_code = _compute_state(
        pid_alive, pid_is_ours, port_listening, heartbeat_stale
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


def _get_token_label(token_match: bool | None) -> str:
    if token_match is None:
        return "not verified by this status check"
    if token_match:
        return "verified"
    return "does not match the recorded service"


def _model_ready_label(value: object) -> str:
    if value is True:
        return "ready"
    if value is False:
        return "not ready"
    return "not reported by service"


def _process_identity_label(pid_alive: bool, pid_is_ours: bool) -> str:
    if pid_is_ours:
        return "verified"
    if pid_alive:
        return "does not match the recorded service"
    return "not verified because the process is not running"


def _network_label(port_listening: bool, pid_alive: bool) -> str:
    if port_listening:
        return "accepting connections"
    if pid_alive:
        return "not accepting connections"
    return "not accepting connections"


def _plain_status_label(state: str) -> str:
    return re.sub(r"\[[^]]*\]", "", state)


def _counted_unit(value: int, singular: str, plural: str | None = None) -> str:
    unit = singular if value == 1 else plural or f"{singular}s"
    return f"{value} {unit}"


def _format_status_duration(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "not reported by service"
    seconds = max(0, int(float(raw)))
    if seconds < 60:
        return _counted_unit(seconds, "second")
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        if seconds:
            return (
                f"{_counted_unit(minutes, 'minute')} {_counted_unit(seconds, 'second')}"
            )
        return _counted_unit(minutes, "minute")
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        if minutes:
            return f"{_counted_unit(hours, 'hour')} {_counted_unit(minutes, 'minute')}"
        return _counted_unit(hours, "hour")
    days, hours = divmod(hours, 24)
    if hours:
        return f"{_counted_unit(days, 'day')} {_counted_unit(hours, 'hour')}"
    return _counted_unit(days, "day")


def _format_started_label(raw: object) -> str:
    if not isinstance(raw, str) or not raw or raw == "unknown":
        return "not reported by local record"
    try:
        started = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw
    return f"{started.astimezone().strftime('%H:%M:%S')} local time"


def _job_progress_summary(job: dict[str, object]) -> str:
    parts = []
    progress = _human_progress(job)
    if progress:
        parts.append(progress)
    stale_progress = _stale_progress_label(job)
    if stale_progress:
        parts.append(stale_progress)
    return f", {', '.join(parts)}" if parts else ""


def _job_command_name(job: dict[str, object]) -> str:
    operation = _operation_label(job)
    project = _project_label(job)
    if project != "project not reported":
        return f"{operation} for {project}"
    return operation


def _current_job_summary(job: dict[str, object] | None) -> str:
    if job is None:
        return "none"
    started_at = job.get("started_at")
    age = (
        _format_status_duration(time.time() - float(started_at))
        if isinstance(started_at, int | float)
        else "not reported by service"
    )
    return f"{_job_command_name(job)} ({age}{_job_progress_summary(job)})"


def _active_job_records(
    job_records: list[dict[str, object]],
) -> list[dict[str, object]]:
    active: list[dict[str, object]] = []
    for entry in job_records:
        if entry.get("phase") != "running":
            continue
        progress = entry.get("progress")
        if isinstance(progress, dict) and progress.get("step") == "queued":
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
        return ["Current job: not reported by service"]
    current_jobs = jobs.get("current_jobs")
    if isinstance(current_jobs, list) and len(current_jobs) > 1:
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
    job = cast("dict[str, object]", current_job)
    started_at = job.get("started_at")
    runtime = (
        _format_status_duration(time.time() - float(started_at))
        if isinstance(started_at, int | float)
        else "not reported by service"
    )
    lines = [
        "Current job:",
        f"  Operation: {_operation_label(job)}",
    ]
    project = _project_label(job)
    if project != "project not reported":
        lines.append(f"  Project: {project}")
    lines.append(f"  Runtime: {runtime}")
    progress = _human_progress(job)
    if progress:
        lines.append(f"  Progress: {progress}")
    warning = _stale_progress_label(job)
    if warning:
        lines.append(f"  Warning: {warning}")
    return lines


def _print_current_job_detail(jobs: dict[str, object] | None) -> None:
    for line in _current_job_detail_lines(jobs):
        _cli.console.print(line, markup=False, highlight=False, soft_wrap=True)


def _print_detail_line(label: str, value: object) -> None:
    _cli.console.print(f"{label}: {value}", markup=False, highlight=False)


def _print_health_detail(
    health: dict[str, object] | None, port_listening: bool
) -> None:
    if isinstance(health, dict):
        _print_detail_line(
            "Requests",
            _status_health_label(health, port_listening=port_listening),
        )
        compute = (
            "GPU available"
            if health.get("cuda") is True
            else "no supported GPU detected"
            if health.get("cuda") is False
            else "not reported by service"
        )
        _print_detail_line("Compute", compute)
        _print_detail_line(
            "Search models", _model_ready_label(health.get("models_loaded"))
        )
        _print_detail_line(
            "Reranking", _model_ready_label(health.get("reranker_loaded"))
        )
        _print_detail_line(
            "Loaded projects",
            health.get("project_count", "not reported by service"),
        )
        _print_detail_line("Uptime", _format_status_duration(health.get("uptime_s")))
    elif port_listening:
        _print_detail_line("Requests", "not reachable")


def _job_records_from_result(result: dict[str, object]) -> list[dict[str, object]]:
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        return []
    return [
        cast("dict[str, object]", entry) for entry in jobs if isinstance(entry, dict)
    ]


def _queued_job_count(job_records: list[dict[str, object]]) -> int:
    queued = 0
    for entry in job_records:
        progress = entry.get("progress")
        if entry.get("phase") == "running" and isinstance(progress, dict):
            queued += int(progress.get("step") == "queued")
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
    port: int | None = None,
) -> str:
    port_arg = f" --port {port}" if port is not None else ""
    if state == "stopped":
        return f"vaultspec-rag server start{port_arg}"
    if state != "running":
        return f"vaultspec-rag server logs --limit 80{port_arg}"
    if not isinstance(health, dict) or health.get("status") != "ready":
        return f"vaultspec-rag server status --verbose{port_arg}"
    running_jobs = jobs.get("running")
    if isinstance(running_jobs, int) and running_jobs > 0:
        return f"vaultspec-rag server jobs --state active{port_arg}"
    return f'vaultspec-rag search "<query>" --type code{port_arg} --timeout 120'


def _status_operational_summary(
    state: str,
    port: int,
    port_listening: bool,
    health: dict[str, object] | None,
    *,
    explicit_port: bool = False,
) -> dict[str, object]:
    jobs = _status_jobs_summary(port, port_listening)
    return {
        "jobs": jobs,
        "next_action": _status_next_action(
            state,
            health,
            jobs,
            port=port if explicit_port else None,
        ),
    }


def _print_operational_detail(
    operational: dict[str, object] | None,
) -> None:
    if not isinstance(operational, dict):
        return
    status_file_port = operational.get("status_file_port")
    if status_file_port:
        _print_detail_line("Status file port", status_file_port)
    jobs = operational.get("jobs")
    if isinstance(jobs, dict):
        if jobs.get("available") is True:
            jobs_dict = cast("dict[str, object]", jobs)
            _print_detail_line("Busy", _status_busy_label(jobs_dict))
            _print_detail_line("Queue", _status_queue_label(jobs_dict))
            _print_detail_line("Processed jobs", _status_jobs_label(jobs_dict))
            _print_current_job_detail(jobs_dict)
        else:
            _print_detail_line("Processed jobs", "not reported by service")
    next_action = operational.get("next_action")
    if next_action:
        _print_next_action(next_action)


def _print_next_action(next_action: object) -> None:
    if next_action:
        _cli.console.print("Next action:", markup=False, highlight=False)
        _cli.console.print(f"  {next_action}", markup=False, highlight=False)


def _status_health_label(
    health: dict[str, object] | None,
    *,
    port_listening: bool,
) -> str:
    if isinstance(health, dict):
        raw_status = health.get("status")
        if not isinstance(raw_status, str) or not raw_status or raw_status == "unknown":
            return "not reported by service"
        status = raw_status
        if status == "ready":
            return "ready for requests"
        if status == "starting":
            return "starting up"
        return status.replace("_", " ")
    return "not reachable" if port_listening else "not available"


def _status_busy_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    if running_count <= 0:
        return "idle"
    active_count = max(0, running_count - queued_count)
    if active_count <= 0 and queued_count > 0:
        return (
            "1 job waiting to write"
            if queued_count == 1
            else f"{queued_count} jobs waiting to write"
        )
    if active_count > 0 and queued_count > 0:
        active_text = (
            "processing 1 job"
            if active_count == 1
            else f"processing {active_count} jobs"
        )
        waiting_text = "1 waiting" if queued_count == 1 else f"{queued_count} waiting"
        return f"{active_text}; {waiting_text}"
    if active_count == 1:
        return "processing 1 job"
    return f"processing {active_count} jobs"


def _status_queue_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    if running_count <= 0:
        return "nothing waiting"
    active_count = max(0, running_count - queued_count)
    if queued_count > 0:
        active_text = (
            "1 active job" if active_count == 1 else f"{active_count} active jobs"
        )
        queued_text = (
            "1 waiting job" if queued_count == 1 else f"{queued_count} waiting jobs"
        )
        return f"{queued_text}; {active_text}"
    running_text = (
        "1 active job" if running_count == 1 else f"{running_count} active jobs"
    )
    return f"nothing waiting; {running_text}"


def _status_jobs_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    phases = jobs.get("phases")
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    active_count = max(0, running_count - queued_count)
    finished_count = 0
    failed_count = 0
    if isinstance(phases, dict):
        phase_dict = cast("dict[str, object]", phases)
        done = phase_dict.get("done")
        error = phase_dict.get("error")
        failed = phase_dict.get("failed")
        if isinstance(done, int):
            finished_count = done
        if isinstance(error, int):
            failed_count += error
        if isinstance(failed, int):
            failed_count += failed
    return (
        f"{finished_count} finished, {active_count} active, "
        f"{queued_count} waiting, {failed_count} failed"
    )


def _status_current_job_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "not reported by service"
    current_job = jobs.get("current_job")
    current_job_dict = (
        cast("dict[str, object]", current_job)
        if isinstance(current_job, dict)
        else None
    )
    summary = _current_job_summary(current_job_dict)
    return "none active" if summary == "none" else summary


def _status_uptime_label(health: dict[str, object] | None) -> str:
    if not isinstance(health, dict):
        return "not reported by service"
    return _format_status_duration(health.get("uptime_s"))


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
        f"Busy: {_status_busy_label(jobs_dict)}",
        f"Address: http://127.0.0.1:{port}",
        f"Uptime: {_status_uptime_label(health)}",
        f"Queue: {_status_queue_label(jobs_dict)}",
        f"Processed jobs: {_status_jobs_label(jobs_dict)}",
    ]
    for line in lines:
        _cli.console.print(line, markup=False, highlight=False)
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
    _print_detail_line("Address", f"http://127.0.0.1:{port}")
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

    _print_health_detail(health, port_listening)
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
    health = _health_probe(port) if port_listening else None
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
    _print_detail_line("Address", f"http://127.0.0.1:{port}")
    _print_detail_line(
        "Network",
        "accepting connections" if port_listening else "not accepting connections",
    )
    _print_detail_line("Server", state)
    _print_health_detail(health, port_listening)
    _print_operational_detail(operational)
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _explicit_port_state(
    port_listening: bool,
    health: dict[str, object] | None,
) -> tuple[str, str, int, bool]:
    if isinstance(health, dict) and health.get("status") == "ready":
        return "running", "running", 0, False
    if port_listening:
        return "unreachable", "unreachable", 4, False
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
    pid_alive = _cli._is_pid_alive(pid)
    pid_is_ours = (
        _cli._is_our_service(pid, port=status_file_port, expected_token=expected_token)
        if pid_alive
        else False
    )
    heartbeat_age = _heartbeat_age_seconds(status)
    port_listening = _port_is_listening(target_port)
    health = _health_probe(target_port) if port_listening else None
    state, state_label, exit_code, heartbeat_stale = _explicit_port_state(
        port_listening,
        health,
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
        _cli.console.print(
            "Local record points to "
            f"http://127.0.0.1:{status_file_port}; "
            f"checking http://127.0.0.1:{target_port}.",
            markup=False,
            highlight=False,
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
                "Emit JSON for scripts instead of human text. Preserves exit "
                "codes 0 (running), 3 (stopped), and 4 (crashed or divergent)."
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
        # No service.json in the configured status dir => this config's
        # service is stopped (exit 3), per the documented contract (exit 4
        # is reserved for a *present* service.json that diverges). We do
        # NOT probe the port here: on the shared default port another
        # project's healthy service would otherwise be misreported as this
        # config's orphan/divergent state (a multi-project false positive).
        # `server start` keeps its own port guard against double-starts.
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
    health = _health_probe(target_port) if port_listening else None
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


@server_app.command(
    "warmup",
    help=(
        "Download GPU model files before they are needed. "
        "Run once before the first index to avoid model download latency at "
        "search time. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def service_warmup() -> None:
    """Download GPU model files before they are needed."""
    try:
        import torch
    except ImportError:
        _cli.console.print("Error: torch is not installed.")
        raise typer.Exit(code=1) from None

    if not torch.cuda.is_available():
        _handle_gpu_error(RuntimeError("CUDA runtime unavailable"))

    try:
        from huggingface_hub import (
            get_token,
            snapshot_download,  # pyright: ignore[reportUnknownVariableType]  # huggingface_hub stubs partially unknown
            try_to_load_from_cache,
        )
    except ImportError:
        _cli.console.print("Error: huggingface_hub is not installed.")
        raise typer.Exit(code=1) from None

    os.environ.setdefault(EnvVar.HF_HUB_DOWNLOAD_TIMEOUT, "300")

    cfg = get_config()
    models = [
        ("Dense (Qwen3)", cfg.embedding_model),
        ("Sparse (SPLADE)", cfg.sparse_model),
        ("Reranker (CrossEncoder)", cfg.reranker_model),
    ]

    _cli.console.print("Model warmup")
    token = get_token()
    if token:
        _print_detail_line("HuggingFace auth", "configured")
    else:
        _print_detail_line(
            "HuggingFace auth",
            "missing; run huggingface-cli login if downloads fail",
        )

    for label, repo_id in models:
        # Check if already cached
        cached = try_to_load_from_cache(repo_id, "config.json")
        if cached is not None:
            _print_detail_line(label, f"{repo_id} cached")
            continue

        try:
            with _cli.console.status(f"Downloading {label}..."):
                snapshot_download(repo_id)
            _print_detail_line(label, f"{repo_id} downloaded")
        except Exception as exc:
            msg = str(exc)
            if "401" in msg or "403" in msg or "GatedRepo" in msg:
                _print_detail_line(
                    label,
                    f"{repo_id} auth required; run huggingface-cli login",
                )
            else:
                _print_detail_line(
                    label,
                    f"{repo_id} failed: {exc}"
                    " (partial cache may remain in ~/.cache/huggingface)",
                )
