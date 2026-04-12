"""Integration tests for ``vaultspec_rag.commands.install_run``/``uninstall_run``.

Real filesystem (``tmp_path``), real ``vaultspec_core`` (installed in the
dev environment via the project dependency), real bundled wheel content
via :mod:`vaultspec_rag.builtins`. No mocks, fakes, or stubs per the
project test mandate.

These tests pin the symmetric-mirror contract between install and
uninstall: install seeds rag's source files and runs core's sync;
uninstall removes the same files and runs the same sync. The
round-trip test (install → uninstall → workspace shape matches
pre-install) is the canonical correctness signal that depends on
vaultspec-core 0.1.10+'s reconciling ``mcp_sync``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from vaultspec_rag.commands import install_run, uninstall_run

pytestmark = [pytest.mark.integration]


_RAG_RULE_REL = Path(".vaultspec") / "rules" / "rules" / "vaultspec-rag.builtin.md"
_RAG_MCP_REL = Path(".vaultspec") / "rules" / "mcps" / "vaultspec-rag.builtin.json"


def _read_mcp_json(target: Path) -> dict:
    return json.loads((target / ".mcp.json").read_text(encoding="utf-8"))


@pytest.fixture()
def fresh_workspace(tmp_path: Path) -> Path:
    """An empty directory rag will bootstrap from scratch."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    return ws


@pytest.fixture()
def installed_workspace(tmp_path: Path) -> Path:
    """An empty directory with rag freshly installed (post-sync)."""
    ws = tmp_path / "workspace"
    ws.mkdir()
    install_run(path=ws)
    return ws


class TestFreshInstall:
    def test_creates_required_directories(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace)
        assert report.action == "install"
        assert (fresh_workspace / ".vault").is_dir()
        assert (fresh_workspace / ".vault" / "data").is_dir()
        assert (fresh_workspace / ".vaultspec" / "rules" / "rules").is_dir()
        assert (fresh_workspace / ".vaultspec" / "rules" / "mcps").is_dir()
        assert "vault" in " ".join(report.created_dirs)

    def test_seeds_both_bundled_files(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace)
        assert sorted(report.seeded) == [
            "mcps/vaultspec-rag.builtin.json",
            "rules/vaultspec-rag.builtin.md",
        ]
        assert (fresh_workspace / _RAG_RULE_REL).is_file()
        assert (fresh_workspace / _RAG_MCP_REL).is_file()

    def test_propagates_mcp_via_core_sync(self, fresh_workspace: Path) -> None:
        install_run(path=fresh_workspace)
        data = _read_mcp_json(fresh_workspace)
        assert "vaultspec-rag" in data["mcpServers"]
        assert "vaultspec-rag" in data.get("_vaultspecManaged", [])

    def test_mcp_command_matches_bundled_definition(
        self, fresh_workspace: Path
    ) -> None:
        install_run(path=fresh_workspace)
        data = _read_mcp_json(fresh_workspace)
        entry = data["mcpServers"]["vaultspec-rag"]
        assert entry["command"] == "uv"
        assert "vaultspec-search-mcp" in entry["args"]


class TestIdempotentInstall:
    def test_reinstall_is_noop_for_seeded_files(
        self, installed_workspace: Path
    ) -> None:
        report = install_run(path=installed_workspace)
        # Files already exist, no force/upgrade → seed nothing
        assert report.seeded == []
        # Files still present
        assert (installed_workspace / _RAG_RULE_REL).is_file()
        assert (installed_workspace / _RAG_MCP_REL).is_file()

    def test_upgrade_re_seeds_existing_files(self, installed_workspace: Path) -> None:
        # Mutate the seeded rule file to detect re-seeding
        rule_path = installed_workspace / _RAG_RULE_REL
        rule_path.write_text("MUTATED", encoding="utf-8")

        report = install_run(path=installed_workspace, upgrade=True)
        assert "rules/vaultspec-rag.builtin.md" in report.seeded
        assert rule_path.read_text(encoding="utf-8") != "MUTATED"

    def test_force_re_seeds_existing_files(self, installed_workspace: Path) -> None:
        rule_path = installed_workspace / _RAG_RULE_REL
        rule_path.write_text("MUTATED", encoding="utf-8")
        install_run(path=installed_workspace, force=True)
        assert rule_path.read_text(encoding="utf-8") != "MUTATED"


