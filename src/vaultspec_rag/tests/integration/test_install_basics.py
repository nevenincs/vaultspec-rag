"""Real installation integration behavior: basics."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003

import pytest
from vaultspec_core.core.manifest import (
    read_manifest,
    write_manifest,
)

from ._install_helpers import (
    _RAG_MCP_REL,
    _RAG_RULE_REL,
    _RAG_SKILL_REL,
    _install,
    read_codex_mcp,
    read_mcp_json,
    workspace_inventory,
)

pytestmark = [pytest.mark.integration]


class TestFreshInstall:
    def test_corrupt_provider_intent_fails_closed_before_any_workspace_mutation(
        self, fresh_workspace: Path
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        vaultspec = fresh_workspace / ".vaultspec"
        vaultspec.mkdir()
        (vaultspec / "providers.json").write_bytes(b"{corrupt-provider-intent")
        (vaultspec / "providers.json.lock").write_bytes(b"operator-lock")
        (vaultspec / "mcps").mkdir()
        (vaultspec / "mcps" / "operator.json").write_bytes(b'{"operator": true}\n')
        (vaultspec / "mcp-ownership.json").write_bytes(
            b'{"version": 1, "targets": {}}\n'
        )
        (fresh_workspace / ".mcp.json").write_bytes(
            b'{"mcpServers": {"operator": {"command": "operator"}}}\n'
        )
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.parent.mkdir()
        codex.write_bytes(b'[mcp_servers.operator]\ncommand = "operator"\n')
        (fresh_workspace / "pyproject.toml").write_bytes(
            b'[project]\nname = "operator"\nversion = "1.0.0"\n'
        )
        before = workspace_inventory(fresh_workspace)

        result = CliRunner().invoke(
            app,
            [
                "install",
                "--target",
                str(fresh_workspace),
                "--no-provision",
                "--no-torch-config",
                "--mcp",
                "--json",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 2, result.output
        report = json.loads(result.output)
        assert report["mcp_failed"] is True
        assert "provider intent is unreadable" in " ".join(report["mcp_errors"])
        assert workspace_inventory(fresh_workspace) == before

    def test_cli_selects_both_project_hosts_without_a_seeded_manifest(
        self, fresh_workspace: Path
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        assert not (fresh_workspace / ".vaultspec" / "providers.json").exists()
        result = CliRunner().invoke(
            app,
            [
                "install",
                "--target",
                str(fresh_workspace),
                "--no-provision",
                "--no-torch-config",
                "--mcp",
                "--json",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        report = json.loads(result.output)
        assert report["mcp_failed"] is False
        assert set(report["sync_providers"]) == {"claude", "codex"}
        assert read_manifest(fresh_workspace) == {"claude", "codex"}
        assert "vaultspec-rag" in read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" in read_codex_mcp(fresh_workspace)

    def test_fresh_provider_selection_merges_unrelated_manifest_entries(
        self, fresh_workspace: Path
    ) -> None:
        write_manifest(fresh_workspace, {"gemini"})

        report = _install(fresh_workspace)

        assert not report.mcp_sync_failed
        assert read_manifest(fresh_workspace) == {"claude", "codex", "gemini"}
        assert set(report.to_dict()["sync_providers"]) == {"claude", "codex"}

    def test_provider_manifest_persistence_failure_restores_prior_bytes(
        self, fresh_workspace: Path
    ) -> None:
        write_manifest(fresh_workspace, {"gemini"})
        manifest = fresh_workspace / ".vaultspec" / "providers.json"
        lock = manifest.with_suffix(".json.lock")
        claude = fresh_workspace / ".mcp.json"
        claude.write_bytes(b'{"mcpServers": {"operator": {"command": "operator"}}}\n')
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.parent.mkdir()
        codex.write_bytes(b'[mcp_servers.operator]\ncommand = "operator"\n')
        before = {
            manifest: manifest.read_bytes(),
            claude: claude.read_bytes(),
            codex: codex.read_bytes(),
        }
        lock.unlink(missing_ok=True)
        lock.mkdir()

        report = _install(fresh_workspace)

        assert report.mcp_sync_failed
        assert {path: path.read_bytes() for path in before} == before
        assert read_manifest(fresh_workspace) == {"gemini"}
        assert lock.is_dir()
        assert not (fresh_workspace / ".mcp.json.lock").exists()
        assert not (fresh_workspace / ".codex" / "config.toml.lock").exists()
        assert not (fresh_workspace / ".vaultspec" / "mcp-ownership.json").exists()
        assert not (fresh_workspace / ".vaultspec" / "mcp-ownership.json.lock").exists()
        assert any("provider enrollment failed" in item for item in report.mcp_errors)

    def test_creates_required_directories(self, fresh_workspace: Path) -> None:
        report = _install(fresh_workspace)
        assert report.action == "install"
        assert (fresh_workspace / ".vault").is_dir()
        assert (fresh_workspace / ".vault" / "data").is_dir()
        # rag folds its builtins flat into .vaultspec/ like core (rules/, mcps/,
        # skills/), not double-nested under .vaultspec/rules/.
        assert (fresh_workspace / ".vaultspec" / "rules").is_dir()
        assert (fresh_workspace / ".vaultspec" / "mcps").is_dir()
        assert (fresh_workspace / ".vaultspec" / "skills").is_dir()
        assert "vault" in " ".join(report.created_dirs)

    def test_seeds_bundled_files(self, fresh_workspace: Path) -> None:
        report = _install(fresh_workspace)
        # (path, action) pairs, matching core's seeder; a fresh install adds all.
        assert sorted(report.seeded) == [
            ("mcps/vaultspec-rag.builtin.json", "[ADD]"),
            ("rules/vaultspec-rag.builtin.md", "[ADD]"),
            ("skills/vaultspec-rag-discovery/SKILL.md", "[ADD]"),
        ]
        assert (fresh_workspace / _RAG_RULE_REL).is_file()
        assert (fresh_workspace / _RAG_MCP_REL).is_file()
        assert (fresh_workspace / _RAG_SKILL_REL).is_file()

    def test_propagates_mcp_via_core_sync(self, fresh_workspace: Path) -> None:
        _install(fresh_workspace)
        assert "vaultspec-rag" in read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" in read_codex_mcp(fresh_workspace)
        ownership = json.loads(
            (fresh_workspace / ".vaultspec" / "mcp-ownership.json").read_text(
                encoding="utf-8"
            )
        )
        assert "vaultspec-rag" in json.dumps(ownership)

    def test_mcp_command_matches_bundled_definition(
        self, fresh_workspace: Path
    ) -> None:
        _install(fresh_workspace)
        claude_entry = read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]
        codex_entry = read_codex_mcp(fresh_workspace)["vaultspec-rag"]
        expected_args = [
            "--from",
            "vaultspec-rag[mcp]",
            "python",
            "-m",
            "vaultspec_rag.server",
        ]
        assert claude_entry == {"command": "uvx", "args": expected_args}
        assert codex_entry == {"command": "uvx", "args": expected_args}


class TestIdempotentInstall:
    def test_reinstall_is_noop_for_seeded_files(
        self, installed_workspace: Path
    ) -> None:
        report = _install(installed_workspace)
        # Files already exist, no force/upgrade → seed nothing
        assert report.seeded == []
        # Files still present
        assert (installed_workspace / _RAG_RULE_REL).is_file()
        assert (installed_workspace / _RAG_MCP_REL).is_file()

    def test_upgrade_re_seeds_existing_files(self, installed_workspace: Path) -> None:
        # Mutate the seeded rule file to detect re-seeding
        rule_path = installed_workspace / _RAG_RULE_REL
        rule_path.write_text("MUTATED", encoding="utf-8")

        report = _install(installed_workspace, upgrade=True)
        # The mutated file is re-seeded as an [UPDATE].
        assert ("rules/vaultspec-rag.builtin.md", "[UPDATE]") in report.seeded
        assert rule_path.read_text(encoding="utf-8") != "MUTATED"

    def test_force_re_seeds_existing_files(self, installed_workspace: Path) -> None:
        rule_path = installed_workspace / _RAG_RULE_REL
        rule_path.write_text("MUTATED", encoding="utf-8")
        _install(installed_workspace, force=True)
        assert rule_path.read_text(encoding="utf-8") != "MUTATED"
