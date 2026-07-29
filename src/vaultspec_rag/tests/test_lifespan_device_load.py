"""Guard test: the ``device_load`` block is published on the health payload.

The reading itself - projection and absent-not-raised behaviour - is a single
shared implementation guarded once in ``test_gpu_admission.py``. This is the
one property specific to this surface: that ``/health`` actually publishes
it.
"""

from __future__ import annotations

import typing
from contextlib import asynccontextmanager
from typing import Any, cast

import pytest

from ..server._lifespan import health_handler

pytestmark = [pytest.mark.unit]


@asynccontextmanager
async def _empty_lifespan(_app: object) -> typing.AsyncGenerator[None]:
    yield


def test_health_payload_carries_the_device_load_key() -> None:
    """The wire-level guard: ``/health`` must publish the block at all.

    Mutation: removed the ``"device_load": device_load_reading()`` entry from
    the ``health_handler`` response body. Observed this assertion fail on
    ``"device_load" in data``.
    """
    from starlette.applications import Starlette
    from starlette.routing import Route
    from starlette.testclient import TestClient

    app = Starlette(routes=[Route("/health", health_handler)], lifespan=_empty_lifespan)
    client = cast("Any", TestClient(app))
    data = client.get("/health").json()

    assert "device_load" in data
