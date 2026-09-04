"""Safety contracts for durable CUDA repair in persistent tool environments."""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING

import pytest
from pytest import MonkeyPatch

from ..cli._gpu_errors import RuntimeEnvKind
from ..commands import _tool_torch

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


def _persistent_tool_env(_interpreter: str) -> RuntimeEnvKind:
    return RuntimeEnvKind.UV_TOOL


def _no_visible_cuda_device(
    _interpreter: str, timeout: float = 60.0
) -> tuple[bool, str]:
    del timeout
    return True, "torch is a CUDA build but no CUDA device is visible (driver/GPU)"


def _cuda_ready_probe(_interpreter: str, timeout: float = 60.0) -> None:
    del timeout
    return None


def _cpu_torch_probe(_interpreter: str, timeout: float = 60.0) -> tuple[bool, str]:
    del timeout
    return True, "the service interpreter has a CPU-only torch wheel"


@pytest.mark.parametrize(
    ("exit_code", "is_installation_defect"),
    [(3, True), (4, True), (5, False), (7, False)],
)
def test_accelerator_probe_defect_classification_matches_its_exit_contract(
    exit_code: int, *, is_installation_defect: bool
) -> None:
    """Only missing torch and no supported accelerator merit a reinstall."""
    from ..cli._process import (
        _accelerator_probe_exit_outcome,
        accelerator_probe_is_torch_installation_defect,
    )

    outcome = _accelerator_probe_exit_outcome(exit_code)

    assert outcome is not None
    assert (
        accelerator_probe_is_torch_installation_defect(outcome[1])
        is is_installation_defect
    )


def test_receipt_requires_the_exact_cuda_wheel(tmp_path: Path) -> None:
    receipt = tmp_path / "uv-receipt.toml"
    wheel = "https://example.test/torch-2.9.0%2Bcu130.whl"
    receipt.write_text(
        '[tool]\nrequirements = [{ name = "torch", url = "' + wheel + '" }]\n',
        encoding="utf-8",
    )
    assert _tool_torch._receipt_has_cuda_requirement(receipt, wheel)
    assert not _tool_torch._receipt_has_cuda_requirement(receipt, wheel + "-other")
    receipt.write_text(
        '[tool]\nrequirements = [{ name = "other", url = "' + wheel + '" }]\n',
        encoding="utf-8",
    )
    assert not _tool_torch._receipt_has_cuda_requirement(receipt, wheel)
    receipt.write_text('[tool]\nnote = "' + wheel + '"\n', encoding="utf-8")
    assert not _tool_torch._receipt_has_cuda_requirement(receipt, wheel)


def test_a_non_interactive_run_reports_the_handoff_instead_of_stopping(
    tmp_path: Path,
) -> None:
    """No terminal is needed to be told what to run.

    The transaction used to demand confirmation for a replacement it performed;
    without a terminal it refused, which made a defective tool environment
    impossible to diagnose from a script. Nothing is replaced now, so nothing
    is asked, and the same report comes back either way.
    """
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter), "CPU-only torch", dry_run=False
    )

    assert outcome.action in {
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
    }
    assert "uv tool install" in outcome.command


def test_a_defective_tool_is_handed_off_rather_than_replaced(
    tmp_path: Path,
) -> None:
    """The transaction refuses and hands over the command; it never replaces.

    The environment being repaired is the one this process runs from, so any
    replacement issued here would have to remove the interpreter issuing it.
    The outcome therefore blocks the install and carries the command for a
    shell that holds nothing.
    """
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter), "CPU-only torch", dry_run=False
    )

    assert outcome.action in {
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
    }
    assert outcome.blocks_install
    assert "uv tool install" in outcome.command
    assert "must run from outside" in outcome.detail


