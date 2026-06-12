"""``server`` lifecycle commands: start, stop, status, warmup."""

from __future__ import annotations

import os
import re
import sys
import time
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
from ._render import _emit_json, _emit_json_error_and_exit
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
    """Fail fast (or provision with consent) before a --qdrant start.

    Never downloads silently: an absent binary without
    ``auto_provision`` prints the exact install command and exits
    non-zero.
    """
    from ..qdrant_runtime import QdrantProvisionAction, provision, resolve_binary

    if resolve_binary() is not None:
        return
    if not auto_provision:
        _print_lifecycle_lines(
            "Service start failed",
            "qdrant server mode needs the server binary, which is not installed.",
            "Run: vaultspec-rag server qdrant install",
            "(or re-run with --qdrant-auto-provision to consent to the download)",
        )
        raise typer.Exit(code=1)
    report = provision()
    if report.action == QdrantProvisionAction.FAILED or resolve_binary() is None:
        _print_lifecycle_lines(
            "Service start failed",
            f"qdrant provisioning failed: {report.message}",
        )
        raise typer.Exit(code=1)
    _print_lifecycle_lines(
        "Provisioned qdrant server",
        f"Version: {report.version}",
        f"Binary: {report.binary}",
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


@server_app.command(
    "start",
    help=(
        "Start the background RAG service as a detached process. "
        "Polls /health until ready and writes a status record to "
        "~/.vaultspec-rag/service.json."
    ),
)
def service_start(
    port: Annotated[
        int,
        typer.Option(
            "--port",
            help="TCP port for the HTTP service.",
            envvar=EnvVar.PORT,
        ),
    ] = 8766,
    watch: Annotated[
        bool | None,
        typer.Option(
            "--watch/--no-watch",
            help="Enable or disable filesystem auto-reindex (default: enabled). "
            "Unset leaves VAULTSPEC_RAG_WATCH_ENABLED untouched.",
        ),
    ] = None,
    watch_debounce_ms: Annotated[
        int | None,
        typer.Option(
            "--watch-debounce-ms",
            help="Watcher debounce window in milliseconds (default 2000).",
        ),
    ] = None,
    watch_cooldown_s: Annotated[
        float | None,
        typer.Option(
            "--watch-cooldown-s",
            help="Per-source re-index cooldown in seconds (default 30).",
        ),
    ] = None,
    qdrant: Annotated[
        bool | None,
        typer.Option(
            "--qdrant/--no-qdrant",
            help="Run the daemon in qdrant server mode: it supervises the "
            "pinned Rust qdrant binary as a loopback child and routes all "
            "stores at it. Unset leaves VAULTSPEC_RAG_QDRANT_SERVER "
            "untouched.",
        ),
    ] = None,
    qdrant_auto_provision: Annotated[
        bool,
        typer.Option(
            "--qdrant-auto-provision",
            help="Consent to downloading the pinned qdrant binary when it "
            "is absent. Without this flag an absent binary fails the start "
            "with the exact install command.",
        ),
    ] = False,
) -> None:
    """Start the background RAG service as a detached process."""
    # Port-level guard: prevents concurrent start races (ADR D1)
    if not _port_is_available(port):
        _print_lifecycle_lines("Service start failed", f"Port {port} is in use.")
        raise typer.Exit(code=1)

    if qdrant:
        _ensure_qdrant_binary(auto_provision=qdrant_auto_provision)

    # Check for existing service
    status = _read_service_status()
    if status is not None:
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
                    f"PID: {existing_pid}",
                    f"Port: {existing_port}",
                )
                return
        # Stale PID -- remove status file
        _status_file().unlink(missing_ok=True)

    log_path = _log_file()
    t0 = time.perf_counter()
    pid = _spawn_service(
        port,
        log_path,
        watch=watch,
        watch_debounce_ms=watch_debounce_ms,
        watch_cooldown_s=watch_cooldown_s,
        qdrant=qdrant,
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
                    f"PID: {pid}",
                    f"Port: {port}",
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
                    f"PID: {pid}",
                    f"Port: {port}",
                    f"Startup: {startup_s:.1f}s",
                    f"Log: {log_path}",
                )
                return

            delay = min(delay * 2, 5.0)

    _print_lifecycle_lines(
        "Service start timed out",
        f"Waited: {deadline:.0f}s",
        f"PID: {pid}",
        "State: process is running but not ready",
        f"Log: {log_path}",
    )
    raise typer.Exit(code=1)


