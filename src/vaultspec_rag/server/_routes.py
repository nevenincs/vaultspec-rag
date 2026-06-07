"""Read-only HTTP routes for the resident service (#142, plan P03).

Per the ``service-observability`` ADR these routes are strictly
read-only - all control stays on MCP. They are registered as Starlette
:class:`~starlette.routing.Route` objects on the *inner* app assembled
in :mod:`._main` (alongside ``Mount("/mcp")`` + ``Route("/health")``),
never as additional ASGI wrappers.

Gating model (ADR Constraints). The HTTP service binds to loopback only
(``127.0.0.1``), which is the real boundary; on top of that these
monitoring routes accept the per-process ``service_token`` as an
optional bearer - via ``Authorization: Bearer <token>`` or a ``?token=``
query parameter - compared in constant time against
``_state._SERVICE_TOKEN``. This is a pragmatic monitoring gate, not an
auth boundary. ``/health`` stays ungated and is registered in
:mod:`._main`, not here.
"""

from __future__ import annotations

import hmac
import logging
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route

import vaultspec_rag.mcp_server as _m

from ..logging_config import read_service_log
from . import _jobs

if TYPE_CHECKING:
    from starlette.requests import Request

logger = logging.getLogger("vaultspec_rag.mcp_server")

# Default and clamp bounds for the ``?lines=`` query parameter.
_DEFAULT_LOG_LINES = 200
_MAX_LOG_LINES = 5_000


def _extract_token(request: Request) -> str | None:
    """Pull the presented token from the bearer header or ``?token=``.

    Prefers the ``Authorization: Bearer <token>`` header; falls back to
    the ``token`` query parameter. Returns ``None`` when neither is
    present.
    """
    auth = request.headers.get("authorization")
    if auth:
        scheme, _, value = auth.partition(" ")
        if scheme.lower() == "bearer" and value:
            return value
    query_token = request.query_params.get("token")
    if query_token:
        return query_token
    return None


def require_token(request: Request) -> JSONResponse | None:
    """Token-gate a request; return a 401 response when it fails.

    The live ``_state._SERVICE_TOKEN`` is read through the package alias
    so the value the lifespan generated at startup is observed. The
    presented token is compared in constant time
    (:func:`hmac.compare_digest`).

    Args:
        request: The incoming Starlette request.

    Returns:
        ``None`` when the token matches (caller proceeds), or a
        ``JSONResponse`` with HTTP 401 when the token is missing or
        wrong (caller must return it).
    """
    expected = _m._SERVICE_TOKEN
    presented = _extract_token(request)
    if expected and presented is not None and hmac.compare_digest(presented, expected):
        return None
    return JSONResponse(
        {
            "ok": False,
            "error": "unauthorized",
            "message": (
                "This monitoring route requires the service_token via "
                "'Authorization: Bearer <token>' or '?token='."
            ),
        },
        status_code=401,
    )


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


async def logs_route(request: Request) -> PlainTextResponse | JSONResponse:
    """Token-gated read-only ``GET /logs`` returning recent log text.

    Returns the last ``?lines=N`` (default 200, clamped to 5000) lines
    of the rotated service log as ``text/plain``, newest last - parity
    with the ``get_logs`` MCP tool.

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``PlainTextResponse`` with the joined log lines, or the
        ``require_token`` 401 ``JSONResponse``.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    lines = _clamp_lines(request.query_params.get("lines"))
    body = "\n".join(read_service_log(lines))
    return PlainTextResponse(body)


def _clamp_limit(raw: str | None) -> int | None:
    """Parse the ``?limit=`` query parameter; ``None`` when absent/invalid.

    Returns ``None`` (no cap) when the parameter is missing or
    non-integer, so the full bounded snapshot is returned.
    """
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


async def jobs_route(request: Request) -> JSONResponse:
    """Token-gated read-only ``GET /jobs`` returning the activity snapshot.

    Returns the newest-first :mod:`._jobs` registry snapshot as JSON -
    parity with the ``get_jobs`` MCP tool. Read-only: it never mutates
    the registry. An optional ``?limit=N`` query parameter caps the
    number of returned records (newest first).

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``JSONResponse`` of ``{"jobs": [...]}`` , or the
        ``require_token`` 401 ``JSONResponse``.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    records = _jobs.snapshot()
    limit = _clamp_limit(request.query_params.get("limit"))
    if limit is not None:
        records = records[:limit] if limit > 0 else []
    return JSONResponse({"jobs": records})


async def metrics_route(request: Request) -> PlainTextResponse | JSONResponse:
    """Token-gated read-only ``GET /metrics`` in Prometheus text format.

    Emits the ``0.0.4`` text exposition format produced inline by
    :func:`~vaultspec_rag.mcp_server.render_prometheus` (counters/gauges
    incremented by the search/reindex tool paths; GPU memory read
    on-demand at scrape time). No background collector thread, no
    ``prometheus_client`` dependency. Read-only.

    Args:
        request: The incoming Starlette request.

    Returns:
        A ``PlainTextResponse`` with the Prometheus exposition text, or
        the ``require_token`` 401 ``JSONResponse``.
    """
    denied = require_token(request)
    if denied is not None:
        return denied
    return PlainTextResponse(
        _m.render_prometheus(),
        media_type="text/plain; version=0.0.4",
    )


# Routes mounted by ``_main`` on the inner Starlette app. Read-only only.
ROUTES: list[Route] = [
    Route("/logs", logs_route, methods=["GET"]),
    Route("/jobs", jobs_route, methods=["GET"]),
    Route("/metrics", metrics_route, methods=["GET"]),
]