def test_the_repair_module_cannot_launch_a_replacement_at_all() -> None:
    """Guard assertion: no path in this module spawns uv.

    A refusal that merely avoids the call today is one refactor away from
    calling it again, so the absence is asserted structurally rather than
    behaviourally.
    """
    source = inspect.getsource(_tool_torch)

    assert "subprocess" not in source
    assert not hasattr(_tool_torch, "subprocess")


def test_cuda_build_without_a_visible_device_never_reinstalls(
    monkeypatch: MonkeyPatch,
) -> None:
    """A driver/device problem is diagnostic, not a reason to rewrite the tool."""
    from ..cli import _gpu_errors, _process

    monkeypatch.setattr(
        _gpu_errors,
        "classify_interpreter_env",
        _persistent_tool_env,
    )
    monkeypatch.setattr(
        _process,
        "_probe_daemon_accelerator",
        _no_visible_cuda_device,
    )

    def _unexpected_repair(
        *_args: object, **_kwargs: object
    ) -> _tool_torch.ToolTorchRepairOutcome:
        raise AssertionError("a CUDA build without a device must not be reinstalled")

    monkeypatch.setattr(_tool_torch, "_repair_defective_tool", _unexpected_repair)

    outcome = _tool_torch.repair_tool_torch(dry_run=False, interpreter="ignored")

    assert outcome.action is _tool_torch.ToolTorchRepairAction.CUDA_UNVERIFIED
    assert outcome.blocks_install


def test_the_handoff_reports_a_receipt_that_already_carries_the_pin(
    tmp_path: Path,
) -> None:
    """An operator is told when the receipt is right and the environment is not.

    The two drift apart exactly once: after a replacement was interrupted, the
    receipt describes an environment that no longer exists. Saying so is what
    separates "run this command" from "your pin is missing".
    """
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()
    spec = _tool_torch.tool_cuda_install_spec()
    (tmp_path / "uv-receipt.toml").write_text(
        f"""[tool]
requirements = [{{ name = "torch", url = "{spec.wheel_url}" }}]
""",
        encoding="utf-8",
    )

    outcome = _tool_torch._handoff_outcome(str(interpreter), spec, "uv tool install")

    assert "the receipt already pins this wheel" in outcome.detail


def test_the_handed_over_command_pins_the_version_and_keeps_recorded_extras(
    tmp_path: Path,
) -> None:
    """A repair asks for the tool it found, not the newest one with new extras.

    Guard assertion: a bare package name resolves to whatever is newest, so
    the command that fixes a torch wheel would also upgrade the tool and
    impose this build's extras on an operator who chose otherwise.
    """
    import importlib.metadata

    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()
    (tmp_path / "uv-receipt.toml").write_text(
        """[tool]
requirements = [{ name = "vaultspec-rag", extras = ["mcp"] }]
""",
        encoding="utf-8",
    )

    requirement = _tool_torch._tool_package_requirement(str(interpreter))

    version = importlib.metadata.version("vaultspec-rag")
    assert requirement == f"vaultspec-rag[mcp]=={version}"
    assert "gpu" not in requirement


def test_a_receipt_without_the_package_falls_back_to_the_bundled_request(
    tmp_path: Path,
) -> None:
    """An environment recording nothing gets the shipped specification."""
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    assert (
        _tool_torch._tool_package_requirement(str(interpreter))
        == _tool_torch._tool_package_spec()
    )


def test_a_handoff_is_visible_without_json(capsys: pytest.CaptureFixture[str]) -> None:
    """The operator sees the refusal, the holders and the command in plain output.

    Guard assertion: this outcome used to reach `--json` only, so an operator
    running the install normally was told nothing at all about an environment
    that cannot run the GPU stack.
    """
    from ..cli._render import _render_tool_torch_repair

    outcome = _tool_torch.ToolTorchRepairOutcome(
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
        "tool CUDA repair must run from outside C:/tools/vaultspec-rag"
        + chr(10)
        + "  holders to clear first:"
        + chr(10)
        + "    pid 4321 (end this process): C:/tools/vaultspec-rag/Scripts/python.exe",
        "uv tool install --force ...",
    )

    _render_tool_torch_repair(outcome)

    printed = capsys.readouterr().out
    assert "Tool environment needs a CUDA repair" in printed
    assert "pid 4321" in printed
    assert "uv tool install --force" in printed


