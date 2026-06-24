"""Integration coverage for the ``server doctor`` live-service axis (#204).

Drives the real ``server doctor`` Typer code path against a real (closed) port
and a real discovery file on disk - no mocks, patches, fakes, or skips. The
status directory is isolated to a tmp dir so the developer host's daemon cannot
perturb the axis under test.

Asserts the residual #204 doctor contract:

- A discovery file naming a dead PID and a closed port makes ``doctor`` report
  ``ready: false`` with a ``needs_restart`` status on the live axis, while the
  installed-dependency axis stays present and labelled (the two are never
  conflated).
- With no discovery file, ``doctor`` still reports installed-dependency
  readiness so a pure pre-install check works.
"""

from __future__ import annotations

import json
import os
import socket
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ...cli import app
from ...config import EnvVar, reset_config
from ...serviceclient._discovery import (
    SERVICE_DISCOVERY_SCHEMA,
    SERVICE_DISCOVERY_VERSION,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.integration]

runner = CliRunner()

# A PID far above the live range on every supported OS: not running and not
# realistically reusable for the duration of the test.
_DEAD_PID = 2_000_000_000


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Redirect the service status dir to *tmp_path* for the test duration."""
    prev = os.environ.get(EnvVar.STATUS_DIR.value)
    status_dir = tmp_path / "vaultspec-rag"
    status_dir.mkdir()
    os.environ[EnvVar.STATUS_DIR.value] = str(status_dir)
    reset_config()
    try:
        yield status_dir
    finally:
        if prev is None:
            os.environ.pop(EnvVar.STATUS_DIR.value, None)
        else:
            os.environ[EnvVar.STATUS_DIR.value] = prev
        reset_config()


def _closed_port() -> int:
    """Return a port number that is currently closed (nothing listening).

    Binds an ephemeral port, reads the kernel-assigned number, then closes the
    socket so the port is free again - a real, currently-closed port.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _write_discovery_file(status_dir: Path, *, pid: int, port: int) -> None:
    sf = status_dir / "service.json"
    sf.write_text(
        json.dumps(
            {
                "schema": SERVICE_DISCOVERY_SCHEMA,
                "version": SERVICE_DISCOVERY_VERSION,
                "pid": pid,
                "port": port,
                "started_at": "2026-06-24T00:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )


def test_doctor_reports_dead_daemon_not_ready(
    isolated_status_dir: Path,
) -> None:
    """A discovery file naming a dead PID + closed port => live axis not ready."""
    _write_discovery_file(
        isolated_status_dir,
        pid=_DEAD_PID,
        port=_closed_port(),
    )

    result = runner.invoke(app, ["server", "doctor", "--json"])

    # A dead-but-expected daemon must never read ready, regardless of installed
    # dependencies, and the verb must exit non-zero.
    assert result.exit_code != 0
    envelope = json.loads(result.stdout)
    data = envelope["data"]
    assert data["ready"] is False
    assert envelope["ok"] is False
    assert data["status"] == "needs_restart"
    # The live-service axis reflects the real dead daemon.
    service = data["service"]
    assert service["present"] is True
    assert service["live"] is False
    assert service["pid_alive"] is False
    assert service["port_listening"] is False
    # The installed-dependency axis is still present, labelled, and separate.
    assert isinstance(data["dependencies"], list)
    names = [dep["name"] for dep in data["dependencies"]]
    assert names == ["torch", "models", "qdrant"]
    assert "dependencies_ready" in data


def test_doctor_dead_daemon_human_render_labels_both_axes(
    isolated_status_dir: Path,
) -> None:
    """Human render names the not-running live service and the dependency axis."""
    _write_discovery_file(
        isolated_status_dir,
        pid=_DEAD_PID,
        port=_closed_port(),
    )

    result = runner.invoke(app, ["server", "doctor"])

    assert result.exit_code != 0
    assert "Live service:" in result.output
    assert "not running" in result.output
    assert "needs restart" in result.output
    assert "Installed dependencies:" in result.output


def test_doctor_no_discovery_file_reports_dependency_readiness(
    isolated_status_dir: Path,
) -> None:
    """With no discovery file the top line reflects installed dependencies."""
    sf = isolated_status_dir / "service.json"
    assert not sf.exists()

    result = runner.invoke(app, ["server", "doctor", "--json"])

    envelope = json.loads(result.stdout)
    data = envelope["data"]
    # No daemon expected => the live axis does not constrain readiness; the
    # top line equals the installed-dependency verdict.
    assert data["service"]["present"] is False
    assert data["service"]["state"] == "not_started"
    assert data["ready"] == data["dependencies_ready"]
    assert envelope["ok"] == data["ready"]
