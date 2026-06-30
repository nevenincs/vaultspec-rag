"""End-to-end tests for the read-only storage survey service surface.

Drives the real background service (server mode) and asserts the survey
flows through three consistent surfaces: the daemon's ``/storage/survey``
route, the MCP ``survey_storage`` tool, and the service-first CLI path.
This is the one read-only storage surface the service owns; the
destructive prune / delete / migrate verbs stay CLI-direct and are not
exposed here. No GPU work runs in the survey itself - it is pure storage
classification against the managed server and the persisted manifest.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ...serviceclient import _do_http_call, _try_http_admin

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.subprocess_gpu]


@pytest.mark.usefixtures("live_service")
def test_storage_survey_route_returns_bounded_envelope(
    live_service: tuple[int, Path],
) -> None:
    """The ``/storage/survey`` route answers with the bounded survey envelope.

    A freshly started service has no indexed roots, so the survey is empty,
    but the envelope (namespaces / returned / total / limit) must be shaped
    and bounded regardless.
    """
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey", None)
    assert result is not None
    assert isinstance(result.get("namespaces"), list)
    assert "returned" in result
    assert "total" in result
    limit = result.get("limit")
    assert isinstance(limit, int)
    assert limit > 0


@pytest.mark.usefixtures("live_service")
def test_storage_survey_route_rejects_bad_status(
    live_service: tuple[int, Path],
) -> None:
    """An unknown ``?status=`` value is a 400, not a silent empty survey."""
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey?status=bogus", None)
    assert result is not None
    assert result.get("ok") is False
    assert result.get("error") == "bad_request"


@pytest.mark.usefixtures("live_service")
def test_storage_survey_route_honours_limit(
    live_service: tuple[int, Path],
) -> None:
    """A ``?limit=`` is echoed and clamped into the response envelope."""
    port, _status_dir = live_service
    result = _do_http_call(port, "/storage/survey?limit=5", None)
    assert result is not None
    assert result.get("limit") == 5


@pytest.mark.usefixtures("live_service")
def test_admin_client_maps_storage_survey_filters(
    live_service: tuple[int, Path],
) -> None:
    """The admin client maps status + limit filters onto the survey route."""
    port, _status_dir = live_service
    result = _try_http_admin(
        "get_storage_survey", {"status": "orphaned", "limit": 3}, port
    )
    assert result is not None
    # Filtered to orphaned (empty on a fresh service) but the envelope holds.
    assert result.get("limit") == 3
    assert isinstance(result.get("namespaces"), list)
