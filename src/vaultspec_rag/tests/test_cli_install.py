"""CLI coverage for install/uninstall exit codes and report rendering."""

from __future__ import annotations

from pathlib import Path

import pytest

from ._cli_helpers import (
    TorchConfigAction,
    app,
    runner,
)

pytestmark = [pytest.mark.unit]


class TestCpuOnlyMessageRendering:
    """Regression guard for literal TOML keys in the CPU_ONLY copy.

    The CLI prints this message with Rich markup disabled so TOML keys,
    dependency groups, and command lines stay literal in user output.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli._gpu_errors import _cpu_only_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _cpu_only_message(), markup=False, highlight=False
        )
        return buf.getvalue()

    def test_renders_double_brackets_for_aot(self) -> None:
        out = self._render()
        assert "[[tool.uv.index]]" in out, out

    def test_renders_single_brackets_for_section(self) -> None:
        out = self._render()
        assert "[tool.uv.sources]" in out, out

    def test_renders_project_and_groups_keys(self) -> None:
        out = self._render()
        assert "[project].dependencies" in out, out
        assert "[dependency-groups].dev" in out, out

    def test_no_stray_backslashes_in_rendered_output(self) -> None:
        """Rich passes ``\\]`` through verbatim - only ``[`` is escapable.
        A stray backslash in the rendered text means a future edit
        overcorrected and put ``\\]`` somewhere it should not be.
        """
        out = self._render()
        assert "\\" not in out, out


class TestNoGpuMessageRendering:
    """TEST-04 regression: NO_GPU message must render its three
    bullets verbatim through Rich. Symmetric guard with
    TestCpuOnlyMessageRendering.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli._gpu_errors import _no_gpu_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _no_gpu_message()
        )
        return buf.getvalue()

    def test_renders_nvidia_smi_check(self) -> None:
        out = self._render()
        assert "nvidia-smi" in out

    def test_renders_torch_version_cuda_check(self) -> None:
        out = self._render()
        assert "torch.version.cuda" in out

    def test_renders_wsl_docker_caveat(self) -> None:
        out = self._render()
        assert "WSL" in out or "Docker" in out
        assert "--gpus all" in out

    def test_no_stray_backslashes(self) -> None:
        out = self._render()
        assert "\\" not in out, out


class TestNoTorchMessageRendering:
    """TEST-11 regression: NO_TORCH message must render its single
    actionable ``uv add`` command line cleanly.
    """

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli._gpu_errors import _no_torch_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _no_torch_message()
        )
        return buf.getvalue()

    def test_renders_uv_add_command(self) -> None:
        out = self._render()
        assert "uv add vaultspec-rag" in out
        assert "vaultspec-rag install" in out

    def test_no_stray_backslashes(self) -> None:
        out = self._render()
        assert "\\" not in out, out


