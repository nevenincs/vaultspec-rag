"""Real installation integration behavior: transaction rollback."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,  # pyright: ignore[reportMissingTypeStubs]
)
from vaultspec_core.core.manifest import (  # pyright: ignore[reportMissingTypeStubs]
    write_manifest,
)
from vaultspec_core.core.workspace_mode import (  # pyright: ignore[reportMissingTypeStubs]
    read_package_declaration,  # pyright: ignore[reportMissingTypeStubs]
)

from ...commands._install import install_run
from ...commands._uninstall import uninstall_run
from ._install_helpers import (
    _CONSUMER_PYPROJECT,
    _RAG_MCP_REL,
    _RAG_RULE_REL,
    _RAG_SKILL_REL,
    _install,
    _node_signature,
    create_windows_junction,
    workspace_file_bytes,
    workspace_inventory,
)

pytestmark = [pytest.mark.integration]


class TestInstallTransactionRollback:
    def test_required_workspace_directory_blocks_mode_transition(
        self, fresh_workspace: Path
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        workspace = fresh_workspace / ".vaultspec" / "workspace.json"
        prior_workspace = workspace.read_bytes()
        workspace.unlink()
        workspace.mkdir()
        (workspace / "operator.json").write_bytes(prior_workspace)
        before = workspace_inventory(fresh_workspace)

        report = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.DEV,
        )

        assert report.mcp_extra_action == "skipped"
        assert report.mcp_sync_failed
        assert "required MCP topology preflight failed" in " ".join(report.mcp_errors)
        assert not report.seeded
        assert not report.sync_results
        assert workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("preexisting_locks", [False, True])
    def test_required_workspace_directory_preserves_exact_intent_inventory(
        self, fresh_workspace: Path, preexisting_locks: bool
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        write_manifest(fresh_workspace, {"claude", "codex"})
        (fresh_workspace / ".vault" / "data").mkdir(parents=True)
        for name in ("mcps", "rules", "skills"):
            (fresh_workspace / ".vaultspec" / name).mkdir(parents=True, exist_ok=True)
        workspace = fresh_workspace / ".vaultspec" / "workspace.json"
        if preexisting_locks:
            pyproject.with_suffix(".toml.lock").write_bytes(b"project-lock\x00")
            workspace.with_suffix(".json.lock").write_bytes(b"workspace-lock\x00")
        workspace.mkdir()
        (workspace / "operator.json").write_bytes(b"preserve\x00")
        before = workspace_inventory(fresh_workspace)

        report = _install(fresh_workspace, mode=InstallMode.DEPENDENCY)

        assert report.mcp_extra_action == "skipped"
        assert report.mcp_sync_failed
        assert "required MCP topology preflight failed" in " ".join(report.mcp_errors)
        assert not report.seeded
        assert not report.sync_results
        assert workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("source_has_sentinel", [False, True])
    def test_required_mcp_source_directory_preserves_full_intent_inventory(
        self, fresh_workspace: Path, source_has_sentinel: bool
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        write_manifest(fresh_workspace, {"claude", "codex"})
        (fresh_workspace / ".vault" / "data").mkdir(parents=True)
        for name in ("mcps", "rules", "skills"):
            (fresh_workspace / ".vaultspec" / name).mkdir(parents=True, exist_ok=True)
        source = fresh_workspace / _RAG_MCP_REL
        source.mkdir()
        if source_has_sentinel:
            (source / "operator.json").write_bytes(b"preserve\x00")
        pyproject.with_suffix(".toml.lock").write_bytes(b"project-lock\x00")
        workspace = fresh_workspace / ".vaultspec" / "workspace.json"
        workspace.with_suffix(".json.lock").write_bytes(b"workspace-lock\x00")
        before = workspace_inventory(fresh_workspace)

        report = install_run(
            path=fresh_workspace,
            install_mcp=True,
            configure_torch=True,
            assume_yes=True,
            provision=False,
            force=True,
            mode=InstallMode.DEPENDENCY,
        )

        assert report.mcp_extra_action == "skipped"
        assert report.mcp_sync_failed
        assert report.torch_config_action == "skipped"
        assert "required MCP topology preflight failed" in " ".join(report.mcp_errors)
        assert not report.seeded
        assert not report.sync_results
        assert workspace_inventory(fresh_workspace) == before
        assert not workspace.exists()
        if not source_has_sentinel:
            from typer.testing import CliRunner

            from ...cli import app

            result = CliRunner().invoke(
                app,
                [
                    "install",
                    "--target",
                    str(fresh_workspace),
                    "--force",
                    "--mode",
                    "dependency",
                    "--mcp",
                    "--no-torch-config",
                    "--no-provision",
                    "--json",
                ],
                catch_exceptions=False,
            )
            assert result.exit_code == 2, result.output
            assert workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("repair_flag", ["force", "upgrade"])
    @pytest.mark.parametrize("existing_builtins", [False, True])
    def test_late_skill_failure_restores_every_builtin_exactly(
        self,
        fresh_workspace: Path,
        repair_flag: str,
        existing_builtins: bool,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        write_manifest(fresh_workspace, {"claude", "codex"})
        (fresh_workspace / ".vault" / "data").mkdir(parents=True)
        for name in ("mcps", "rules", "skills"):
            (fresh_workspace / ".vaultspec" / name).mkdir(parents=True, exist_ok=True)
        skill = fresh_workspace / _RAG_SKILL_REL
        skill.parent.mkdir(parents=True)
        if existing_builtins:
            (fresh_workspace / _RAG_MCP_REL).write_bytes(b"operator-mcp\x00")
            (fresh_workspace / _RAG_RULE_REL).write_bytes(b"operator-rule\x00")
        skill.mkdir()
        (skill / "operator.md").write_bytes(b"operator-skill\x00")
        unrelated = fresh_workspace / ".vaultspec" / "rules" / "operator.md"
        unrelated.write_bytes(b"unrelated\x00")
        workspace = fresh_workspace / ".vaultspec" / "workspace.json"
        pyproject.with_suffix(".toml.lock").write_bytes(b"project-lock\x00")
        workspace.with_suffix(".json.lock").write_bytes(b"workspace-lock\x00")
        before = workspace_inventory(fresh_workspace)

        report = install_run(
            path=fresh_workspace,
            install_mcp=True,
            configure_torch=False,
            provision=False,
            mode=InstallMode.DEPENDENCY,
            force=repair_flag == "force",
            upgrade=repair_flag == "upgrade",
        )

        assert report.mcp_extra_action == "error"
        assert report.mcp_sync_failed
        assert not report.seeded
        assert not report.sync_results
        assert workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("repair_flag", ["force", "upgrade"])
    @pytest.mark.parametrize("link_case", ["live-relative", "broken-relative"])
    def test_late_skill_failure_restores_rule_symlink_topology(
        self,
        fresh_workspace: Path,
        repair_flag: str,
        link_case: str,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        write_manifest(fresh_workspace, {"claude", "codex"})
        (fresh_workspace / ".vault" / "data").mkdir(parents=True)
        for name in ("mcps", "rules", "skills"):
            (fresh_workspace / ".vaultspec" / name).mkdir(parents=True, exist_ok=True)
        rule = fresh_workspace / _RAG_RULE_REL
        link_target = (
            Path("operator-target.md")
            if link_case == "live-relative"
            else Path("missing-target.md")
        )
        live_target = rule.parent / "operator-target.md"
        if link_case == "live-relative":
            live_target.write_bytes(b"operator-target\x00")
        rule.symlink_to(link_target, target_is_directory=False)
        skill = fresh_workspace / _RAG_SKILL_REL
        skill.parent.mkdir(parents=True)
        skill.mkdir()
        (skill / "operator.md").write_bytes(b"operator-skill\x00")
        before = workspace_inventory(fresh_workspace)
        signature = _node_signature(rule)

        report = install_run(
            path=fresh_workspace,
            install_mcp=True,
            configure_torch=False,
            provision=False,
            mode=InstallMode.DEPENDENCY,
            force=repair_flag == "force",
            upgrade=repair_flag == "upgrade",
        )

        assert report.mcp_extra_action == "error"
        assert report.mcp_sync_failed
        assert _node_signature(rule) == signature
        assert rule.is_symlink()
        assert os.readlink(rule) == str(link_target)
        if link_case == "live-relative":
            assert live_target.read_bytes() == b"operator-target\x00"
        else:
            assert not (rule.parent / link_target).exists()
        assert workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("snapshot_kind", ["regular", "relative-symlink"])
    @pytest.mark.parametrize(
        "collision_kind",
        ["regular", "live-symlink", "broken-symlink"],
    )
    def test_rollback_restore_ignores_predictable_temp_collisions(
        self,
        fresh_workspace: Path,
        snapshot_kind: str,
        collision_kind: str,
    ) -> None:
        from ...commands._mcp_topology import file_snapshot, restore_file_snapshot

        destination = fresh_workspace / "builtin-rule.md"
        destination_target = fresh_workspace / "builtin-target.md"
        if snapshot_kind == "regular":
            destination.write_bytes(b"original-rule\x00")
            destination.chmod(stat.S_IREAD)
        else:
            destination_target.write_bytes(b"link-target\x00")
            destination.symlink_to(
                destination_target.name,
                target_is_directory=False,
            )
        snapshot = file_snapshot(destination)
        if snapshot_kind == "regular":
            destination.chmod(stat.S_IREAD | stat.S_IWRITE)
        destination.unlink()
        destination.write_bytes(b"transaction-rule")

        collision = destination.with_suffix(
            destination.suffix + f".{os.getpid()}.rollback.tmp"
        )
        collision_target = fresh_workspace / "collision-target.md"
        if collision_kind == "regular":
            collision.write_bytes(b"operator-collision\x00")
        elif collision_kind == "live-symlink":
            collision_target.write_bytes(b"operator-target\x00")
            collision.symlink_to(collision_target.name, target_is_directory=False)
        else:
            collision.symlink_to("missing-collision.md", target_is_directory=False)
        collision_signature = _node_signature(collision)
        collision_bytes = (
            collision.read_bytes() if collision_kind != "broken-symlink" else None
        )

        restore_file_snapshot(destination, snapshot)

        assert file_snapshot(destination) == snapshot
        assert _node_signature(collision) == collision_signature
        if collision_bytes is not None:
            assert collision.read_bytes() == collision_bytes
        if collision_kind == "live-symlink":
            assert collision_target.read_bytes() == b"operator-target\x00"
        elif collision_kind == "broken-symlink":
            assert not (fresh_workspace / "missing-collision.md").exists()
        assert not list(fresh_workspace.glob(f".{destination.name}.rollback-*.tmp"))

    @pytest.mark.parametrize(
        ("content", "initial_mode", "target_mode", "target_location"),
        [
            (
                '[project]\nname = "consumer"\nversion = "0.1.0"\n'
                'dependencies = ["vaultspec-rag"]\n',
                InstallMode.DEPENDENCY,
                InstallMode.DEV,
                "[dependency-groups].dev",
            ),
            (
                '[project]\nname = "consumer"\nversion = "0.1.0"\n\n'
                '[dependency-groups]\ndev = ["vaultspec-rag"]\n',
                InstallMode.DEV,
                InstallMode.DEPENDENCY,
                "[project].dependencies",
            ),
        ],
    )
    def test_owned_extra_moves_with_dependency_dev_mode_and_uninstalls(
        self,
        fresh_workspace: Path,
        content: str,
        initial_mode: InstallMode,
        target_mode: InstallMode,
        target_location: str,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        original = content.encode()
        pyproject.write_bytes(original)
        _install(fresh_workspace, mode=initial_mode)
        initial_managed = pyproject.read_bytes()
        before = workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=target_mode,
        )

        assert preview.mcp_extra_action == "would-move"
        assert workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=target_mode,
        )
        assert actual.mcp_extra_action == "moved"
        assert f'location = "{target_location}"' in pyproject.read_text(
            encoding="utf-8"
        )
        declaration = read_package_declaration(fresh_workspace, "vaultspec-rag")
        assert declaration is not None
        assert declaration.install_mode is target_mode

        returned = _install(
            fresh_workspace,
            upgrade=True,
            mode=initial_mode,
        )
        assert returned.mcp_extra_action == "moved"
        assert pyproject.read_bytes() == initial_managed
        uninstall_run(path=fresh_workspace, force=True)
        assert pyproject.read_bytes() == original

    if os.name == "nt":

        @pytest.mark.parametrize("repair_flag", ["force", "upgrade"])
        def test_late_junction_blocker_preserves_reparse_topology(
            self,
            fresh_workspace: Path,
            repair_flag: str,
        ) -> None:
            pyproject = fresh_workspace / "pyproject.toml"
            pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
            write_manifest(fresh_workspace, {"claude", "codex"})
            (fresh_workspace / ".vault" / "data").mkdir(parents=True)
            for name in ("mcps", "rules", "skills"):
                (fresh_workspace / ".vaultspec" / name).mkdir(
                    parents=True, exist_ok=True
                )
            (fresh_workspace / _RAG_MCP_REL).write_bytes(b"operator-mcp\x00")
            (fresh_workspace / _RAG_RULE_REL).write_bytes(b"operator-rule\x00")
            skill = fresh_workspace / _RAG_SKILL_REL
            skill.parent.mkdir(parents=True)
            target = fresh_workspace / ".vaultspec" / "operator-junction-target"
            target.mkdir()
            (target / "sentinel").write_bytes(b"junction-target\x00")
            create_windows_junction(skill, target)
            before = workspace_inventory(fresh_workspace)
            signature = _node_signature(skill)

            report = install_run(
                path=fresh_workspace,
                install_mcp=True,
                configure_torch=False,
                provision=False,
                mode=InstallMode.DEPENDENCY,
                force=repair_flag == "force",
                upgrade=repair_flag == "upgrade",
            )

            assert report.mcp_extra_action == "error"
            assert report.mcp_sync_failed
            assert skill.is_junction()
            assert _node_signature(skill) == signature
            assert (target / "sentinel").read_bytes() == b"junction-target\x00"
            assert workspace_inventory(fresh_workspace) == before

        def test_junction_snapshot_recreates_removed_reparse_node(
            self, fresh_workspace: Path
        ) -> None:
            from ...commands._mcp_topology import file_snapshot, restore_file_snapshot

            target = fresh_workspace / "operator-target"
            target.mkdir()
            (target / "sentinel").write_bytes(b"target-owned\x00")
            junction = fresh_workspace / "builtin-junction"
            create_windows_junction(junction, target)
            snapshot = file_snapshot(junction)
            signature = _node_signature(junction)
            junction.rmdir()
            junction.write_bytes(b"transaction-replacement")

            restore_file_snapshot(junction, snapshot)

            assert junction.is_junction()
            assert _node_signature(junction) == signature
            assert (target / "sentinel").read_bytes() == b"target-owned\x00"
