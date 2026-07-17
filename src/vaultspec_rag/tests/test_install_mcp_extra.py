"""`vaultspec-rag install` ensures the optional [mcp] extra, with a --no-mcp opt-out.

Install wires up the MCP surface (it seeds the rag MCP config that
`uv run vaultspec-search-mcp` launches), so by default it also installs that
server's dependency via `uv add vaultspec-rag[mcp]` - mcp is a base-install
opt-out, not a setup-time opt-in, mirroring the `--torch-config/--no-torch-config`
and `--provision/--no-provision` polarity. These tests are mock-free: the dry-run
path records intent without shelling out, and the classifier is a pure function.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..commands import install_run
from ..commands._uv_sync import (
    _classify_uv_add_result,  # pyright: ignore[reportPrivateUsage]
    _detect_rag_placement,  # pyright: ignore[reportPrivateUsage]
    _mcp_extra_add_command,  # pyright: ignore[reportPrivateUsage]
)

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.unit]


class TestInstallEnsuresMcpExtra:
    """install_mcp=True ensures the [mcp] extra; the CLI defaults it on."""

    def test_install_mcp_true_would_add_the_extra(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=True)
        assert report.mcp_extra_action == "would-add"

    def test_no_mcp_skips_the_extra(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=False)
        assert report.mcp_extra_action == "skipped"

    def test_orchestrator_default_is_off_so_callers_do_not_shell_out(
        self, tmp_path: Path
    ) -> None:
        # install_run defaults install_mcp=False (mirroring provision) so
        # programmatic callers and their network-free tests never run uv add;
        # the on-by-default polarity lives at the CLI edge.
        report = install_run(path=tmp_path, dry_run=True)
        assert report.mcp_extra_action == "skipped"

    def test_mcp_action_is_in_the_json_report(self, tmp_path: Path) -> None:
        report = install_run(path=tmp_path, dry_run=True, install_mcp=True)
        assert report.to_dict()["mcp_extra_action"] == "would-add"


def test_cli_install_flag_defaults_mcp_on() -> None:
    """The `vaultspec-rag install` --mcp/--no-mcp flag defaults to on."""
    import inspect

    from ..cli._install import handle_install

    param = inspect.signature(handle_install).parameters["install_mcp"]
    assert param.default is True


class TestClassifyUvAdd:
    """The uv-add result classifier covers success and failure streams."""

    def test_zero_exit_is_success_no_warning(self) -> None:
        action, warning = _classify_uv_add_result(returncode=0, stdout="", stderr="")
        assert action == "succeeded"
        assert warning is None

    def test_nonzero_exit_surfaces_stderr_as_a_warning(self) -> None:
        action, warning = _classify_uv_add_result(
            returncode=1, stdout="", stderr="No solution found"
        )
        assert action == "failed"
        assert warning is not None
        assert "No solution found" in warning
        assert "--no-mcp" in warning  # actionable remediation

    def test_nonzero_exit_falls_back_to_stdout(self) -> None:
        action, warning = _classify_uv_add_result(
            returncode=2, stdout="lockfile conflict", stderr=""
        )
        assert action == "failed"
        assert warning is not None
        assert "lockfile conflict" in warning


class TestMcpExtraPlacement:
    """The extra follows the host's declaration, then the declared mode.

    A bare ``uv add`` always targets runtime ``[project.dependencies]``,
    which leaked ``vaultspec-rag[mcp]`` into a dev-mode host's published
    dependency list (issue #231). The command matrix is a pure function.
    """

    @pytest.mark.parametrize(
        ("placement", "mode", "expected"),
        [
            (None, "dependency", ["uv", "add", "vaultspec-rag[mcp]"]),
            (None, "dev", ["uv", "add", "--group", "dev", "vaultspec-rag[mcp]"]),
            ("runtime", "dev", ["uv", "add", "vaultspec-rag[mcp]"]),
            ("runtime", "dependency", ["uv", "add", "vaultspec-rag[mcp]"]),
            (
                "dev",
                "dependency",
                ["uv", "add", "--group", "dev", "vaultspec-rag[mcp]"],
            ),
            ("docs", "dev", ["uv", "add", "--group", "docs", "vaultspec-rag[mcp]"]),
        ],
    )
    def test_placement_matrix(
        self, placement: str | None, mode: str, expected: list[str]
    ) -> None:
        assert _mcp_extra_add_command(placement, mode) == expected

    @pytest.mark.parametrize("placement", [None, "runtime", "dev"])
    def test_tool_mode_never_runs_uv_add(self, placement: str | None) -> None:
        assert _mcp_extra_add_command(placement, "tool") is None

    def test_tool_mode_reports_skip_without_subprocess(self, tmp_path: Path) -> None:
        from ..commands._models import InstallReport
        from ..commands._uv_sync import (
            _run_uv_add_mcp_extra,  # pyright: ignore[reportPrivateUsage]
        )

        report = InstallReport(action="install", target=tmp_path)
        _run_uv_add_mcp_extra(target=tmp_path, report=report, mode="tool")
        assert report.mcp_extra_action == "skipped-tool-mode"
        assert not report.warnings


class TestDetectRagPlacement:
    """Reading the host's actual vaultspec-rag declaration from pyproject."""

    def test_runtime_dependencies_win(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0"\n'
            'dependencies = ["vaultspec-rag[mcp]>=0.2.23"]\n'
            '[dependency-groups]\ndev = ["vaultspec-rag"]\n',
            encoding="utf-8",
        )
        assert _detect_rag_placement(tmp_path) == "runtime"

    def test_dev_group_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0"\ndependencies = []\n'
            '[dependency-groups]\ndev = ["pytest", "vaultspec-rag>=0.3.0"]\n',
            encoding="utf-8",
        )
        assert _detect_rag_placement(tmp_path) == "dev"

    def test_custom_group_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0"\n'
            '[dependency-groups]\ntooling = ["vaultspec-rag"]\n',
            encoding="utf-8",
        )
        assert _detect_rag_placement(tmp_path) == "tooling"

    def test_longer_names_do_not_match(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0"\n'
            'dependencies = ["vaultspec-rag-extras"]\n',
            encoding="utf-8",
        )
        assert _detect_rag_placement(tmp_path) is None

    def test_absent_declaration_and_missing_file(self, tmp_path: Path) -> None:
        assert _detect_rag_placement(tmp_path) is None
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0"\n', encoding="utf-8"
        )
        assert _detect_rag_placement(tmp_path) is None

    def test_malformed_pyproject_is_non_fatal(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text("not [ toml", encoding="utf-8")
        assert _detect_rag_placement(tmp_path) is None


class TestSeedRefreshOnUpgrade:
    """install --upgrade rewrites a pre-parity exe-form MCP seed (issue #231).

    Pre-parity workspaces carry the old static exe-form entry that bypasses
    core's renderer entirely (the Windows exe-lock incident shape); the
    seeder must classify it [UPDATE] under force and land the tokenized form
    with the tool-mode extra spec.
    """

    def test_stale_exe_seed_is_refreshed_to_tokenized_form(
        self, tmp_path: Path
    ) -> None:
        import json

        from ..builtins import seed_builtins

        mcps = tmp_path / ".vaultspec" / "mcps"
        mcps.mkdir(parents=True)
        stale = mcps / "vaultspec-rag.builtin.json"
        stale.write_text(
            '{"command": "uv", "args": ["run", "vaultspec-search-mcp"]}',
            encoding="utf-8",
        )

        results = seed_builtins(tmp_path / ".vaultspec", force=True)
        actions = dict(results)
        assert actions["mcps/vaultspec-rag.builtin.json"] == "[UPDATE]"
        seeded = json.loads(stale.read_text(encoding="utf-8"))
        assert seeded["_vaultspec_mode_tool_spec"] == "vaultspec-rag[mcp]"
        assert seeded["command"] == "@@VAULTSPEC_INSTALL_MODE_COMMAND@@"

    def test_existing_seed_untouched_without_force(self, tmp_path: Path) -> None:
        from ..builtins import seed_builtins

        mcps = tmp_path / ".vaultspec" / "mcps"
        mcps.mkdir(parents=True)
        stale = mcps / "vaultspec-rag.builtin.json"
        stale.write_text('{"command": "uv"}', encoding="utf-8")

        results = seed_builtins(tmp_path / ".vaultspec", force=False)
        assert "mcps/vaultspec-rag.builtin.json" not in dict(results)
        assert stale.read_text(encoding="utf-8") == '{"command": "uv"}'


class TestUpgradeRefreshesSeedEndToEnd:
    """install_run(upgrade=True) itself forces the seed refresh (issue #231).

    The direct seeder test above pins the mechanism; this pins the wiring -
    the upgrade flag must reach seed_builtins as force.
    """

    def test_install_upgrade_rewrites_a_stale_exe_seed(self, tmp_path: Path) -> None:
        import json

        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0"\ndependencies = []\n',
            encoding="utf-8",
        )
        mcps = tmp_path / ".vaultspec" / "mcps"
        mcps.mkdir(parents=True)
        stale = mcps / "vaultspec-rag.builtin.json"
        stale.write_text(
            '{"command": "uv", "args": ["run", "vaultspec-search-mcp"]}',
            encoding="utf-8",
        )

        install_run(
            path=tmp_path,
            upgrade=True,
            provision=False,
            configure_torch=False,
            install_mcp=False,
        )

        seeded = json.loads(stale.read_text(encoding="utf-8"))
        assert seeded.get("_vaultspec_mode_tool_spec") == "vaultspec-rag[mcp]"


class TestClassifierNamesTheRealCommand:
    """Failure remediation must repeat the placement-aware command that ran."""

    def test_group_command_appears_in_failure_warning(self) -> None:
        action, warning = _classify_uv_add_result(
            returncode=2,
            stdout="",
            stderr="resolution failed",
            command_display='uv add --group dev "vaultspec-rag[mcp]"',
        )
        assert action == "failed"
        assert warning is not None
        assert 'uv add --group dev "vaultspec-rag[mcp]"' in warning
        assert "run `uv add vaultspec-rag[mcp]` manually" not in warning

    def test_normalized_names_still_detected(self, tmp_path: Path) -> None:
        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "host"\nversion = "0"\n'
            '[dependency-groups]\ndev = ["Vaultspec_RAG>=0.3.0"]\n',
            encoding="utf-8",
        )
        assert _detect_rag_placement(tmp_path) == "dev"