@server_app.command("stop")
def service_stop() -> None:
    """Stop the background RAG service.

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
            f"PID {pid} is no longer running.",
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
    _print_lifecycle_lines("Service stopped", f"PID: {pid}")


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
    started_at = str(status.get("started_at", "unknown"))

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
            {"error": state, "message": f"Service state: {state}"}
            if exit_code != 0
            else {}
        ),
    )
    if exit_code != 0:
        raise typer.Exit(code=exit_code)


def _get_token_label(token_match: bool | None) -> str:
    if token_match is None:
        return "n/a"
    if token_match:
        return "yes"
    return "no"


def _plain_status_label(state: str) -> str:
    return re.sub(r"\[[^]]*\]", "", state)


def _format_status_duration(raw: object) -> str:
    if not isinstance(raw, int | float):
        return "unknown"
    seconds = max(0, int(float(raw)))
    if seconds < 60:
        return f"{seconds}s"
    minutes, seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {seconds}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def _job_progress_summary(job: dict[str, object]) -> str:
    progress = job.get("progress")
    if not isinstance(progress, dict):
        return ""
    progress_dict = cast("dict[str, object]", progress)
    step = str(progress_dict.get("step") or "")
    completed = progress_dict.get("completed")
    total = progress_dict.get("total")
    if step and isinstance(total, int | float):
        return f", {step} {completed}/{total}"
    if step:
        return f", {step}"
    return ""


def _job_command_name(job: dict[str, object]) -> str:
    initiator = job.get("initiator")
    if isinstance(initiator, dict):
        command = initiator.get("command")
        if command:
            return str(command)
    source = str(job.get("source") or "job")
    trigger = str(job.get("trigger") or "service")
    return f"{trigger}_{source}"


def _current_job_summary(job: dict[str, object] | None) -> str:
    if job is None:
        return "none"
    started_at = job.get("started_at")
    age = (
        _format_status_duration(time.time() - float(started_at))
        if isinstance(started_at, int | float)
        else "unknown"
    )
    return f"{_job_command_name(job)} ({age}{_job_progress_summary(job)})"


def _print_detail_line(label: str, value: object) -> None:
    _cli.console.print(f"{label}: {value}", markup=False, highlight=False)


def _print_health_detail(
    health: dict[str, object] | None, port_listening: bool
) -> None:
    if isinstance(health, dict):
        _print_detail_line(
            "Health",
            _status_health_label(health, port_listening=port_listening),
        )
        _print_detail_line("CUDA", health.get("cuda", "unknown"))
        _print_detail_line("Models loaded", health.get("models_loaded", "unknown"))
        _print_detail_line("Reranker loaded", health.get("reranker_loaded", "unknown"))
        _print_detail_line("Projects", health.get("project_count", "unknown"))
        _print_detail_line("Uptime", _format_status_duration(health.get("uptime_s")))
    elif port_listening:
        _print_detail_line("Health", "not reachable")


def _job_records_from_result(result: dict[str, object]) -> list[dict[str, object]]:
    jobs = result.get("jobs")
    if not isinstance(jobs, list):
        return []
    return [
        cast("dict[str, object]", entry) for entry in jobs if isinstance(entry, dict)
    ]


def _first_running_job(
    job_records: list[dict[str, object]],
) -> dict[str, object] | None:
    return next(
        (entry for entry in job_records if entry.get("phase") == "running"), None
    )


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
    total_count = _summary_count(result.get("total"), fallback=len(job_records))
    returned_count = _summary_count(result.get("returned"), fallback=len(job_records))
    return {
        "available": True,
        "running": _running_job_count(summary_dict, job_records),
        "total": total_count,
        "returned": returned_count,
        "queued": _queued_job_count(job_records),
        "current_job": _first_running_job(job_records),
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
    if state != "running":
        return f"vaultspec-rag server logs --lines 80{port_arg}"
    if not isinstance(health, dict) or health.get("status") != "ready":
        return f"vaultspec-rag server status --verbose{port_arg}"
    running_jobs = jobs.get("running")
    if isinstance(running_jobs, int) and running_jobs > 0:
        return f"vaultspec-rag server jobs --running{port_arg}"
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
            _print_detail_line("Jobs", _status_jobs_label(jobs_dict))
            _print_detail_line("Current job", _status_current_job_label(jobs_dict))
        else:
            _print_detail_line("Jobs", "unavailable")
    next_action = operational.get("next_action")
    if next_action:
        _cli.console.print("Next action:", markup=False, highlight=False)
        _cli.console.print(f"  {next_action}", markup=False, highlight=False)


def _status_health_label(
    health: dict[str, object] | None,
    *,
    port_listening: bool,
) -> str:
    if isinstance(health, dict):
        status = str(health.get("status", "unknown"))
        if status == "ready":
            return "ready for requests"
        if status == "starting":
            return "starting up"
        return status.replace("_", " ")
    return "not reachable" if port_listening else "not available"


def _status_busy_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "unknown"
    running = jobs.get("running")
    running_count = running if isinstance(running, int) else 0
    if running_count <= 0:
        return "idle"
    if running_count == 1:
        return "processing 1 job"
    return f"processing {running_count} jobs"


def _status_queue_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "unavailable"
    running = jobs.get("running")
    queued = jobs.get("queued")
    running_count = running if isinstance(running, int) else 0
    queued_count = queued if isinstance(queued, int) else 0
    if running_count <= 0:
        return "no queued work"
    active_count = max(0, running_count - queued_count)
    if queued_count > 0:
        active_text = (
            "1 active job" if active_count == 1 else f"{active_count} active jobs"
        )
        queued_text = (
            "1 queued job" if queued_count == 1 else f"{queued_count} queued jobs"
        )
        return f"{queued_text}; {active_text}"
    running_text = (
        "1 active job" if running_count == 1 else f"{running_count} active jobs"
    )
    return f"no queued work; {running_text}"


def _status_jobs_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "unavailable"
    phases = jobs.get("phases")
    total = jobs.get("total")
    running = jobs.get("running")
    total_count = total if isinstance(total, int) else 0
    running_count = running if isinstance(running, int) else 0
    processed = max(0, total_count - running_count)
    if isinstance(phases, dict):
        phase_dict = cast("dict[str, object]", phases)
        phase_processed = sum(
            int(count)
            for phase, count in phase_dict.items()
            if phase != "running" and isinstance(count, int)
        )
        if phase_processed > 0:
            processed = phase_processed
    processed_word = "job" if processed == 1 else "jobs"
    running_text = (
        "none running"
        if running_count == 0
        else ("1 running" if running_count == 1 else f"{running_count} running")
    )
    total_word = "job" if total_count == 1 else "jobs"
    return (
        f"{processed} processed {processed_word}; "
        f"{running_text}; {total_count} recent {total_word}"
    )


def _status_current_job_label(jobs: dict[str, object] | None) -> str:
    if not isinstance(jobs, dict) or jobs.get("available") is not True:
        return "unavailable"
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
        return "unknown"
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
        f"Ready: {_status_health_label(health, port_listening=port_listening)}",
        f"Busy: {_status_busy_label(jobs_dict)}",
        f"Address: http://127.0.0.1:{port}",
        f"Uptime: {_status_uptime_label(health)}",
        f"Queue: {_status_queue_label(jobs_dict)}",
        f"Jobs: {_status_jobs_label(jobs_dict)}",
        f"Current job: {_status_current_job_label(jobs_dict)}",
    ]
    for line in lines:
        _cli.console.print(line, markup=False, highlight=False)
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
    _print_detail_line("Service file", "present")
    _print_detail_line("PID", pid)
    _print_detail_line("Port", port)
    _print_detail_line("Started", started_at)
    _print_detail_line("PID alive", "yes" if pid_alive else "no")
    pid_match = "yes" if pid_is_ours else "no" if pid_alive else "n/a"
    _print_detail_line("PID matches service", pid_match)
    _print_detail_line("Service token match", _get_token_label(token_match))
    port_state = "yes" if port_listening else "no" if pid_alive else "n/a"
    _print_detail_line("Port listening", port_state)
    if heartbeat_age is None:
        _print_detail_line("Heartbeat", "absent")
    else:
        suffix = " (stale)" if heartbeat_stale else ""
        _print_detail_line("Heartbeat", f"{heartbeat_age:.0f}s ago{suffix}")
    _print_detail_line("State", _plain_status_label(state_label))

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
                {"error": state, "message": f"Service state: {state}"}
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
    _print_detail_line("Service file", "missing")
    _print_detail_line("PID", "n/a")
    _print_detail_line("Port", port)
    _print_detail_line("Port listening", "yes" if port_listening else "no")
    _print_detail_line("State", state)
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
            f"Status file port is {status_file_port}; probing {target_port}.",
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


def service_health(
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option(
            "--json",
            help="Emit the full /health JSON envelope for automation.",
        ),
    ] = False,
) -> None:
    """Internal compatibility helper for probing the service ``/health`` endpoint."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        message = "Service is not running. Start it with `vaultspec-rag server start`."
        if json_mode:
            _emit_json_error_and_exit(
                "service.health",
                "service_not_running",
                message,
                3,
            )
        _cli.console.print(
            "Ready: unavailable\n"
            "Use `vaultspec-rag server status` for service state and next actions.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(3)

    health = _health_probe(resolved_port)
    if health is None:
        message = (
            f"Service on port {resolved_port} is unreachable. "
            "Start it with `vaultspec-rag server start`."
        )
        if json_mode:
            _emit_json_error_and_exit(
                "service.health",
                "service_not_running",
                message,
                3,
                port=resolved_port,
            )
        _cli.console.print(
            "Ready: unreachable\n"
            f"Use `vaultspec-rag server status --port {resolved_port}` for "
            "service state and next actions.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(3)

    if json_mode:
        _emit_json(True, "service.health", data=health, port=resolved_port)
        return

    _cli.console.print(
        f"Ready: {_status_health_label(health, port_listening=True)}\n"
        f"Use `vaultspec-rag server status --port {resolved_port}` for "
        "service state and next actions.",
        markup=False,
        highlight=False,
    )


@server_app.command(
    "status",
    help=(
        "Show the human operator summary for service state, readiness, work, "
        "and next checks."
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
                "Emit one full-fidelity JSON envelope to stdout instead of the "
                "plain human summary. Preserves exit codes 0 (running) / 3 (stopped) "
                "/ 4 (crashed-* or divergent)."
            ),
        ),
    ] = False,
    verbose: Annotated[
        bool,
        typer.Option(
            "--verbose",
            help=(
                "Show process, heartbeat, token, model, and backend diagnostic "
                "rows in the human output."
            ),
        ),
    ] = False,
) -> None:
    """Display the current status of the background RAG service.

    Gathers four signals before rendering - ``service.json`` present,
    PID alive, port listening, heartbeat fresh - and surfaces each as
    its own row plus a derived ``State`` row. Avoids the previous
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
            _print_detail_line("Service file", "missing")
            _print_detail_line("State", "stopped")
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
        "Pre-download GPU model files to the HuggingFace cache. "
        "Run once before the first index to avoid model-download latency at "
        "search time. "
        "See the indexing architecture guide: docs/indexing.md"
    ),
)
def service_warmup() -> None:
    """Pre-download GPU model files to the HuggingFace cache."""
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