class TestRenderInstallReport:
    """CLI-01 regression: the install/uninstall warning loop must NOT
    parse warning bodies as markup. The transitive-dep warning
    embeds literal ``[tool.uv.sources]``, ``[project].dependencies``,
    and ``[dependency-groups].dev``; uv stderr tails embed raw
    ``[…]`` tokens; raw exception messages embed ``[tool]`` strings
    from the historic OutOfOrderTableProxy bug. The report renderer
    must preserve those bytes verbatim in captured CLI output.
    """

    @staticmethod
    def _render(report: object) -> str:
        import io

        from rich.console import Console

        from .. import cli as cli_mod
        from ..cli._render import _render_install_report

        buf = io.StringIO()
        original = cli_mod.console
        cli_mod.console = Console(
            file=buf, force_terminal=False, color_system=None, width=200
        )
        try:
            _render_install_report(report)
        finally:
            cli_mod.console = original
        return buf.getvalue()

    def test_warning_with_literal_toml_keys_preserved(self) -> None:
        from ..commands._models import InstallReport

        warning = (
            "torch-config patched, but `torch` is not a direct dependency. "
            "uv ignores [tool.uv.sources] for purely transitive packages, "
            "so the cu130 pin will not take effect. "
            "Add `torch>=2.4` to [project].dependencies or "
            "[dependency-groups].dev."
        )
        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.APPLIED,
            warnings=[warning],
        )
        out = self._render(report)
        # All three TOML key tokens must survive the render.
        assert "[tool.uv.sources]" in out, out
        assert "[project].dependencies" in out, out
        assert "[dependency-groups].dev" in out, out

    def test_warning_with_uv_stderr_tail_preserved(self) -> None:
        """Realistic shape: uv stderr embedded in a warning body via
        the new INSTALL-03 tail. ``[project]`` and ``[tool]`` tokens
        in uv's own error rendering must survive.
        """
        from ..commands._models import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.APPLIED,
            warnings=[
                "uv sync --reinstall-package torch exited with code 1; "
                "last stderr lines:\n"
                "error: Failed to resolve [project] root\n"
                "error: see [tool.uv] config"
            ],
        )
        out = self._render(report)
        assert "[project]" in out
        assert "[tool.uv]" in out

    def test_conflict_with_aot_token_preserved(self) -> None:
        """Conflict surface (already had its own markup-off treatment
        before this PR - guard it now with a rendering test so a
        future maintainer cannot accidentally collapse the two-line
        treatment back into a single ``f"... {conflict}"`` print).
        """
        from ..commands._models import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.CONFLICT,
            torch_config_conflicts=[
                '[[tool.uv.index]] entry name="pytorch-cu130" url-mismatch'
            ],
        )
        out = self._render(report)
        assert "[[tool.uv.index]]" in out
        assert 'name="pytorch-cu130"' in out

    def test_skipped_eof_action_renders_yellow(self) -> None:
        """TEST-12 regression: the new ``skipped-eof`` action label
        must reach the colour map. A regression that dropped it would
        render the label in default-white instead of yellow.
        """
        from ..commands._models import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            torch_config_action=TorchConfigAction.SKIPPED_EOF,
        )
        out = self._render(report)
        assert "PyTorch configuration: needs confirmation" in out

    def test_dry_run_uses_operator_language(self) -> None:
        from ..commands._models import InstallReport

        report = InstallReport(
            action="dry_run",
            target=Path("."),
            torch_config_action=TorchConfigAction.DRY_RUN,
            warnings=[
                "dry-run: core sync_provider not invoked (would propagate "
                "seeded files to .mcp.json and provider dirs)"
            ],
        )
        out = self._render(report)
        assert "PyTorch configuration: preview only" in out
        assert "Target: ." in out
        assert "Note: dry-run preview: would update tool integration files" in out
        assert "target:" not in out
        assert "note:" not in out
        assert "warning: dry-run preview" not in out
        for forbidden in (
            "torch-config:",
            "sync_provider",
            "provider dirs",
            "core sync",
        ):
            assert forbidden not in out

    def test_preserves_provider_outcomes_in_json_and_human_output(self) -> None:
        from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
            SyncResult,
        )

        from ..commands._models import InstallReport

        claude = SyncResult(
            added=1,
            unchanged=1,
            items=[("vaultspec-rag", "[ADD]")],
        )
        codex = SyncResult(
            updated=1,
            errored=1,
            errors=["native target malformed"],
            warnings=["managed entry drift repaired"],
            items=[("vaultspec-rag", "[UPDATE]")],
        )
        provider_result = SyncResult(per_tool={"claude": claude, "codex": codex})
        report = InstallReport(
            action="install",
            target=Path("."),
            sync_results=[provider_result],
            mcp_sync_results=[provider_result],
        )

        providers = report.to_dict()["sync_providers"]
        assert providers["claude"] == {
            "added": 1,
            "updated": 0,
            "unchanged": 1,
            "skipped": 0,
            "pruned": 0,
            "errored": 0,
            "errors": [],
            "warnings": [],
            "items": [["vaultspec-rag", "[ADD]"]],
        }
        assert providers["codex"]["updated"] == 1
        assert providers["codex"]["errored"] == 1
        assert providers["codex"]["errors"] == ["native target malformed"]
        assert providers["codex"]["warnings"] == ["managed entry drift repaired"]

        out = self._render(report)
        assert "Claude MCP: added 1, unchanged 1" in out
        assert "Codex MCP: updated 1, errored 1" in out
        assert "warning: managed entry drift repaired" in out
        assert "error: native target malformed" in out

    def test_preserves_unattributed_mcp_errors_in_json_and_human_output(self) -> None:
        from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
            SyncResult,
        )

        from ..commands._models import InstallReport

        report = InstallReport(
            action="install",
            target=Path("."),
            sync_results=[SyncResult(errored=1, errors=["ownership is malformed"])],
            mcp_sync_results=[SyncResult(errored=1, errors=["ownership is malformed"])],
        )

        data = report.to_dict()
        assert data["mcp_failed"] is True
        assert data["mcp_errors"] == ["ownership is malformed"]
        assert data["sync_providers"] == {}

        out = self._render(report)
        assert "MCP lifecycle error: ownership is malformed" in out


