"""Unit coverage for the ``server doctor`` readiness CLI verb.

Exercises the real Typer surface and asserts the verb renders two distinct
axes: the installed-dependency snapshot (``api.get_readiness``) and a
live-service axis derived from the discovery file. No mocks, patches, fakes, or
skips. The CLI/route parity for the dependency snapshot is asserted at the
integration tier in ``integration/test_server_doctor_route.py``; the
live-service axis honesty (a dead daemon never reads ready) is asserted in
``integration/test_service_doctor_liveness.py``.

The status directory is isolated to a tmp dir so an ambient daemon on the
developer host cannot perturb the live-service axis under test.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..api import get_readiness
from ..cli import app
from ..config import EnvVar, reset_config

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Redirect the service status dir to *tmp_path* (no ambient daemon)."""
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


def test_doctor_json_envelope_carries_both_axes(
    isolated_status_dir: Path,
) -> None:
    """With no discovery file the envelope carries the dependency snapshot
    verbatim and a not-started live-service axis."""
    _ = isolated_status_dir
    result = runner.invoke(app, ["server", "doctor", "--json"])
    envelope = json.loads(result.stdout)
    assert envelope["command"] == "server doctor"
    data = envelope["data"]
    # The installed-dependency snapshot is preserved verbatim and labelled.
    snapshot = get_readiness()
    assert data["dependencies"] == snapshot["dependencies"]
    assert data["dependencies_ready"] == bool(snapshot["ready"])
    assert data["server_mode"] == bool(snapshot["server_mode"])
    # The live-service axis reports "not started" when no discovery file exists.
    assert data["service"]["present"] is False
    assert data["service"]["state"] == "not_started"
    # No daemon expected => top-line tracks installed dependencies.
    assert data["ready"] == bool(snapshot["ready"])
    assert envelope["ok"] == data["ready"]
    # No daemon expected => exit 0 regardless of dependency readiness (the
    # pre-install informational contract); the non-zero exit is reserved for a
    # daemon that is expected but dead.
    assert result.exit_code == 0


def test_doctor_json_dependency_axis_is_bounded_three_dimensions(
    isolated_status_dir: Path,
) -> None:
    _ = isolated_status_dir
    result = runner.invoke(app, ["server", "doctor", "--json"])
    data = json.loads(result.stdout)["data"]
    names = [dep["name"] for dep in data["dependencies"]]
    assert names == ["torch", "models", "qdrant"]
    assert isinstance(data["dependencies_ready"], bool)
    assert isinstance(data["server_mode"], bool)
    assert isinstance(data["ready"], bool)


def test_doctor_human_render_labels_both_axes(
    isolated_status_dir: Path,
) -> None:
    _ = isolated_status_dir
    result = runner.invoke(app, ["server", "doctor"])
    assert "Service readiness" in result.output
    assert "Readiness:" in result.output
    # Both axes are labelled and never conflated.
    assert "Live service:" in result.output
    assert "Installed dependencies:" in result.output
    for name in ("torch", "models", "qdrant"):
        assert name in result.output
