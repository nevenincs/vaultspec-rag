"""Real install and uninstall acceptance across native MCP host targets.

The suite uses real temporary workspaces, Core provider enrollment, RAG's bundled
sources, and the installed Claude Code and Codex CLIs. It proves dry-run byte safety,
provider-local drift reporting and repair, exact repeat-install stability, selective
unenrollment, user and Core sibling preservation, and host recognition without mocks,
fakes, stubs, patches, or skipped behavior.
"""

from __future__ import annotations

import io
import json
import os
import stat
import subprocess
import tomllib
from contextvars import Context
from importlib.resources import files
from pathlib import Path
from threading import Event, Thread
from typing import TYPE_CHECKING, Any

import pytest
from vaultspec_core.config.workspace import (  # pyright: ignore[reportMissingTypeStubs]
    resolve_workspace,
)
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,
)
from vaultspec_core.core.manifest import (  # pyright: ignore[reportMissingTypeStubs]
    read_manifest,
    write_manifest,
)
from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
    get_context,
    init_paths,
)
from vaultspec_core.core.workspace_mode import (  # pyright: ignore[reportMissingTypeStubs]
    read_package_declaration,
)

from ...commands import install_run, uninstall_run

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = [pytest.mark.integration]


_RAG_RULE_REL = Path(".vaultspec") / "rules" / "vaultspec-rag.builtin.md"
_RAG_MCP_REL = Path(".vaultspec") / "mcps" / "vaultspec-rag.builtin.json"
_RAG_SKILL_REL = Path(".vaultspec") / "skills" / "vaultspec-rag-discovery" / "SKILL.md"
_REQUIRED_MCP_RELATIVES = (
    Path(".mcp.json"),
    Path(".codex") / "config.toml",
    Path(".vaultspec") / "mcp-ownership.json",
    Path(".vaultspec") / "providers.json",
    Path(".vaultspec") / "workspace.json",
    _RAG_MCP_REL,
)

_CONSUMER_PYPROJECT = (
    "[project]\n"
    'name = "demo-consumer"\n'
    'version = "0.1.0"\n'
    'dependencies = ["vaultspec-rag"]\n'
)


def _read_mcp_json(target: Path) -> dict[str, Any]:
    return json.loads((target / ".mcp.json").read_text(encoding="utf-8"))


def _read_codex_mcp(target: Path) -> dict[str, Any]:
    raw = tomllib.loads((target / ".codex" / "config.toml").read_text(encoding="utf-8"))
    return raw["mcp_servers"]


def _workspace_file_bytes(target: Path) -> dict[str, bytes]:
    """Capture every real workspace file for byte-inert preview assertions."""
    return {
        path.relative_to(target).as_posix(): path.read_bytes()
        for path in target.rglob("*")
        if path.is_file()
    }


def _workspace_inventory(target: Path) -> dict[str, tuple[str, bytes]]:
    return {
        path.relative_to(target).as_posix(): (
            ("file", path.read_bytes()) if path.is_file() else ("directory", b"")
        )
        for path in target.rglob("*")
    }


def _node_signature(path: Path) -> tuple[str, str | int, bool]:
    if path.is_junction():
        return ("junction", os.readlink(path), True)
    if path.is_symlink():
        metadata = path.lstat()
        attributes = int(getattr(metadata, "st_file_attributes", 0))
        is_directory = path.is_dir() or bool(
            attributes & getattr(stat, "FILE_ATTRIBUTE_DIRECTORY", 0)
        )
        return ("symlink", os.readlink(path), is_directory)
    return ("node", stat.S_IFMT(path.lstat().st_mode), path.is_dir())


def _required_mcp_transaction_inventory(
    target: Path,
) -> dict[str, tuple[tuple[str, str | int, bool] | None, bytes | None]]:
    required = (
        *(target / relative for relative in _REQUIRED_MCP_RELATIVES),
        target / "pyproject.toml",
    )
    paths = (
        *required,
        *(path.with_suffix(path.suffix + ".lock") for path in required),
    )
    return {
        path.relative_to(target).as_posix(): (
            _node_signature(path) if path.exists() or path.is_symlink() else None,
            path.read_bytes() if path.is_file() else None,
        )
        for path in paths
    }


def _create_windows_junction(path: Path, target: Path) -> None:
    environment = {
        **os.environ,
        "VAULTSPEC_TEST_JUNCTION_PATH": str(path),
        "VAULTSPEC_TEST_JUNCTION_TARGET": str(target),
    }
    command = (
        "$ErrorActionPreference = 'Stop'; "
        "New-Item -ItemType Junction -Path $env:VAULTSPEC_TEST_JUNCTION_PATH "
        "-Target $env:VAULTSPEC_TEST_JUNCTION_TARGET | Out-Null"
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        check=True,
        capture_output=True,
        env=environment,
        text=True,
    )


def _install(target: Path, **overrides: Any) -> Any:
    """Run a network-free dual-provider install with MCP intent enabled."""
    options: dict[str, Any] = {
        "install_mcp": True,
        "configure_torch": False,
        "provision": False,
    }
    options.update(overrides)
    return install_run(path=target, **options)