class TestDryRunInstall:
    def test_dry_run_creates_no_dirs_or_files(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace, dry_run=True)
        assert report.action == "dry_run"
        # Filesystem untouched
        assert not (fresh_workspace / ".vault").exists()
        assert not (fresh_workspace / ".vaultspec").exists()
        # Report still lists planned work
        assert report.created_dirs
        assert "rules/vaultspec-rag.builtin.md" in report.seeded

    def test_dry_run_does_not_invoke_sync(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace, dry_run=True)
        assert report.sync_results == []
        assert any("dry-run" in w for w in report.warnings)


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

    def test_uninstall_propagates_via_core_sync(
        self, installed_workspace: Path
    ) -> None:
        uninstall_run(path=installed_workspace, force=True)
        # The .mcp.json file is removed entirely once the only managed
        # entry is pruned (core's mcp_sync deletes the empty file).
        # If any user-added entries remained the file would persist;
        # there are none in this fixture.
        mcp_json = installed_workspace / ".mcp.json"
        if mcp_json.exists():
            data = json.loads(mcp_json.read_text(encoding="utf-8"))
            assert "vaultspec-rag" not in data.get("mcpServers", {})
            assert "vaultspec-rag" not in data.get("_vaultspecManaged", [])

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

        install_run(path=fresh_workspace)
        data = _read_mcp_json(fresh_workspace)
        # User entry survived
        assert data["mcpServers"]["my-tool"]["command"] == "custom"
        # rag's entry got added
        assert "vaultspec-rag" in data["mcpServers"]
        # User entry NOT taken into managed set
        assert "my-tool" not in data["_vaultspecManaged"]
        assert "vaultspec-rag" in data["_vaultspecManaged"]

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

        install_run(path=fresh_workspace)
        uninstall_run(path=fresh_workspace, force=True)

        # The .mcp.json file persists because the user entry survives
        data = _read_mcp_json(fresh_workspace)
        assert data["mcpServers"]["my-tool"]["command"] == "custom"
        assert "vaultspec-rag" not in data["mcpServers"]
        assert "vaultspec-rag" not in data.get("_vaultspecManaged", [])

    def test_preexisting_user_rule_file_survives_uninstall(
        self, installed_workspace: Path
    ) -> None:
        # Pre-existing user-authored rule must not be touched by rag
        # uninstall — it removes only its two named files.
        user_rule = (
            installed_workspace / ".vaultspec" / "rules" / "rules" / "my-custom-rule.md"
        )
        user_rule.write_text("---\nname: custom\n---\n# user rule\n", encoding="utf-8")

        uninstall_run(path=installed_workspace, force=True)
        assert user_rule.is_file()


class TestSymmetricRoundTrip:
    def test_install_then_uninstall_returns_to_clean_state(
        self, fresh_workspace: Path
    ) -> None:
        """Canonical correctness signal: installing then uninstalling
        leaves no rag-owned artefacts behind. This is the test that
        depends on vaultspec-core 0.1.10+'s reconciling mcp_sync.
        """
        install_run(path=fresh_workspace)
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
            assert "vaultspec-rag" not in data.get("_vaultspecManaged", [])

        # rag's local infrastructure (.vault/, .vault/data/) is
        # preserved unless --remove-data was passed
        assert (fresh_workspace / ".vault").is_dir()
        assert (fresh_workspace / ".vault" / "data").is_dir()


class TestReportSerialization:
    def test_install_report_to_dict_keys(self, fresh_workspace: Path) -> None:
        report = install_run(path=fresh_workspace)
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
