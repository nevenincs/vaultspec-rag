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
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,
)
from vaultspec_core.core.manifest import (  # pyright: ignore[reportMissingTypeStubs]
    write_manifest,
)
from vaultspec_core.core.workspace_mode import (  # pyright: ignore[reportMissingTypeStubs]
    PackageDeclaration,
    write_package_declaration,
)

from ..api import get_readiness
from ..cli import app
from ..commands import install_run

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()

_PROJECT_WITH_RAG = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


def _install_rag_workspace(tmp_path: Path, mode: InstallMode) -> Path:
    """Build a real rag-provisioned workspace (no network, no provisioning)."""
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pyproject.toml").write_text(_PROJECT_WITH_RAG, encoding="utf-8", newline="")
    write_manifest(ws, {"claude"})
    install_run(
        path=ws,
        mode=mode,
        provision=False,
        configure_torch=False,
        install_mcp=True,
    )
    return ws


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


def test_doctor_omits_mode_axis_when_no_rag_declaration(
    isolated_status_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A directory with no committed rag entry surfaces no provisioning axis."""
    _ = isolated_status_dir
    bare = tmp_path / "bare"
    bare.mkdir()
    monkeypatch.chdir(bare)

    result = runner.invoke(app, ["server", "doctor", "--json"])

    data = json.loads(result.stdout)["data"]
    assert data["mode"] is None
    # No declaration and no daemon keeps the informational exit-0 contract.
    assert result.exit_code == 0


def test_doctor_reports_clean_rag_mode_and_floor(
    isolated_status_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanly provisioned rag workspace reads mode ok, floor ok, exit 0."""
    _ = isolated_status_dir
    ws = _install_rag_workspace(tmp_path, InstallMode.TOOL)
    monkeypatch.chdir(ws)

    result = runner.invoke(app, ["server", "doctor", "--json"])

    mode = json.loads(result.stdout)["data"]["mode"]
    assert mode is not None
    assert mode["package"] == "vaultspec-rag"
    assert mode["declared_mode"] == "tool"
    assert mode["mode_mismatch"] == "clean"
    assert mode["version_floor"] == "ok"
    assert result.exit_code == 0


def test_doctor_weights_below_floor_as_error(
    isolated_status_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rag entry whose floor outranks the running core exits 2 (error)."""
    _ = isolated_status_dir
    ws = _install_rag_workspace(tmp_path, InstallMode.TOOL)
    # Declare a floor the running vaultspec-core cannot satisfy, leaving the
    # mode axis clean so the exit code reflects only the floor error.
    write_package_declaration(
        ws,
        "vaultspec-rag",
        PackageDeclaration(install_mode=InstallMode.TOOL, minimum_version="99.0.0"),
    )
    monkeypatch.chdir(ws)

    result = runner.invoke(app, ["server", "doctor", "--json"])

    mode = json.loads(result.stdout)["data"]["mode"]
    assert mode["version_floor"] == "below"
    assert mode["version_floor_minimum"] == "99.0.0"
    assert result.exit_code == 2


def test_doctor_weights_mode_mismatch_as_warning(
    isolated_status_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rag entry whose deployed launch disagrees with its mode exits 1 (warn)."""
    _ = isolated_status_dir
    ws = _install_rag_workspace(tmp_path, InstallMode.TOOL)
    # Rewrite rag's deployed .mcp.json entry to the dependency launch shape while
    # the declaration still names tool mode, so the artifact disagrees with the
    # declared mode.
    mcp_path = ws / ".mcp.json"
    raw = json.loads(mcp_path.read_text(encoding="utf-8"))
    raw["mcpServers"]["vaultspec-rag"] = {
        "command": "uv",
        "args": ["run", "python", "-m", "vaultspec_rag.server"],
    }
    mcp_path.write_text(json.dumps(raw), encoding="utf-8")
    monkeypatch.chdir(ws)

    result = runner.invoke(app, ["server", "doctor", "--json"])

    mode = json.loads(result.stdout)["data"]["mode"]
    assert mode["mode_mismatch"] == "mismatch"
    assert mode["version_floor"] == "ok"
    assert result.exit_code == 1


def test_doctor_human_render_labels_mode_axis(
    isolated_status_dir: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The human render surfaces a labelled provisioning block for rag."""
    _ = isolated_status_dir
    ws = _install_rag_workspace(tmp_path, InstallMode.TOOL)
    monkeypatch.chdir(ws)

    result = runner.invoke(app, ["server", "doctor"])

    assert "Provisioning (vaultspec-rag):" in result.output
    assert "declared mode: tool" in result.output
