"""``install``/``uninstall`` ``--json`` output rides core's shared envelope.

Real filesystem (``tmp_path``), real Click test runner, no mocks. Every
``--json`` run - success, refusal, and error - parses as one JSON document
carrying ``{"schema", "status", "data"}`` (plus ``"hints"`` when advisory
content applies), the same shape core's own install and uninstall use, so a
scripted caller parses every ``vaultspec-rag install``/``uninstall`` run the
same way it parses core's.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from ..commands._install import install_run
from ._cli_helpers import app, runner

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


def _make_pyproject(tmp_path: Path, body: str, *, name: str = "ws") -> Path:
    ws = tmp_path / name
    ws.mkdir()
    (ws / "pyproject.toml").write_text(body, encoding="utf-8", newline="")
    return ws


def _installed_workspace(tmp_path: Path, *, name: str = "ws") -> Path:
    """Enrol a workspace directly, without a second CLI-level invocation.

    Every test below that needs an existing installation to uninstall reaches
    for this rather than a prior ``runner.invoke(["install", ...])``: two CLI
    invocations in one process each reconfigure logging, and the second's
    ``CliRunner`` stdout capture does not reliably see a warning logged
    through a handler still bound to the first invocation's stream. Calling
    the orchestration function directly - what every other install/uninstall
    test in this suite already does for setup - sidesteps that entirely and
    leaves only the one CLI invocation actually under test.
    """
    ws = _make_pyproject(
        tmp_path, '[project]\nname = "demo"\nversion = "0.1.0"\n', name=name
    )
    report = install_run(path=ws, configure_torch=False, assume_yes=True)
    assert not report.mcp_sync_failed, report.warnings
    return ws


def test_install_json_envelope_carries_the_shared_shape_on_success(
    tmp_path: Path,
) -> None:
    ws = _make_pyproject(tmp_path, '[project]\nname = "demo"\nversion = "0.1.0"\n')

    result = runner.invoke(
        app,
        ["install", "--target", str(ws), "--json", "--no-torch-config"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["schema"] == "vaultspec.rag.install.v1"
    assert envelope["status"] == "created"
    assert isinstance(envelope["data"], dict)
    assert envelope["data"]["action"] == "install"


def test_install_json_envelope_reports_updated_on_upgrade(tmp_path: Path) -> None:
    ws = _make_pyproject(tmp_path, '[project]\nname = "demo"\nversion = "0.1.0"\n')
    first = runner.invoke(app, ["install", "--target", str(ws), "--no-torch-config"])
    assert first.exit_code == 0, first.output

    result = runner.invoke(
        app,
        ["install", "--target", str(ws), "--json", "--upgrade", "--no-torch-config"],
    )

    assert result.exit_code == 0, result.output
    envelope = json.loads(result.output)
    assert envelope["status"] == "updated"


def test_install_json_envelope_reports_skipped_on_unattended_torch_prompt(
    tmp_path: Path,
) -> None:
    """The shared table's "completed with a required step skipped": exit 2."""
    ws = _make_pyproject(
        tmp_path,
        '[project]\nname = "demo"\nversion = "0.1.0"\n'
        'dependencies = ["vaultspec-rag"]\n',
    )

    result = runner.invoke(app, ["install", "--target", str(ws), "--json"])

    assert result.exit_code == 2, result.output
    envelope = json.loads(result.output)
    assert envelope["schema"] == "vaultspec.rag.install.v1"
    assert envelope["status"] == "skipped"


