"""No command runs a helper program out of the directory it was typed in.

This package runs a few programs it does not ship: the monitor, the graphics
driver's query tool, the package manager, and operating-system tools. Each
used to be named and left to the operating system to find, and a stock
Windows machine looks in the working directory first. These commands are
typed inside project checkouts.

Each test here plants a program under the real name in the working
directory, puts the process in the state a stock machine searches in, and
drives the production code that runs the program. The plant is a real
program: where it can leave a file behind, the assertion is that it did not;
where it cannot, the assertion is on what the production code reported,
which differs when the plant is what answered.

``PATH`` holds nothing but relative entries and, where a test needs the real
tool, the one directory it lives in. So no test here depends on what the
machine running it has installed.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from .._process_probe import _windows_image_matches
from .._python_child import inline_command
from .._win32 import system_directory
from ..commands._mcp_topology import _restore_junction
from ..commands._models import InstallReport
from ..commands._tool_torch import _run_repair
from ..commands._uv_sync import _run_uv_sync_torch
from ..config._types import EnvVar
from ..monitor_process import MonitorProcess, _resolve_monitor_executable
from ..operator_state._hardware import read_hardware
from ..qdrant_runtime._resolve import reap_qdrant_orphan
from ._planted_programs import (
    plant_marking_program,
    plant_native_program,
    stock_search_state,
)
from ._ports import free_loopback_port
from .conftest import managed_env

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

_windows_only = pytest.mark.skipif(
    sys.platform != "win32", reason="the tool is a Windows operating-system program"
)


@pytest.fixture
def checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A working directory in the state a stock machine searches it in."""
    directory = tmp_path / "checkout"
    directory.mkdir()
    stock_search_state(monkeypatch, directory)
    return directory


@pytest.fixture
def fresh_hardware_reading() -> Generator[None]:
    """The hardware is read for this test alone, and its answer kept by no other.

    The reading is cached for the life of a process, and this test takes it
    with ``PATH`` emptied.
    """
    read_hardware.cache_clear()
    try:
        yield
    finally:
        read_hardware.cache_clear()


def test_status_does_not_run_a_driver_tool_from_the_working_directory(
    checkout: Path, fresh_hardware_reading: None
) -> None:
    """Reading the hardware runs the driver's tool, or none, never the plant.

    Shown to fail by resolving the tool with the standard lookup again: the
    planted program runs and the assertion fires. Passes with the lookup
    restored.
    """
    del fresh_hardware_reading
    ran = plant_marking_program(checkout, "nvidia-smi")

    read_hardware()

    assert not ran.exists(), "the working directory's nvidia-smi was run"


def test_the_repair_does_not_run_a_uv_from_the_working_directory(
    checkout: Path,
) -> None:
    """The torch repair finds no uv rather than the checkout's.

    Shown to fail by resolving uv with the standard lookup again: the planted
    program is asked for its tool directory, runs, and the first assertion
    fires. Passes with the lookup restored.
    """
    ran = plant_marking_program(checkout, "uv")

    repaired, detail = _run_repair(sys.executable, stream=False)

    assert not ran.exists(), "the working directory's uv was run"
    assert not repaired
    assert "uv is not on PATH" in detail


def test_install_sync_does_not_run_a_uv_from_the_working_directory(
    checkout: Path, tmp_path: Path
) -> None:
    """``install --sync`` reports uv missing rather than running the checkout's.

    The plant is a native program, because this site handed a bare name
    straight to process creation, which completes it with ``.exe`` alone.
    Shown to fail by running the bare name again: the plant runs, exits
    non-zero on arguments it does not know, and the sync is reported as
    failed where the first assertion requires it to be reported as not
    found. Passes with the lookup restored.
    """
    plant_native_program(checkout, "uv")
    ran = plant_marking_program(checkout, "uv")
    project = tmp_path / "project"
    project.mkdir()
    report = InstallReport(action="install", target=project)

    _run_uv_sync_torch(target=project, report=report)

    assert report.torch_sync_action == "uv-not-found", report.warnings
    assert not ran.exists(), "the working directory's uv was run"


