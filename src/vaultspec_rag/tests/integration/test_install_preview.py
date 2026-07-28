"""Real installation integration behavior: preview."""

from __future__ import annotations

import json
import os
from contextvars import Context
from pathlib import Path  # noqa: TC003

import pytest
from vaultspec_core.config.workspace import (  # pyright: ignore[reportMissingTypeStubs]
    resolve_workspace,
)
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,
)
from vaultspec_core.core.manifest import (  # pyright: ignore[reportMissingTypeStubs]
    write_manifest,
)
from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
    get_context,
    init_paths,
)

from ...commands._install import install_run
from ._install_helpers import (
    _install,
    _node_signature,
    create_windows_junction,
    read_codex_mcp,
    read_mcp_json,
    workspace_file_bytes,
    workspace_inventory,
)

pytestmark = [pytest.mark.integration]


class TestDryRunInstall:
    def test_dry_run_creates_no_dirs_or_files(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace, dry_run=True)
        assert report.action == "dry_run"
        # Filesystem untouched
        assert not (fresh_workspace / ".vault").exists()
        assert not (fresh_workspace / ".vaultspec").exists()
        # Report still lists planned work
        assert report.created_dirs
        assert ("rules/vaultspec-rag.builtin.md", "[ADD]") in report.seeded

    def test_dry_run_reports_provider_repairs_without_writing(
        self, fresh_workspace: Path
    ) -> None:
        _install(fresh_workspace)
        claude_path = fresh_workspace / ".mcp.json"
        codex_path = fresh_workspace / ".codex" / "config.toml"
        claude = read_mcp_json(fresh_workspace)
        claude["mcpServers"]["vaultspec-rag"]["command"] = "drifted"
        claude_path.write_text(json.dumps(claude, indent=2) + "\n", encoding="utf-8")
        codex = codex_path.read_text(encoding="utf-8").replace(
            'command = "uvx"', 'command = "drifted"', 1
        )
        codex_path.write_text(codex, encoding="utf-8")
        tracked = (claude_path, codex_path, fresh_workspace / "pyproject.toml")
        before = {path: path.read_bytes() for path in tracked if path.exists()}

        report = _install(fresh_workspace, dry_run=True, force=True)

        assert {path: path.read_bytes() for path in before} == before
        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["updated"] == 1
        assert providers["codex"]["updated"] == 1

    def test_fresh_mcp_dry_run_reports_native_additions_without_writing(
        self, fresh_workspace: Path
    ) -> None:
        before = workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        report = _install(fresh_workspace, dry_run=True)

        assert workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["added"] == 1
        assert providers["codex"]["added"] == 1
        assert providers["claude"]["items"] == [["vaultspec-rag", "[ADD]"]]
        assert providers["codex"]["items"] == [["vaultspec-rag", "[ADD]"]]

    def test_fresh_explicit_mode_preview_matches_real_without_synthetic_pass(
        self, fresh_workspace: Path
    ) -> None:
        before = workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            mode=InstallMode.TOOL,
        )

        assert workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(fresh_workspace, mode=InstallMode.TOOL)
        preview_providers = preview.to_dict()["sync_providers"]
        actual_providers = actual.to_dict()["sync_providers"]
        assert preview_providers == actual_providers
        for provider in ("claude", "codex"):
            assert preview_providers[provider]["added"] == 1
            assert preview_providers[provider]["unchanged"] == 0
            assert preview_providers[provider]["items"] == [["vaultspec-rag", "[ADD]"]]

    def test_unowned_collision_and_absent_sibling_preview_matches_real(
        self, fresh_workspace: Path
    ) -> None:
        write_manifest(fresh_workspace, {"claude", "codex"})
        user_entry = {"command": "user-owned", "args": ["--keep"]}
        claude_path = fresh_workspace / ".mcp.json"
        claude_path.write_text(
            json.dumps({"mcpServers": {"vaultspec-rag": user_entry}}, indent=2) + "\n",
            encoding="utf-8",
        )
        claude_before = claude_path.read_bytes()
        before = workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            mode=InstallMode.TOOL,
        )

        assert workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(fresh_workspace, mode=InstallMode.TOOL)
        preview_providers = preview.to_dict()["sync_providers"]
        actual_providers = actual.to_dict()["sync_providers"]
        assert preview_providers == actual_providers
        assert preview_providers["claude"]["skipped"] == 1
        assert preview_providers["claude"]["items"] == [["vaultspec-rag", "[SKIP]"]]
        assert preview_providers["codex"]["added"] == 1
        assert preview_providers["codex"]["unchanged"] == 0
        assert preview_providers["codex"]["items"] == [["vaultspec-rag", "[ADD]"]]
        assert claude_path.read_bytes() == claude_before
        assert read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"] == (
            user_entry
        )
        assert read_codex_mcp(fresh_workspace)["vaultspec-rag"]["command"] == "uvx"

    def test_no_mcp_dry_run_reports_native_prunes_without_writing(
        self, installed_workspace: Path
    ) -> None:
        before = workspace_file_bytes(installed_workspace)
        locks_before = sorted(installed_workspace.rglob("*.lock"))

        report = _install(
            installed_workspace,
            dry_run=True,
            install_mcp=False,
        )

        assert workspace_file_bytes(installed_workspace) == before
        assert sorted(installed_workspace.rglob("*.lock")) == locks_before
        assert ("mcps/vaultspec-rag.builtin.json", "[REMOVE]") in report.seeded
        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["pruned"] == 1
        assert providers["codex"]["pruned"] == 1
        assert providers["claude"]["items"] == [["vaultspec-rag", "[DELETE]"]]
        assert providers["codex"]["items"] == [["vaultspec-rag", "[DELETE]"]]

    def test_cli_dry_run_json_reports_desired_provider_plan_without_writing(
        self, tmp_path: Path
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        runner = CliRunner()
        fresh_workspace = tmp_path / "fresh"
        fresh_workspace.mkdir()
        fresh_before = workspace_file_bytes(fresh_workspace)
        add_result = runner.invoke(
            app,
            [
                "install",
                "--target",
                str(fresh_workspace),
                "--dry-run",
                "--no-provision",
                "--no-torch-config",
                "--mcp",
                "--json",
            ],
            catch_exceptions=False,
        )
        assert add_result.exit_code == 0, add_result.output
        add_report = json.loads(add_result.output)
        assert add_report["sync_providers"]["claude"]["added"] == 1
        assert add_report["sync_providers"]["codex"]["added"] == 1
        assert workspace_file_bytes(fresh_workspace) == fresh_before

        installed_workspace = tmp_path / "installed"
        installed_workspace.mkdir()
        _install(installed_workspace)
        installed_before = workspace_file_bytes(installed_workspace)
        remove_result = runner.invoke(
            app,
            [
                "install",
                "--target",
                str(installed_workspace),
                "--dry-run",
                "--no-provision",
                "--no-torch-config",
                "--no-mcp",
                "--json",
            ],
            catch_exceptions=False,
        )
        assert remove_result.exit_code == 0, remove_result.output
        remove_report = json.loads(remove_result.output)
        assert remove_report["sync_providers"]["claude"]["pruned"] == 1
        assert remove_report["sync_providers"]["codex"]["pruned"] == 1
        assert workspace_file_bytes(installed_workspace) == installed_before

    @pytest.mark.parametrize("malformed_ownership", [False, True])
    def test_preview_restores_a_prior_core_context(
        self,
        tmp_path: Path,
        malformed_ownership: bool,
    ) -> None:
        durable = tmp_path / "durable"
        (durable / ".vaultspec").mkdir(parents=True)
        (durable / ".vault").mkdir()
        init_paths(resolve_workspace(target_override=durable))
        prior = get_context()

        target = tmp_path / "preview"
        target.mkdir()
        if malformed_ownership:
            (target / ".vaultspec").mkdir()
            (target / ".vaultspec" / "mcp-ownership.json").write_text(
                "{not-json",
                encoding="utf-8",
            )
        report = _install(target, dry_run=True)

        assert report.mcp_sync_failed is malformed_ownership
        assert get_context() is prior
        assert get_context().target_dir == durable

    def test_preview_preserves_an_unset_core_context(self, tmp_path: Path) -> None:
        target = tmp_path / "preview"
        target.mkdir()

        def run_without_context() -> None:
            with pytest.raises(LookupError):
                get_context()
            report = _install(target, dry_run=True)
            assert not report.mcp_sync_failed
            with pytest.raises(LookupError):
                get_context()

        Context().run(run_without_context)

    @pytest.mark.parametrize("link_case", ["live", "broken"])
    def test_preview_does_not_follow_unrelated_vaultspec_symlinks(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
        link_case: str,
    ) -> None:
        _install(fresh_workspace)
        link = fresh_workspace / ".vaultspec" / f"operator-{link_case}"
        if link_case == "live":
            target = tmp_path / "operator-target"
            target.mkdir()
            (target / "sentinel").write_bytes(b"operator-owned\x00")
            (target / "nested-broken").symlink_to(
                "missing-nested-target",
                target_is_directory=True,
            )
            link.symlink_to(target, target_is_directory=True)
            target_before = workspace_inventory(target)
        else:
            link.symlink_to("missing-operator-target", target_is_directory=True)
            target = None
            target_before = None
        signature = _node_signature(link)

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        actual = _install(fresh_workspace, upgrade=True)

        assert not preview.mcp_sync_failed
        assert preview.to_dict()["sync_providers"] == actual.to_dict()["sync_providers"]
        assert _node_signature(link) == signature
        if target is not None:
            assert workspace_inventory(target) == target_before

    if os.name == "nt":

        def test_preview_does_not_follow_an_unrelated_windows_junction(
            self,
            fresh_workspace: Path,
            tmp_path: Path,
        ) -> None:
            _install(fresh_workspace)
            target = tmp_path / "operator-junction-target"
            target.mkdir()
            (target / "sentinel").write_bytes(b"operator-owned\x00")
            (target / "nested-broken").symlink_to(
                "missing-nested-target",
                target_is_directory=True,
            )
            junction = fresh_workspace / ".vaultspec" / "operator-junction"
            create_windows_junction(junction, target)
            signature = _node_signature(junction)
            target_before = workspace_inventory(target)

            preview = _install(fresh_workspace, dry_run=True, upgrade=True)
            actual = _install(fresh_workspace, upgrade=True)

            assert not preview.mcp_sync_failed
            assert (
                preview.to_dict()["sync_providers"]
                == actual.to_dict()["sync_providers"]
            )
            assert _node_signature(junction) == signature
            assert workspace_inventory(target) == target_before
