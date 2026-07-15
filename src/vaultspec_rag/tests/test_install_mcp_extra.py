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
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,
)

from ..commands import install_run, uninstall_run
from ..commands._mcp_extra import reconcile_mcp_extra
from ..commands._uv_sync import (
    _classify_uv_add_result,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestInstallEnsuresMcpExtra:
    """install_mcp=True ensures the [mcp] extra; the CLI defaults it on."""

    def test_install_mcp_true_uses_ephemeral_tool_extra(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=True)
        assert report.mcp_extra_action == "tool"

    def test_no_mcp_reports_an_absent_project_extra(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=False)
        assert report.mcp_extra_action == "absent"

    def test_orchestrator_default_is_off_so_callers_do_not_shell_out(
        self, tmp_path: Path
    ) -> None:
        # install_run defaults install_mcp=False (mirroring provision) so
        # programmatic callers and their network-free tests never run uv add;
        # the on-by-default polarity lives at the CLI edge.
        report = install_run(path=tmp_path, dry_run=True)
        assert report.mcp_extra_action == "absent"

    def test_mcp_action_is_in_the_json_report(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=True)
        assert report.to_dict()["mcp_extra_action"] == "tool"

    def test_corrupt_pyproject_reports_error_without_mutation(
        self, tmp_path: Path
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        original = b"[project\nname ="
        pyproject.write_bytes(original)

        report = install_run(
            path=tmp_path,
            install_mcp=True,
            configure_torch=False,
            provision=False,
            skip={"core"},
        )

        assert report.mcp_extra_action == "error"
        assert any("MCP extra inspect failed" in warning for warning in report.warnings)
        assert pyproject.read_bytes() == original

    def test_no_mcp_retains_rule_and_skill_but_removes_source(
        self, tmp_path: Path
    ) -> None:
        enabled = install_run(
            path=tmp_path,
            install_mcp=True,
            configure_torch=False,
            provision=False,
        )
        assert enabled.mcp_extra_action == "tool"
        assert (
            tmp_path / ".vaultspec" / "mcps" / "vaultspec-rag.builtin.json"
        ).is_file()

        disabled = install_run(
            path=tmp_path,
            install_mcp=False,
            configure_torch=False,
            provision=False,
        )

        assert disabled.mcp_extra_action == "absent"
        assert (
            "mcps/vaultspec-rag.builtin.json",
            "[REMOVE]",
        ) in disabled.seeded
        assert not (
            tmp_path / ".vaultspec" / "mcps" / "vaultspec-rag.builtin.json"
        ).exists()
        assert (
            tmp_path / ".vaultspec" / "rules" / "vaultspec-rag.builtin.md"
        ).is_file()
        assert (
            tmp_path / ".vaultspec" / "skills" / "vaultspec-rag-discovery" / "SKILL.md"
        ).is_file()


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


class TestMcpExtraPlacement:
    """The MCP extra follows the resolved project dependency surface."""

    def test_dependency_mode_preserves_and_restores_runtime_requirement(
        self, tmp_path: Path
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        original = (
            b'[project]\nname = "consumer"\n'
            b"dependencies = [\"vaultspec-rag>=0.3; python_version >= '3.12'\"]\n"
        )
        pyproject.write_bytes(original)

        preview = reconcile_mcp_extra(
            pyproject, mode=InstallMode.DEPENDENCY, enabled=True, dry_run=True
        )
        assert preview.action == "would-apply"
        assert preview.location == "[project].dependencies"
        assert pyproject.read_bytes() == original

    def test_uninstall_previews_then_restores_owned_requirement(
        self, tmp_path: Path
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        original = (
            b'[project]\nname = "consumer"\ndependencies = ["vaultspec-rag>=0.3"]\n'
        )
        pyproject.write_bytes(original)
        (tmp_path / ".vaultspec").mkdir()

        applied = reconcile_mcp_extra(
            pyproject, mode=InstallMode.DEPENDENCY, enabled=True
        )
        assert applied.action == "applied"
        managed = pyproject.read_bytes()
        assert managed != original

        preview = uninstall_run(path=tmp_path, skip={"core"})
        assert preview.action == "dry_run"
        assert pyproject.read_bytes() == managed

        removed = uninstall_run(path=tmp_path, force=True, skip={"core"})
        assert removed.action == "uninstall"
        assert pyproject.read_bytes() == original

        applied = reconcile_mcp_extra(
            pyproject, mode=InstallMode.DEPENDENCY, enabled=True
        )
        assert applied.action == "applied"
        assert "vaultspec-rag[mcp]>=0.3" in pyproject.read_text(encoding="utf-8")
        assert (
            reconcile_mcp_extra(
                pyproject, mode=InstallMode.DEPENDENCY, enabled=True
            ).action
            == "already"
        )

        removed = reconcile_mcp_extra(
            pyproject, mode=InstallMode.DEPENDENCY, enabled=False
        )
        assert removed.action == "removed"
        assert pyproject.read_bytes() == original

    @pytest.mark.parametrize(
        ("content", "location"),
        [
            (
                '[project]\nname = "consumer"\n\n'
                '[dependency-groups]\ndev = ["vaultspec-rag>=0.3"]\n',
                "[dependency-groups].dev",
            ),
            (
                '[project]\nname = "consumer"\n\n'
                '[tool.uv]\ndev-dependencies = ["vaultspec-rag>=0.3"]\n',
                "[tool.uv].dev-dependencies",
            ),
        ],
    )
    def test_dev_mode_updates_existing_dev_placement(
        self, tmp_path: Path, content: str, location: str
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(content, encoding="utf-8")

        report = reconcile_mcp_extra(pyproject, mode=InstallMode.DEV, enabled=True)

        assert report.action == "applied"
        assert report.location == location
        assert "vaultspec-rag[mcp]>=0.3" in pyproject.read_text(encoding="utf-8")

    def test_tool_transition_reverses_only_owned_created_dev_surface(
        self, tmp_path: Path
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        original = b'[project]\nname = "consumer"\n'
        pyproject.write_bytes(original)

        assert (
            reconcile_mcp_extra(pyproject, mode=InstallMode.DEV, enabled=True).action
            == "applied"
        )
        report = reconcile_mcp_extra(pyproject, mode=InstallMode.TOOL, enabled=True)

        assert report.action == "removed"
        assert pyproject.read_bytes() == original

    def test_unowned_extra_is_preserved_on_disable(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        original = (
            b'[project]\nname = "consumer"\n'
            b'dependencies = ["vaultspec-rag[mcp]>=0.3"]\n'
        )
        pyproject.write_bytes(original)

        assert (
            reconcile_mcp_extra(
                pyproject, mode=InstallMode.DEPENDENCY, enabled=True
            ).action
            == "already"
        )
        assert (
            reconcile_mcp_extra(
                pyproject, mode=InstallMode.DEPENDENCY, enabled=False
            ).action
            == "already-absent"
        )
        assert pyproject.read_bytes() == original

    def test_owned_requirement_drift_is_a_non_destructive_conflict(
        self, tmp_path: Path
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "consumer"\ndependencies = ["vaultspec-rag>=0.3"]\n',
            encoding="utf-8",
        )
        assert (
            reconcile_mcp_extra(
                pyproject, mode=InstallMode.DEPENDENCY, enabled=True
            ).action
            == "applied"
        )
        drifted = pyproject.read_text(encoding="utf-8").replace(
            "vaultspec-rag[mcp]>=0.3", "vaultspec-rag[mcp]>=0.4", 1
        )
        pyproject.write_text(drifted, encoding="utf-8")

        report = reconcile_mcp_extra(
            pyproject, mode=InstallMode.DEPENDENCY, enabled=False
        )

        assert report.action == "conflict"
        assert report.conflicts
        assert pyproject.read_text(encoding="utf-8") == drifted

    def test_wrong_mode_placement_is_a_non_destructive_conflict(
        self, tmp_path: Path
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        original = (
            b'[project]\nname = "consumer"\n\n'
            b'[dependency-groups]\ndev = ["vaultspec-rag>=0.3"]\n'
        )
        pyproject.write_bytes(original)

        report = reconcile_mcp_extra(
            pyproject, mode=InstallMode.DEPENDENCY, enabled=True
        )

        assert report.action == "conflict"
        assert report.conflicts
        assert pyproject.read_bytes() == original
