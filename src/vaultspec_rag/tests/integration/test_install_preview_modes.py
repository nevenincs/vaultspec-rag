"""Real installation integration behavior: preview modes."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003

import pytest
from vaultspec_core.core.enums import (
    InstallMode,
)
from vaultspec_core.core.workspace_mode import (
    read_package_declaration,
)

from ...commands._uninstall import uninstall_run
from ._install_helpers import (
    _CONSUMER_PYPROJECT,
    _RAG_MCP_REL,
    _install,
    _node_signature,
    read_codex_mcp,
    read_mcp_json,
    workspace_file_bytes,
)

pytestmark = [pytest.mark.integration]


class TestInstallModeTransitions:
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
            read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == "uv"
        )
        (fresh_workspace / ".vaultspec" / "workspace.json").unlink()
        before = workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.TOOL,
        )

        assert workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.TOOL,
        )
        preview_providers = preview.to_dict()["sync_providers"]
        actual_providers = actual.to_dict()["sync_providers"]
        for provider in ("claude", "codex"):
            # Core 0.1.48 reports a refreshed-but-otherwise-unchanged entry as
            # separate updated/unchanged counts rather than folding it into
            # skipped.
            assert preview_providers[provider]["unchanged"] == 1
            assert preview_providers[provider]["updated"] == 1
            assert preview_providers[provider] == actual_providers[provider]
        entry = read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]
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
            read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == "uvx"
        )
        before = workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=InstallMode.DEPENDENCY,
        )

        assert workspace_file_bytes(fresh_workspace) == before
        assert sorted(fresh_workspace.rglob("*.lock")) == locks_before
        actual = _install(
            fresh_workspace,
            upgrade=True,
            mode=InstallMode.DEPENDENCY,
        )
        preview_providers = preview.to_dict()["sync_providers"]
        actual_providers = actual.to_dict()["sync_providers"]
        for provider in ("claude", "codex"):
            # Core 0.1.48 reports a refreshed-but-otherwise-unchanged entry as
            # separate updated/unchanged counts rather than folding it into
            # skipped.
            assert preview_providers[provider]["unchanged"] == 1
            assert preview_providers[provider]["updated"] == 1
            assert preview_providers[provider] == actual_providers[provider]
        entry = read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]
        assert entry == {
            "command": "uv",
            "args": ["run", "--no-sync", "python", "-m", "vaultspec_rag.server"],
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
        before = workspace_file_bytes(fresh_workspace)
        locks_before = sorted(fresh_workspace.rglob("*.lock"))

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            mode=target_mode,
        )

        assert workspace_file_bytes(fresh_workspace) == before
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
        # Core 0.1.48 reports a refreshed-but-otherwise-unchanged entry as
        # separate updated/unchanged counts rather than folding it into
        # skipped.
        assert preview_providers[existing_provider]["unchanged"] == 1
        assert preview_providers[existing_provider]["updated"] == 1
        assert preview_providers[missing_provider]["added"] == 1
        assert preview_providers[missing_provider]["unchanged"] == 1
        assert not preview_providers["claude"]["errors"]
        assert not preview_providers["codex"]["errors"]
        assert (
            read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == expected_command
        )
        assert read_codex_mcp(fresh_workspace)["vaultspec-rag"]["command"] == (
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
        workspace_before = workspace_file_bytes(fresh_workspace)
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

        assert workspace_file_bytes(fresh_workspace) == workspace_before
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
            read_mcp_json(fresh_workspace)["mcpServers"]["vaultspec-rag"]["command"]
            == expected_command
        )
        assert read_codex_mcp(fresh_workspace)["vaultspec-rag"]["command"] == (
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
        workspace_before = workspace_file_bytes(fresh_workspace)
        locks_before = {
            path: path.read_bytes() for path in fresh_workspace.rglob("*.lock")
        }

        preview = _install(
            fresh_workspace,
            dry_run=True,
            upgrade=True,
            skip=set(skip_tokens),
        )

        assert workspace_file_bytes(fresh_workspace) == workspace_before
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
        before = workspace_file_bytes(fresh_workspace)

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
        assert workspace_file_bytes(fresh_workspace) == before
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
        assert workspace_file_bytes(fresh_workspace) == before