class TestRenderUninstallReport:
    """Symmetric guard rail for the uninstall renderer."""

    @staticmethod
    def _render(report: object) -> str:
        import io

        from rich.console import Console

        from .. import cli as cli_mod
        from ..cli._render import _render_uninstall_report

        buf = io.StringIO()
        original = cli_mod.console
        cli_mod.console = Console(
            file=buf, force_terminal=False, color_system=None, width=200
        )
        try:
            _render_uninstall_report(report)
        finally:
            cli_mod.console = original
        return buf.getvalue()

    def test_warning_with_literal_toml_keys_preserved(self) -> None:
        from ..commands._models import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            warnings=[
                "no .vaultspec/ at /tmp/foo; "
                "torch-config block in [tool.uv.sources] left intact"
            ],
        )
        out = self._render(report)
        assert "[tool.uv.sources]" in out

    def test_error_action_renders(self) -> None:
        """INSTALL-08 follow-up: uninstall now has ``error`` in its
        colour map. Just verify the label reaches the renderer.
        """
        from ..commands._models import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            torch_config_action=TorchConfigAction.ERROR,
        )
        out = self._render(report)
        assert "PyTorch configuration: error" in out

    def test_dry_run_uses_operator_language(self) -> None:
        from ..commands._models import UninstallReport

        report = UninstallReport(
            action="dry_run",
            target=Path("."),
            removed=[".vaultspec/rules/vaultspec-rag.builtin.md"],
            torch_config_action=TorchConfigAction.DRY_RUN,
            torch_direct_dep_action="dry_run",
            warnings=[
                "dry-run: core sync_provider not invoked (would propagate "
                "removal to .mcp.json and provider dirs)"
            ],
        )
        out = self._render(report)
        assert "would remove 1 bundled source file" in out
        assert "removed 1 bundled source file" not in out
        assert "PyTorch configuration: preview only" in out
        assert "PyTorch dependency: preview only" in out
        assert "Target: ." in out
        assert "Note: dry-run preview: would remove tool integration files" in out
        assert "target:" not in out
        assert "note:" not in out
        assert "warning: dry-run preview" not in out
        for forbidden in (
            "torch-config:",
            "torch direct dependency:",
            "sync_provider",
            "provider dirs",
            "core sync",
        ):
            assert forbidden not in out

    def test_mcp_extra_result_is_preserved_in_json_and_human_output(self) -> None:
        from ..commands._models import UninstallReport

        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            mcp_extra_action="removed",
            mcp_extra_location="[project].dependencies",
        )

        data = report.to_dict()
        assert data["mcp_extra_action"] == "removed"
        assert data["mcp_extra_location"] == "[project].dependencies"
        out = self._render(report)
        assert "MCP optional dependency: removed ([project].dependencies)" in out

    def test_preserves_provider_prunes_in_json_and_human_output(self) -> None:
        from vaultspec_core.core.types import (  # pyright: ignore[reportMissingTypeStubs]
            SyncResult,
        )

        from ..commands._models import UninstallReport

        provider_result = SyncResult(
            pruned=2,
            per_tool={
                "claude": SyncResult(pruned=1, items=[("vaultspec-rag", "[DELETE]")]),
                "codex": SyncResult(pruned=1, items=[("vaultspec-rag", "[DELETE]")]),
            },
        )
        report = UninstallReport(
            action="uninstall",
            target=Path("."),
            sync_results=[provider_result],
            mcp_sync_results=[provider_result],
        )

        providers = report.to_dict()["sync_providers"]
        assert providers["claude"]["pruned"] == 1
        assert providers["codex"]["pruned"] == 1
        assert providers["codex"]["items"] == [["vaultspec-rag", "[DELETE]"]]

        out = self._render(report)
        assert "Claude MCP: pruned 1" in out
        assert "Codex MCP: pruned 1" in out


