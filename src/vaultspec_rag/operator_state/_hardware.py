"""Which accelerator the machine has, read without importing torch.

The answer is about hardware alone, so it can be reported next to an
environment that cannot use it - the case that matters most: a workstation
with a capable GPU and a CPU-only torch build. ``nvidia-smi`` ships with the
NVIDIA driver rather than with this product, so it is resolved from ``PATH``
and run with arguments only, never through a shell. It can hang on a wedged
driver, so every read is bounded, and a read that does not answer is
``UNKNOWN``, never a claim that the GPU is missing.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from functools import cache
from typing import TYPE_CHECKING

from ._installation import HardwarePresence
from ._models import HardwareReading

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["query_hardware", "read_hardware"]

NVIDIA_SMI_TIMEOUT_SECONDS = 5.0
_NVIDIA_SMI_QUERY = ("--query-gpu=name,memory.total", "--format=csv,noheader,nounits")


@cache
def read_hardware() -> HardwareReading:
    """Return this machine's accelerator, read once per process.

    The hardware does not change under a running process, and the read costs
    a driver round trip, so the first answer is kept.
    """
    nvidia_smi = shutil.which("nvidia-smi")
    return query_hardware(
        (nvidia_smi,) if nvidia_smi else None,
        platform_name=sys.platform,
        machine=platform.machine(),
    )


def query_hardware(
    nvidia_smi: Sequence[str] | None,
    *,
    platform_name: str,
    machine: str,
    timeout: float = NVIDIA_SMI_TIMEOUT_SECONDS,
) -> HardwareReading:
    """Classify the machine's accelerator from the platform and ``nvidia-smi``.

    *nvidia_smi* is the command that runs the driver utility, or ``None`` when
    it is not installed.
    """
    if platform_name == "darwin":
        presence = (
            HardwarePresence.APPLE_SILICON
            if machine.lower() == "arm64"
            else HardwarePresence.NONE
        )
        return HardwareReading(presence=presence)
    if nvidia_smi is None:
        return HardwareReading(presence=HardwarePresence.UNKNOWN)
    try:
        proc = subprocess.run(
            [*nvidia_smi, *_NVIDIA_SMI_QUERY],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return HardwareReading(presence=HardwarePresence.UNKNOWN)
    if proc.returncode != 0:
        return HardwareReading(presence=HardwarePresence.UNKNOWN)
    return _first_gpu(proc.stdout)


def _first_gpu(stdout: str) -> HardwareReading:
    """Read device 0, the one inference runs on, from the CSV query output."""
    for line in stdout.splitlines():
        name, _, memory = line.partition(",")
        if name.strip():
            memory = memory.strip()
            return HardwareReading(
                presence=HardwarePresence.NVIDIA_GPU,
                name=name.strip(),
                memory_mib=int(memory) if memory.isdigit() else None,
            )
    return HardwareReading(presence=HardwarePresence.NONE)
