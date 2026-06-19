"""Integration tests for the CLI ``--port`` health-token auth fallback.

A CLI invocation that points ``--port`` at a service started out-of-band (under
a different status directory, or after a restart that rotated the token) has no
usable ``service_token`` in its local status file. The client must then read the
live token from the target port's ungated ``/health`` so token-gated routes
authenticate. These tests spawn a real service and drive the real HTTP client
helper against the real token gate - no mocks, patches, or skips.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, cast

import pytest

from ...cli import _spawn_service, _terminate_pid
from ...cli._http_search import _do_http_call
from ...cli._service_status import _status_file
from ._helpers import (
    _get_ephemeral_port,
    _poll_health,
    _service_env,
    _wait_for_exit,
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]

# Local-only keeps the test focused on the HTTP auth path: token gating is
# backend-independent, so there is no need to provision the Qdrant server.
_LOCAL_ONLY = {"VAULTSPEC_RAG_LOCAL_ONLY": "1"}


@pytest.mark.subprocess_gpu
def test_jobs_via_port_authenticates_via_health_when_status_token_absent(
    tmp_path: Path,
) -> None:
    """With no local status file, a gated route authenticates via /health.

    Reproduces the reported cross-process case: the service is up on the port,
    but the CLI's status directory has no ``service.json`` (it was written
    elsewhere), so the only source of the token is the live ``/health``.
    """
    with _service_env(tmp_path, _LOCAL_ONLY):
        port = _get_ephemeral_port()
        pid = _spawn_service(port, tmp_path / "service.log")
        try:
            _poll_health(port)
            # Drop the status file so the client has no token to send.
            sf = _status_file()
            if sf.exists():
                sf.unlink()

            res = _do_http_call(port, "/jobs", None)
            assert isinstance(res, dict)
            assert res.get("error") != "unauthorized", res
            assert res.get("ok") is not False, res
            # Authenticated /jobs returns the activity snapshot.
            assert "jobs" in res or "summary" in res or "returned" in res, res
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)


@pytest.mark.subprocess_gpu
def test_jobs_via_port_refreshes_stale_status_token_from_health(
    tmp_path: Path,
) -> None:
    """A stale status-file token (post-restart rotation) is refreshed on 401.

    The first request carries the wrong token and is rejected; the client must
    refetch the live token from ``/health`` and retry once, transparently.
    """
    with _service_env(tmp_path, _LOCAL_ONLY):
        port = _get_ephemeral_port()
        pid = _spawn_service(port, tmp_path / "service.log")
        try:
            _poll_health(port)
            # Corrupt the persisted token so it no longer matches the running
            # service; pid/port stay valid so the status read still resolves.
            sf = _status_file()
            raw = sf.read_text(encoding="utf-8") if sf.exists() else "{}"
            data: dict[str, object] = cast("dict[str, object]", json.loads(raw))
            data.setdefault("pid", pid)
            data.setdefault("port", port)
            data["service_token"] = "stale-wrong-token-deadbeefdeadbeef"
            sf.write_text(json.dumps(data), encoding="utf-8")

            res = _do_http_call(port, "/jobs", None)
            assert isinstance(res, dict)
            assert res.get("error") != "unauthorized", res
            assert res.get("ok") is not False, res
            assert "jobs" in res or "summary" in res or "returned" in res, res
        finally:
            _terminate_pid(pid)
            _wait_for_exit(pid)
