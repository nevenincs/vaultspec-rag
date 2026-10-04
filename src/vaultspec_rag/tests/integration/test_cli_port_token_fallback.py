"""Explicit-port clients resolve protected discovery without public token recovery."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..._machine_lock import (
    acquire_machine_lock_lease,
    publish_machine_discovery,
    release_machine_lock_lease,
)
from ...serviceclient._discovery import read_service_status
from ...serviceclient._transport import _do_http_call
from .._production_service import production_service

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("status_token", [None, "stale-token"])
def test_explicit_port_uses_the_protected_machine_pointer(
    isolated_status_dir: Path, status_token: str | None
) -> None:
    with production_service(isolated_status_dir) as service:
        payload = read_service_status()
        assert payload is not None
        lease, _ = acquire_machine_lock_lease()
        assert lease is not None
        try:
            publish_machine_discovery(lease, payload)
            if status_token is None:
                (isolated_status_dir / "service.json").unlink()
            else:
                from ...serviceclient._discovery import _merge_service_status

                _merge_service_status({"service_token": status_token})
            result = _do_http_call(service.port, "/jobs", None)
            assert result is not None and "jobs" in result
        finally:
            release_machine_lock_lease(lease)


def test_explicit_port_without_discovery_cannot_bootstrap_from_health(
    isolated_status_dir: Path,
) -> None:
    with production_service(isolated_status_dir) as service:
        (isolated_status_dir / "service.json").unlink()
        result = _do_http_call(service.port, "/jobs", None)
        assert result is not None and result["error"] == "unauthorized"
        public = _do_http_call(service.port, "/health", None)
        assert public is not None and "service_token" not in public
