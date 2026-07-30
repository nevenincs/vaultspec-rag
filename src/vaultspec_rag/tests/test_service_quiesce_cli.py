"""Guard tests for real ``server pause`` / ``server resume`` route outcomes."""

from __future__ import annotations

import contextlib
import json
import os
import threading
import time
from typing import TYPE_CHECKING

import pytest
import uvicorn
from typer.testing import CliRunner

from ..cli import app
from ..config._types import EnvVar
from ..jobs import mapping
from ..server import ServerRouteRuntime, create_http_app
from ..service import ServiceRegistry
from ..service_quiesce import QuiesceState
from ..serviceclient._transport import _try_http_admin
from ._ports import free_loopback_port
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

    from typer.testing import Result

    from ..service_quiesce import ComputeTicket

pytestmark = [pytest.mark.unit]

runner = CliRunner()

_SERVICE_TOKEN = "quiesce-cli-route-token"
def _publish_service_discovery(status_dir: Path, *, port: int) -> None:
    """Publish the in-process route host with the production writer."""
    from ..config._paths import SERVICE_STATUS_FILENAME
    from ..serviceclient._compat import SERVICE_VERSION_FIELD, local_package_version
    from ..serviceclient._discovery import (
        SERVICE_DISCOVERY_SCHEMA,
        SERVICE_DISCOVERY_VERSION,
        _replace_service_status,
    )

    _replace_service_status(
        {
            "pid": os.getpid(),
            "port": port,
            "schema": SERVICE_DISCOVERY_SCHEMA,
            "version": SERVICE_DISCOVERY_VERSION,
            SERVICE_VERSION_FIELD: local_package_version(),
            "service_token": _SERVICE_TOKEN,
        },
        path=status_dir / SERVICE_STATUS_FILENAME,
    )


@contextlib.contextmanager
def _quiesce_service(tmp_path: Path) -> Generator[tuple[int, ServiceRegistry]]:
    """Serve real authenticated quiesce routes without the daemon lifespan."""
    status_dir = tmp_path / "status"
    registry = ServiceRegistry()
    port = free_loopback_port()
    route_server = uvicorn.Server(
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
    thread = threading.Thread(target=route_server.run, daemon=True)
    with managed_env(
        **{
            EnvVar.STATUS_DIR.value: str(status_dir),
            EnvVar.LOCAL_ONLY.value: "true",
        }
    ):
        thread.start()
        try:
            deadline = time.monotonic() + 5.0
            while not route_server.started and time.monotonic() < deadline:
                time.sleep(0.01)
            assert route_server.started
            _publish_service_discovery(status_dir, port=port)
            yield port, registry
        finally:
            _try_http_admin("resume_service", {}, port)
            route_server.should_exit = True
            thread.join(timeout=5)
            assert not thread.is_alive()


def _invoke(verb: str, port: int | None) -> Result:
    """Run one quiesce verb, passing the actual route port when it is up."""
    args = ["server", verb, "--json"]
    if port is not None:
        args += ["--port", str(port)]
    return runner.invoke(app, args)


def _json(result: Result) -> dict[str, object]:
    return mapping(json.loads(result.output))


def _data(result: Result) -> dict[str, object]:
    return mapping(_json(result).get("data"))


def _quiesce(data: dict[str, object]) -> dict[str, object]:
    return mapping(data.get("quiesce"))


def test_pause_change_is_success_exit_zero(tmp_path: Path) -> None:
    """A real pause transition is successful only after the route quiesces."""
    with _quiesce_service(tmp_path) as (port, _):
        result = _invoke("pause", port)

    assert result.exit_code == 0, result.output
    body = _json(result)
    data = _data(result)
    quiesce = _quiesce(data)
    assert body["ok"] is True
    assert data["ok"] is True
    assert data["status"] == "quiesced"
    assert quiesce["state"] == "quiesced"
    assert quiesce["vram_released"] is True
    assert quiesce["safe_to_borrow_gpu"] is True


def test_pause_already_paused_is_idempotent_success(tmp_path: Path) -> None:
    """A second real pause preserves the service's idempotent outcome."""
    with _quiesce_service(tmp_path) as (port, _):
        first = _invoke("pause", port)
        second = _invoke("pause", port)

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    assert _data(second)["status"] == "already_quiesced"
    assert _quiesce(_data(second))["state"] == "quiesced"


def test_resume_already_running_is_idempotent_success(tmp_path: Path) -> None:
    """A real resume from running remains a successful no-op."""
    with _quiesce_service(tmp_path) as (port, _):
        result = _invoke("resume", port)

    assert result.exit_code == 0, result.output
    assert _data(result)["status"] == "running"
    assert _quiesce(_data(result))["state"] == "running"


def _start_pause_held_by_a_real_ticket(
    port: int,
    registry: ServiceRegistry,
) -> tuple[ComputeTicket, threading.Thread, list[dict[str, object] | None]]:
    """Begin the real pause route while one admitted ticket keeps it pending."""
    ticket = registry.acquire_compute_ticket()
    outcomes: list[dict[str, object] | None] = []
    owner = threading.Thread(
        target=lambda: outcomes.append(_try_http_admin("pause_service", {}, port)),
        daemon=True,
    )
    owner.start()
    deadline = time.monotonic() + 2.0
    while registry.quiesce_snapshot().state is not QuiesceState.PAUSING:
        if time.monotonic() >= deadline:
            raise AssertionError("the real pause route did not enter pausing")
        time.sleep(0.01)
    return ticket, owner, outcomes


def test_resume_conflict_preserves_the_real_route_failure_envelope(
    tmp_path: Path,
) -> None:
    """A resume conflicting with an active pause remains a retryable failure."""
    with _quiesce_service(tmp_path) as (port, registry):
        ticket, owner, outcomes = _start_pause_held_by_a_real_ticket(port, registry)
        try:
            transport = _try_http_admin("resume_service", {}, port)
            result = _invoke("resume", port)
        finally:
            ticket.release()
            owner.join(timeout=5)

    assert not owner.is_alive()
    assert outcomes and outcomes[0] is not None
    assert transport is not None
    assert result.exit_code == 1, result.output
    body = _json(result)
    data = _data(result)
    assert transport["ok"] is False
    assert transport["error"] == "quiesce_transition_conflict"
    assert transport["retryable"] is True
    assert body["ok"] is False
    assert body["error"] == "quiesce_transition_conflict"
    assert body["status"] == "quiesce_transition_conflict"
    assert body["retryable"] is True
    assert data["ok"] is False
    assert data["error"] == "quiesce_transition_conflict"
    assert data["retryable"] is True
    assert _quiesce(data)["state"] == "pausing"


def test_unreachable_service_is_failure_exit_one() -> None:
    """No port is a real absence, not a fabricated transport return value."""
    result = _invoke("pause", None)

    assert result.exit_code == 1, result.output
    assert _json(result)["error"] == "service_unreachable"


def test_exactly_one_json_envelope_per_invocation(tmp_path: Path) -> None:
    """The successful real route emits exactly one machine-readable result."""
    with _quiesce_service(tmp_path) as (port, _):
        result = _invoke("pause", port)
    lines = [line for line in result.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, result.stdout
    json.loads(lines[0])
