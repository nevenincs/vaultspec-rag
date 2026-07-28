"""Real installation integration behavior: provider failures."""

from __future__ import annotations

import json
from pathlib import Path  # noqa: TC003

import pytest
from vaultspec_core.core.enums import (  # pyright: ignore[reportMissingTypeStubs]
    InstallMode,
)
from vaultspec_core.core.manifest import (  # pyright: ignore[reportMissingTypeStubs]
    write_manifest,
)

from ...commands._uninstall import uninstall_run
from ._install_helpers import (
    _CONSUMER_PYPROJECT,
    _RAG_MCP_REL,
    _RAG_SKILL_REL,
    _install,
    read_codex_mcp,
    read_mcp_json,
    workspace_inventory,
)

pytestmark = [pytest.mark.integration]


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
        before = workspace_inventory(fresh_workspace)

        report = uninstall_run(path=fresh_workspace, force=True)

        assert report.mcp_sync_failed
        assert workspace_inventory(fresh_workspace) == before

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
        before = workspace_inventory(fresh_workspace)

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
        assert workspace_inventory(fresh_workspace) == before
        assert (fresh_workspace / _RAG_MCP_REL).is_file()
        assert "vaultspec-rag" in read_mcp_json(fresh_workspace)["mcpServers"]
        assert "vaultspec-rag" in read_codex_mcp(fresh_workspace)
