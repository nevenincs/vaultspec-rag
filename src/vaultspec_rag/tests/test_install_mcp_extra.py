"""Placement-aware optional MCP-extra enrollment with a --no-mcp opt-out.

Install wires up the MCP surface and reconciles the extra at RAG's existing
runtime or development dependency placement. Tool mode uses the canonical uvx
launch without mutating the project. These tests exercise real TOML files and
workspace state without mocks or subprocess classifiers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,
)

from ..commands._install import install_run
from ..commands._mcp_extra import reconcile_mcp_extra
from ..commands._uninstall import uninstall_run

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

    def test_orchestrator_default_leaves_mcp_disabled(self, tmp_path: Path) -> None:
        # install_run defaults install_mcp=False (mirroring provision) so
        # programmatic callers retain explicit control; the on-by-default
        # polarity lives at the CLI edge.
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
    from typer._click import Context as ClickContext
    from typer.core import TyperOption
    from typer.main import get_command

    from ..cli._app import _LiteralArgvGroup, app

    root = get_command(app)
    assert isinstance(root, _LiteralArgvGroup)
    install = root.get_command(ClickContext(root), "install")
    assert install is not None
    mcp_option = next(
        option
        for option in install.params
        if isinstance(option, TyperOption) and option.name == "mcp"
    )
    assert mcp_option.default is True


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

    @pytest.mark.parametrize(
        ("content", "initial_mode", "target_mode", "target_location"),
        [
            (
                '[project]\nname = "consumer"\ndependencies = ["vaultspec-rag>=0.3"]\n',
                InstallMode.DEPENDENCY,
                InstallMode.DEV,
                "[dependency-groups].dev",
            ),
            (
                '[project]\nname = "consumer"\n\n'
                '[dependency-groups]\ndev = ["vaultspec-rag>=0.3"]\n',
                InstallMode.DEV,
                InstallMode.DEPENDENCY,
                "[project].dependencies",
            ),
        ],
    )
    def test_owned_extra_moves_between_runtime_and_dev_and_round_trips(
        self,
        tmp_path: Path,
        content: str,
        initial_mode: InstallMode,
        target_mode: InstallMode,
        target_location: str,
    ) -> None:
        pyproject = tmp_path / "pyproject.toml"
        original = content.encode()
        pyproject.write_bytes(original)
        assert (
            reconcile_mcp_extra(pyproject, mode=initial_mode, enabled=True).action
            == "applied"
        )
        initial_managed = pyproject.read_bytes()

        preview = reconcile_mcp_extra(
            pyproject,
            mode=target_mode,
            enabled=True,
            dry_run=True,
        )

        assert preview.action == "would-move"
        assert preview.location == target_location
        assert pyproject.read_bytes() == initial_managed
        moved = reconcile_mcp_extra(
            pyproject,
            mode=target_mode,
            enabled=True,
        )
        assert moved.action == "moved"
        assert moved.location == target_location
        text = pyproject.read_text(encoding="utf-8")
        assert f'location = "{target_location}"' in text
        assert "vaultspec-rag[mcp]" in text

        returned = reconcile_mcp_extra(
            pyproject,
            mode=initial_mode,
            enabled=True,
        )
        assert returned.action == "moved"
        assert pyproject.read_bytes() == initial_managed
        removed = reconcile_mcp_extra(
            pyproject,
            mode=initial_mode,
            enabled=False,
        )
        assert removed.action == "removed"
        assert pyproject.read_bytes() == original

    def test_owned_move_preserves_unowned_extra_at_target(self, tmp_path: Path) -> None:
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "consumer"\ndependencies = ["vaultspec-rag>=0.3"]\n',
            encoding="utf-8",
        )
        assert (
            reconcile_mcp_extra(
                pyproject,
                mode=InstallMode.DEPENDENCY,
                enabled=True,
            ).action
            == "applied"
        )
        with pyproject.open("a", encoding="utf-8", newline="") as stream:
            stream.write('\n[dependency-groups]\ndev = ["vaultspec-rag[mcp]>=0.3"]\n')
        unowned_target = 'dev = ["vaultspec-rag[mcp]>=0.3"]'

        report = reconcile_mcp_extra(
            pyproject,
            mode=InstallMode.DEV,
            enabled=True,
        )

        assert report.action == "moved"
        text = pyproject.read_text(encoding="utf-8")
        assert unowned_target in text
        assert 'dependencies = ["vaultspec-rag>=0.3"]' in text
        assert "mcp-extra" not in text

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
