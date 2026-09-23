"""The daemon-interpreter probe names every environment state it can see.

The probe runs the real classification in a real child interpreter where the
process boundary is the point - torch staying out of the metadata depth, a
missing interpreter, a verdict matching independent truth. Classification of
environments this host does not have is exercised through the pure verdicts
over installed versions and over an imported torch module.
"""

from __future__ import annotations

import subprocess
import sys
from types import ModuleType, SimpleNamespace

import pytest

from ..operator_state._compute import (
    ProbeDepth,
    classify_torch,
    metadata_verdict,
    role_for,
)
from ..operator_state._environment_probe import (
    _PROBE_SCRIPT,
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
    epilogue = "assert 'torch' not in sys.modules, 'metadata depth loaded torch'\n"
    proc = subprocess.run(
        [sys.executable, "-c", _PROBE_SCRIPT + epilogue, ProbeDepth.METADATA.value],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )

    assert proc.returncode == 0, proc.stderr
    assert _parse(sys.executable, proc).compute.capability is not (
        ComputeCapability.UNKNOWN
    )


def test_an_environment_without_the_inference_stack_is_a_client() -> None:
    verdict = metadata_verdict(None, "2.14.0+cu130", "linux")

    assert role_for(None) is InstallRole.CLIENT
    assert verdict is ComputeCapability.NOT_APPLICABLE
    assert not verdict.is_defect


def test_a_host_that_lost_torch_is_a_defect_not_a_client() -> None:
    verdict = metadata_verdict("5.0", None, "linux")

    assert role_for("5.0") is InstallRole.HOST
    assert verdict is ComputeCapability.TORCH_MISSING
    assert verdict.is_defect


@pytest.mark.parametrize(
    ("torch_version", "platform", "expected"),
    [
        ("2.14.0+cpu", "linux", ComputeCapability.CPU_ONLY_BUILD),
        ("2.14.0+cu130", "win32", ComputeCapability.BUILD_PRESENT),
        ("2.14.0", "win32", ComputeCapability.CPU_ONLY_BUILD),
        ("2.14.0", "linux", ComputeCapability.BUILD_PRESENT),
        ("2.14.0", "darwin", ComputeCapability.BUILD_PRESENT),
        ("2.14.0+cpu.cxx11.abi", "linux", ComputeCapability.CPU_ONLY_BUILD),
        ("2.14.0+rocm6.2", "linux", ComputeCapability.UNKNOWN),
    ],
)
def test_the_metadata_depth_reads_the_torch_build_from_its_version(
    torch_version: str, platform: str, expected: ComputeCapability
) -> None:
    """A CPU-only wheel on a GPU workstation is named without importing torch."""
    assert metadata_verdict("5.0", torch_version, platform) is expected


def test_a_probe_that_overruns_its_bound_is_unknown_not_a_failure() -> None:
    """A wedged interpreter must not hang a start or read as broken.

    Mutation check: dropping the timeout from the probe's subprocess call lets
    the child run to completion and answer, failing the ``UNKNOWN`` assertion;
    restoring it passes.
    """
    facts = probe_interpreter(sys.executable, ProbeDepth.METADATA, timeout=0.01)

    assert facts.compute.capability is ComputeCapability.UNKNOWN
    assert not facts.compute.capability.blocks_start


def test_unreadable_probe_output_is_unknown_not_a_failure() -> None:
    proc = subprocess.CompletedProcess(
        args=[], returncode=1, stdout="", stderr="Traceback\nImportError: boom\n"
    )

    facts = _parse("python", proc)

    assert facts.compute.capability is ComputeCapability.UNKNOWN
    assert facts.compute.detail == "ImportError: boom"
    assert not facts.compute.capability.blocks_start


def _torch_double(*, cuda_build: str | None, cuda: bool, mps: bool) -> ModuleType:
    """A torch module exposing only the attributes classification reads."""
    torch = ModuleType("torch")
    torch.__dict__.update(
        __version__="2.14.0",
        version=SimpleNamespace(cuda=cuda_build),
        cuda=SimpleNamespace(
            is_available=lambda: cuda,
            get_device_name=lambda _index: "NVIDIA Test GPU",
            get_device_properties=lambda _index: SimpleNamespace(
                total_memory=16 * 1024 * 1024 * 1024
            ),
        ),
        backends=SimpleNamespace(mps=SimpleNamespace(is_available=lambda: mps)),
    )
    return torch


@pytest.mark.parametrize(
    ("cuda_build", "cuda", "mps", "expected"),
    [
        (None, False, False, ComputeCapability.CPU_ONLY_BUILD),
        (None, False, True, ComputeCapability.READY),
        ("13.0", False, False, ComputeCapability.NO_DEVICE),
        ("13.0", True, False, ComputeCapability.READY),
    ],
)
def test_an_imported_torch_is_classified_against_the_accelerator_contract(
    monkeypatch: pytest.MonkeyPatch,
    cuda_build: str | None,
    *,
    cuda: bool,
    mps: bool,
    expected: ComputeCapability,
) -> None:
    monkeypatch.delenv("PYTORCH_ENABLE_MPS_FALLBACK", raising=False)

    report = classify_torch(_torch_double(cuda_build=cuda_build, cuda=cuda, mps=mps))

    assert report.capability is expected


def test_a_visible_apple_gpu_with_cpu_fallback_enabled_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PYTORCH_ENABLE_MPS_FALLBACK", "1")

    report = classify_torch(_torch_double(cuda_build=None, cuda=False, mps=True))

    assert report.capability is ComputeCapability.MPS_POLICY_REFUSED


def test_a_ready_cuda_device_reports_its_name_and_memory() -> None:
    report = classify_torch(_torch_double(cuda_build="13.0", cuda=True, mps=False))

    assert report.backend == "cuda"
    assert report.device_name == "NVIDIA Test GPU"
    assert report.memory_mib == 16 * 1024
