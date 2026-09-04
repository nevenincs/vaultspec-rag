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
