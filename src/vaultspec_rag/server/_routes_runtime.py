"""Authenticated projections of service-owned resource observations."""

from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync
from starlette.responses import JSONResponse

from ..concurrency import limiter_stats
from ..runtime_observations import runtime_observations
from ._auth import require_token
from ._runtime import get_request_runtime

if TYPE_CHECKING:
    from starlette.requests import Request


async def runtime_observations_route(request: Request) -> JSONResponse:
    denied = require_token(request)
    if denied is not None:
        return denied
    observation = await run_sync(
        partial(
            runtime_observations,
            port=get_request_runtime(request).port,
        )
    )
    observation["models"] = get_request_runtime(request).registry.model_observation()
    observation["quiesce"] = (
        get_request_runtime(request).registry.quiesce_snapshot().as_envelope()
    )
    observation["pools"] = limiter_stats()
    return JSONResponse(observation)
