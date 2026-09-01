"""Real installation integration behavior: uninstall contracts."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path  # noqa: TC003

import pytest
from vaultspec_core.core.enums import (
    InstallMode,
)

from ...commands._uninstall import uninstall_run
from ._install_helpers import (
    _CONSUMER_PYPROJECT,
    _RAG_MCP_REL,
    _RAG_RULE_REL,
    _RAG_SKILL_REL,
    _install,
    read_codex_mcp,
    read_mcp_json,
    seed_core_mcp_source,
)

pytestmark = [pytest.mark.integration]


class TestUninstallSafety:
    def test_uninstall_without_force_is_dry_run(
        self, installed_workspace: Path
    ) -> None:
        report = uninstall_run(path=installed_workspace)
        assert report.action == "dry_run"
        # Files still present
        assert (installed_workspace / _RAG_RULE_REL).is_file()
        assert (installed_workspace / _RAG_MCP_REL).is_file()

    def test_uninstall_force_removes_only_rag_files(
        self, installed_workspace: Path
    ) -> None:
        report = uninstall_run(path=installed_workspace, force=True)
        assert report.action == "uninstall"
        assert not (installed_workspace / _RAG_RULE_REL).exists()
        assert not (installed_workspace / _RAG_MCP_REL).exists()
        # rag must never touch .vault/ documents
        assert (installed_workspace / ".vault").is_dir()
        # rag must never touch .vault/data/ unless --remove-data
        assert (installed_workspace / ".vault" / "data").is_dir()

    def test_uninstall_mcp_skip_preserves_the_complete_mcp_domain(
        self, fresh_workspace: Path
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        tracked = [
            pyproject,
            fresh_workspace / _RAG_MCP_REL,
            fresh_workspace / ".vaultspec" / "workspace.json",
            fresh_workspace / ".vaultspec" / "mcp-ownership.json",
            fresh_workspace / ".mcp.json",
            fresh_workspace / ".codex" / "config.toml",
        ]
        tracked.extend(
            path
            for path in fresh_workspace.rglob("*.lock")
            if path.is_file()
            and path.name
            in {
                "pyproject.toml.lock",
                "workspace.json.lock",
                "mcp-ownership.json.lock",
                ".mcp.json.lock",
                "config.toml.lock",
            }
            and path not in tracked
        )
        before = {path: path.read_bytes() for path in tracked}

        report = uninstall_run(path=fresh_workspace, force=True, skip={"mcp"})

        assert not report.mcp_sync_failed
        assert report.mcp_extra_action == "skipped"
        assert not report.to_dict()["sync_providers"]
        assert {path: path.read_bytes() for path in tracked} == before
        assert not (fresh_workspace / _RAG_RULE_REL).exists()
        assert not (fresh_workspace / _RAG_SKILL_REL).exists()
        assert (fresh_workspace / _RAG_MCP_REL).is_file()

    def test_uninstall_propagates_via_core_sync(
        self, installed_workspace: Path
    ) -> None:
        report = uninstall_run(path=installed_workspace, force=True)
        # The .mcp.json file is removed entirely once the only managed
        # entry is pruned (core's mcp_sync deletes the empty file).
        # If any user-added entries remained the file would persist;
        # there are none in this fixture.
        mcp_json = installed_workspace / ".mcp.json"
        if mcp_json.exists():
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            assert "vaultspec-rag" not in data.get("mcpServers", {})
        codex_config = installed_workspace / ".codex" / "config.toml"
        if codex_config.exists():
            assert "vaultspec-rag" not in read_codex_mcp(installed_workspace)
        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["pruned"] == 1
        assert providers["codex"]["pruned"] == 1

    def test_remove_data_purges_index_dir(self, installed_workspace: Path) -> None:
        # Drop a sentinel file in .vault/data/ to detect deletion
        (installed_workspace / ".vault" / "data" / "sentinel").write_text(
            "x", encoding="utf-8"
        )
        report = uninstall_run(path=installed_workspace, force=True, remove_data=True)
        assert report.data_removed
        assert not (installed_workspace / ".vault" / "data").exists()
        # .vault/ itself preserved
        assert (installed_workspace / ".vault").is_dir()


class TestUserContentPreservation:
    def test_preexisting_user_mcp_entry_survives_install(
        self, fresh_workspace: Path
    ) -> None:
        # Bootstrap minimum dirs and pre-populate .mcp.json with a
        # user-added entry that has nothing to do with rag.
        (fresh_workspace / ".vaultspec").mkdir()
        (fresh_workspace / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {"my-tool": {"command": "custom", "args": []}},
                    "_vaultspecManaged": [],
                }
            ),
            encoding="utf-8",
        )

        _install(fresh_workspace)
        data = read_mcp_json(fresh_workspace)
        # User entry survived
        assert data["mcpServers"]["my-tool"]["command"] == "custom"
        # rag's entry got added
        assert "vaultspec-rag" in data["mcpServers"]
        # User entry NOT taken into managed set
        ownership = (fresh_workspace / ".vaultspec" / "mcp-ownership.json").read_text(
            encoding="utf-8"
        )
        assert "my-tool" not in ownership
        assert "vaultspec-rag" in ownership

    def test_preexisting_user_mcp_entry_survives_uninstall(
        self, fresh_workspace: Path
    ) -> None:
        (fresh_workspace / ".vaultspec").mkdir()
        (fresh_workspace / ".mcp.json").write_text(
            json.dumps(
                {
                    "mcpServers": {"my-tool": {"command": "custom", "args": []}},
                    "_vaultspecManaged": [],
                }
            ),
            encoding="utf-8",
        )

        _install(fresh_workspace)
        uninstall_run(path=fresh_workspace, force=True)

        # The .mcp.json file persists because the user entry survives
        data = read_mcp_json(fresh_workspace)
        assert data["mcpServers"]["my-tool"]["command"] == "custom"
        assert "vaultspec-rag" not in data["mcpServers"]

    def test_preexisting_user_rule_file_survives_uninstall(
        self, installed_workspace: Path
    ) -> None:
        # Pre-existing user-authored rule must not be touched by rag
        # uninstall - it removes only its two named files.
        user_rule = installed_workspace / ".vaultspec" / "rules" / "my-custom-rule.md"
        user_rule.write_text("---\nname: custom\n---\n# user rule\n", encoding="utf-8")

        uninstall_run(path=installed_workspace, force=True)
        # The user rule survives uninstall (rag removes only its own named
        # files). vaultspec-core's sync migrates flat custom rules under
        # rules/project/, so accept either the original or migrated location.
        migrated_rule = (
            installed_workspace
            / ".vaultspec"
            / "rules"
            / "project"
            / "my-custom-rule.md"
        )
        assert user_rule.is_file() or migrated_rule.is_file()


class TestProviderLifecycleAcceptance:
    def test_uninstall_preserves_core_user_entries_and_fingerprints(
        self, fresh_workspace: Path
    ) -> None:
        seed_core_mcp_source(fresh_workspace)
        _install(fresh_workspace)
        claude_path = fresh_workspace / ".mcp.json"
        codex_path = fresh_workspace / ".codex" / "config.toml"
        ownership_path = fresh_workspace / ".vaultspec" / "mcp-ownership.json"

        claude = read_mcp_json(fresh_workspace)
        claude["mcpServers"]["user-tool"] = {"command": "custom", "args": []}
        claude_path.write_text(json.dumps(claude, indent=2) + "\n", encoding="utf-8")
        with codex_path.open("a", encoding="utf-8", newline="") as stream:
            stream.write('\n[mcp_servers.user-tool]\ncommand = "custom"\nargs = []\n')

        ownership_before = json.loads(ownership_path.read_text(encoding="utf-8"))
        core_fingerprints = {
            key: target["managed"]["vaultspec-core"]
            for key, target in ownership_before["targets"].items()
            if "vaultspec-core" in target["managed"]
        }
        core_claude = read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-core"]
        core_codex = read_codex_mcp(fresh_workspace)["vaultspec-core"]

        report = uninstall_run(path=fresh_workspace, force=True)

        claude_after = read_mcp_json(fresh_workspace)["mcpServers"]
        codex_after = read_codex_mcp(fresh_workspace)
        assert claude_after["vaultspec-core"] == core_claude
        assert codex_after["vaultspec-core"] == core_codex
        assert claude_after["user-tool"] == {"command": "custom", "args": []}
        assert codex_after["user-tool"] == {"command": "custom", "args": []}
        assert "vaultspec-rag" not in claude_after
        assert "vaultspec-rag" not in codex_after

        ownership_after = json.loads(ownership_path.read_text(encoding="utf-8"))
        assert {
            key: target["managed"]["vaultspec-core"]
            for key, target in ownership_after["targets"].items()
            if "vaultspec-core" in target["managed"]
        } == core_fingerprints
        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["pruned"] == 1
        assert providers["codex"]["pruned"] == 1

    def test_real_host_clis_recognize_project_entries(
        self, fresh_workspace: Path
    ) -> None:
        subprocess.run(
            ["git", "init", "-q"],
            cwd=fresh_workspace,
            check=True,
            timeout=30,
        )
        _install(fresh_workspace)

        claude = subprocess.run(
            ["claude", "mcp", "get", "vaultspec-rag"],
            cwd=fresh_workspace,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        assert claude.returncode == 0, claude.stderr or claude.stdout
        assert "vaultspec-rag" in claude.stdout
        assert "Scope: Project config" in claude.stdout

        codex_executable = "codex.cmd" if os.name == "nt" else "codex"
        codex_home = fresh_workspace.parent / "codex-home"
        codex_home.mkdir()
        project_key = str(fresh_workspace.resolve())
        if os.name == "nt":
            project_key = project_key.lower()
        (codex_home / "config.toml").write_text(
            f'[projects.{json.dumps(project_key)}]\ntrust_level = "trusted"\n',
            encoding="utf-8",
        )
        codex = subprocess.run(
            [codex_executable, "mcp", "get", "vaultspec-rag", "--json"],
            cwd=fresh_workspace,
            env={**os.environ, "CODEX_HOME": str(codex_home)},
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )
        assert codex.returncode == 0, codex.stderr or codex.stdout
        codex_entry = json.loads(codex.stdout)
        assert codex_entry["name"] == "vaultspec-rag"
        assert codex_entry["transport"]["command"] == "uvx"
        assert "vaultspec-rag[gpu,mcp]" in codex_entry["transport"]["args"]


class TestSymmetricRoundTrip:
    def test_install_then_uninstall_returns_to_clean_state(
        self, fresh_workspace: Path
    ) -> None:
        """Canonical correctness signal: installing then uninstalling
        leaves no rag-owned artefacts behind. This is the test that
        depends on vaultspec-core 0.1.10+'s reconciling mcp_sync.
        """
        _install(fresh_workspace)
        uninstall_run(path=fresh_workspace, force=True)

        # Both rag-owned source files are gone
        assert not (fresh_workspace / _RAG_RULE_REL).exists()
        assert not (fresh_workspace / _RAG_MCP_REL).exists()

        # No rag MCP entry lingers in .mcp.json (file may or may not
        # exist depending on whether other entries remain)
        mcp_json = fresh_workspace / ".mcp.json"
        if mcp_json.exists():
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            assert "vaultspec-rag" not in data.get("mcpServers", {})
        codex_config = fresh_workspace / ".codex" / "config.toml"
        if codex_config.exists():
            assert "vaultspec-rag" not in read_codex_mcp(fresh_workspace)

        # rag's local infrastructure (.vault/, .vault/data/) is
        # preserved unless --remove-data was passed
        assert (fresh_workspace / ".vault").is_dir()
        assert (fresh_workspace / ".vault" / "data").is_dir()


class TestReportSerialization:
    def test_install_report_to_dict_keys(self, fresh_workspace: Path) -> None:
        report = _install(fresh_workspace)
        d = report.to_dict()
        assert d["action"] == "install"
        assert d["target"] == str(fresh_workspace)
        assert isinstance(d["created_dirs"], list)
        assert isinstance(d["seeded"], list)
        assert "sync_added" in d
        # Must round-trip through json.dumps without error
        json.dumps(d)

    def test_uninstall_report_to_dict_keys(self, installed_workspace: Path) -> None:
        report = uninstall_run(path=installed_workspace, force=True)
        d = report.to_dict()
        assert d["action"] == "uninstall"
        assert isinstance(d["removed"], list)
        assert isinstance(d["data_removed"], bool)
        assert "sync_pruned" in d
        json.dumps(d)
