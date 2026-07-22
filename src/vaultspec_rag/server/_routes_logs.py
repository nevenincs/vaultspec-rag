"""HTTP request parsing for the service-domain managed-log contract."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from starlette.requests import Request

__all__ = [
    "_log_filters_from_request",
]


def _log_filters_from_request(request: Request) -> dict[str, str]:
    filters: dict[str, str] = {}
    job_id = request.query_params.get("job_id")
    contains = request.query_params.get("contains")
    if job_id and job_id.strip():
        filters["job_id"] = job_id.strip()
    if contains and contains.strip():
        filters["contains"] = contains.strip()
    return filters