def test_a_healthy_tool_environment_prints_no_repair_section(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An install with no tool problem does not grow a section saying so."""
    from ..cli._render import _render_tool_torch_repair

    _render_tool_torch_repair(
        _tool_torch.ToolTorchRepairOutcome(
            _tool_torch.ToolTorchRepairAction.ALREADY_READY, "fine", ""
        )
    )
    _render_tool_torch_repair(None)

    assert capsys.readouterr().out == ""


def test_the_install_report_itself_carries_the_repair_section(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The section reaches plain install output, not just the helper.

    Guard assertion: the defect this closes was a renderer that never read
    `tool_torch_repair` at all, so proving the helper works in isolation
    proves nothing about what an operator sees. This renders the whole report.
    """
    from ..cli._render import _render_install_report
    from ..commands._models import InstallReport

    report = InstallReport(action="install", target=tmp_path)
    report.tool_torch_repair = _tool_torch.ToolTorchRepairOutcome(
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        "tool CUDA repair must run from outside " + str(tmp_path),
        "uv tool install --force ...",
    )

    _render_install_report(report)

    printed = capsys.readouterr().out
    assert "Tool environment needs a CUDA repair" in printed
    assert "uv tool install --force" in printed


def test_a_healthy_tool_interpreter_needs_no_repair(monkeypatch: MonkeyPatch) -> None:
    """A CUDA-ready environment ends the transaction without a report."""
    from ..cli import _gpu_errors, _process

    monkeypatch.setattr(_gpu_errors, "classify_interpreter_env", _persistent_tool_env)
    monkeypatch.setattr(_process, "_probe_daemon_accelerator", _cuda_ready_probe)

    outcome = _tool_torch.repair_tool_torch(dry_run=False, interpreter="ignored")

    assert outcome.action is _tool_torch.ToolTorchRepairAction.ALREADY_READY
    assert not outcome.blocks_install


def test_a_project_venv_is_not_this_transaction_s_business(
    monkeypatch: MonkeyPatch,
) -> None:
    """Only a persistent tool environment is repaired through this path."""
    from ..cli import _gpu_errors

    monkeypatch.setattr(
        _gpu_errors,
        "classify_interpreter_env",
        lambda _interpreter: RuntimeEnvKind.PROJECT_VENV,
    )

    outcome = _tool_torch.repair_tool_torch(dry_run=False, interpreter="ignored")

    assert outcome.action is _tool_torch.ToolTorchRepairAction.NOT_APPLICABLE
    assert not outcome.blocks_install


def test_a_dry_run_previews_the_command_without_inspecting_holders(
    tmp_path: Path,
) -> None:
    """A preview names what is needed and why, and stops there."""
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()

    outcome = _tool_torch._repair_defective_tool(
        str(interpreter), "CPU-only torch", dry_run=True
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.DRY_RUN
    assert "CPU-only torch" in outcome.detail
    assert "uv tool install" in outcome.command
    assert outcome.holders == ()


@pytest.mark.parametrize(
    "action",
    [
        _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED,
        _tool_torch.ToolTorchRepairAction.HANDOFF_REQUIRED,
        _tool_torch.ToolTorchRepairAction.CUDA_UNVERIFIED,
    ],
)
def test_every_unresolved_outcome_stops_the_install(
    action: _tool_torch.ToolTorchRepairAction,
) -> None:
    """An environment that cannot run the stack is never installed over.

    Guard assertion: continuing past any of these would leave the operator with
    a completed install on top of an environment that cannot serve a request.
    """
    outcome = _tool_torch.ToolTorchRepairOutcome(action, "detail", "command")

    assert outcome.blocks_install


@pytest.mark.parametrize(
    "action",
    [
        _tool_torch.ToolTorchRepairAction.NOT_APPLICABLE,
        _tool_torch.ToolTorchRepairAction.ALREADY_READY,
        _tool_torch.ToolTorchRepairAction.DRY_RUN,
    ],
)
def test_a_resolved_outcome_lets_the_install_continue(
    action: _tool_torch.ToolTorchRepairAction,
) -> None:
    """Nothing to repair, or nothing asked for, does not block the install."""
    outcome = _tool_torch.ToolTorchRepairOutcome(action, "detail", "command")

    assert not outcome.blocks_install


def test_a_real_holder_is_named_in_the_refusal(tmp_path: Path) -> None:
    """A live process in the environment is reported, with its pid and relation.

    Real environment, real holder: the refusal an operator reads has to name
    the process they must actually end, not merely state that one exists.
    """
    from ._uv_env_harness import (
        build_wheel,
        hold_environment,
        index_arguments,
        sandbox_from,
        serve_wheels,
    )

    sandbox = sandbox_from(tmp_path)
    wheels = tmp_path / "wheels"
    build_wheel(wheels, name="provtool", version="1.0.0")
    with serve_wheels(wheels) as base_url:
        installed = sandbox.run(
            "tool", "install", "provtool", *index_arguments(base_url)
        )
        assert installed.returncode == 0, installed.stderr

    root = sandbox.tool_root("provtool")
    interpreter = root / "Scripts" / "python.exe"
    if not interpreter.exists():
        interpreter = root / "bin" / "python"

    with hold_environment(root, by_image=True) as holder:
        outcome = _tool_torch._handoff_outcome(
            str(interpreter),
            _tool_torch.tool_cuda_install_spec(),
            "uv tool install --force ...",
        )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.HOLDER_DETECTED
    assert any(found.pid == holder.pid for found in outcome.holders)
    assert f"pid {holder.pid}" in outcome.detail
    assert "end this process" in outcome.detail
    assert outcome.blocks_install


def _torch_absent_by_design(_interpreter: str, timeout: float = 60.0):
    del timeout
    from ..cli._process import _accelerator_probe_exit_outcome

    return _accelerator_probe_exit_outcome(6)


def test_an_install_without_the_gpu_extra_is_not_a_defect(
    monkeypatch: MonkeyPatch,
) -> None:
    """A deliberately torch-free install completes instead of failing.

    Guard assertion: absence of torch used to classify as an installation
    defect, whose blocking outcome short-circuited the whole install to exit 2.
    That made the torch-free install this project deliberately offers
    impossible to complete without a terminal - a defect introduced by reading
    a choice as a fault.
    """
    from ..cli import _gpu_errors, _process

    monkeypatch.setattr(_gpu_errors, "classify_interpreter_env", _persistent_tool_env)
    monkeypatch.setattr(_process, "_probe_daemon_accelerator", _torch_absent_by_design)

    outcome = _tool_torch.repair_tool_torch(dry_run=False, interpreter="ignored")

    assert outcome.action is _tool_torch.ToolTorchRepairAction.NOT_APPLICABLE
    assert not outcome.blocks_install
    assert "GPU extra" in outcome.detail


def test_torch_missing_from_a_gpu_install_is_still_a_defect() -> None:
    """The half-destroyed environment keeps its defect classification.

    Exit 3 means the GPU stack is installed and torch is gone anyway, which is
    what an interrupted replacement leaves behind - the field failure. It must
    not be softened by the by-design branch beside it.
    """
    from ..cli._process import (
        _accelerator_probe_exit_outcome,
        accelerator_probe_is_torch_absent_by_design,
        accelerator_probe_is_torch_installation_defect,
    )

    outcome = _accelerator_probe_exit_outcome(3)

    assert outcome is not None
    assert accelerator_probe_is_torch_installation_defect(outcome[1])
    assert not accelerator_probe_is_torch_absent_by_design(outcome[1])