def test_the_monitor_is_not_started_from_the_working_directory(
    checkout: Path, isolated_singleton_dirs: Path
) -> None:
    """Starting the monitor finds none rather than the checkout's.

    The monitor is started on every service start. Shown to fail by
    resolving it with the standard lookup again: the planted program is
    started as the monitor and the first assertion fires. Passes with the
    lookup restored.
    """
    del isolated_singleton_dirs
    ran = plant_marking_program(checkout, "vaultspec-rag-monitor")

    with (
        managed_env(**{EnvVar.MONITOR_BINARY.value: None}),
        pytest.raises(RuntimeError) as refused,
    ):
        MonitorProcess(free_loopback_port()).start(timeout=20)

    assert not ran.exists(), "the working directory's monitor was started"
    assert "executable is required" in str(refused.value)


def test_a_monitor_beside_the_installation_is_found_without_path(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The monitor that ships beside this package's commands needs no ``PATH``.

    The running program is stood in for by a directory of its own, so the
    test plants nothing in the real environment.
    """
    plant_marking_program(checkout, "vaultspec-rag-monitor")
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    plant_marking_program(bundle, "vaultspec-rag-monitor")
    monkeypatch.setattr(sys, "executable", str(bundle / "vaultspec-rag"))

    with managed_env(**{EnvVar.MONITOR_BINARY.value: None}):
        resolved = _resolve_monitor_executable()

    assert resolved.parent == bundle.resolve()


@_windows_only
def test_an_image_check_does_not_run_a_tasklist_from_the_working_directory(
    checkout: Path,
) -> None:
    """The image check asks the operating system's tasklist, not the checkout's.

    What answers here decides whether a process may be killed. Shown to fail
    by running the bare name again: the planted program answers, its output
    names no image, and the check reports that this very process is not a
    Python process. Passes with the lookup restored.
    """
    plant_native_program(checkout, "tasklist")

    assert _windows_image_matches(os.getpid(), "python", 60.0)


@_windows_only
def test_an_orphan_reap_does_not_run_a_taskkill_from_the_working_directory(
    checkout: Path,
) -> None:
    """The reap kills its target with the operating system's taskkill.

    The target is a real process that ends by itself within two minutes
    whatever happens here. The reap is given a minute because the real tool
    asks the operating system's management service for the process tree, and
    that answer has been seen to take many seconds on a busy machine; alone
    it takes about one. Shown to fail by running the bare name again: the
    planted program answers, kills nothing, and the target is still alive
    when the reap gives up. Passes with the lookup restored.
    """
    plant_native_program(checkout, "taskkill")
    target = subprocess.Popen(
        inline_command(sys.executable, "import time; time.sleep(120)"),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        reaped = reap_qdrant_orphan(target.pid, wait_seconds=60.0)

        assert reaped, "the working directory's taskkill answered; nothing was killed"
        assert target.wait(timeout=15) is not None
    finally:
        target.kill()
        target.wait(timeout=15)


@_windows_only
def test_a_junction_is_not_restored_by_a_powershell_from_the_working_directory(
    checkout: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An install rollback restores a junction with the real PowerShell.

    ``PATH`` names the one directory the real program lives in, after the
    relative entries. Shown to fail by running the bare name again: the
    planted program answers, creates nothing, and the restore raises. Passes
    with the lookup restored.
    """
    plant_native_program(checkout, "powershell")
    powershell_home = os.path.join(system_directory(), "WindowsPowerShell", "v1.0")
    monkeypatch.setenv("PATH", os.pathsep.join(["", os.curdir, powershell_home]))
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = tmp_path / "junction"

    _restore_junction(junction, str(target))

    assert junction.is_junction()
    assert junction.resolve() == target.resolve()
