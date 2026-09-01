"""Safety contracts for durable CUDA repair in persistent tool environments."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from ..commands import _tool_torch

pytestmark = [pytest.mark.unit]

if TYPE_CHECKING:
    from pathlib import Path


def test_receipt_requires_the_exact_cuda_wheel(tmp_path: Path) -> None:
    receipt = tmp_path / "uv-receipt.toml"
    wheel = "https://example.test/torch-2.9.0%2Bcu130.whl"
    receipt.write_text(
        '[tool]\nrequirements = ["torch @ ' + wheel + '"]\n', encoding="utf-8"
    )
    assert _tool_torch._receipt_has_cuda_requirement(receipt, wheel)
    assert not _tool_torch._receipt_has_cuda_requirement(receipt, wheel + "-other")


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
