"""Bearer/query-token gating shared by every monitoring and control route.

The per-process ``service_token`` is a pragmatic monitoring gate, not an auth
boundary - the real boundary is the loopback-only HTTP bind. Every route
handler across the route modules calls :func:`require_token` first and
returns its 401 response unchanged when gating fails.
"""

from __future__ import annotations

import hmac
from typing import TYPE_CHECKING

from starlette.responses import JSONResponse

from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from starlette.requests import Request

__all__ = ["require_token"]


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

    The token comes from the immutable runtime installed on the current
    HTTP application. The presented token is compared in constant time
    (:func:`hmac.compare_digest`).

    Args:
        request: The incoming Starlette request.

    Returns:
        ``None`` when the token matches (caller proceeds), or a
        ``JSONResponse`` with HTTP 401 when the token is missing or
        wrong (caller must return it).
    """
    expected = get_request_runtime(request).token
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
