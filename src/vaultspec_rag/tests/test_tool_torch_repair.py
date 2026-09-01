"""Safety contracts for durable CUDA repair in persistent tool environments."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pytest import MonkeyPatch

from ..cli._gpu_errors import RuntimeEnvKind
from ..commands import _tool_torch
from ..serviceclient._discovery import (
    DISCOVERY_STATE_READY,
    MachineResolution,
)

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


def _ready_machine_resolution() -> MachineResolution:
    return MachineResolution(
        state=DISCOVERY_STATE_READY,
        source="machine_pointer",
        holder_pid=438,
        port=7331,
    )


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


def test_declined_confirmation_blocks_without_a_reinstall() -> None:
    outcome = _tool_torch._confirmation_outcome(
        lambda _prompt: False, assume_yes=False, command="uv tool install"
    )
    assert outcome is not None
    assert outcome.action is _tool_torch.ToolTorchRepairAction.DECLINED
    assert outcome.blocks_install


def test_noninteractive_confirmation_blocks_without_a_reinstall() -> None:
    outcome = _tool_torch._confirmation_outcome(
        None, assume_yes=False, command="uv tool install"
    )
    assert outcome is not None
    assert outcome.action is _tool_torch.ToolTorchRepairAction.SKIPPED_NON_TTY
    assert outcome.blocks_install


def test_service_holder_refuses_before_reinstall(monkeypatch: MonkeyPatch) -> None:
    """A live service holder prevents changing the tool interpreter in place."""
    from ..serviceclient import _discovery

    monkeypatch.setattr(
        _discovery,
        "resolve_machine_service",
        _ready_machine_resolution,
    )

    def _unexpected_reinstall(
        _spec: _tool_torch.ToolCudaInstallSpec, _command: str
    ) -> _tool_torch.ToolTorchRepairOutcome | None:
        raise AssertionError("service holder must prevent tool reinstall")

    monkeypatch.setattr(_tool_torch, "_run_tool_reinstall", _unexpected_reinstall)

    outcome = _tool_torch._repair_defective_tool(
        "ignored", "CPU-only torch", assume_yes=True, confirm=None, dry_run=False
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.SERVICE_HELD
    assert outcome.blocks_install


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
        "_probe_daemon_cuda",
        _no_visible_cuda_device,
    )

    def _unexpected_repair(
        *_args: object, **_kwargs: object
    ) -> _tool_torch.ToolTorchRepairOutcome:
        raise AssertionError("a CUDA build without a device must not be reinstalled")

    monkeypatch.setattr(_tool_torch, "_repair_defective_tool", _unexpected_repair)

    outcome = _tool_torch.repair_tool_torch(
        assume_yes=True, confirm=None, dry_run=False, interpreter="ignored"
    )

    assert outcome.action is _tool_torch.ToolTorchRepairAction.CUDA_UNVERIFIED
    assert outcome.blocks_install


def test_verify_repair_requires_cuda_and_structured_receipt(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """A successful repair is durable only after both required postconditions hold."""
    from ..cli import _process

    wheel = "https://example.test/torch-2.9.0%2Bcu130.whl"
    spec = _tool_torch.ToolCudaInstallSpec(("uv",), wheel)
    interpreter = tmp_path / "Scripts" / "python.exe"
    interpreter.parent.mkdir()
    receipt = tmp_path / "uv-receipt.toml"
    receipt.write_text(
        '[tool]\nrequirements = [{ name = "torch", url = "' + wheel + '" }]\n',
        encoding="utf-8",
    )
    monkeypatch.setattr(_process, "_probe_daemon_cuda", _cuda_ready_probe)

    outcome = _tool_torch._verify_tool_repair(str(interpreter), spec, "uv tool")

    assert outcome.action is _tool_torch.ToolTorchRepairAction.REPAIRED

    monkeypatch.setattr(
        _process,
        "_probe_daemon_cuda",
        _cpu_torch_probe,
    )
    outcome = _tool_torch._verify_tool_repair(str(interpreter), spec, "uv tool")
    assert outcome.action is _tool_torch.ToolTorchRepairAction.CUDA_UNVERIFIED

    monkeypatch.setattr(_process, "_probe_daemon_cuda", _cuda_ready_probe)
    receipt.unlink()
    outcome = _tool_torch._verify_tool_repair(str(interpreter), spec, "uv tool")
    assert outcome.action is _tool_torch.ToolTorchRepairAction.RECEIPT_UNVERIFIED
