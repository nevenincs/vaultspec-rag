"""Pure label and duration formatting for the ``server status`` renderer.

Deterministic string producers extracted from ``_status_render``: they map raw
health/jobs signals to the operator-facing words (identity, network, model,
busy/queue/jobs) and format durations and timestamps. No console I/O and no
service probing - the renderer computes the signals and these turn them into
text, which keeps the render module focused on orchestration.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import cast

from ._cli_format import _counted_unit

__all__ = [
    "_format_started_label",
    "_format_status_duration",
    "_get_token_label",
    "_model_ready_label",
    "_network_label",
    "_plain_status_label",
    "_process_identity_label",
    "_status_busy_label",
    "_status_env_label",
    "_status_health_label",
    "_status_jobs_label",
    "_status_queue_label",
    "_status_uptime_label",
]


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


def _status_uptime_label(health: dict[str, object] | None) -> str:
    if not isinstance(health, dict):
        return "not reported by service"
    return _format_status_duration(health.get("uptime_s"))


def _status_env_label(health: dict[str, object] | None) -> str:
    """Return the daemon's python interpreter from /health, or a clear miss.

    The service runs in whatever interpreter launched ``server start`` (it does
    not provision its own python), so surfacing it makes the service<->env
    coupling visible at a glance.
    """
    if isinstance(health, dict):
        exe = health.get("executable")
        if isinstance(exe, str) and exe:
            return exe
    return "not reported by service"
