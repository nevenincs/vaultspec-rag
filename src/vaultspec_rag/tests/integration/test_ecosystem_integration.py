"""Ecosystem integration tests: vaultspec-core + vaultspec-rag cohabitation.

Verifies the companion-package integration model end-to-end:
vaultspec-core install → RAG companion files seeded → vaultspec-core sync
→ RAG rule and MCP server propagated to all providers.

These tests use subprocess calls to the installed vaultspec-core CLI,
targeting a temporary directory. No GPU or Qdrant required.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.integration]

# Path to RAG's companion files (relative to repo root)
_REPO_ROOT = Path(__file__).resolve().parents[4]
_RAG_RULE = _REPO_ROOT / ".vaultspec" / "rules" / "rules" / "vaultspec-rag.builtin.md"
_RAG_MCP_DEF = (
    _REPO_ROOT / ".vaultspec" / "rules" / "mcps" / "vaultspec-rag.builtin.json"
)

# Providers that core installs by default
_DEFAULT_PROVIDERS = ("claude", "gemini", "antigravity", "codex")

# Provider directory names (antigravity uses .agents/)
_PROVIDER_DIRS = {
    "claude": ".claude",
    "gemini": ".gemini",
    "antigravity": ".agents",
    "codex": ".codex",
}


def _run_core(
    *args: str,
    target: Path,
    timeout: int = 60,
) -> subprocess.CompletedProcess[str]:
    """Run a vaultspec-core CLI command targeting a directory."""
    cmd = [
        sys.executable,
        "-m",
        "vaultspec_core",
        *args,
        "--target",
        str(target),
    ]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )


@pytest.fixture(scope="module")
def workspace(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Create a fresh vaultspec workspace with RAG companion files.

    Steps:
      1. vaultspec-core install into temp dir
      2. Seed RAG builtin rule and MCP definition
      3. vaultspec-core sync to propagate
    """
    root = tmp_path_factory.mktemp("ecosystem")

    # Step 1: install core
    result = _run_core("install", target=root)
    assert result.returncode == 0, f"install failed: {result.stderr}"

    # Step 2: seed RAG companion files
    rules_dir = root / ".vaultspec" / "rules" / "rules"
    mcps_dir = root / ".vaultspec" / "rules" / "mcps"
    mcps_dir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(_RAG_RULE, rules_dir / _RAG_RULE.name)
    shutil.copy2(_RAG_MCP_DEF, mcps_dir / _RAG_MCP_DEF.name)

    # Step 3: sync (CLI display may crash due to core#54 but sync completes)
    _run_core("sync", target=root)

    # Also run MCP sync explicitly in case the main sync crashed before it
    _run_core("spec", "mcps", "sync", target=root)

    return root


class TestRulePropagatesToAllProviders:
    """Verify the RAG builtin rule lands in every provider's rules dir."""

    def test_rule_exists_in_all_providers(self, workspace: Path) -> None:
        for provider, dirname in _PROVIDER_DIRS.items():
            rule_path = workspace / dirname / "rules" / "vaultspec-rag.builtin.md"
            assert rule_path.exists(), (
                f"RAG rule missing in {provider} provider: {rule_path}"
            )

    def test_rule_content_has_rag_header(self, workspace: Path) -> None:
        rule = workspace / ".claude" / "rules" / "vaultspec-rag.builtin.md"
        content = rule.read_text(encoding="utf-8")
        assert "Vaultspec RAG" in content
        assert "GPU-accelerated search" in content

    def test_rule_documents_mcp_tools(self, workspace: Path) -> None:
        rule = workspace / ".claude" / "rules" / "vaultspec-rag.builtin.md"
        content = rule.read_text(encoding="utf-8")
        for tool in (
            "search_vault",
            "search_codebase",
            "get_index_status",
            "get_code_file",
            "reindex_vault",
            "reindex_codebase",
        ):
            assert tool in content, f"MCP tool {tool} not documented in rule"

    def test_rule_documents_cli_commands(self, workspace: Path) -> None:
        rule = workspace / ".claude" / "rules" / "vaultspec-rag.builtin.md"
        content = rule.read_text(encoding="utf-8")
        for cmd in (
            "index",
            "search",
            "status",
            "server mcp start",
            "server start",
        ):
            assert cmd in content, f"CLI command '{cmd}' not documented in rule"