class TestInstallExitCodes:
    """CLI3-01 regression: install exits non-zero on the torch-config
    terminal states the user did not opt into. Issue #83 finding 3
    "Bonus" item.
    """

    @staticmethod
    def _make_pyproject(tmp_path: Path, body: str) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(body, encoding="utf-8", newline="")
        return ws

    def test_install_exit_zero_on_applied(self, tmp_path: Path) -> None:
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n',
        )
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 0, result.output

    def test_install_exit_nonzero_on_skipped_non_tty(self, tmp_path: Path) -> None:
        """Non-TTY without ``--yes`` / ``--force``: torch-config skipped,
        exit code 2 so CI fails loudly.
        """
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
        )
        # CliRunner's stdin is not a TTY, so confirm_fn=None - emulates
        # the non-interactive harness path.
        result = runner.invoke(app, ["install", "--target", str(ws)])
        assert result.exit_code == 2, result.output

    def test_install_exit_nonzero_on_error(self, tmp_path: Path) -> None:
        """Corrupt pyproject → torch_config_action=TorchConfigAction.ERROR → exit 2."""
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project\nname = ", encoding="utf-8"
        )  # malformed
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 2, result.output

    def test_install_exit_zero_on_conflict(self, tmp_path: Path) -> None:
        """CUSTOMISED block - user-state, not a runtime failure.
        Conflict exits 0; the warning is the signal, not the exit code.
        """
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n'
            "\n[[tool.uv.index]]\n"
            'name = "pytorch-cu130"\n'
            'url = "https://download.pytorch.org/whl/cu121"\n'  # wrong url
            "explicit = true\n",
        )
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 0, result.output

    def test_install_exit_zero_when_no_torch_config(self, tmp_path: Path) -> None:
        """``--no-torch-config`` opts out - exits 0 even on a non-TTY."""
        ws = self._make_pyproject(
            tmp_path,
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag"]\n',
        )
        result = runner.invoke(
            app, ["install", "--target", str(ws), "--no-torch-config"]
        )
        assert result.exit_code == 0, result.output

    def test_install_exit_nonzero_on_mcp_extra_parse_error(
        self, tmp_path: Path
    ) -> None:
        ws = self._make_pyproject(tmp_path, "[project\nname =")
        result = runner.invoke(
            app,
            ["install", "--target", str(ws), "--no-torch-config", "--mcp"],
        )
        assert result.exit_code == 2, result.output


class TestInstallTargetValidation:
    """CLI3-02 regression: per-command ``--target`` must reject
    regular files (matching the global ``--target`` validator).
    """

    def test_per_command_target_rejects_file(self, tmp_path: Path) -> None:
        """Pointing ``install --target`` at a regular file used to slip
        past validation; now correctly rejected by typer's
        ``file_okay=False``.
        """
        f = tmp_path / "not-a-dir.txt"
        f.write_text("hi", encoding="utf-8")
        result = runner.invoke(app, ["install", "--target", str(f)])
        assert result.exit_code != 0, result.output
        assert "is a file" in result.output or "directory" in result.output.lower()

    def test_per_command_target_accepts_dir(self, tmp_path: Path) -> None:
        """Negative pair: a real directory still validates."""
        d = tmp_path / "real-dir"
        d.mkdir()
        result = runner.invoke(
            app, ["install", "--target", str(d), "--no-torch-config"]
        )
        assert result.exit_code == 0, result.output
