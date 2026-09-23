"""What an installation is, what hardware it sits on, and whether it can compute.

These three are kept apart because they fail independently. A workstation can
carry a capable GPU while its environment holds a CPU-only torch build, and a
client installation never needs torch at all; collapsing the three into one
"GPU available" flag is what reported a hardware fault on hosts that had none.
"""

from __future__ import annotations

from enum import StrEnum

from .._operator_commands import server_doctor_command

__all__ = ["ComputeCapability", "HardwarePresence", "InstallRole"]

_DOCTOR = f"`{server_doctor_command()}` prints the exact command for this environment."


class InstallRole(StrEnum):
    """Whether this environment carries the inference stack.

    Derived from the installed distributions, never persisted: adding or
    removing the ``gpu`` extra changes the role on the next read.
    """

    CLIENT = "client"
    HOST = "host"

    @property
    def label(self) -> str:
        """Plain-language description of the role."""
        return {
            InstallRole.CLIENT: "client (searches run in the vaultspec-rag service)",
            InstallRole.HOST: "inference host (runs the search models on this machine)",
        }[self]


class HardwarePresence(StrEnum):
    """Which accelerator the machine has, read without importing torch."""

    NVIDIA_GPU = "nvidia_gpu"
    APPLE_SILICON = "apple_silicon"
    NONE = "none"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        """Plain-language description of the detected hardware."""
        return {
            HardwarePresence.NVIDIA_GPU: "NVIDIA GPU",
            HardwarePresence.APPLE_SILICON: "Apple silicon GPU",
            HardwarePresence.NONE: "no supported GPU detected",
            HardwarePresence.UNKNOWN: "not detected",
        }[self]


class ComputeCapability(StrEnum):
    """Whether an environment can run inference, and if not, exactly why.

    ``BUILD_PRESENT`` comes from package metadata alone and is never a verified
    device; only the full probe yields ``READY``. ``UNKNOWN`` means the check
    did not finish and must never be rendered as a failure.
    """

    NOT_APPLICABLE = "not_applicable"
    READY = "ready"
    BUILD_PRESENT = "build_present"
    TORCH_MISSING = "torch_missing"
    TORCH_IMPORT_FAILED = "torch_import_failed"
    CPU_ONLY_BUILD = "cpu_only_build"
    NO_DEVICE = "no_device"
    MPS_POLICY_REFUSED = "mps_policy_refused"
    INTERPRETER_MISSING = "interpreter_missing"
    UNKNOWN = "unknown"

    @property
    def label(self) -> str:
        """Plain-language statement of the capability."""
        return {
            ComputeCapability.NOT_APPLICABLE: (
                "not needed (this installation is a client)"
            ),
            ComputeCapability.READY: "ready",
            ComputeCapability.BUILD_PRESENT: (
                "GPU build of torch installed (device not yet verified)"
            ),
            ComputeCapability.TORCH_MISSING: "torch is not installed",
            ComputeCapability.TORCH_IMPORT_FAILED: (
                "torch is installed but fails to load"
            ),
            ComputeCapability.CPU_ONLY_BUILD: (
                "torch is a CPU-only build, so the GPU cannot be used"
            ),
            ComputeCapability.NO_DEVICE: (
                "torch has GPU support but no usable GPU is visible"
            ),
            ComputeCapability.MPS_POLICY_REFUSED: (
                "the Apple GPU is visible but its CPU-fallback policy is enabled"
            ),
            ComputeCapability.INTERPRETER_MISSING: (
                "the Python interpreter that would run the service was not found"
            ),
            ComputeCapability.UNKNOWN: "not checked",
        }[self]

    @property
    def remediation(self) -> str | None:
        """What the operator should do, or ``None`` when nothing is needed."""
        return {
            ComputeCapability.NOT_APPLICABLE: (
                "To run searches on this machine, install `vaultspec-rag[gpu]`."
            ),
            ComputeCapability.READY: None,
            ComputeCapability.BUILD_PRESENT: None,
            ComputeCapability.TORCH_MISSING: (
                f"Reinstall vaultspec-rag with the `gpu` extra. {_DOCTOR}"
            ),
            ComputeCapability.TORCH_IMPORT_FAILED: (
                f"Reinstall torch in this environment. {_DOCTOR}"
            ),
            ComputeCapability.CPU_ONLY_BUILD: (
                f"Replace torch with its CUDA build. {_DOCTOR}"
            ),
            ComputeCapability.NO_DEVICE: (
                "Check the GPU driver with `nvidia-smi`, then start the service again."
            ),
            ComputeCapability.MPS_POLICY_REFUSED: (
                "Unset PYTORCH_ENABLE_MPS_FALLBACK or set it to 0."
            ),
            ComputeCapability.INTERPRETER_MISSING: (
                "Reinstall vaultspec-rag; the environment that runs the service "
                "is incomplete."
            ),
            ComputeCapability.UNKNOWN: (
                f"Run `{server_doctor_command()}` to check this environment."
            ),
        }[self]

    @property
    def blocks_start(self) -> bool:
        """Whether a service started in this environment must be refused."""
        return self not in {
            ComputeCapability.READY,
            ComputeCapability.BUILD_PRESENT,
            ComputeCapability.UNKNOWN,
        }

    @property
    def is_defect(self) -> bool:
        """Whether this is a broken inference host rather than a choice.

        A client lacking torch cannot serve, but it is not broken.
        """
        return self.blocks_start and self is not ComputeCapability.NOT_APPLICABLE
