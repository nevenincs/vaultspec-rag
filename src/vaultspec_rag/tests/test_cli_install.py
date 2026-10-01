"""CLI coverage for install/uninstall exit codes and report rendering."""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, TextIO, cast

import pytest

from ..commands._tool_torch import ToolTorchRepairAction, ToolTorchRepairOutcome
from ..operator_state import _environment_probe
from ..operator_state._compute import ProbeDepth
from ..operator_state._environment_probe import InterpreterFacts
from ..operator_state._installation import ComputeCapability, InstallRole
from ..operator_state._models import ComputeReport
from ._cli_helpers import (
    TorchConfigAction,
    app,
    runner,
)

if TYPE_CHECKING:
    from ..commands._models import InstallReport, UninstallReport

pytestmark = [pytest.mark.unit]


def _fake_mps_torch() -> ModuleType:
    fake_torch = ModuleType("torch")
    fake_torch.__dict__.update(
        version=SimpleNamespace(cuda=None),
        cuda=SimpleNamespace(is_available=lambda: False),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: True)),
    )
    return fake_torch


def _probe_reporting(capability: ComputeCapability):
    """A daemon-interpreter probe double reporting *capability*."""

    def probe(
        interpreter: str,
        depth: ProbeDepth = ProbeDepth.METADATA,
        *,
        timeout: float | None = None,
    ) -> InterpreterFacts:
        del depth, timeout
        return InterpreterFacts(
            interpreter=interpreter,
            role=InstallRole.HOST,
            mcp_adapter=False,
            executable=interpreter,
            prefix="",
            compute=ComputeReport(capability=capability),
        )

    return probe


def test_install_warning_refuses_enabled_mps_cpu_fallback(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from ..cli import _gpu_errors

    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.MPS_POLICY_REFUSED),
    )

    _gpu_errors.warn_if_active_torch_not_accelerator()

    rendered = capsys.readouterr().out
    assert "PYTORCH_ENABLE_MPS_FALLBACK" in rendered
    assert "must be disabled" in rendered


def test_a_client_install_is_never_warned_about_torch(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A torch-free install is a choice, and must not read as a broken one.

    Mutation check: warning on every capability that blocks a start, rather
    than on defects only, prints the no-accelerator warning here; restoring
    the defect gate passes.
    """
    from ..cli import _gpu_errors

    monkeypatch.setattr(
        _environment_probe,
        "probe_interpreter",
        _probe_reporting(ComputeCapability.NOT_APPLICABLE),
    )

    _gpu_errors.warn_if_active_torch_not_accelerator()

    assert capsys.readouterr().out == ""


def test_gpu_error_reports_mps_fallback_refusal_not_missing_mps(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    import typer

    from .._gpu import MPS_FALLBACK_MESSAGE
    from ..cli import _gpu_errors

    monkeypatch.setitem(sys.modules, "torch", _fake_mps_torch())
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    with pytest.raises(typer.Exit):
        _gpu_errors._handle_gpu_error(RuntimeError(MPS_FALLBACK_MESSAGE))

    rendered = capsys.readouterr().out
    assert "Error: Apple MPS CPU fallback must be disabled" in rendered
    assert "PYTORCH_ENABLE_MPS_FALLBACK=1" in rendered


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
    """The NO_TORCH message renders its one install command whole."""

    @staticmethod
    def _render() -> str:
        import io

        from rich.console import Console

        from ..cli._gpu_errors import _no_torch_message

        buf = io.StringIO()
        Console(file=buf, force_terminal=False, color_system=None, width=120).print(
            _no_torch_message(), markup=False, highlight=False, soft_wrap=True
        )
        return buf.getvalue()

    def test_renders_the_gpu_host_install(self) -> None:
        # Mutation proof: restoring the bare `uv add "vaultspec-rag[gpu]"`
        # remedy, which resolves PyPI's CPU-only torch on Windows, failed the
        # first assertion.
        from ..operator_state._provisioning import host_install_command

        out = self._render()
        assert host_install_command() in out
        assert "uv add" not in out

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
    def _render(report: InstallReport) -> str:
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
        from vaultspec_core.core.types import (
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
        from vaultspec_core.core.types import (
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
    def _render(report: UninstallReport) -> str:
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
        from vaultspec_core.core.types import (
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


@pytest.mark.usefixtures("inference_host")
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

    def test_install_exit_skipped_code_on_skipped_non_tty(self, tmp_path: Path) -> None:
        """Non-TTY without ``--yes`` / ``--force``: torch-config skipped.

        Exit 2 is the shared table's "completed with a required step
        skipped", and it is the only outcome that earns that code - a run
        that failed exits 1.
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

    def test_install_exit_failure_code_on_error(self, tmp_path: Path) -> None:
        """A corrupt pyproject fails the run, so it exits 1, not 2.

        The two non-zero codes are not interchangeable: 2 means the run
        completed and skipped a required step, which a failed run did not
        do.
        """
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            "[project\nname = ", encoding="utf-8"
        )  # malformed
        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])
        assert result.exit_code == 1, result.output

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
        assert result.exit_code == 1, result.output


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


