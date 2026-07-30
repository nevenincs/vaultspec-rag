"""Guard test: the ``device_load`` block is published on the health payload.

The reading itself - projection and absent-not-raised behaviour - is a single
shared implementation guarded once in ``test_gpu_admission.py``. This is the
one property specific to this surface: that ``/health`` actually publishes
it.
"""

from __future__ import annotations

from typing import cast

import pytest

from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry

pytestmark = [pytest.mark.unit]


def test_health_payload_carries_the_device_load_key() -> None:
    """The wire-level guard: ``/health`` must publish the block at all.

    Mutation: removed the ``"device_load": device_load_reading()`` entry from
    the ``health_handler`` response body. Observed this assertion fail on
    ``"device_load" in data``.
    """
    from starlette.testclient import TestClient

    app = create_http_app(
        ServerRouteRuntime(
            token="lifespan-device-load-test-token",
            registry=ServiceRegistry(),
            port=8765,
        ),
        lifespan=None,
    )
    data = cast("dict[str, object]", TestClient(app).get("/health").json())

    assert "device_load" in data
