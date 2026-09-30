"""The host install command: the GPU build on every platform, and one spelling.

vaultspec-rag never runs inference on CPU, and PyPI's torch is CPU-only on
Windows, so the command every surface hands out must carry the CUDA index
wherever PyTorch publishes CUDA wheels. Apple silicon takes PyPI's standard
wheel, which is the build with Metal support.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ..operator_state._provisioning import CU130_INDEX_STRATEGY, host_install_command
from ..torch_config._index import CU130_INDEX_URL

pytestmark = pytest.mark.unit

_README = Path(__file__).resolve().parents[3] / "README.md"


@pytest.mark.parametrize("platform_name", ["win32", "linux"])
def test_a_cuda_platform_install_pins_the_cuda_index(platform_name: str) -> None:
    # Mutation proof: adding the index arguments only on "linux" failed the
    # "win32" case on this assertion.
    command = host_install_command(platform_name)
    assert f"--index {CU130_INDEX_URL} --index-strategy {CU130_INDEX_STRATEGY}" in (
        command
    )
    assert '"vaultspec-rag[gpu,mcp]"' in command


def test_apple_silicon_takes_the_standard_wheel() -> None:
    assert host_install_command("darwin") == (
        'uv tool install --python 3.13 "vaultspec-rag[gpu,mcp]"'
    )


def test_the_readme_hands_out_the_product_s_own_commands() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert host_install_command("win32") in readme
    assert host_install_command("darwin") in readme