_REFUSAL_COMMAND = "uv pip install --python sentinel --reinstall-package torch"


def _blocking_repair(*_args: object, **_kwargs: object) -> ToolTorchRepairOutcome:
    """A repair outcome that stops the install, as a held tool env yields."""
    return ToolTorchRepairOutcome(
        ToolTorchRepairAction.HOLDER_DETECTED,
        "tool CUDA repair must run from outside C:/tools/vaultspec-rag\n"
        "  holders to clear first:",
        (_REFUSAL_COMMAND,),
        steps=(f"Install the CUDA build of torch: {_REFUSAL_COMMAND}",),
        capability=ComputeCapability.CPU_ONLY_BUILD,
        reason=ComputeCapability.CPU_ONLY_BUILD.label,
    )


class TestRefusedInstall:
    """A run that stopped before its first step says so, once.

    The blocked path reported ``action="install"``, so the report opened with
    "vaultspec-rag installed" over a run that wrote nothing, printed the
    default of provisioning steps that never ran, copied the refusal into the
    warnings so it appeared twice, and then diagnosed the same interpreter a
    second time in different words.
    """

    @staticmethod
    def _workspace(tmp_path: Path) -> Path:
        ws = tmp_path / "ws"
        ws.mkdir()
        (ws / "pyproject.toml").write_text(
            '[project]\nname = "demo"\nversion = "0.1.0"\n'
            'dependencies = ["vaultspec-rag", "torch>=2.4"]\n',
            encoding="utf-8",
            newline="",
        )
        return ws

    def test_a_blocked_install_renders_as_refused_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from ..commands import _install

        monkeypatch.setattr(_install, "repair_tool_torch", _blocking_repair)
        ws = self._workspace(tmp_path)

        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])

        # A refusal is a failure, not a skip for want of consent: nothing was
        # installed, so the requested state was not reached.
        assert result.exit_code == 1, result.output
        assert "vaultspec-rag installed" not in result.output
        assert "refused" in result.output
        assert ComputeCapability.CPU_ONLY_BUILD.label in result.output
        # A step that never ran has no outcome to report.
        assert "PyTorch configuration" not in result.output
        # One refusal, one command: the detail and the command used to be
        # copied into the warnings and printed a second time underneath.
        assert result.output.count(_REFUSAL_COMMAND) == 1
        assert result.output.count("must run from outside") == 1

    def test_a_blocked_upgrade_is_named_an_upgrade(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The refusal names the run that was asked for, not always install."""
        from ..commands import _install

        monkeypatch.setattr(_install, "repair_tool_torch", _blocking_repair)
        ws = self._workspace(tmp_path)

        result = runner.invoke(
            app, ["install", "--target", str(ws), "--yes", "--upgrade"]
        )

        assert "upgrade refused" in result.output
        assert result.exit_code == 1

    def test_the_refusal_is_one_stable_json_envelope(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import json

        from ..commands import _install

        monkeypatch.setattr(_install, "repair_tool_torch", _blocking_repair)
        ws = self._workspace(tmp_path)

        result = runner.invoke(app, ["install", "--target", str(ws), "--yes", "--json"])

        envelope = json.loads(result.stdout)
        assert envelope["status"] == "failed"
        payload = envelope["data"]
        assert payload["action"] == "install"
        assert payload["refused"]
        assert payload["warnings"] == []
        assert payload["tool_torch_repair"]["commands"] == [_REFUSAL_COMMAND]
        assert result.exit_code == 1
        # A step that never ran reports nothing, not its default: "not
        # changed" and "skipped" are answers a run gives.
        for field in (
            "torch_config_action",
            "torch_direct_dep_action",
            "torch_sync_action",
            "mcp_extra_action",
            "sync_added",
            "sync_updated",
            "sync_pruned",
            "provisioning",
        ):
            assert payload[field] is None, field

    def test_force_alone_does_not_authorise_the_repair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Guard assertion: --force overwrites files, it does not consent.

        It authorises replacing artefacts this product owns. Reading it as
        consent let a scripted `install --force` start a multi-gigabyte
        reinstall of packages in an environment the product did not create,
        which the accepted decision limits to `--yes` or a prompt.
        """
        from ..commands import _install

        authorised: list[bool] = []

        def _record(request: object) -> ToolTorchRepairOutcome:
            authorised.append(bool(getattr(request, "assume_yes", False)))
            return _blocking_repair()

        monkeypatch.setattr(_install, "repair_tool_torch", _record)
        ws = self._workspace(tmp_path)

        result = runner.invoke(app, ["install", "--target", str(ws), "--force"])

        assert authorised == [False]
        assert result.exit_code == 1, result.output
        assert _REFUSAL_COMMAND in result.output

    def test_yes_authorises_the_repair(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The pair of the flag above: --yes is consent, and reaches it."""
        from ..commands import _install

        authorised: list[bool] = []

        def _record(request: object) -> ToolTorchRepairOutcome:
            authorised.append(bool(getattr(request, "assume_yes", False)))
            return _blocking_repair()

        monkeypatch.setattr(_install, "repair_tool_torch", _record)
        ws = self._workspace(tmp_path)

        runner.invoke(app, ["install", "--target", str(ws), "--yes"])

        assert authorised == [True]

    def test_a_json_run_is_never_given_a_confirmer(self) -> None:
        """Guard assertion: one JSON document, whatever the streams look like.

        The prompt renders on the same stream as the envelope, and Windows
        reports stdin redirected from NUL as a terminal, so the terminal test
        alone put a question in front of the document a broker parses. Both
        streams here report a terminal and the environment declares nothing,
        so the JSON flag is the only thing that can withhold the confirmer.
        """
        from ..cli._install import _confirmation_hook

        class _Terminal:
            @staticmethod
            def isatty() -> bool:
                return True

        terminal = cast("TextIO", _Terminal())

        def _confirm(prompt: str) -> bool:
            raise AssertionError(f"resolving the hook asked: {prompt}")

        def _hook(*, json_output: bool) -> object:
            return _confirmation_hook(
                _confirm,
                json_output=json_output,
                environ={},
                stdin=terminal,
                stdout=terminal,
            )

        assert _hook(json_output=False) is _confirm
        assert _hook(json_output=True) is None

    def test_an_install_run_probes_an_interpreter_at_most_once(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two verify probes of one interpreter is two diagnoses of one fault.

        Guard assertion: the repair probed the interpreter and the
        post-install warning probed it again, which cost a second child
        interpreter and let one run print two verdicts that need not agree.
        """
        from ..commands import _tool_torch
        from ..operator_state._provisioning import ToolReceiptVerdict
        from ..operator_state._topology import RuntimeEnvKind

        calls: list[str] = []
        probe = _probe_reporting(ComputeCapability.READY)

        def counting_probe(
            interpreter: str,
            depth: ProbeDepth = ProbeDepth.METADATA,
            *,
            timeout: float | None = None,
        ) -> InterpreterFacts:
            if depth is ProbeDepth.VERIFY:
                calls.append(interpreter)
            return probe(interpreter, depth, timeout=timeout)

        monkeypatch.setattr(_environment_probe, "probe_interpreter", counting_probe)

        def _tool_env(_root: object) -> RuntimeEnvKind:
            return RuntimeEnvKind.UV_TOOL

        monkeypatch.setattr(_tool_torch, "classify_environment", _tool_env)

        def _durable(_interpreter: str) -> ToolReceiptVerdict:
            return ToolReceiptVerdict.DURABLE

        # A durable receipt is what leaves this environment needing nothing,
        # so the run reaches the post-install warning with the verdict the
        # repair already obtained. Without it the repair would run uv against
        # a real tool installation from a unit test.
        monkeypatch.setattr(_tool_torch, "classify_tool_receipt", _durable)
        ws = self._workspace(tmp_path)

        result = runner.invoke(app, ["install", "--target", str(ws), "--yes"])

        assert result.exit_code == 0, result.output
        assert len(calls) == 1, calls
