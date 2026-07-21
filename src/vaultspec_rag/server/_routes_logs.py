"""Bounded managed-log shaping shared by live and offline adapters.

The helpers preserve source groups and apply filters and tails independently to
each producer. They never merge service and Qdrant records or imply a shared
chronology. Both authenticated HTTP routes and the CLI's offline fallback use
this module so the output contract cannot drift between adapters.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

    from ..logging_config import ManagedLogGroup

__all__ = [
    "_DEFAULT_LOG_LINES",
    "_MAX_LOG_LINES",
    "_clamp_lines",
    "_filter_log_groups",
    "_log_filters_from_request",
    "_managed_log_payload",
    "_render_plain_log_groups",
    "_tail_log_groups",
]

# Default and clamp bounds for the ``?lines=`` query parameter.
_DEFAULT_LOG_LINES = 200
_MAX_LOG_LINES = 5_000


def _clamp_lines(raw: str | None) -> int:
    """Parse and clamp the ``?lines=`` query parameter.

    Non-integer or non-positive values fall back to the default; the
    value is clamped to ``_MAX_LOG_LINES`` to bound the response size.
    """
    if raw is None:
        return _DEFAULT_LOG_LINES
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _DEFAULT_LOG_LINES
    if value <= 0:
        return _DEFAULT_LOG_LINES
    return min(value, _MAX_LOG_LINES)


def _filter_log_groups(
    groups: list[ManagedLogGroup],
    *,
    job_id: str | None = None,
    contains: str | None = None,
) -> list[ManagedLogGroup]:
    """Apply case-insensitive AND filters independently within each group."""
    job_filter = job_id.strip().lower() if job_id else None
    contains_filter = contains.strip().lower() if contains else None
    if not job_filter and not contains_filter:
        return [
            {"source": group["source"], "lines": list(group["lines"])}
            for group in groups
        ]
    filtered_groups: list[ManagedLogGroup] = []
    for group in groups:
        filtered_lines: list[str] = []
        for line in group["lines"]:
            lowered = line.lower()
            if job_filter and job_filter not in lowered:
                continue
            if contains_filter and contains_filter not in lowered:
                continue
            filtered_lines.append(line)
        filtered_groups.append({"source": group["source"], "lines": filtered_lines})
    return filtered_groups


def _tail_log_groups(
    groups: list[ManagedLogGroup],
    lines: int,
) -> list[ManagedLogGroup]:
    """Take the final *lines* records independently from every source group."""
    limit = max(0, lines)
    return [
        {
            "source": group["source"],
            "lines": group["lines"][-limit:] if limit else [],
        }
        for group in groups
    ]


def _managed_log_payload(
    *,
    source: str,
    limit: int,
    groups: list[ManagedLogGroup],
    filters: dict[str, str],
) -> dict[str, object]:
    """Build the one grouped JSON outcome used live and offline."""
    return {
        "source": source,
        "limit": limit,
        "groups": groups,
        "filters": filters,
    }


def _render_plain_log_groups(groups: list[ManagedLogGroup]) -> str:
    """Render labeled source sections without altering record contents."""
    rendered: list[str] = []
    for group in groups:
        rendered.append(f"[{group['source']}]")
        rendered.extend(group["lines"])
    return "\n".join(rendered)


def _log_filters_from_request(request: Request) -> dict[str, str]:
    filters: dict[str, str] = {}
    job_id = request.query_params.get("job_id")
    contains = request.query_params.get("contains")
    if job_id and job_id.strip():
        filters["job_id"] = job_id.strip()
    if contains and contains.strip():
        filters["contains"] = contains.strip()
    return filters