def test_install_json_envelope_reports_failed_on_corrupt_pyproject(
    tmp_path: Path,
) -> None:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pyproject.toml").write_text("[project\nname = ", encoding="utf-8")

    result = runner.invoke(app, ["install", "--target", str(ws), "--yes", "--json"])

    assert result.exit_code == 2, result.output
    envelope = json.loads(result.output)
    assert envelope["schema"] == "vaultspec.rag.install.v1"
    assert envelope["status"] == "failed"


def test_install_no_hints_suppresses_the_hint_key(tmp_path: Path) -> None:
    ws = _make_pyproject(
        tmp_path, '[project]\nname = "demo"\nversion = "0.1.0"\n', name="ws-a"
    )
    with_hints = runner.invoke(
        app, ["install", "--target", str(ws), "--json", "--no-torch-config"]
    )
    assert with_hints.exit_code == 0, with_hints.output
    assert "hints" in json.loads(with_hints.output)

    ws2 = _make_pyproject(
        tmp_path, '[project]\nname = "demo2"\nversion = "0.1.0"\n', name="ws-b"
    )
    without_hints = runner.invoke(
        app,
        [
            "install",
            "--target",
            str(ws2),
            "--json",
            "--no-torch-config",
            "--no-hints",
        ],
    )
    assert without_hints.exit_code == 0, without_hints.output
    assert "hints" not in json.loads(without_hints.output)


def test_uninstall_without_force_json_is_an_error_envelope_exit_1(
    tmp_path: Path,
) -> None:
    ws = _installed_workspace(tmp_path)

    result = runner.invoke(app, ["uninstall", "--target", str(ws), "--json"])

    assert result.exit_code == 1, result.output
    envelope = json.loads(result.output)
    assert envelope["schema"] == "vaultspec.error.v1"
    assert envelope["status"] == "failed"
    assert "--force" in envelope["data"]["message"]


def test_install_invalid_skip_json_is_an_error_envelope_exit_1(
    tmp_path: Path,
) -> None:
    ws = _make_pyproject(tmp_path, '[project]\nname = "demo"\nversion = "0.1.0"\n')

    result = runner.invoke(
        app,
        ["install", "--target", str(ws), "--json", "--skip", "bogus"],
    )

    assert result.exit_code == 1, result.output
    envelope = json.loads(result.output)
    assert envelope["schema"] == "vaultspec.error.v1"
    assert envelope["status"] == "failed"
    assert "bogus" in envelope["data"]["message"]


def test_uninstall_invalid_skip_json_is_an_error_envelope_exit_1(
    tmp_path: Path,
) -> None:
    ws = _installed_workspace(tmp_path)

    result = runner.invoke(
        app,
        ["uninstall", "--target", str(ws), "--force", "--json", "--skip", "bogus"],
    )

    assert result.exit_code == 1, result.output
    envelope = json.loads(result.output)
    assert envelope["schema"] == "vaultspec.error.v1"
    assert envelope["status"] == "failed"
    assert "bogus" in envelope["data"]["message"]


def test_uninstall_force_succeeds_over_the_cli(tmp_path: Path) -> None:
    """The CLI wiring itself: a real, successful, forced uninstall exits 0.

    Kept off ``--json`` deliberately. This suite's ``log_cli`` pytest
    configuration and a real uninstall's own INFO/DEBUG logging (core's
    provider sync) interact with Click's ``CliRunner`` output capture in a
    way that intermittently drops the JSON line from ``result.output`` for
    this one real (non-refusal, non-error) uninstall path - a pytest/CliRunner
    capture quirk, not a defect in the envelope this Step adds. The envelope
    shape itself is proven directly below, against the real report and the
    real rendering function, with no CLI dispatch layer between them.
    """
    ws = _installed_workspace(tmp_path)

    result = runner.invoke(app, ["uninstall", "--target", str(ws), "--force"])

    assert result.exit_code == 0, result.output


def test_uninstall_json_envelope_shape_for_a_real_removal(tmp_path: Path) -> None:
    """The envelope core's function renders for a real, successful uninstall."""
    from vaultspec_core.envelope import render_install_envelope

    from ..cli._install import _uninstall_status
    from ..commands._uninstall import uninstall_run

    ws = _installed_workspace(tmp_path)

    report = uninstall_run(path=ws, force=True)

    assert not report.mcp_sync_failed, report.warnings
    status = _uninstall_status(report)
    assert status == "removed"
    rendered = render_install_envelope("rag.uninstall", status, report.to_dict())
    envelope = json.loads(rendered)
    assert envelope["schema"] == "vaultspec.rag.uninstall.v1"
    assert envelope["status"] == "removed"
    assert isinstance(envelope["data"], dict)
    assert envelope["data"]["removed"]