class TestMcpRegistration:
    """Verify the RAG MCP server is registered in .mcp.json."""

    def test_mcp_json_has_rag_entry(self, workspace: Path) -> None:
        mcp_json = workspace / ".mcp.json"
        assert mcp_json.exists(), ".mcp.json not found"
        data = json.loads(mcp_json.read_text(encoding="utf-8"))
        servers = data.get("mcpServers", {})
        assert "vaultspec-rag" in servers, (
            f"vaultspec-rag not in .mcp.json servers: {list(servers.keys())}"
        )

    def test_mcp_entry_uses_correct_command(self, workspace: Path) -> None:
        data = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        entry = data["mcpServers"]["vaultspec-rag"]
        assert entry["command"] == "uv"
        assert "vaultspec-search-mcp" in entry["args"]

    def test_core_mcp_entry_preserved(self, workspace: Path) -> None:
        data = json.loads((workspace / ".mcp.json").read_text(encoding="utf-8"))
        assert "vaultspec-core" in data["mcpServers"], (
            "core MCP entry was clobbered by RAG registration"
        )


class TestProviderConfigEnrollment:
    """Verify provider configs enroll the RAG rule."""

    def test_claude_md_enrolls_rag_rule(self, workspace: Path) -> None:
        claude_md = workspace / "CLAUDE.md"
        assert claude_md.exists(), "CLAUDE.md not found"
        content = claude_md.read_text(encoding="utf-8")
        assert "vaultspec-rag.builtin.md" in content, (
            "RAG rule not enrolled in CLAUDE.md"
        )

    def test_gemini_md_exists(self, workspace: Path) -> None:
        assert (workspace / "GEMINI.md").exists()

    def test_agents_md_exists(self, workspace: Path) -> None:
        assert (workspace / "AGENTS.md").exists()


class TestWorkspaceStructure:
    """Verify the overall workspace structure is cohesive."""

    def test_vault_dir_exists(self, workspace: Path) -> None:
        assert (workspace / ".vault").is_dir()

    def test_vaultspec_dir_exists(self, workspace: Path) -> None:
        assert (workspace / ".vaultspec").is_dir()

    def test_rag_rule_source_exists(self, workspace: Path) -> None:
        assert (
            workspace / ".vaultspec" / "rules" / "rules" / "vaultspec-rag.builtin.md"
        ).exists()

    def test_rag_mcp_definition_exists(self, workspace: Path) -> None:
        assert (
            workspace / ".vaultspec" / "rules" / "mcps" / "vaultspec-rag.builtin.json"
        ).exists()

    def test_precommit_config_exists(self, workspace: Path) -> None:
        assert (workspace / ".pre-commit-config.yaml").exists()

    def test_precommit_has_canonical_hooks(self, workspace: Path) -> None:
        content = (workspace / ".pre-commit-config.yaml").read_text(
            encoding="utf-8",
        )
        for hook_id in (
            "vault-fix",
            "check-provider-artifacts",
            "spec-check",
        ):
            assert hook_id in content, (
                f"Canonical hook '{hook_id}' missing from .pre-commit-config.yaml"
            )


class TestCoreUninstallReinstallCycle:
    """Verify RAG companion files survive core uninstall/reinstall."""

    @pytest.fixture(scope="class")
    def reinstalled(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> Path:
        """Workspace that went through install → seed → uninstall → reinstall."""
        root = tmp_path_factory.mktemp("reinstall")

        # Install + seed
        _run_core("install", target=root)
        rules_dir = root / ".vaultspec" / "rules" / "rules"
        mcps_dir = root / ".vaultspec" / "rules" / "mcps"
        mcps_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_RAG_RULE, rules_dir / _RAG_RULE.name)
        shutil.copy2(_RAG_MCP_DEF, mcps_dir / _RAG_MCP_DEF.name)
        _run_core("sync", target=root)
        _run_core("spec", "mcps", "sync", target=root)

        # Uninstall (preserves .vault/)
        _run_core("uninstall", "--force", target=root)

        # Reinstall + re-seed
        _run_core("install", target=root)
        mcps_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_RAG_RULE, rules_dir / _RAG_RULE.name)
        shutil.copy2(_RAG_MCP_DEF, mcps_dir / _RAG_MCP_DEF.name)
        _run_core("sync", target=root)
        _run_core("spec", "mcps", "sync", target=root)

        return root

    def test_vault_preserved_after_uninstall(
        self,
        reinstalled: Path,
    ) -> None:
        assert (reinstalled / ".vault").is_dir()

    def test_providers_restored_after_reinstall(
        self,
        reinstalled: Path,
    ) -> None:
        for dirname in _PROVIDER_DIRS.values():
            assert (reinstalled / dirname).is_dir(), (
                f"Provider dir {dirname} not restored"
            )

    def test_rag_rule_in_providers_after_reinstall(
        self,
        reinstalled: Path,
    ) -> None:
        for provider, dirname in _PROVIDER_DIRS.items():
            rule = reinstalled / dirname / "rules" / "vaultspec-rag.builtin.md"
            assert rule.exists(), f"RAG rule missing in {provider} after reinstall"

    def test_mcp_entry_restored_after_reinstall(
        self,
        reinstalled: Path,
    ) -> None:
        data = json.loads(
            (reinstalled / ".mcp.json").read_text(encoding="utf-8"),
        )
        assert "vaultspec-rag" in data["mcpServers"]
        assert "vaultspec-core" in data["mcpServers"]