def _seed_core_mcp_source(target: Path) -> None:
    source = files("vaultspec_core.builtins") / "mcps" / "vaultspec-core.builtin.json"
    destination = target / ".vaultspec" / "mcps" / "vaultspec-core.builtin.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    write_manifest(target, {"claude", "codex"})


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
    _install(ws)
    return ws


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
        before = _workspace_inventory(fresh_workspace)

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
        assert _workspace_inventory(fresh_workspace) == before

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
        assert "vaultspec-rag" in _read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" in _read_codex_mcp(fresh_workspace)

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
        assert "vaultspec-rag" in _read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" in _read_codex_mcp(fresh_workspace)
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
        claude_entry = _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]
        codex_entry = _read_codex_mcp(fresh_workspace)["vaultspec-rag"]
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
        claude = _read_mcp_json(fresh_workspace)
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
        before = _workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        report = _install(fresh_workspace, dry_run=True)

        assert _workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["added"] == 1
        assert providers["codex"]["added"] == 1
        assert providers["claude"]["items"] == [["vaultspec-rag", "[ADD]"]]
        assert providers["codex"]["items"] == [["vaultspec-rag", "[ADD]"]]

    def test_fresh_explicit_mode_preview_matches_real_without_synthetic_pass(
        self, fresh_workspace: Path
    ) -> None:
        before = _workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            mode=InstallMode.TOOL,
        )

        assert _workspace_file_bytes(fresh_workspace) == before
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
        before = _workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            mode=InstallMode.TOOL,
        )

        assert _workspace_file_bytes(fresh_workspace) == before
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
        assert _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"] == (
            user_entry
        )
        assert _read_codex_mcp(fresh_workspace)["vaultspec-rag"]["command"] == "uvx"

    def test_no_mcp_dry_run_reports_native_prunes_without_writing(
        self, installed_workspace: Path
    ) -> None:
        before = _workspace_file_bytes(installed_workspace)
        locks_before = sorted(installed_workspace.rglob("*.lock"))

        report = _install(
            installed_workspace,
            dry_run=True,
            install_mcp=False,
        )

        assert _workspace_file_bytes(installed_workspace) == before
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
        fresh_before = _workspace_file_bytes(fresh_workspace)
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
        assert _workspace_file_bytes(fresh_workspace) == fresh_before

        installed_workspace = tmp_path / "installed"
        installed_workspace.mkdir()
        _install(installed_workspace)
        installed_before = _workspace_file_bytes(installed_workspace)
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
        assert _workspace_file_bytes(installed_workspace) == installed_before

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
            target_before = _workspace_inventory(target)
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
            assert _workspace_inventory(target) == target_before

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
            _create_windows_junction(junction, target)
            signature = _node_signature(junction)
            target_before = _workspace_inventory(target)

            preview = _install(fresh_workspace, dry_run=True, upgrade=True)
            actual = _install(fresh_workspace, upgrade=True)

            assert not preview.mcp_sync_failed
            assert (
                preview.to_dict()["sync_providers"]
                == actual.to_dict()["sync_providers"]
            )
            assert _node_signature(junction) == signature
            assert _workspace_inventory(target) == target_before

    @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
    def test_required_relative_file_link_preserves_preview_apply_parity(
        self,
        fresh_workspace: Path,
        relative: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / relative
        linked_target = node.with_name(f"{node.name}.operator")
        node.replace(linked_target)
        node.symlink_to(linked_target.name)
        link_signature = _node_signature(node)
        target_before_preview = linked_target.read_bytes()

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert not preview.mcp_sync_failed
        assert _node_signature(node) == link_signature
        assert linked_target.read_bytes() == target_before_preview
        applied = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        assert not applied.mcp_sync_failed
        assert (
            preview.to_dict()["sync_providers"] == applied.to_dict()["sync_providers"]
        )
        assert _node_signature(node) == link_signature
        assert node.read_bytes() == linked_target.read_bytes()

        repeated = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert not repeated.mcp_sync_failed
        assert _node_signature(node) == link_signature
        assert linked_target.is_file()
        assert node.read_bytes() == linked_target.read_bytes()

    @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
    def test_required_relative_file_link_publishes_logical_delta_to_target(
        self,
        fresh_workspace: Path,
        relative: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / relative
        linked_target = node.with_name(f"{node.name}.operator")
        node.replace(linked_target)
        node.symlink_to(linked_target.name)
        link_signature = _node_signature(node)

        if relative == Path(".mcp.json"):
            linked_target.write_text(
                linked_target.read_text(encoding="utf-8").replace(
                    '"command": "uvx"',
                    '"command": "operator-drift"',
                    1,
                ),
                encoding="utf-8",
            )
        elif relative == Path(".codex") / "config.toml":
            linked_target.write_text(
                linked_target.read_text(encoding="utf-8").replace(
                    'command = "uvx"',
                    'command = "operator-drift"',
                    1,
                ),
                encoding="utf-8",
            )
        elif relative == Path(".vaultspec") / "mcp-ownership.json":
            state = json.loads(linked_target.read_text(encoding="utf-8"))
            del state["targets"]["claude:project"]
            linked_target.write_text(
                json.dumps(state, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        elif relative == Path(".vaultspec") / "providers.json":
            manifest = json.loads(linked_target.read_text(encoding="utf-8"))
            manifest["installed"] = []
            linked_target.write_text(
                json.dumps(manifest, indent=2) + "\n",
                encoding="utf-8",
            )
        elif relative == Path(".vaultspec") / "workspace.json":
            workspace = json.loads(linked_target.read_text(encoding="utf-8"))
            workspace["packages"]["vaultspec-rag"]["install_mode"] = "dependency"
            linked_target.write_text(
                json.dumps(workspace, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        else:
            definition = json.loads(linked_target.read_text(encoding="utf-8"))
            definition["_vaultspec_mode_tool_spec"] = "operator-drift"
            linked_target.write_text(
                json.dumps(definition, indent=2) + "\n",
                encoding="utf-8",
            )
        drifted = linked_target.read_bytes()

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )
        assert _node_signature(node) == link_signature
        assert linked_target.read_bytes() == drifted
        applied = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert not preview.mcp_sync_failed
        assert not applied.mcp_sync_failed
        assert (
            preview.to_dict()["sync_providers"] == applied.to_dict()["sync_providers"]
        )
        assert _node_signature(node) == link_signature
        assert linked_target.read_bytes() != drifted
        assert node.read_bytes() == linked_target.read_bytes()
        repeated = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )
        assert not repeated.mcp_sync_failed
        assert _node_signature(node) == link_signature
        assert node.read_bytes() == linked_target.read_bytes()

    def test_failed_native_reconciliation_restores_link_and_target_exactly(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        claude = fresh_workspace / ".mcp.json"
        linked_target = fresh_workspace / ".mcp.operator.json"
        claude.replace(linked_target)
        claude.symlink_to(linked_target.name)
        linked_target.write_text(
            linked_target.read_text(encoding="utf-8").replace(
                '"command": "uvx"',
                '"command": "operator-drift"',
                1,
            ),
            encoding="utf-8",
        )
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        signature = _node_signature(claude)
        target_before = linked_target.read_bytes()
        codex_before = codex.read_bytes()

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert report.mcp_sync_failed
        assert _node_signature(claude) == signature
        assert linked_target.read_bytes() == target_before
        assert codex.read_bytes() == codex_before

    def test_failed_native_reconciliation_restores_all_regular_required_nodes(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        before = _required_mcp_transaction_inventory(fresh_workspace)

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert report.mcp_sync_failed
        assert _required_mcp_transaction_inventory(fresh_workspace) == before
        assert codex.read_bytes() == b'invalid = "unterminated'

    def test_partial_ownership_update_uses_real_root_replay_token(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        ownership = fresh_workspace / ".vaultspec" / "mcp-ownership.json"
        state = json.loads(ownership.read_text(encoding="utf-8"))
        del state["targets"]["claude:project"]
        ownership.write_text(
            json.dumps(state, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        before = _required_mcp_transaction_inventory(fresh_workspace)

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            mode=InstallMode.TOOL,
        )

        assert report.mcp_sync_failed
        assert _required_mcp_transaction_inventory(fresh_workspace) == before
        assert not any(
            "mcp-ownership.json: concurrent update preserved" in warning
            for warning in report.warnings
        )

    def test_mode_migration_finishes_before_non_mcp_provider_sync(
        self,
        fresh_workspace: Path,
    ) -> None:
        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT,
            encoding="utf-8",
        )
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        documents = (
            fresh_workspace / "CLAUDE.md",
            fresh_workspace / "AGENTS.md",
        )
        for document in documents:
            document.unlink(missing_ok=True)
        codex = fresh_workspace / ".codex" / "config.toml"
        documents_seen = Event()
        stop = Event()

        def corrupt_codex_after_documents() -> None:
            while not stop.wait(0.001):
                if all(document.is_file() for document in documents):
                    codex.write_text('invalid = "unterminated', encoding="utf-8")
                    documents_seen.set()
                    return

        watcher = Thread(target=corrupt_codex_after_documents, daemon=True)
        watcher.start()
        try:
            report = _install(
                fresh_workspace,
                upgrade=True,
                force=False,
                mode=InstallMode.TOOL,
            )
            documents_seen.wait(2)
        finally:
            stop.set()
            watcher.join(timeout=2)

        assert documents_seen.is_set()
        assert not report.mcp_sync_failed
        assert all(document.is_file() for document in documents)

    def test_all_canonical_source_links_have_preview_apply_parity(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        source_dir = fresh_workspace / ".vaultspec" / "mcps"
        linked_target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        linked_target.write_bytes((fresh_workspace / _RAG_MCP_REL).read_bytes())
        source = source_dir / "operator-extra.builtin.json"
        source.symlink_to(os.path.relpath(linked_target, source.parent))
        source_signature = _node_signature(source)
        target_before = linked_target.read_bytes()

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        applied = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert not preview.mcp_sync_failed
        assert not applied.mcp_sync_failed
        assert (
            preview.to_dict()["sync_providers"] == applied.to_dict()["sync_providers"]
        )
        for provider in ("claude", "codex"):
            assert ["operator-extra", "[ADD]"] in preview.to_dict()["sync_providers"][
                provider
            ]["items"]
        assert _node_signature(source) == source_signature
        assert linked_target.read_bytes() == target_before

    @pytest.mark.parametrize(
        "link_case",
        ["outside-relative", "broken-relative", "absolute", "chained"],
    )
    def test_unsafe_extra_canonical_source_link_fails_with_parity(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
        link_case: str,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        source = fresh_workspace / ".vaultspec" / "mcps" / "operator-extra.builtin.json"
        local_target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        local_target.write_bytes((fresh_workspace / _RAG_MCP_REL).read_bytes())
        if link_case == "outside-relative":
            target = tmp_path / "outside-operator-extra.json"
            target.write_bytes(local_target.read_bytes())
            link_text = os.path.relpath(target, source.parent)
        elif link_case == "absolute":
            target = local_target
            link_text = str(target.resolve())
        elif link_case == "chained":
            target = local_target
            intermediate = source.parent / "operator-extra.intermediate.json"
            intermediate.symlink_to(os.path.relpath(target, intermediate.parent))
            link_text = intermediate.name
        else:
            target = None
            link_text = "missing-operator-extra.json"
        source.symlink_to(link_text)
        before = _workspace_inventory(fresh_workspace)

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert _workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("linked_target", [False, True])
    def test_required_hardlink_topology_fails_closed_before_mutation(
        self,
        fresh_workspace: Path,
        linked_target: bool,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / ".mcp.json"
        if linked_target:
            target = fresh_workspace / ".mcp.operator.json"
            node.replace(target)
            alias = fresh_workspace / ".mcp.operator.alias.json"
            os.link(target, alias)
            node.symlink_to(target.name)
        else:
            target = node
            alias = fresh_workspace / ".mcp.alias.json"
            os.link(target, alias)
        before = _workspace_inventory(fresh_workspace)
        inode_pair = (target.stat().st_ino, alias.stat().st_ino)

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert "hard links" in " ".join(preview.mcp_errors)
        assert _workspace_inventory(fresh_workspace) == before
        assert (target.stat().st_ino, alias.stat().st_ino) == inode_pair

    def test_pre_materialization_race_preserves_newer_required_bytes(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        node = fresh_workspace / ".mcp.json"
        concurrent = b'{"operator": "newer"}\n'
        node.write_bytes(concurrent)

        with pytest.raises(OSError, match="changed during transaction"):
            topology.materialize()

        assert node.read_bytes() == concurrent

    def test_in_flight_regular_node_race_is_preserved_on_rollback(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        topology.materialize()
        node = fresh_workspace / ".mcp.json"
        concurrent = b'{"operator": "newer"}\n'
        node.write_bytes(concurrent)

        errors = topology.finish(commit=False)

        assert errors
        assert "concurrent update preserved" in " ".join(errors)
        assert node.read_bytes() == concurrent

    def test_post_mutation_cas_preserves_later_regular_node_update(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        topology.materialize()
        node = fresh_workspace / ".mcp.json"
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)
        node.write_bytes(b'{"transaction": "authored"}\n')
        concurrent = b'{"operator": "newer"}\n'
        node.write_bytes(concurrent)

        errors = topology.finish(commit=False)

        assert errors
        assert "concurrent update preserved" in " ".join(errors)
        assert node.read_bytes() == concurrent

    def test_replay_token_preserves_pre_rollback_atomic_operator_save(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)
        node = fresh_workspace / ".mcp.json"
        replacement = fresh_workspace / ".operator-save.json"
        concurrent = b'{"operator": "atomic-newer"}\n'
        replacement.write_bytes(concurrent)
        os.replace(replacement, node)

        errors = topology.finish(commit=False)

        assert errors
        assert node.read_bytes() == concurrent

    def test_replay_token_preserves_operator_created_absent_node(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)
        node = fresh_workspace / ".mcp.json"
        concurrent = b'{"operator": "created-newer"}\n'
        node.write_bytes(concurrent)

        errors = topology.finish(commit=False)

        assert errors
        assert node.read_bytes() == concurrent

    def test_replay_token_restores_same_inode_transaction_publication(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        node = fresh_workspace / ".mcp.json"
        original = node.read_bytes()
        authored = b'{"transaction": "copy-fallback"}\n'
        (projection / ".mcp.json").write_bytes(authored)
        topology.capture_expected_projection(projection)
        inode = node.stat().st_ino
        node.write_bytes(authored)
        assert node.stat().st_ino == inode

        errors = topology.finish(commit=False)

        assert not errors
        assert node.read_bytes() == original

    def test_replay_token_restores_link_after_immediate_materialized_abort(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / ".mcp.json"
        target = fresh_workspace / ".mcp.operator.json"
        node.replace(target)
        node.symlink_to(target.name)
        signature = _node_signature(node)
        original = target.read_bytes()
        topology = inspect_required_mcp_topology(fresh_workspace)
        projection = tmp_path / "replay"
        topology.populate_projection(projection)
        (projection / ".mcp.json").write_bytes(b'{"transaction": "authored"}\n')
        topology.capture_expected_projection(projection)

        topology.materialize()
        errors = topology.finish(commit=False)

        assert not errors
        assert _node_signature(node) == signature
        assert node.read_bytes() == original

    def test_materialize_write_failure_restores_just_removed_link(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        source_dir = fresh_workspace / ".vaultspec" / "mcps"
        source_dir.mkdir(parents=True)
        target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        target.write_bytes(b'{"command": "operator", "args": []}\n')
        source = source_dir / ("operator-" + "x" * 225 + ".json")
        source.symlink_to(os.path.relpath(target, source.parent))
        signature = _node_signature(source)
        topology = inspect_required_mcp_topology(fresh_workspace)

        with pytest.raises(OSError):
            topology.materialize()

        assert _node_signature(source) == signature
        assert source.read_bytes() == target.read_bytes()

    def test_link_target_race_is_preserved_on_commit_refusal(
        self,
        fresh_workspace: Path,
    ) -> None:
        from ...commands._mcp_topology import inspect_required_mcp_topology

        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / ".mcp.json"
        target = fresh_workspace / ".mcp.operator.json"
        node.replace(target)
        node.symlink_to(target.name)
        link_signature = _node_signature(node)
        topology = inspect_required_mcp_topology(fresh_workspace)
        topology.materialize()
        concurrent = b'{"operator": "newer"}\n'
        target.write_bytes(concurrent)

        errors = topology.finish(commit=True)

        assert errors
        assert target.read_bytes() == concurrent
        assert _node_signature(node) == link_signature

    def test_failed_no_mcp_restores_dependency_placement_exactly(
        self,
        fresh_workspace: Path,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        codex = fresh_workspace / ".codex" / "config.toml"
        codex.write_text('invalid = "unterminated', encoding="utf-8")
        before = _required_mcp_transaction_inventory(fresh_workspace)

        report = _install(
            fresh_workspace,
            upgrade=True,
            force=True,
            install_mcp=False,
            mode=InstallMode.DEPENDENCY,
        )

        assert report.mcp_sync_failed
        assert _required_mcp_transaction_inventory(fresh_workspace) == before

    @pytest.mark.parametrize("operation", ["no-mcp", "uninstall"])
    def test_unrelated_safe_linked_source_does_not_block_disenrollment(
        self,
        fresh_workspace: Path,
        operation: str,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        source = fresh_workspace / ".vaultspec" / "mcps" / "operator-extra.builtin.json"
        target = fresh_workspace / ".vaultspec" / "operator-extra.json"
        target.write_bytes((fresh_workspace / _RAG_MCP_REL).read_bytes())
        source.symlink_to(os.path.relpath(target, source.parent))
        enrolled = _install(fresh_workspace, upgrade=True)
        assert not enrolled.mcp_sync_failed
        signature = _node_signature(source)
        target_before = target.read_bytes()

        if operation == "no-mcp":
            preview = _install(
                fresh_workspace,
                dry_run=True,
                upgrade=True,
                install_mcp=False,
            )
            applied = _install(
                fresh_workspace,
                upgrade=True,
                install_mcp=False,
            )
        else:
            preview = uninstall_run(path=fresh_workspace, force=False)
            applied = uninstall_run(path=fresh_workspace, force=True)

        assert not preview.mcp_sync_failed
        assert not applied.mcp_sync_failed
        assert _node_signature(source) == signature
        assert target.read_bytes() == target_before
        assert "vaultspec-rag" not in _read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" not in _read_codex_mcp(fresh_workspace)

    @pytest.mark.parametrize(
        "container_relative",
        [Path(".vaultspec"), Path(".codex"), Path(".vaultspec") / "mcps"],
    )
    def test_linked_required_container_fails_before_lifecycle_mutation(
        self,
        fresh_workspace: Path,
        container_relative: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        container = fresh_workspace / container_relative
        linked_target = container.with_name(f"{container.name}.operator")
        container.replace(linked_target)
        container.symlink_to(linked_target.name, target_is_directory=True)
        signature = _node_signature(container)
        target_before = _workspace_inventory(linked_target)

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert _node_signature(container) == signature
        assert _workspace_inventory(linked_target) == target_before

    @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
    @pytest.mark.parametrize(
        "link_case",
        ["outside-relative", "broken-relative", "absolute"],
    )
    def test_unsafe_required_file_link_fails_before_lifecycle_mutation(
        self,
        fresh_workspace: Path,
        tmp_path: Path,
        relative: Path,
        link_case: str,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / relative
        original = node.read_bytes()
        preserved = node.with_name(f"{node.name}.preserved")
        node.replace(preserved)
        if link_case == "outside-relative":
            linked_target = tmp_path / f"outside-{relative.name}"
            linked_target.write_bytes(original)
            link_text = os.path.relpath(linked_target, node.parent)
        elif link_case == "absolute":
            linked_target = preserved
            link_text = str(linked_target.resolve())
        else:
            linked_target = None
            link_text = f"missing-{relative.name}"
        node.symlink_to(link_text)
        signature = _node_signature(node)
        preserved_before = preserved.read_bytes()
        outside_before = (
            linked_target.read_bytes() if linked_target is not None else None
        )

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        applied = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        for report in (preview, applied):
            assert report.mcp_sync_failed
            assert report.mcp_errors
            assert not report.seeded
            assert not report.sync_results
        assert preview.mcp_errors == applied.mcp_errors
        assert _node_signature(node) == signature
        assert preserved.read_bytes() == preserved_before
        if linked_target is not None:
            assert linked_target.read_bytes() == outside_before

    def test_required_links_cannot_alias_one_target(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        claude = fresh_workspace / ".mcp.json"
        codex = fresh_workspace / ".codex" / "config.toml"
        shared = fresh_workspace / "shared-required-target"
        shared.write_bytes(claude.read_bytes())
        claude.unlink()
        codex.unlink()
        claude.symlink_to(shared.name)
        codex.symlink_to(os.path.relpath(shared, codex.parent))
        signatures = (_node_signature(claude), _node_signature(codex))
        shared_before = shared.read_bytes()

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert "aliases required node" in " ".join(preview.mcp_errors)
        assert (_node_signature(claude), _node_signature(codex)) == signatures
        assert shared.read_bytes() == shared_before

    def test_required_link_cannot_overlap_another_required_node(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        ownership = fresh_workspace / ".vaultspec" / "mcp-ownership.json"
        providers = fresh_workspace / ".vaultspec" / "providers.json"
        ownership.unlink()
        ownership.symlink_to(providers.name)
        signature = _node_signature(ownership)
        providers_before = providers.read_bytes()

        preview = _install(fresh_workspace, dry_run=True, upgrade=True)
        applied = _install(fresh_workspace, upgrade=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert "overlaps a required MCP node" in " ".join(preview.mcp_errors)
        assert _node_signature(ownership) == signature
        assert providers.read_bytes() == providers_before

    def test_cli_reports_unsafe_required_topology_with_nonzero_json(
        self,
        fresh_workspace: Path,
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        _install(fresh_workspace, mode=InstallMode.TOOL)
        claude = fresh_workspace / ".mcp.json"
        preserved = fresh_workspace / ".mcp.preserved.json"
        claude.replace(preserved)
        claude.symlink_to("missing-required-target")
        signature = _node_signature(claude)
        preserved_before = preserved.read_bytes()

        result = CliRunner().invoke(
            app,
            [
                "install",
                "--target",
                str(fresh_workspace),
                "--upgrade",
                "--dry-run",
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
        assert "required MCP topology preflight failed" in " ".join(
            report["mcp_errors"]
        )
        assert _node_signature(claude) == signature
        assert preserved.read_bytes() == preserved_before

    if os.name == "nt":

        @pytest.mark.parametrize("relative", _REQUIRED_MCP_RELATIVES)
        def test_required_junction_fails_before_lifecycle_mutation(
            self,
            fresh_workspace: Path,
            tmp_path: Path,
            relative: Path,
        ) -> None:
            _install(fresh_workspace, mode=InstallMode.TOOL)
            node = fresh_workspace / relative
            preserved = node.with_name(f"{node.name}.preserved")
            node.replace(preserved)
            junction_target = tmp_path / f"junction-{relative.name}"
            junction_target.mkdir()
            (junction_target / "sentinel").write_bytes(b"operator-owned\x00")
            target_before = _workspace_inventory(junction_target)
            _create_windows_junction(node, junction_target)
            signature = _node_signature(node)

            preview = _install(fresh_workspace, dry_run=True, upgrade=True)
            applied = _install(fresh_workspace, upgrade=True)

            assert preview.mcp_sync_failed and applied.mcp_sync_failed
            assert preview.mcp_errors == applied.mcp_errors
            assert _node_signature(node) == signature
            assert _workspace_inventory(junction_target) == target_before

        @pytest.mark.parametrize(
            "container_relative",
            [Path(".vaultspec"), Path(".codex"), Path(".vaultspec") / "mcps"],
        )
        def test_required_junction_container_fails_before_lifecycle_mutation(
            self,
            fresh_workspace: Path,
            tmp_path: Path,
            container_relative: Path,
        ) -> None:
            _install(fresh_workspace, mode=InstallMode.TOOL)
            container = fresh_workspace / container_relative
            preserved = container.with_name(f"{container.name}.preserved")
            container.replace(preserved)
            junction_target = tmp_path / f"junction-{container.name}"
            preserved.replace(junction_target)
            target_before = _workspace_inventory(junction_target)
            _create_windows_junction(container, junction_target)
            signature = _node_signature(container)

            preview = _install(fresh_workspace, dry_run=True, upgrade=True)
            applied = _install(fresh_workspace, upgrade=True)

            assert preview.mcp_sync_failed and applied.mcp_sync_failed
            assert preview.mcp_errors == applied.mcp_errors
            assert _node_signature(container) == signature
            assert _workspace_inventory(junction_target) == target_before

    def test_uninstall_fails_before_removing_a_required_relative_link(
        self,
        fresh_workspace: Path,
    ) -> None:
        _install(fresh_workspace, mode=InstallMode.TOOL)
        node = fresh_workspace / ".mcp.json"
        linked_target = fresh_workspace / ".mcp.operator.json"
        node.replace(linked_target)
        node.symlink_to(linked_target.name)
        signature = _node_signature(node)
        target_before = linked_target.read_bytes()

        preview = uninstall_run(path=fresh_workspace, force=False)
        applied = uninstall_run(path=fresh_workspace, force=True)

        assert preview.mcp_sync_failed and applied.mcp_sync_failed
        assert preview.mcp_errors == applied.mcp_errors
        assert not preview.removed and not applied.removed
        assert _node_signature(node) == signature
        assert linked_target.read_bytes() == target_before

    @pytest.mark.parametrize(
        ("initial_mode", "pyproject_body"),
        [
            (
                InstallMode.DEPENDENCY,
                '[project]\nname = "consumer"\nversion = "0.1.0"\n'
                'dependencies = ["vaultspec-rag"]\n',
            ),
            (
                InstallMode.DEV,
                '[project]\nname = "consumer"\nversion = "0.1.0"\n\n'
                '[dependency-groups]\ndev = ["vaultspec-rag"]\n',
            ),
        ],
    )
    def test_legacy_project_mode_to_tool_preview_matches_real_update(
        self,
        fresh_workspace: Path,
        initial_mode: InstallMode,
        pyproject_body: str,
    ) -> None:
        (fresh_workspace / "pyproject.toml").write_text(
            pyproject_body, encoding="utf-8"
        )
        _install(fresh_workspace, mode=initial_mode)
        assert (
            _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == "uv"
        )
        (fresh_workspace / ".vaultspec" / "workspace.json").unlink()
        before = _workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert _workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        preview_providers = preview.to_dict()["sync_providers"]
        actual_providers = actual.to_dict()["sync_providers"]
        for provider in ("claude", "codex"):
            assert preview_providers[provider]["skipped"] == 1
            assert preview_providers[provider]["updated"] == 1
            assert preview_providers[provider] == actual_providers[provider]
        entry = _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]
        assert entry["command"] == "uvx"
        assert entry["args"][:2] == ["--from", "vaultspec-rag[mcp]"]

    def test_tool_to_dependency_preview_matches_real_update(
        self, fresh_workspace: Path
    ) -> None:
        (fresh_workspace / "pyproject.toml").write_text(
            '[project]\nname = "consumer"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
            encoding="utf-8",
        )
        _install(fresh_workspace, mode=InstallMode.TOOL)
        assert (
            _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == "uvx"
        )
        before = _workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.DEPENDENCY,
        )

        assert _workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.DEPENDENCY,
        )
        preview_providers = preview.to_dict()["sync_providers"]
        actual_providers = actual.to_dict()["sync_providers"]
        for provider in ("claude", "codex"):
            assert preview_providers[provider]["skipped"] == 1
            assert preview_providers[provider]["updated"] == 1
            assert preview_providers[provider] == actual_providers[provider]
        entry = _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]
        assert entry == {
            "command": "uv",
            "args": ["run", "python", "-m", "vaultspec_rag.server"],
        }

    @pytest.mark.parametrize("missing_provider", ["claude", "codex"])
    @pytest.mark.parametrize(
        ("initial_mode", "target_mode", "expected_command"),
        [
            (InstallMode.DEPENDENCY, InstallMode.TOOL, "uvx"),
            (InstallMode.TOOL, InstallMode.DEPENDENCY, "uv"),
        ],
    )
    def test_partial_provider_mode_preview_matches_real_without_false_success(
        self,
        fresh_workspace: Path,
        missing_provider: str,
        initial_mode: InstallMode,
        target_mode: InstallMode,
        expected_command: str,
    ) -> None:
        (fresh_workspace / "pyproject.toml").write_text(
            '[project]\nname = "consumer"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
            encoding="utf-8",
        )
        _install(fresh_workspace, mode=initial_mode)
        (fresh_workspace / ".vaultspec" / "workspace.json").unlink()
        missing_path = (
            fresh_workspace / ".mcp.json"
            if missing_provider == "claude"
            else fresh_workspace / ".codex" / "config.toml"
        )
        missing_path.unlink()
        before = _workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=target_mode,
        )

        assert _workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=target_mode,
        )
        assert preview.mcp_sync_failed is False
        assert actual.mcp_sync_failed is False
        preview_providers = preview.to_dict()["sync_providers"]
        actual_providers = actual.to_dict()["sync_providers"]
        assert preview_providers == actual_providers
        existing_provider = "codex" if missing_provider == "claude" else "claude"
        assert preview_providers[existing_provider]["skipped"] == 1
        assert preview_providers[existing_provider]["updated"] == 1
        assert preview_providers[missing_provider]["added"] == 1
        assert preview_providers[missing_provider]["unchanged"] == 1
        assert not preview_providers["claude"]["errors"]
        assert not preview_providers["codex"]["errors"]
        assert (
            _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == expected_command
        )
        assert _read_codex_mcp(fresh_workspace)["vaultspec-rag"]["command"] == (
            expected_command
        )

    @pytest.mark.parametrize(
        "skip_tokens",
        [frozenset({"mcp"}), frozenset({"core", "mcp"})],
    )
    @pytest.mark.parametrize(
        ("initial_mode", "target_mode", "expected_command"),
        [
            (InstallMode.DEPENDENCY, InstallMode.TOOL, "uv"),
            (InstallMode.TOOL, InstallMode.DEPENDENCY, "uvx"),
        ],
    )
    def test_mcp_skip_is_hard_boundary_for_mode_transitions(
        self,
        fresh_workspace: Path,
        skip_tokens: frozenset[str],
        initial_mode: InstallMode,
        target_mode: InstallMode,
        expected_command: str,
    ) -> None:
        (fresh_workspace / "pyproject.toml").write_text(
            '[project]\nname = "consumer"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
            encoding="utf-8",
        )
        _install(fresh_workspace, mode=initial_mode)
        protected_paths = [
            fresh_workspace / ".mcp.json",
            fresh_workspace / ".codex" / "config.toml",
            fresh_workspace / ".vaultspec" / "mcp-ownership.json",
            fresh_workspace / _RAG_MCP_REL,
        ]
        protected_before = {path: path.read_bytes() for path in protected_paths}
        workspace_before = _workspace_file_bytes(fresh_workspace)
        locks_before = {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        }

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=target_mode,
            skip=set(skip_tokens),
        )

        assert _workspace_file_bytes(fresh_workspace) == workspace_before
        assert {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        } == locks_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=target_mode,
            skip=set(skip_tokens),
        )
        assert preview.to_dict()["sync_providers"] == {}
        assert actual.to_dict()["sync_providers"] == {}
        assert not preview.mcp_sync_results
        assert not actual.mcp_sync_results
        assert {path: path.read_bytes() for path in protected_paths} == (
            protected_before
        )
        assert {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        } == locks_before
        assert (
            _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == expected_command
        )
        assert _read_codex_mcp(fresh_workspace)["vaultspec-rag"]["command"] == (
            expected_command
        )
        declaration = read_package_declaration(fresh_workspace, "vaultspec-rag")
        assert declaration is not None
        expected_mode = initial_mode if "core" in skip_tokens else target_mode
        assert declaration.install_mode is expected_mode

    @pytest.mark.parametrize(
        "skip_tokens",
        [frozenset({"mcp"}), frozenset({"core", "mcp"})],
    )
    @pytest.mark.parametrize("corrupt_surface", ["codex", "ownership"])
    def test_implicit_upgrade_mcp_skip_uses_only_durable_package_placement(
        self,
        fresh_workspace: Path,
        skip_tokens: frozenset[str],
        corrupt_surface: str,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "consumer"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
            encoding="utf-8",
        )
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        (fresh_workspace / ".vaultspec" / "workspace.json").unlink()
        if corrupt_surface == "codex":
            (fresh_workspace / ".codex" / "config.toml").write_text(
                'invalid = "unterminated',
                encoding="utf-8",
            )
        else:
            (fresh_workspace / ".vaultspec" / "mcp-ownership.json").write_text(
                "{not-json",
                encoding="utf-8",
            )
        protected_paths = [
            pyproject,
            fresh_workspace / ".mcp.json",
            fresh_workspace / ".codex" / "config.toml",
            fresh_workspace / ".vaultspec" / "mcp-ownership.json",
            fresh_workspace / _RAG_MCP_REL,
        ]
        protected_before = {path: path.read_bytes() for path in protected_paths}
        workspace_before = _workspace_file_bytes(fresh_workspace)
        locks_before = {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        }

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            skip=set(skip_tokens),
        )

        assert _workspace_file_bytes(fresh_workspace) == workspace_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            skip=set(skip_tokens),
        )
        assert preview.to_dict()["sync_providers"] == {}
        assert actual.to_dict()["sync_providers"] == {}
        assert not preview.mcp_sync_results
        assert not actual.mcp_sync_results
        assert not preview.mcp_errors
        assert not actual.mcp_errors
        assert {path: path.read_bytes() for path in protected_paths} == (
            protected_before
        )
        assert {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        } == locks_before
        declaration = read_package_declaration(fresh_workspace, "vaultspec-rag")
        if "core" in skip_tokens:
            assert declaration is None
        else:
            assert declaration is not None
            assert declaration.install_mode is InstallMode.DEPENDENCY

    @pytest.mark.parametrize(
        "skip_tokens",
        [frozenset({"mcp"}), frozenset({"core", "mcp"})],
    )
    @pytest.mark.parametrize("install_mcp", [True, False])
    @pytest.mark.parametrize("drift_source", [False, True])
    def test_mcp_skip_preserves_complete_intent_domain(
        self,
        fresh_workspace: Path,
        skip_tokens: frozenset[str],
        install_mcp: bool,
        drift_source: bool,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        source = fresh_workspace / _RAG_MCP_REL
        if drift_source:
            source.write_bytes(b'{"operator": "owned bytes"}\n')
        protected_paths = [
            pyproject,
            source,
            fresh_workspace / ".mcp.json",
            fresh_workspace / ".codex" / "config.toml",
            fresh_workspace / ".vaultspec" / "mcp-ownership.json",
        ]
        protected_before = {path: path.read_bytes() for path in protected_paths}
        locks_before = {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        }

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            install_mcp=install_mcp,
            skip=set(skip_tokens),
        )
        actual = _install(
            fresh_workspace,
            upgrade=True,
            install_mcp=install_mcp,
            skip=set(skip_tokens),
        )

        for report in (preview, actual):
            assert report.mcp_extra_action == "skipped"
            assert not report.mcp_sync_results
            assert not report.mcp_errors
            assert report.to_dict()["sync_providers"] == {}
            assert all(
                not relative.startswith("mcps/") for relative, _ in report.seeded
            )
        assert {path: path.read_bytes() for path in protected_paths} == protected_before
        assert {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        } == locks_before

    @pytest.mark.parametrize("conflict_kind", ["owned-drift", "ambiguous-target"])
    def test_placement_conflict_blocks_mode_source_and_provider_commit(
        self, fresh_workspace: Path, conflict_kind: str
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        content = pyproject.read_text(encoding="utf-8")
        if conflict_kind == "owned-drift":
            content = content.replace("vaultspec-rag[mcp]", "vaultspec-rag[mcp]>=9", 1)
        else:
            content += (
                '\n[dependency-groups]\ndev = ["vaultspec-rag"]\n\n'
                '[tool.uv]\ndev-dependencies = ["vaultspec-rag"]\n'
            )
        pyproject.write_text(content, encoding="utf-8")
        before = _workspace_file_bytes(fresh_workspace)

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.DEV,
        )
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.DEV,
        )

        for report in (preview, actual):
            assert report.mcp_extra_action == "conflict"
            assert report.mcp_sync_failed
            assert report.mcp_errors
            assert not report.seeded
            assert not report.sync_results
        assert _workspace_file_bytes(fresh_workspace) == before
        declaration = read_package_declaration(fresh_workspace, "vaultspec-rag")
        assert declaration is not None
        assert declaration.install_mode is InstallMode.DEPENDENCY

        result = CliRunner().invoke(
            app,
            [
                "install",
                "--target",
                str(fresh_workspace),
                "--upgrade",
                "--mode",
                "dev",
                "--mcp",
                "--no-provision",
                "--no-torch-config",
                "--json",
            ],
            catch_exceptions=False,
        )
        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["mcp_extra_action"] == "conflict"
        assert data["mcp_failed"] is True
        assert _workspace_file_bytes(fresh_workspace) == before

    def test_mode_write_failure_rolls_back_extra_placement(
        self, fresh_workspace: Path
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        before = _workspace_file_bytes(fresh_workspace)
        workspace = fresh_workspace / ".vaultspec" / "workspace.json"
        write_blocker = workspace.with_suffix(workspace.suffix + f".{os.getpid()}.tmp")
        write_blocker.mkdir()

        report = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.DEV,
        )
        write_blocker.rmdir()

        assert report.mcp_extra_action == "error"
        assert report.mcp_sync_failed
        assert report.mcp_errors
        assert not report.seeded
        assert not report.sync_results
        assert _workspace_file_bytes(fresh_workspace) == before
        declaration = read_package_declaration(fresh_workspace, "vaultspec-rag")
        assert declaration is not None
        assert declaration.install_mode is InstallMode.DEPENDENCY

    @pytest.mark.parametrize("preexisting_locks", [False, True])
    def test_fresh_mode_write_failure_restores_exact_intent_inventory(
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
        write_blocker = workspace.with_suffix(workspace.suffix + f".{os.getpid()}.tmp")
        write_blocker.mkdir()
        before = _workspace_inventory(fresh_workspace)

        report = _install(fresh_workspace, mode=InstallMode.DEPENDENCY)

        assert report.mcp_extra_action == "error"
        assert report.mcp_sync_failed
        assert not report.seeded
        assert not report.sync_results
        assert _workspace_inventory(fresh_workspace) == before
        assert not workspace.exists()

    @pytest.mark.parametrize("existing_source", [False, True])
    def test_mcp_source_write_failure_rolls_back_full_intent_transaction(
        self, fresh_workspace: Path, existing_source: bool
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        write_manifest(fresh_workspace, {"claude", "codex"})
        (fresh_workspace / ".vault" / "data").mkdir(parents=True)
        for name in ("mcps", "rules", "skills"):
            (fresh_workspace / ".vaultspec" / name).mkdir(parents=True, exist_ok=True)
        source = fresh_workspace / _RAG_MCP_REL
        if existing_source:
            source.write_bytes(b'{"operator": "preserve exact bytes"}\n')
        source.with_suffix(source.suffix + f".{os.getpid()}.tmp").mkdir()
        pyproject.with_suffix(".toml.lock").write_bytes(b"project-lock\x00")
        workspace = fresh_workspace / ".vaultspec" / "workspace.json"
        workspace.with_suffix(".json.lock").write_bytes(b"workspace-lock\x00")
        before = _workspace_inventory(fresh_workspace)

        report = install_run(
            path=fresh_workspace,
            install_mcp=True,
            configure_torch=True,
            assume_yes=True,
            provision=False,
            force=True,
            mode=InstallMode.DEPENDENCY,
        )

        assert report.mcp_extra_action == "error"
        assert report.mcp_sync_failed
        assert report.torch_config_action == "error"
        assert not report.seeded
        assert not report.sync_results
        assert _workspace_inventory(fresh_workspace) == before
        assert not workspace.exists()
        if not existing_source:
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
            assert _workspace_inventory(fresh_workspace) == before

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
            skill.write_bytes(b"operator-skill\x00")
        blocker = skill.with_suffix(skill.suffix + f".{os.getpid()}.tmp")
        blocker.mkdir()
        (blocker / "sentinel").write_bytes(b"blocker-owned")
        unrelated = fresh_workspace / ".vaultspec" / "rules" / "operator.md"
        unrelated.write_bytes(b"unrelated\x00")
        workspace = fresh_workspace / ".vaultspec" / "workspace.json"
        pyproject.with_suffix(".toml.lock").write_bytes(b"project-lock\x00")
        workspace.with_suffix(".json.lock").write_bytes(b"workspace-lock\x00")
        before = _workspace_inventory(fresh_workspace)

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
        assert _workspace_inventory(fresh_workspace) == before

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
        blocker = skill.with_suffix(skill.suffix + f".{os.getpid()}.tmp")
        blocker.mkdir()
        (blocker / "sentinel").write_bytes(b"blocker-owned")
        before = _workspace_inventory(fresh_workspace)
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
        assert _workspace_inventory(fresh_workspace) == before

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
        from ...commands._install import _file_snapshot, _restore_file_snapshot

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
        snapshot = _file_snapshot(destination)
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

        _restore_file_snapshot(destination, snapshot)

        assert _file_snapshot(destination) == snapshot
        assert _node_signature(collision) == collision_signature
        if collision_bytes is not None:
            assert collision.read_bytes() == collision_bytes
        if collision_kind == "live-symlink":
            assert collision_target.read_bytes() == b"operator-target\x00"
        elif collision_kind == "broken-symlink":
            assert not (fresh_workspace / "missing-collision.md").exists()
        assert not list(fresh_workspace.glob(f".{destination.name}.rollback-*.tmp"))

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
            _create_windows_junction(skill, target)
            before = _workspace_inventory(fresh_workspace)
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
            assert _workspace_inventory(fresh_workspace) == before

        def test_junction_snapshot_recreates_removed_reparse_node(
            self, fresh_workspace: Path
        ) -> None:
            from ...commands._install import _file_snapshot, _restore_file_snapshot

            target = fresh_workspace / "operator-target"
            target.mkdir()
            (target / "sentinel").write_bytes(b"target-owned\x00")
            junction = fresh_workspace / "builtin-junction"
            _create_windows_junction(junction, target)
            snapshot = _file_snapshot(junction)
            signature = _node_signature(junction)
            junction.rmdir()
            junction.write_bytes(b"transaction-replacement")

            _restore_file_snapshot(junction, snapshot)

            assert junction.is_junction()
            assert _node_signature(junction) == signature
            assert (target / "sentinel").read_bytes() == b"target-owned\x00"

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
        before = _workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=target_mode,
        )

        assert preview.mcp_extra_action == "would-move"
        assert _workspace_file_bytes(fresh_workspace) == before
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


class TestProviderFailureContract:
    def test_api_report_preserves_top_level_ownership_error(
        self, fresh_workspace: Path
    ) -> None:
        write_manifest(fresh_workspace, {"claude", "codex"})
        ownership = fresh_workspace / ".vaultspec" / "mcp-ownership.json"
        ownership.write_text("{not-json", encoding="utf-8")

        report = _install(fresh_workspace)
        data = report.to_dict()

        assert report.mcp_sync_failed
        assert data["mcp_failed"] is True
        assert data["mcp_errors"]
        assert data["sync_providers"] == {}
        assert "ownership" in " ".join(data["mcp_errors"]).lower()

    def test_install_cli_exits_nonzero_and_reports_provider_error(
        self, fresh_workspace: Path
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        write_manifest(fresh_workspace, {"codex"})
        codex_config = fresh_workspace / ".codex" / "config.toml"
        codex_config.parent.mkdir()
        codex_config.write_text('invalid = "unterminated', encoding="utf-8")

        runner = CliRunner()
        result = runner.invoke(
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
        data = json.loads(result.output)
        assert data["mcp_failed"] is True
        assert data["sync_providers"]["codex"]["errored"] == 1
        assert data["sync_providers"]["codex"]["errors"]

        human_result = runner.invoke(
            app,
            [
                "install",
                "--target",
                str(fresh_workspace),
                "--no-provision",
                "--no-torch-config",
                "--mcp",
            ],
            catch_exceptions=False,
        )
        assert human_result.exit_code == 2, human_result.output
        assert "Codex MCP: errored 1" in human_result.output
        assert "error:" in human_result.output

    def test_uninstall_cli_exits_nonzero_and_reports_ownership_error(
        self, installed_workspace: Path
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        ownership = installed_workspace / ".vaultspec" / "mcp-ownership.json"
        ownership.write_text("{not-json", encoding="utf-8")
        discovery_skill = installed_workspace / _RAG_SKILL_REL
        discovery_skill.unlink()
        discovery_skill.parent.rmdir()

        result = CliRunner().invoke(
            app,
            [
                "uninstall",
                "--target",
                str(installed_workspace),
                "--force",
                "--json",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 2, result.output
        data = json.loads(result.output)
        assert data["mcp_failed"] is True
        assert data["mcp_errors"]
        assert "ownership" in " ".join(data["mcp_errors"]).lower()

    def test_failed_uninstall_restores_placement_and_canonical_assets(
        self,
        fresh_workspace: Path,
    ) -> None:
        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        ownership = fresh_workspace / ".vaultspec" / "mcp-ownership.json"
        ownership.write_text("{not-json", encoding="utf-8")
        before = _workspace_inventory(fresh_workspace)

        report = uninstall_run(path=fresh_workspace, force=True)

        assert report.mcp_sync_failed
        assert _workspace_inventory(fresh_workspace) == before

    @pytest.mark.parametrize(
        ("failure_kind", "expected_action"),
        [("drift", "conflict"), ("malformed", "error")],
    )
    def test_uninstall_extra_failure_is_fail_closed_and_exits_two(
        self,
        fresh_workspace: Path,
        failure_kind: str,
        expected_action: str,
    ) -> None:
        from typer.testing import CliRunner

        from ...cli import app

        pyproject = fresh_workspace / "pyproject.toml"
        pyproject.write_text(_CONSUMER_PYPROJECT, encoding="utf-8")
        _install(fresh_workspace, mode=InstallMode.DEPENDENCY)
        if failure_kind == "drift":
            pyproject.write_text(
                pyproject.read_text(encoding="utf-8").replace(
                    "vaultspec-rag[mcp]",
                    "vaultspec-rag[mcp]>=9",
                    1,
                ),
                encoding="utf-8",
            )
        else:
            pyproject.write_text("[project\n", encoding="utf-8")
        before = _workspace_inventory(fresh_workspace)

        result = CliRunner().invoke(
            app,
            [
                "uninstall",
                "--target",
                str(fresh_workspace),
                "--force",
                "--json",
            ],
            catch_exceptions=False,
        )

        assert result.exit_code == 2, result.output
        report = json.loads(result.output)
        assert report["mcp_failed"] is True
        assert report["mcp_extra_action"] == expected_action
        assert report["mcp_errors"]
        assert _workspace_inventory(fresh_workspace) == before
        assert (fresh_workspace / _RAG_MCP_REL).is_file()
        assert "vaultspec-rag" in _read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" in _read_codex_mcp(fresh_workspace)


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
            assert "vaultspec-rag" not in _read_codex_mcp(installed_workspace)
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
        data = _read_mcp_json(fresh_workspace)
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
        data = _read_mcp_json(fresh_workspace)
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
        _seed_core_mcp_source(fresh_workspace)
        _install(fresh_workspace)
        claude_path = fresh_workspace / ".mcp.json"
        codex_path = fresh_workspace / ".codex" / "config.toml"
        ownership_path = fresh_workspace / ".vaultspec" / "mcp-ownership.json"

        claude = _read_mcp_json(fresh_workspace)
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
        core_claude = _read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-core"]
        core_codex = _read_codex_mcp(fresh_workspace)["vaultspec-core"]

        report = uninstall_run(path=fresh_workspace, force=True)

        claude_after = _read_mcp_json(fresh_workspace)["mcpServers"]
        codex_after = _read_codex_mcp(fresh_workspace)
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
        assert "vaultspec-rag[mcp]" in codex_entry["transport"]["args"]


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
            assert "vaultspec-rag" not in _read_codex_mcp(fresh_workspace)

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


class TestSafetyGuards:
    """Destruction-safety regression tests.

    These tests pin the safety contract: rag must never follow a
    symlink out of the workspace, never escape ``target_rules_dir`` via
    a malicious bundled rel path, and never leave a half-installed
    workspace if seeding fails partway through.
    """

    def test_remove_data_refuses_symlink_target(
        self, installed_workspace: Path, tmp_path: Path
    ) -> None:
        """If ``.vault/data/`` is a symlink, ``--remove-data`` must
        refuse the operation rather than follow the symlink and
        rmtree something outside the workspace. The symlink itself
        is left alone - the user must resolve it manually.
        """
        # Replace .vault/data/ with a symlink pointing outside the
        # workspace. Drop a sentinel inside the link target so we can
        # detect any traversal.
        outside = tmp_path / "outside-data"
        outside.mkdir()
        sentinel = outside / "MUST_NOT_BE_DELETED"
        sentinel.write_text("safe", encoding="utf-8")

        data_dir = installed_workspace / ".vault" / "data"
        # Drop existing data dir and replace with symlink. On Windows
        # symlink creation may need admin/dev mode; if it fails, skip
        # the test rather than passing it falsely.
        import shutil as _shutil

        _shutil.rmtree(data_dir)
        try:
            data_dir.symlink_to(outside, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            raise RuntimeError(f"symlink creation unsupported: {exc}") from exc

        report = uninstall_run(path=installed_workspace, force=True, remove_data=True)

        # The symlink target's contents must be untouched.
        assert sentinel.is_file()
        assert sentinel.read_text(encoding="utf-8") == "safe"
        # The operation must NOT report data_removed=True.
        assert not report.data_removed
        # A clear warning must surface to the user.
        assert any("symlink" in w for w in report.warnings)

    def test_install_run_in_unrelated_directory_does_not_escape(
        self, tmp_path: Path
    ) -> None:
        """A sentinel file outside the install target must survive an
        install run. This guards against any code path that might
        accidentally write outside ``target``.
        """
        ws = tmp_path / "workspace"
        ws.mkdir()

        sibling = tmp_path / "sibling"
        sibling.mkdir()
        sentinel = sibling / "untouched.txt"
        sentinel.write_text("safe", encoding="utf-8")

        _install(ws)

        assert sentinel.is_file()
        assert sentinel.read_text(encoding="utf-8") == "safe"
        # Confirm install actually did its job in the target.
        assert (ws / _RAG_RULE_REL).is_file()

    def test_uninstall_force_does_not_touch_user_data_outside_index(
        self, installed_workspace: Path
    ) -> None:
        """Uninstall must never touch user-authored content under
        ``.vault/`` even with ``--force``. Drops several sentinel docs
        and asserts they all survive.
        """
        vault = installed_workspace / ".vault"
        sentinels = [
            vault / "adr" / "user-decision.md",
            vault / "research" / "user-notes.md",
            vault / "plan" / "user-plan.md",
        ]
        for s in sentinels:
            s.parent.mkdir(parents=True, exist_ok=True)
            s.write_text(f"# {s.name}\n", encoding="utf-8")

        uninstall_run(path=installed_workspace, force=True)

        for s in sentinels:
            assert s.is_file(), f"user file {s.name} was destroyed"

    def test_install_rolls_back_seeded_files_on_seed_failure(
        self, tmp_path: Path
    ) -> None:
        """If ``seed_builtins`` fails partway through, ``install_run``
        must remove any files it had successfully written so the
        workspace is not left half-installed.

        ``seed_builtins`` walks the package tree in sorted order. A
        genuine atomic-temp blocker at the final skill destination
        therefore fails only after the MCP and rule files were written.
        """
        ws = tmp_path / "workspace"
        ws.mkdir()
        (ws / ".vault" / "data").mkdir(parents=True)
        (ws / ".vaultspec" / "mcps").mkdir(parents=True)
        (ws / ".vaultspec" / "rules").mkdir(parents=True)
        (ws / ".vaultspec" / "skills").mkdir(parents=True)
        skill = ws / _RAG_SKILL_REL
        skill.parent.mkdir(parents=True)
        blocker = skill.with_suffix(skill.suffix + f".{os.getpid()}.tmp")
        blocker.mkdir()
        (blocker / "sentinel").write_text("x", encoding="utf-8")
        before = _workspace_inventory(ws)

        report = install_run(path=ws, force=True)

        assert report.mcp_sync_failed
        assert report.mcp_extra_action == "error"
        assert _workspace_inventory(ws) == before

    def test_uninstall_in_empty_dir_does_not_create_workspace(
        self, tmp_path: Path
    ) -> None:
        """Codex P2: ``vaultspec-rag uninstall --force`` against an
        empty directory must NOT create ``.vault/`` or ``.vaultspec/``
        as a side effect. Cleanup automation that points at the wrong
        directory should be a no-op, not a destructive bootstrap.
        """
        ws = tmp_path / "empty-workspace"
        ws.mkdir()
        # Confirm starting state
        assert not (ws / ".vault").exists()
        assert not (ws / ".vaultspec").exists()

        report = uninstall_run(path=ws, force=True)

        # The directories must NOT have been created.
        assert not (ws / ".vault").exists()
        assert not (ws / ".vaultspec").exists()
        # The report must reflect that nothing was removed.
        assert report.removed == []
        assert any("nothing to uninstall" in w for w in report.warnings), (
            report.warnings
        )

    def test_uninstall_in_dir_without_vaultspec_returns_early(
        self, tmp_path: Path
    ) -> None:
        """If ``.vault/`` exists but ``.vaultspec/`` does not, uninstall
        must still no-op rather than creating the missing dir or
        attempting to read non-existent rag artefacts.
        """
        ws = tmp_path / "partial-workspace"
        ws.mkdir()
        (ws / ".vault").mkdir()  # only one of the two dirs exists

        report = uninstall_run(path=ws, force=True)

        # .vaultspec was NOT created.
        assert not (ws / ".vaultspec").exists()
        assert report.removed == []
        assert any("nothing to uninstall" in w for w in report.warnings)

    def test_seed_builtins_raises_on_per_file_failure(self, tmp_path: Path) -> None:
        """Codex P2: ``seed_builtins`` must raise on per-file write
        failures, not log-and-continue. Silent partial seeding bypasses
        the install_run rollback path and leaves the workspace in an
        undetectable broken state.
        """
        from ...builtins import seed_builtins

        target = tmp_path / "rules"
        target.mkdir()
        # Block one of the destination paths by making its parent dir
        # a file. ``mcps/`` comes before ``rules/`` alphabetically in
        # the bundled tuple, so the mcps write attempt will fail.
        (target / "mcps").write_text("blocker", encoding="utf-8")

        import pytest as _pytest

        with _pytest.raises(OSError):
            seed_builtins(target)

    def test_seed_builtins_out_param_captures_partial_progress(
        self, tmp_path: Path
    ) -> None:
        """The ``written`` out-list must contain everything seeded
        before the failing iteration, so callers (install_run) can
        roll back targeted partial state.
        """
        from ...builtins import seed_builtins

        target = tmp_path / "rules"
        target.mkdir()
        # seed_builtins walks the package tree in sorted order, so
        # ``mcps/...`` is written before ``rules/...``. Let mcps
        # succeed and block the second (rules) iteration by
        # pre-creating its dest path as a non-empty directory. With
        # force=True the existence check is bypassed and atomic_write
        # fails on the dir replacement.
        (target / "rules").mkdir()
        (target / "mcps").mkdir()
        (target / "rules" / "vaultspec-rag.builtin.md").mkdir()
        (target / "rules" / "vaultspec-rag.builtin.md" / "x").write_text(
            "y", encoding="utf-8"
        )

        written: list[str] = []
        import pytest as _pytest

        with _pytest.raises(OSError):
            seed_builtins(target, force=True, written=written)

        # mcps file got written before the rules failure
        assert "mcps/vaultspec-rag.builtin.json" in written
        # rules file did NOT
        assert "rules/vaultspec-rag.builtin.md" not in written

    def test_global_target_flag_routes_to_install(self, tmp_path: Path) -> None:
        """Codex P1: ``vaultspec-rag --target /path install`` must
        install into ``/path``, not into the current working
        directory. The root callback's global ``--target`` is
        consumed by Click before the subcommand options, so the
        subcommand handler must explicitly read it from the context.
        """
        from typer.testing import CliRunner

        from ...cli import app

        ws = tmp_path / "global-target-ws"
        ws.mkdir()

        runner = CliRunner()
        result = runner.invoke(
            app, ["--target", str(ws), "install"], catch_exceptions=False
        )

        assert result.exit_code == 0, result.output
        # The bundled files must have landed in the global target,
        # not in cwd.
        assert (ws / _RAG_RULE_REL).is_file()
        assert (ws / _RAG_MCP_REL).is_file()

    def test_global_target_flag_routes_to_uninstall(
        self, installed_workspace: Path
    ) -> None:
        """Same routing rule for uninstall: ``vaultspec-rag --target
        /path uninstall --force`` must uninstall from ``/path``.
        """
        from typer.testing import CliRunner

        from ...cli import app

        runner = CliRunner()
        result = runner.invoke(
            app,
            ["--target", str(installed_workspace), "uninstall", "--force"],
            catch_exceptions=False,
        )

        assert result.exit_code == 0, result.output
        # rag-owned files removed from the global target.
        assert not (installed_workspace / _RAG_RULE_REL).exists()
        assert not (installed_workspace / _RAG_MCP_REL).exists()

    def test_seed_builtins_refuses_dest_outside_target(self, tmp_path: Path) -> None:
        """Defense-in-depth: ``seed_builtins`` must never write a dest
        that resolves outside ``target_rules_dir``.

        The bundled set is now whatever ships under the package, so a
        traversal can no longer enter through a corrupt manifest. We
        instead point the source root at a crafted tree containing a
        nested builtin and confirm the containment guard governs every
        write: the seeded dest stays inside the target, mirroring the
        files relative to the source root.

        We swap ``_builtins_root`` by direct attribute assignment with
        restore in ``finally`` (no monkeypatch fixture, honouring the
        project no-mocks rule).
        """
        from ... import builtins as _builtins

        # Build a crafted source tree with one nested builtin file.
        fake_src = tmp_path / "fake-builtins"
        (fake_src / "rules").mkdir(parents=True)
        (fake_src / "rules" / "vaultspec-rag.builtin.md").write_text(
            "---\nname: vaultspec-rag\n---\n", encoding="utf-8"
        )

        original_root = _builtins._builtins_root

        def _fake_root() -> Path:
            return fake_src

        # NB: not a mock - rebinding a module function via __dict__ (restored
        # below); __dict__ assignment avoids retyping the module attribute.
        _builtins.__dict__["_builtins_root"] = _fake_root
        try:
            target = tmp_path / "rules-target"
            target.mkdir()

            results = _builtins.seed_builtins(target)

            # The nested file seeded into the target, contained.
            assert ("rules/vaultspec-rag.builtin.md", "[ADD]") in results
            seeded = target / "rules" / "vaultspec-rag.builtin.md"
            assert seeded.is_file()
            assert seeded.resolve().is_relative_to(target.resolve())
        finally:
            _builtins.__dict__["_builtins_root"] = original_root


@pytest.fixture()
def isolated_status_dir(tmp_path: Path) -> Iterator[Path]:
    """Point the managed service / qdrant bin dir at tmp and reset config.

    Keeps the provisioning front door's qdrant resolution off any ambient
    ``~/.vaultspec-rag/`` state, per the service-tests-isolate-STATUS_DIR
    discipline, so the test cannot disturb the live service.
    """
    from ...config import EnvVar, reset_config

    key = EnvVar.STATUS_DIR.value
    prev = os.environ.get(key)
    os.environ[key] = str(tmp_path / "status")
    reset_config()
    try:
        yield tmp_path
    finally:
        if prev is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = prev
        reset_config()


class TestProvisioningReport:
    """The default install provisioning path reports heterogeneous outcomes.

    Network-free by construction: ``local_only=True`` skips the qdrant
    binary download and ``provision_skip={"models"}`` skips the model
    fetch, so the only step that does real work is the torch configurator,
    which patches the temp workspace's own ``pyproject.toml``. The result
    is three honest, *different* per-dependency outcomes - torch
    sync-pending, models skipped, qdrant skipped - which is exactly the
    heterogeneity the report must surface. No mocks, no large downloads,
    and the live service is untouched.
    """

    @pytest.fixture()
    def provisioned_report(
        self, fresh_workspace: Path, isolated_status_dir: Path
    ) -> Any:
        _ = isolated_status_dir
        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT, encoding="utf-8", newline=""
        )
        return install_run(
            path=fresh_workspace,
            provision=True,
            local_only=True,
            provision_skip={"models"},
            assume_yes=True,
        )

    def test_report_carries_a_provisioning_outcome(
        self, provisioned_report: Any
    ) -> None:
        assert provisioned_report.provision_outcome is not None
        steps = {r.step for r in provisioned_report.provision_outcome.steps}
        # The enrollment torch step runs separately; the front door is told
        # to skip torch so it does not double-report. So the front-door
        # outcome carries the two fetch-and-go dependencies.
        assert "models" in {str(s) for s in steps}
        assert "qdrant" in {str(s) for s in steps}

    def test_json_provisioning_key_is_heterogeneous_and_serialisable(
        self, provisioned_report: Any
    ) -> None:
        data = provisioned_report.to_dict()
        json.dumps(data)  # must not raise
        provisioning = data["provisioning"]
        assert provisioning is not None
        actions = {step["action"] for step in provisioning["steps"]}
        # models and qdrant are both opted out here, so both are skipped,
        # each carrying its own distinct reason (heterogeneous detail).
        details = {step["step"]: step["detail"] for step in provisioning["steps"]}
        assert "local-only" in details["qdrant"]
        assert details["models"] != details["qdrant"]
        assert "skipped" in actions

    def test_torch_enrollment_step_reports_configured_sync_pending(
        self, provisioned_report: Any
    ) -> None:
        from ...torch_config import TorchConfigAction

        # The enrollment torch step actually patched the consumer
        # pyproject; its honest two-phase state is the headline the
        # renderer must surface as "configured, sync pending".
        assert provisioned_report.torch_config_action == TorchConfigAction.APPLIED
        assert provisioned_report.torch_sync_action == "skipped"

    def test_rendered_report_surfaces_heterogeneous_provisioning_wording(
        self, provisioned_report: Any
    ) -> None:
        from rich.console import Console

        from ...cli import _render
        from ...cli._render import _render_install_report

        buffer = io.StringIO()
        captured = Console(
            file=buffer, force_terminal=False, legacy_windows=False, width=200
        )
        original = _render._cli.console
        _render._cli.console = captured  # not a mock: swap restored in finally
        try:
            _render_install_report(provisioned_report)
        finally:
            _render._cli.console = original

        output = buffer.getvalue()
        # The qdrant binary skip and the models skip both render honestly...
        assert "Qdrant binary: skipped" in output
        assert "local-only" in output
        # ...and the provisioning summary line is present and bounded.
        assert "Provisioning:" in output

    def test_dry_run_provisioning_previews_without_writing(
        self, fresh_workspace: Path, isolated_status_dir: Path
    ) -> None:
        from ...commands import ProvisionAction, ProvisionStep

        (fresh_workspace / "pyproject.toml").write_text(
            _CONSUMER_PYPROJECT, encoding="utf-8", newline=""
        )
        report = install_run(
            path=fresh_workspace,
            provision=True,
            dry_run=True,
            provision_skip={"models"},
            assume_yes=True,
        )
        assert report.provision_outcome is not None
        assert report.provision_outcome.dry_run is True
        # A dry-run preview must not have provisioned a qdrant binary into
        # the isolated managed dir nor disturbed the live service.
        qdrant = report.provision_outcome.result_for(ProvisionStep.QDRANT)
        assert qdrant is not None
        assert qdrant.action in {ProvisionAction.DRY_RUN, ProvisionAction.SKIPPED}
        assert not (isolated_status_dir / "status" / "bin").exists()
