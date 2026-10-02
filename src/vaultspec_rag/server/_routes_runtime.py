"""Authenticated projections of service-owned resource observations."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync
from starlette.responses import JSONResponse

from ..concurrency import limiter_stats
from ..runtime_observations import DEFAULT_OBSERVED_CLIENTS, runtime_observations
from ._auth import require_token
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from starlette.requests import Request


async def runtime_observations_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    raw_limit = request.query_params.get("client_limit")
    try:
        limit = int(raw_limit) if raw_limit is not None else DEFAULT_OBSERVED_CLIENTS
    except ValueError:
        return JSONResponse(
            {
                "ok": False,
                "error": "invalid_client_limit",
                "message": "client_limit must be an integer",
            },
            status_code=400,
        )
    observation = await run_sync(
        partial(
            runtime_observations,
            port=get_request_runtime(request).port,
            client_limit=limit,
        )
    )
    observation["models"] = get_request_runtime(request).registry.model_observation()
    observation["quiesce"] = (
        get_request_runtime(request).registry.quiesce_snapshot().as_envelope()
    )
    observation["pools"] = limiter_stats()
    return JSONResponse(observation)
