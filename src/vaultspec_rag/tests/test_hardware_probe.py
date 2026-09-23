"""The hardware read names the accelerator, and never guesses when it cannot.

``nvidia-smi`` is stood in for by a real child interpreter that prints what the
driver utility would, so the bounded subprocess path runs for real without
depending on this host's GPU.
"""

from __future__ import annotations

import sys

import pytest

from ..operator_state._hardware import query_hardware
from ..operator_state._installation import HardwarePresence

pytestmark = [pytest.mark.unit]


def _fake_nvidia_smi(script: str) -> tuple[str, ...]:
    return (sys.executable, "-c", script)


def test_an_nvidia_gpu_is_named_with_its_memory() -> None:
    reading = query_hardware(
        _fake_nvidia_smi(
            "print('NVIDIA GeForce RTX 4080 SUPER, 16376')\nprint('NVIDIA T400, 2048')"
        ),
        platform_name="win32",
        machine="AMD64",
    )

    assert reading.presence is HardwarePresence.NVIDIA_GPU
    assert reading.name == "NVIDIA GeForce RTX 4080 SUPER"
    assert reading.memory_mib == 16376


def test_a_driver_that_lists_no_device_means_no_gpu() -> None:
    reading = query_hardware(
        _fake_nvidia_smi("print('')"), platform_name="linux", machine="x86_64"
    )

    assert reading.presence is HardwarePresence.NONE


def test_an_absent_driver_utility_is_unknown_not_missing_hardware() -> None:
    reading = query_hardware(None, platform_name="win32", machine="AMD64")

    assert reading.presence is HardwarePresence.UNKNOWN


def test_a_failing_driver_utility_is_unknown() -> None:
    reading = query_hardware(
        _fake_nvidia_smi("import sys; print('NVIDIA-SMI has failed'); sys.exit(9)"),
        platform_name="linux",
        machine="x86_64",
    )

    assert reading.presence is HardwarePresence.UNKNOWN


def test_a_hung_driver_utility_is_bounded_and_unknown() -> None:
    """A wedged driver must not hang a status command.

    Mutation check: dropping the timeout from the subprocess call makes this
    test block for the child's full sleep and fail on the pytest timeout
    instead of returning ``UNKNOWN``; restoring it passes.
    """
    reading = query_hardware(
        _fake_nvidia_smi("import time; time.sleep(60)"),
        platform_name="linux",
        machine="x86_64",
        timeout=1.0,
    )

    assert reading.presence is HardwarePresence.UNKNOWN


@pytest.mark.parametrize(
    ("machine", "expected"),
    [("arm64", HardwarePresence.APPLE_SILICON), ("x86_64", HardwarePresence.NONE)],
)
def test_a_mac_is_classified_by_its_chip(
    machine: str, expected: HardwarePresence
) -> None:
    reading = query_hardware(None, platform_name="darwin", machine=machine)

    assert reading.presence is expected