class TestCoreVaultManagement:
    """Verify core vault CRUD works alongside RAG companion files."""

    @pytest.fixture(scope="class")
    def vault_workspace(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> Path:
        """Workspace with vault documents for testing core vault commands."""
        root = tmp_path_factory.mktemp("vault-mgmt")

        _run_core("install", target=root)
        mcps_dir = root / ".vaultspec" / "rules" / "mcps"
        mcps_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            _RAG_RULE,
            root / ".vaultspec" / "rules" / "rules" / _RAG_RULE.name,
        )
        shutil.copy2(_RAG_MCP_DEF, mcps_dir / _RAG_MCP_DEF.name)
        _run_core("sync", target=root)
        _run_core("spec", "mcps", "sync", target=root)

        # Create test vault documents
        research_dir = root / ".vault" / "research"
        research_dir.mkdir(parents=True, exist_ok=True)
        (research_dir / "2026-04-11-cohabitation-research.md").write_text(
            '---\ntags:\n  - "#research"\n  - "#cohabitation"\n'
            "date: 2026-04-11\nrelated: []\n---\n\n"
            "# cohabitation research\n\nTest document.\n",
            encoding="utf-8",
        )
        return root

    def test_core_vault_list(self, vault_workspace: Path) -> None:
        result = _run_core("vault", "list", target=vault_workspace)
        assert "cohabitation" in result.stdout

    def test_core_vault_stats(self, vault_workspace: Path) -> None:
        result = _run_core("vault", "stats", target=vault_workspace)
        assert "research: 1" in result.stdout

    def test_core_spec_rules_includes_rag(
        self,
        vault_workspace: Path,
    ) -> None:
        result = _run_core(
            "spec",
            "rules",
            "list",
            target=vault_workspace,
        )
        assert "vaultspec-rag" in result.stdout

    def test_core_spec_mcps_includes_rag(
        self,
        vault_workspace: Path,
    ) -> None:
        result = _run_core(
            "spec",
            "mcps",
            "list",
            target=vault_workspace,
        )
        assert "vaultspec-rag" in result.stdout


class TestIdempotentSync:
    """Verify sync is idempotent - running twice produces same result."""

    @pytest.fixture(scope="class")
    def double_synced(
        self,
        tmp_path_factory: pytest.TempPathFactory,
    ) -> Path:
        root = tmp_path_factory.mktemp("idempotent")

        _run_core("install", target=root)
        mcps_dir = root / ".vaultspec" / "rules" / "mcps"
        mcps_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            _RAG_RULE,
            root / ".vaultspec" / "rules" / "rules" / _RAG_RULE.name,
        )
        shutil.copy2(_RAG_MCP_DEF, mcps_dir / _RAG_MCP_DEF.name)

        # Sync twice
        _run_core("sync", target=root)
        _run_core("spec", "mcps", "sync", target=root)
        _run_core("sync", target=root)
        _run_core("spec", "mcps", "sync", target=root)

        return root

    def test_no_duplicate_mcp_entries(
        self,
        double_synced: Path,
    ) -> None:
        data = json.loads(
            (double_synced / ".mcp.json").read_text(encoding="utf-8"),
        )
        assert len(data["mcpServers"]) == 2  # core + rag, not more

    def test_rule_not_duplicated(self, double_synced: Path) -> None:
        rules = list(
            (double_synced / ".claude" / "rules").glob(
                "vaultspec-rag*",
            ),
        )
        assert len(rules) == 1

    def test_claude_md_single_enrollment(
        self,
        double_synced: Path,
    ) -> None:
        content = (double_synced / "CLAUDE.md").read_text(encoding="utf-8")
        count = content.count("vaultspec-rag.builtin.md")
        assert count == 1, f"RAG rule enrolled {count} times in CLAUDE.md"
