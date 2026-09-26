"""Uninstall's safety gate and the deprecated ``-y``/``--yes`` no-op.

Real filesystem (``tmp_path``), real Click test runner. No mocks. Uninstall
is destructive by default: without ``--force`` and without ``--dry-run`` it
must refuse rather than silently preview, matching the shape vaultspec-core
uses for its own uninstall guard.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from ..cli import app
from ..commands._install import install_run
from ..commands._uninstall import uninstall_run

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]

runner = CliRunner()


def _installed_workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "consumer"
    ws.mkdir()
    install_run(path=ws, assume_yes=True)
    return ws


def test_uninstall_without_force_or_dry_run_is_refused(tmp_path: Path) -> None:
    ws = _installed_workspace(tmp_path)
    marker = ws / ".vaultspec"
    files_before = sorted(marker.rglob("*"))

    with pytest.raises(ValueError, match="--force"):
        uninstall_run(path=ws)

    assert sorted(marker.rglob("*")) == files_before


def test_uninstall_dry_run_previews_without_force(tmp_path: Path) -> None:
    ws = _installed_workspace(tmp_path)
    marker = ws / ".vaultspec"
    files_before = sorted(marker.rglob("*"))

    report = uninstall_run(path=ws, dry_run=True)

    assert report.action == "dry_run"
    assert sorted(marker.rglob("*")) == files_before


def test_uninstall_force_executes(tmp_path: Path) -> None:
    ws = _installed_workspace(tmp_path)

    report = uninstall_run(path=ws, force=True)

    assert report.action == "uninstall"


def test_uninstall_yes_is_a_deprecated_no_op(tmp_path: Path) -> None:
    ws = _installed_workspace(tmp_path)

    report = uninstall_run(path=ws, force=True, assume_yes=True)

    assert any("deprecated" in warning for warning in report.warnings)


def test_uninstall_without_yes_carries_no_deprecation_warning(tmp_path: Path) -> None:
    ws = _installed_workspace(tmp_path)

    report = uninstall_run(path=ws, force=True, assume_yes=False)

    assert not any("deprecated" in warning for warning in report.warnings)


def test_cli_uninstall_yes_is_hidden_from_help() -> None:
    result = runner.invoke(app, ["uninstall", "--help"])
    assert result.exit_code == 0, result.output
    assert "--yes" not in result.output
    assert "-y" not in result.output


def test_cli_uninstall_yes_still_parses_and_warns(tmp_path: Path) -> None:
    ws = _installed_workspace(tmp_path)
    result = runner.invoke(app, ["uninstall", "--target", str(ws), "--force", "--yes"])
    assert result.exit_code == 0, result.output
    assert "deprecated" in result.output.lower()


def test_cli_uninstall_without_force_exits_nonzero(tmp_path: Path) -> None:
    ws = _installed_workspace(tmp_path)
    result = runner.invoke(app, ["uninstall", "--target", str(ws)])
    assert result.exit_code == 1, result.output
    assert "--force" in result.output
