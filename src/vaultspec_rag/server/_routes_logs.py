"""Bounded log-tail shaping helpers for the ``/logs`` routes.

The ``?lines=`` clamp, the ``?job_id=``/``?contains=`` line filter, and the
request-to-filter extraction shared by the ``logs_route`` and ``logs_json_route``
handlers in :mod:`._routes`. Bounded-and-filterable operator-view semantics
(``operator-views-are-bounded``): the clamp caps the response window and the
filters search a bounded maximum window before returning the requested tail.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

__all__ = [
    "_DEFAULT_LOG_LINES",
    "_MAX_LOG_LINES",
    "_clamp_lines",
    "_filter_log_lines",
    "_log_filters_from_request",
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


def _filter_log_lines(
    lines: list[str],
    *,
    job_id: str | None = None,
    contains: str | None = None,
) -> list[str]:
    job_filter = job_id.strip().lower() if job_id else None
    contains_filter = contains.strip().lower() if contains else None
    if not job_filter and not contains_filter:
        return lines
    filtered: list[str] = []
    for line in lines:
        lowered = line.lower()
        if job_filter and job_filter not in lowered:
            continue
        if contains_filter and contains_filter not in lowered:
            continue
        filtered.append(line)
    return filtered


def _log_filters_from_request(request: Request) -> dict[str, str]:
    filters: dict[str, str] = {}
    job_id = request.query_params.get("job_id")
    contains = request.query_params.get("contains")
    if job_id and job_id.strip():
        filters["job_id"] = job_id.strip()
    if contains and contains.strip():
        filters["contains"] = contains.strip()
    return filters
