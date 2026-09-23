"""The daemon-interpreter probe names every environment state it can see.

The probe script runs in a real child interpreter throughout. Where a test
needs an environment this host does not have - a client with no inference
stack, a CPU-only wheel - the child's package-metadata lookup is replaced
before the unmodified script runs, which isolates the classification without
installing anything.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from ..operator_state._environment_probe import (
    _PROBE_SCRIPT,
    ProbeDepth,
    _parse,
    probe_interpreter,
)
from ..operator_state._installation import ComputeCapability, InstallRole

pytestmark = [pytest.mark.unit]

# Independent accelerator truth, evaluated in its own child so this torch-free
# test process never imports torch. Exit 0 means CUDA or MPS is usable.
_TRUTH = (
    "import importlib.util, sys\n"
    "if importlib.util.find_spec('torch') is None:\n"
    "    sys.exit(3)\n"
    "import torch\n"
    "sys.exit(0 if (torch.cuda.is_available() or "
    "torch.backends.mps.is_available()) else 1)\n"
)


def _run_script(
    depth: ProbeDepth,
    *,
    versions: dict[str, str | None] | None = None,
    platform: str | None = None,
    epilogue: str = "",
) -> subprocess.CompletedProcess[str]:
    """Run the real probe script with optional metadata and platform overrides."""
    prelude = ""
    if versions is not None:
        prelude += (
            "import importlib.metadata as _metadata\n"
            "_real = _metadata.version\n"
            f"_fake = {versions!r}\n"
            "def _version(name):\n"
            "    if name in _fake:\n"
            "        if _fake[name] is None:\n"
            "            raise _metadata.PackageNotFoundError(name)\n"
            "        return _fake[name]\n"
            "    return _real(name)\n"
            "_metadata.version = _version\n"
        )
    if platform is not None:
        prelude += f"import sys as _sys\n_sys.platform = {platform!r}\n"
    return subprocess.run(
        [sys.executable, "-c", prelude + _PROBE_SCRIPT + epilogue, depth.value],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )


def test_verify_agrees_with_independent_truth_for_this_interpreter() -> None:
    truth = subprocess.run(
        [sys.executable, "-c", _TRUTH],
        capture_output=True,
        timeout=120,
        check=False,
    ).returncode

    facts = probe_interpreter(sys.executable, ProbeDepth.VERIFY)

    if truth == 0:
        assert facts.compute.capability is ComputeCapability.READY
        assert facts.compute.backend in {"cuda", "mps"}
        assert facts.compute.device_name
    else:
        assert facts.compute.capability.blocks_start


def test_a_missing_interpreter_is_named_and_blocks_a_start() -> None:
    facts = probe_interpreter("this-interpreter-does-not-exist-xyz")

    assert facts.compute.capability is ComputeCapability.INTERPRETER_MISSING
    assert facts.compute.capability.blocks_start


def test_the_metadata_depth_never_imports_torch() -> None:
    """The default status pays for an interpreter start, never for torch.

    Mutation check: routing the metadata depth through the verifying branch
    imports torch in the child and fails this assertion; restoring passes.
    """
    proc = _run_script(
        ProbeDepth.METADATA,
        epilogue="\nassert 'torch' not in sys.modules, 'metadata depth loaded torch'\n",
    )

    assert proc.returncode == 0, proc.stderr


def test_an_environment_without_the_inference_stack_is_a_client() -> None:
    proc = _run_script(
        ProbeDepth.VERIFY, versions={"sentence-transformers": None, "torch": None}
    )

    facts = _parse(sys.executable, proc)

    assert facts.role is InstallRole.CLIENT
    assert facts.compute.capability is ComputeCapability.NOT_APPLICABLE
    assert not facts.compute.capability.is_defect


def test_a_host_that_lost_torch_is_a_defect_not_a_client() -> None:
    proc = _run_script(
        ProbeDepth.METADATA, versions={"sentence-transformers": "5.0", "torch": None}
    )

    facts = _parse(sys.executable, proc)

    assert facts.role is InstallRole.HOST
    assert facts.compute.capability is ComputeCapability.TORCH_MISSING


@pytest.mark.parametrize(
    ("torch_version", "platform", "expected"),
    [
        ("2.14.0+cpu", "linux", ComputeCapability.CPU_ONLY_BUILD),
        ("2.14.0+cu130", "win32", ComputeCapability.BUILD_PRESENT),
        ("2.14.0", "win32", ComputeCapability.CPU_ONLY_BUILD),
        ("2.14.0", "linux", ComputeCapability.BUILD_PRESENT),
        ("2.14.0", "darwin", ComputeCapability.BUILD_PRESENT),
        ("2.14.0+rocm6.2", "linux", ComputeCapability.UNKNOWN),
    ],
)
def test_the_metadata_depth_reads_the_torch_build_from_its_version(
    torch_version: str, platform: str, expected: ComputeCapability
) -> None:
    """A CPU-only wheel on a GPU workstation is named without importing torch."""
    proc = _run_script(
        ProbeDepth.METADATA,
        versions={"sentence-transformers": "5.0", "torch": torch_version},
        platform=platform,
    )

    facts = _parse(sys.executable, proc)

    assert facts.compute.capability is expected
    assert facts.compute.torch_version == torch_version


def test_unreadable_probe_output_is_unknown_not_a_failure() -> None:
    proc = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="Traceback\nImportError: boom\n"
    )

    facts = _parse("python", proc)

    assert facts.compute.capability is ComputeCapability.UNKNOWN
    assert facts.compute.detail == "ImportError: boom"
    assert not facts.compute.capability.blocks_start
