"""Real transport coverage for the non-authorizing service preflight CLI."""

from __future__ import annotations

import contextlib
import os
import threading
import time
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import uvicorn
from typer.testing import CliRunner

from ..cli import app
from ..config._paths import SERVICE_STATUS_FILENAME
from ..service import ServiceRegistry
from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
from ..serviceclient._discovery import (
    HEARTBEAT_STALENESS_SECONDS,
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
    _replace_service_status,
)
from ..serviceclient._transport import _try_http_admin
from ._import_probe import assert_fresh_import_excludes, import_probe_source
from ._ports import free_loopback_port

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_SERVICE_TOKEN = "service-preflight-route-token"
runner = CliRunner()


def _publish_discovery(
    status_dir: Path,
    *,
    port: int,
    heartbeat: str | None = None,
) -> None:
    """Publish the real route host through the production discovery writer."""
    _replace_service_status(
        {
            "pid": os.getpid(),
            "port": port,
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            "service_token": _SERVICE_TOKEN,
            "last_heartbeat": heartbeat
            or datetime.now(UTC).isoformat(timespec="seconds"),
            "stale_after_s": HEARTBEAT_STALENESS_SECONDS,
        },
        path=status_dir / SERVICE_STATUS_FILENAME,
    )


@contextlib.contextmanager
def _production_service(status_dir: Path) -> Generator[tuple[ServiceRegistry, int]]:
    """Serve the real authenticated route table without the daemon lifespan."""
    from ..server import ServerRouteRuntime, create_http_app

    registry = ServiceRegistry()
    port = free_loopback_port()
    server = uvicorn.Server(
        uvicorn.Config(
            create_http_app(
                ServerRouteRuntime(
                    token=_SERVICE_TOKEN,
                    registry=registry,
                    port=port,
                ),
                lifespan=None,
            ),
            host="127.0.0.1",
            port=port,
            log_config=None,
            access_log=False,
            lifespan="off",
        )
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5.0
        while not server.started and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        _publish_discovery(status_dir, port=port)
        yield registry, port
    finally:
        _try_http_admin("resume_service", {}, port)
        server.should_exit = True
        thread.join(timeout=5)
        assert not thread.is_alive()


def test_preflight_observes_safe_service_but_never_authorizes_gpu(
    isolated_status_dir: Path,
) -> None:
    """A safe remote snapshot succeeds only as an observation, never a grant."""
    with _production_service(isolated_status_dir) as (_registry, port):
        pause = _try_http_admin("pause_service", {}, port)
        assert pause is not None, "the real pause route did not answer"
        assert pause["status"] == "quiesced", pause
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 0, result.output
    assert len(result.output.splitlines()) == 1, result.output
    assert '"ok": true' in result.output
    assert '"source": "service"' in result.output
    assert f'"port": {port}' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output
    assert (
        '"authorization": "A borrower lease is required before GPU work may begin."'
        in result.output
    )
    assert '"state": "quiesced"' in result.output
    assert '"safe_to_borrow_gpu": true' in result.output
    assert '"capacity": {' in result.output


def test_preflight_refuses_a_discovered_service_that_is_not_safe(
    isolated_status_dir: Path,
) -> None:
    """Running is observable, but only acknowledged quiescence is safe."""
    with _production_service(isolated_status_dir) as (_registry, _port):
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"ok": false' in result.output
    assert '"error": "service_not_safe_to_borrow_gpu"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_stale_discovery_without_a_local_fallback(
    isolated_status_dir: Path,
) -> None:
    """A stale discovery record fails before any remote observation is trusted."""
    with _production_service(isolated_status_dir) as (_registry, port):
        _publish_discovery(
            isolated_status_dir,
            port=port,
            heartbeat=(
                datetime.now(UTC) - timedelta(seconds=HEARTBEAT_STALENESS_SECONDS + 5)
            ).isoformat(timespec="seconds"),
        )
        result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_stale"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


def test_preflight_refuses_when_no_service_is_discovered(
    isolated_status_dir: Path,
) -> None:
    """A missing service is never replaced with a local device probe."""
    del isolated_status_dir
    result = runner.invoke(app, ["server", "preflight", "--json"])

    assert result.exit_code == 1, result.output
    assert '"error": "service_discovery_unavailable"' in result.output
    assert '"authorized": false' in result.output
    assert '"lease_required": true' in result.output


class TestTorchFreedom:
    """The CLI observation surface must remain torch-free on import."""

    def test_importing_the_verb_loads_no_torch(self) -> None:
        assert_fresh_import_excludes(
            import_probe_source("vaultspec_rag.cli._service_preflight")
        )
