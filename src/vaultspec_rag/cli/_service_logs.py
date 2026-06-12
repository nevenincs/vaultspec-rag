"""``server logs``: show recent service activity.

Calls the logs admin endpoint through the shared HTTP admin client and
renders a compact operator activity feed by default. Raw log access is
kept behind ``--raw`` and ``--json`` remains the script-facing format.
Service-not-running yields exit code 3.
"""

from __future__ import annotations

import re
import sys
from typing import Annotated, cast

import typer

import vaultspec_rag.cli as _cli

from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port

_LOG_LINE_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}) "
    r"(?P<clock>\d{2}:\d{2}:\d{2})(?:,\d+)?\s+"
    r"(?P<level>\S+)\s+"
    r"(?P<logger>[^:]+):\s+"
    r"(?P<message>.*)$"
)
_FIELD_RE = re.compile(
    r"(?P<key>[A-Za-z_][\w.-]*)=(?P<value>.*?)(?=\s+[A-Za-z_][\w.-]*=|$)"
)
_ACCESS_RE = re.compile(
    r'"(?P<method>[A-Z]+)\s+(?P<path>[^ ]+)\s+HTTP/[^"]+"\s+(?P<status>\d{3})'
)
_STORE_UPDATE_RE = re.compile(
    r"^(?P<verb>Upserted|Deleted)\s+"
    r"(?P<count>\d+)\s+"
    r"(?P<kind>document|vault chunk|codebase chunk|code chunk)\(s\)$"
)


def _log_parts(raw: str) -> dict[str, str]:
    match = _LOG_LINE_RE.match(raw)
    if match is None:
        return {
            "clock": "??:??:??",
            "level": "",
            "logger": "",
            "message": raw,
            "timestamped": "",
        }
    parts = match.groupdict()
    parts["timestamped"] = "1"
    return parts


def _structured_fields(message: str) -> dict[str, str] | None:
    marker = "service.lifecycle "
    if marker not in message:
        return None
    _, _, tail = message.partition(marker)
    fields = {
        match.group("key"): match.group("value").strip()
        for match in _FIELD_RE.finditer(tail)
    }
    return fields or None


def _project_label(raw: str | None) -> str | None:
    if not raw:
        return None
    parts = raw.replace("\\", "/").rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else raw


