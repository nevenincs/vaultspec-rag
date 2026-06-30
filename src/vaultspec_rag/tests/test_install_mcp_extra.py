"""`vaultspec-rag install` ensures the optional [mcp] extra, with a --no-mcp opt-out.

Install wires up the MCP surface (it seeds the rag MCP config that
`uv run vaultspec-search-mcp` launches), so by default it also installs that
server's dependency via `uv add vaultspec-rag[mcp]` - mcp is a base-install
opt-out, not a setup-time opt-in, mirroring the `--torch-config/--no-torch-config`
and `--provision/--no-provision` polarity. These tests are mock-free: the dry-run
path records intent without shelling out, and the classifier is a pure function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..commands import install_run
from ..commands._uv_sync import (
    _classify_uv_add_result,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestInstallEnsuresMcpExtra:
    """install_mcp=True ensures the [mcp] extra; the CLI defaults it on."""

    def test_install_mcp_true_would_add_the_extra(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=True)
        assert report.mcp_extra_action == "would-add"

    def test_no_mcp_skips_the_extra(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=False)
        assert report.mcp_extra_action == "skipped"

    def test_orchestrator_default_is_off_so_callers_do_not_shell_out(
        self, tmp_path: Path
    ) -> None:
        # install_run defaults install_mcp=False (mirroring provision) so
        # programmatic callers and their network-free tests never run uv add;
        # the on-by-default polarity lives at the CLI edge.
        report = install_run(path=tmp_path, dry_run=True)
        assert report.mcp_extra_action == "skipped"

    def test_mcp_action_is_in_the_json_report(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=True)
        assert report.to_dict()["mcp_extra_action"] == "would-add"


def test_cli_install_flag_defaults_mcp_on() -> None:
    """The `vaultspec-rag install` --mcp/--no-mcp flag defaults to on."""
    import inspect

    from ..cli._install import handle_install

    param = inspect.signature(handle_install).parameters["install_mcp"]
    assert param.default is True


class TestClassifyUvAdd:
    """The uv-add result classifier covers success and failure streams."""

    def test_zero_exit_is_success_no_warning(self) -> None:
        action, warning = _classify_uv_add_result(returncode=0, stdout="", stderr="")
        assert action == "succeeded"
        assert warning is None

    def test_nonzero_exit_surfaces_stderr_as_a_warning(self) -> None:
        action, warning = _classify_uv_add_result(
            returncode=1, stdout="", stderr="No solution found"
        )
        assert action == "failed"
        assert warning is not None
        assert "No solution found" in warning
        assert "--no-mcp" in warning  # actionable remediation

    def test_nonzero_exit_falls_back_to_stdout(self) -> None:
        action, warning = _classify_uv_add_result(
            returncode=2, stdout="lockfile conflict", stderr=""
        )
        assert action == "failed"
        assert warning is not None
        assert "lockfile conflict" in warning
