"""``server logs``: inspect bounded managed logs live or offline.

The command preserves the production managed-log contract across adapters. It
uses the authenticated JSON route while the daemon is reachable and falls back
to the same reader, filter, and tail helpers for retained local files.
"""

from __future__ import annotations

import sys
from typing import Annotated, Literal, cast

import typer

import vaultspec_rag.cli as _cli

from ..logging_config import ManagedLogGroup, ManagedLogSource, read_managed_logs
from ..server._routes_logs import (
    _DEFAULT_LOG_LINES,
    _MAX_LOG_LINES,
    _clamp_lines,
    _filter_log_groups,
    _managed_log_payload,
    _render_plain_log_groups,
    _tail_log_groups,
)
from ._app import server_app
from ._http_search import _try_http_admin
from ._render import _emit_json, _emit_json_error_and_exit
from ._service_status import _default_service_port

_LOGS_COMMAND = "server.logs"


def _cli_log_filters(
    *,
    job_id: str | None,
    contains: str | None,
) -> dict[str, str]:
    """Return the non-empty, trimmed filters forwarded by the CLI adapter."""
    filters: dict[str, str] = {}
    if job_id and job_id.strip():
        filters["job_id"] = job_id.strip()
    if contains and contains.strip():
        filters["contains"] = contains.strip()
    return filters


def _group_source(raw: object) -> Literal["service", "qdrant"] | None:
    """Narrow an untyped transport value to a concrete managed source."""
    if raw == "service":
        return "service"
    if raw == "qdrant":
        return "qdrant"
    return None


def _local_log_payload(
    *,
    lines: int,
    source: ManagedLogSource,
    filters: dict[str, str],
) -> dict[str, object]:
    """Read and shape retained logs through the production contract."""
    limit = _clamp_lines(str(lines))
    read_limit = _MAX_LOG_LINES if filters else limit
    groups = read_managed_logs(read_limit, source=source)
    if filters:
        groups = _filter_log_groups(groups, **filters)
    groups = _tail_log_groups(groups, limit)
    return _managed_log_payload(
        source=source,
        limit=limit,
        groups=groups,
        filters=filters,
    )


def _payload_groups(
    payload: dict[str, object],
    *,
    source: ManagedLogSource,
    limit: int,
    filters: dict[str, str],
) -> list[ManagedLogGroup] | None:
    """Validate and return groups from a live managed-log payload."""
    if payload.get("source") != source or payload.get("limit") != limit:
        return None
    if payload.get("filters") != filters:
        return None
    raw_groups = payload.get("groups")
    if not isinstance(raw_groups, list):
        return None

    groups: list[ManagedLogGroup] = []
    for raw_group in cast("list[object]", raw_groups):
        if not isinstance(raw_group, dict):
            return None
        group_data = cast("dict[str, object]", raw_group)
        raw_source = _group_source(group_data.get("source"))
        raw_lines = group_data.get("lines")
        if raw_source is None or not isinstance(raw_lines, list):
            return None
        if any(not isinstance(line, str) for line in cast("list[object]", raw_lines)):
            return None
        groups.append(
            {
                "source": raw_source,
                "lines": cast("list[str]", raw_lines),
            }
        )

    expected_sources = ["service", "qdrant"] if source == "all" else [source]
    if [group["source"] for group in groups] != expected_sources:
        return None
    return groups


def _exit_live_log_error(
    result: dict[str, object],
    *,
    json_mode: bool,
) -> None:
    """Render a live service error without replacing it with local output."""
    error = str(result.get("error") or "service_error")
    message = str(result.get("message") or "The service could not read managed logs.")
    if json_mode:
        _emit_json_error_and_exit(_LOGS_COMMAND, error, message, 1)
    _cli.console.print(f"Logs: {message}", markup=False, highlight=False)
    raise typer.Exit(1)


def _render_log_groups(groups: list[ManagedLogGroup]) -> None:
    """Write labeled raw groups without Rich markup or record rewriting."""
    rendered = _render_plain_log_groups(groups)
    if rendered:
        sys.stdout.write(rendered)
        sys.stdout.write("\n")
        sys.stdout.flush()


@server_app.command("logs")
def service_logs(
    lines: Annotated[
        int,
        typer.Option(
            "--limit",
            help="Maximum recent lines returned per selected source.",
        ),
    ] = _DEFAULT_LOG_LINES,
    source: Annotated[
        Literal["service", "qdrant", "all"],
        typer.Option(
            "--source",
            help="Managed log source: service, qdrant, or all.",
        ),
    ] = "all",
    job_id: Annotated[
        str | None,
        typer.Option("--job-id", help="Keep lines containing this job ID."),
    ] = None,
    contains: Annotated[
        str | None,
        typer.Option("--contains", help="Keep lines containing this text."),
    ] = None,
    port: Annotated[
        int | None,
        typer.Option(
            "--port",
            help="Use this live service port before reading retained local logs.",
        ),
    ] = None,
    json_mode: Annotated[
        bool,
        typer.Option("--json", help="Emit JSON for scripts instead of human text."),
    ] = False,
) -> None:
    """Show grouped raw service and Qdrant logs live or offline."""
    filters = _cli_log_filters(job_id=job_id, contains=contains)
    limit = _clamp_lines(str(lines))
    resolved_port = port if port is not None else _default_service_port()
    result: dict[str, object] | None = None
    if resolved_port is not None:
        result = _try_http_admin(
            "get_logs",
            {"lines": lines, "source": source, **filters},
            resolved_port,
        )

    if result is None:
        payload = _local_log_payload(lines=lines, source=source, filters=filters)
        groups = cast("list[ManagedLogGroup]", payload["groups"])
    else:
        if result.get("ok") is False:
            _exit_live_log_error(result, json_mode=json_mode)
            return
        groups = _payload_groups(
            result,
            source=source,
            limit=limit,
            filters=filters,
        )
        if groups is None:
            _exit_live_log_error(
                {
                    "error": "unexpected_response",
                    "message": "The service returned an invalid managed-log response.",
                },
                json_mode=json_mode,
            )
            return
        payload = result

    if json_mode:
        _emit_json(True, _LOGS_COMMAND, data=payload)
        return
    _render_log_groups(groups)