def _format_duration(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return raw
    if seconds < 10:
        return f"{seconds:.2f}s"
    if seconds < 100:
        return f"{seconds:.1f}s"
    return f"{seconds:.0f}s"


def _result_count(raw: str | None) -> str | None:
    if raw is None:
        return None
    try:
        count = int(raw)
    except ValueError:
        return f"{raw} results"
    noun = "result" if count == 1 else "results"
    return f"{count} {noun}"


def _short_id(raw: str | None) -> str | None:
    if not raw:
        return None
    return raw[:8] if len(raw) > 8 else raw


def _compact_detail(key: str, value: str | None) -> str | None:
    if value in (None, ""):
        return None
    return f"{key} {value}"


def _join_row(parts: list[str | None]) -> str:
    return " ".join(part for part in parts if part)


def _activity_search(clock: str, fields: dict[str, str]) -> str:
    search_type = fields.get("search_type") or fields.get("type") or "search"
    return _join_row(
        [
            clock,
            "search",
            search_type,
            _result_count(fields.get("results")),
            _format_duration(fields.get("total_seconds")),
            _project_label(fields.get("root") or fields.get("project_root")),
            _compact_detail("request", _short_id(fields.get("request_id"))),
        ]
    )


def _activity_startup(clock: str, fields: dict[str, str]) -> str:
    return _join_row(
        [clock, "service", "started", _compact_detail("process", fields.get("pid"))]
    )


def _activity_shutdown(clock: str, fields: dict[str, str]) -> str:
    return _join_row(
        [
            clock,
            "service",
            "stopped",
            _compact_detail("reason", fields.get("reason")),
            _compact_detail("process", fields.get("pid")),
        ]
    )


def _activity_cleanup_failed(clock: str, fields: dict[str, str]) -> str:
    return _join_row(
        [
            clock,
            "service",
            "cleanup failed",
            _compact_detail("error", fields.get("error")),
        ]
    )


def _activity_generic(clock: str, event: str, fields: dict[str, str]) -> str:
    row_parts = [clock, "service", event.replace("_", " ")]
    for key in ("job_id", "request_id", "root", "project_root", "reason", "error"):
        value = fields.get(key)
        if key in ("root", "project_root"):
            value = _project_label(value)
            key = "project"
        elif key in ("request_id",):
            key = "request"
            value = _short_id(value)
        elif key == "job_id":
            key = "job"
            value = _short_id(value)
        rendered = _compact_detail(key, value)
        if rendered:
            row_parts.append(rendered)
    return " ".join(row_parts)


def _activity_from_lifecycle(parts: dict[str, str], fields: dict[str, str]) -> str:
    clock = parts["clock"]
    event = fields.get("event", "activity")
    if event == "search":
        return _activity_search(clock, fields)
    if event == "startup":
        return _activity_startup(clock, fields)
    if event == "shutdown":
        return _activity_shutdown(clock, fields)
    if event in ("heartbeat_failed", "heartbeat_initial_failed"):
        return f"{clock} service heartbeat failed"
    if event == "cleanup_failed":
        return _activity_cleanup_failed(clock, fields)
    return _activity_generic(clock, event, fields)


def _activity_from_access(parts: dict[str, str]) -> tuple[str, str] | None:
    match = _ACCESS_RE.search(parts["message"])
    if match is None:
        return None
    method = match.group("method")
    path = match.group("path").split("?", 1)[0]
    status = match.group("status")
    row = f"{parts['clock']} http {method} {path} {status}"
    return row, f"{method} {path}"


def _activity_from_store_update(parts: dict[str, str]) -> str | None:
    if parts["logger"] != "vaultspec_rag.store":
        return None
    match = _STORE_UPDATE_RE.match(parts["message"])
    if match is None:
        return None
    verb = "updated" if match.group("verb") == "Upserted" else "removed"
    count = match.group("count")
    kind = match.group("kind")
    if kind in ("codebase chunk", "code chunk"):
        noun = "source code section" if count == "1" else "source code sections"
    elif kind == "document":
        noun = "doc" if count == "1" else "docs"
    else:
        noun = f"{kind}s"
    return f"{parts['clock']} index {verb} {count} {noun}"


def _activity_from_unstructured(parts: dict[str, str]) -> str | None:
    store_update = _activity_from_store_update(parts)
    if store_update is not None:
        return store_update
    level = parts["level"].lower()
    if level not in ("warning", "error", "critical"):
        return None
    logger_name = parts["logger"].rsplit(".", 1)[-1] or "service"
    return (
        f"{parts['clock']} {level} {logger_name}; run with --raw for original log line"
    )


def _activity_feed_lines(log_lines: list[object]) -> list[str]:
    activities: list[tuple[str | None, str]] = []
    saw_lifecycle_search = False
    for raw_line in log_lines:
        parts = _log_parts(str(raw_line))
        if not parts["timestamped"]:
            continue
        fields = _structured_fields(parts["message"])
        if fields is not None:
            if fields.get("event") == "search":
                saw_lifecycle_search = True
            activities.append((None, _activity_from_lifecycle(parts, fields)))
            continue
        access = _activity_from_access(parts)
        if access is not None:
            row, key = access
            activities.append((key, row))
            continue
        unstructured = _activity_from_unstructured(parts)
        if unstructured:
            activities.append((None, unstructured))

    if saw_lifecycle_search:
        activities = [
            (key, row)
            for key, row in activities
            if key not in ("POST /search", "GET /search")
        ]

    deduped: list[str] = []
    seen: set[str] = set()
    for _key, row in activities:
        if row in seen:
            continue
        seen.add(row)
        deduped.append(row)
    return deduped


def _render_raw_lines(log_lines: list[object]) -> None:
    for line in log_lines:
        sys.stdout.write(f"{line}\n")
    sys.stdout.flush()


def _command_value(value: object) -> str:
    text = str(value)
    if re.fullmatch(r"[A-Za-z0-9_.:/\\-]+", text):
        return text
    return '"' + text.replace('"', '\\"') + '"'


def _raw_logs_command(
    *,
    port: int,
    lines: int,
    job_id: str | None,
    contains: str | None,
) -> str:
    parts = [
        "vaultspec-rag",
        "server",
        "logs",
        "--raw",
        "--limit",
        str(lines),
        "--port",
        str(port),
    ]
    if job_id:
        parts.extend(["--job-id", _command_value(job_id)])
    if contains:
        parts.extend(["--contains", _command_value(contains)])
    return " ".join(parts)


def _render_no_activity_hint(
    port: int,
    *,
    lines: int,
    job_id: str | None,
    contains: str | None,
) -> None:
    filters: list[str] = []
    if job_id:
        filters.append(f"job {_short_id(job_id)}")
    if contains:
        filters.append(f'text "{contains}"')
    scope = f" matching {' and '.join(filters)}" if filters else ""
    _cli.console.print(
        f"Service is reachable at http://127.0.0.1:{port}.",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    _cli.console.print(
        f"No service activity{scope} was found in the last {lines} log lines.",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    _cli.console.print("Try:", markup=False, highlight=False, soft_wrap=True)
    _cli.console.print(
        f"  vaultspec-rag server jobs --running --port {port}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    _cli.console.print(
        f"  vaultspec-rag server status --port {port}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )
    raw_command = _raw_logs_command(
        port=port,
        lines=lines,
        job_id=job_id,
        contains=contains,
    )
    _cli.console.print(
        f"  {raw_command}",
        markup=False,
        highlight=False,
        soft_wrap=True,
    )


def _render_activity_feed(
    log_lines: list[object],
    *,
    port: int,
    lines: int,
    job_id: str | None,
    contains: str | None,
) -> None:
    activity_lines = _activity_feed_lines(log_lines)
    if not activity_lines:
        _render_no_activity_hint(port, lines=lines, job_id=job_id, contains=contains)
        return
    for line in activity_lines:
        _cli.console.print(line, markup=False, highlight=False, soft_wrap=True)


@server_app.command("logs")
def service_logs(
    lines: Annotated[
        int,
        typer.Option(
            "--limit",
            "--lines",
            help="Number of recent service log lines to inspect.",
        ),
    ] = 200,
    job_id: Annotated[
        str | None,
        typer.Option("--job-id", help="Only inspect log lines for this job ID."),
    ] = None,
    contains: Annotated[
        str | None,
        typer.Option("--contains", help="Only inspect log lines containing this text."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option("--port", help="Service port (defaults to running service)."),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
    raw: Annotated[
        bool,
        typer.Option("--raw", help="Show original log lines."),
    ] = False,
) -> None:
    """Show recent activity from the running service log."""
    resolved_port = port if port is not None else _default_service_port()
    if resolved_port is None:
        if json_mode:
            _emit_json_error_and_exit(
                "service.logs",
                "service_not_running",
                "Service is not running. Start it with `vaultspec-rag server start`.",
                3,
            )
        _cli.console.print(
            "Service is not running. Start it with `vaultspec-rag server start`.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(3)
    args: dict[str, object] = {"lines": lines}
    if job_id:
        args["job_id"] = job_id
    if contains:
        args["contains"] = contains
    result = _try_http_admin("get_logs", args, resolved_port)
    if result is None:
        if json_mode:
            _emit_json_error_and_exit(
                "service.logs",
                "service_not_running",
                "Service is not running. Start it with `vaultspec-rag server start`.",
                3,
            )
        _cli.console.print(
            "Service is not running. Start it with `vaultspec-rag server start`.",
            markup=False,
            highlight=False,
        )
        raise typer.Exit(3)

    if json_mode:
        _emit_json(True, "service.logs", data=result)
        return

    raw_lines = result.get("lines")
    log_lines: list[object] = (
        cast("list[object]", raw_lines) if isinstance(raw_lines, list) else []
    )
    if not log_lines:
        _render_no_activity_hint(
            resolved_port,
            lines=lines,
            job_id=job_id,
            contains=contains,
        )
        return
    if raw:
        _render_raw_lines(log_lines)
        return
    _render_activity_feed(
        log_lines,
        port=resolved_port,
        lines=lines,
        job_id=job_id,
        contains=contains,
    )
