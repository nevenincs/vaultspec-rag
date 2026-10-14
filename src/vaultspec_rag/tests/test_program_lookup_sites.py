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
import threading
import time
from typing import TYPE_CHECKING

import pytest

from .._process_probe import _windows_image_matches, pid_image_path
from .._python_child import inline_command
from ..commands._mcp_topology import _restore_junction
from ..commands._models import InstallReport
from ..commands._tool_torch import _run_repair
from ..commands._uv_sync import _run_uv_sync_torch
from ..config._types import EnvVar
from ..monitor_process import MonitorProcess
from ..monitor_runtime._assets import (
    MONITOR_PROGRAM,
    monitor_archive_name,
    monitor_executable_name,
)
from ..monitor_runtime._pins import MonitorPin, PinProvenance
from ..monitor_runtime._resolve import managed_monitor_path, monitor_for_launch
from ..native_binary._install import file_sha256
from ..native_binary._targets import host_target
from ..operator_state._hardware import read_hardware
from ..qdrant_runtime._resolve import reap_qdrant_orphan
from ._planted_programs import (
    plant_marking_program,
    plant_native_program,
    plant_waiting_program,
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


def _install_managed_monitor() -> tuple[Path, MonitorPin]:
    """Install a program where a release's managed monitor install belongs.

    The managed directory is machine-wide and keyed by release and target
    alone, so it is the one place every environment of a release resolves
    through - the managed service runtime's interpreter included, which has
    no monitor of its own beside it.

    The program is a stock one that outlives its start and answers nothing:
    what is under test is which file a process is created from. The pin is
    built from the bytes installed, as a release's pin is built from the
    bytes it published.

    Returns:
        The installed executable and the pin that admits it.
    """
    target = host_target()
    version = "9.9.9"
    directory = managed_monitor_path(version, target).parent
    directory.mkdir(parents=True, exist_ok=True)
    installed = plant_waiting_program(directory, MONITOR_PROGRAM)
    pin = MonitorPin(
        provenance=PinProvenance.DEVELOPMENT,
        version=version,
        tag="",
        target=target,
        archive_name=monitor_archive_name(version, target),
        archive_sha256="0" * 64,
        executable_name=monitor_executable_name(target),
        executable_sha256=file_sha256(installed),
    )
    assert installed == managed_monitor_path(pin.version, pin.target)
    return installed, pin


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
    checkout: Path, isolated_singleton_dirs: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The monitor that starts is the file resolution named, not the plant.

    The monitor is started on every service start, and what admits one is a
    digest, so a program of the right name proves nothing. This drives the
    real start against a real managed install - the tier a daemon started
    from the managed service runtime always resolves through, because the
    runtime's own interpreter has no monitor beside it - and asserts the
    image the started process was created from. The plants are both shapes a
    lookup could answer with: a command script, which the standard lookup
    finds through ``PATHEXT``, and a native program, which a bare name handed
    to process creation starts.

    The installed monitor is a stock program that outlives its start and
    answers nothing, so the start ends at the wait for readiness. That is
    after process creation, which is what is under test: which file a
    process was created from is settled the moment the process exists, and
    the image is read while it is alive. What a real monitor then does is the
    lifecycle tests' subject.

    Mutation: replaced the resolved path with the bare program name in the
    start's argument vector and dropped ``executable`` from it, which is the
    lookup this site used to make. Observed this test fail on the image
    assertion, naming the working directory's planted program as what was
    started. Restored; passes.
    """
    del isolated_singleton_dirs
    ran = plant_marking_program(checkout, "vaultspec-rag-monitor")
    planted = plant_waiting_program(checkout, "vaultspec-rag-monitor")
    installed, pin = _install_managed_monitor()
    monitor = MonitorProcess(free_loopback_port())

    with managed_env(
        **{
            EnvVar.MONITOR_BINARY.value: None,
            EnvVar.MONITOR_BINARY_SHA256.value: None,
        }
    ):
        # The digests of a release are what admit a monitor, and this
        # checkout carries none until it compiles one. They are the test's
        # stated input so that where the resolver looks, and what it admits,
        # are production's throughout; the install above is a real file in
        # the real managed directory.
        monkeypatch.setattr(
            "vaultspec_rag.monitor_runtime._resolve.monitor_pin", lambda _target: pin
        )
        # Resolution is production's, and its answer is what the started
        # process is held to below.
        resolved = monitor_for_launch()
        assert resolved.path == installed
        images: list[str | None] = []
        done = threading.Event()

        def read_the_image() -> None:
            """Read the image of whatever the start creates, while it lives."""
            while not done.is_set():
                started = monitor.process
                if started is not None:
                    images.append(pid_image_path(started.pid))
                    return
                time.sleep(0.005)

        reader = threading.Thread(target=read_the_image, name="started-image")
        reader.start()
        refused: Exception | None = None
        try:
            monitor.start(timeout=3)
        except Exception as exc:  # reported below, after the guard's own answer
            refused = exc
        finally:
            done.set()
            reader.join(timeout=10)
            monitor.stop()

    assert images and images[0] is not None, "nothing started could be identified"
    assert os.path.normcase(images[0]) == os.path.normcase(str(resolved.path)), (
        f"{images[0]} was started; {resolved.path} was resolved"
    )
    assert os.path.normcase(images[0]) != os.path.normcase(str(planted))
    assert not ran.exists(), "the working directory's monitor was started"
    # The stand-in answers no page, so the start can only end at the wait.
    assert refused is not None
    assert "ready" in str(refused), refused


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

    A same-named program stands in the working directory and in the one
    absolute directory ``PATH`` names; the directory the real one lives in is
    not on ``PATH`` at all. Shown to fail by finding the program on ``PATH``
    again: the planted program answers, creates nothing, and the restore
    raises. Passes with the operating system's own directories asked.
    """
    plant_native_program(checkout, "powershell")
    shadow = tmp_path / "ports"
    shadow.mkdir()
    plant_native_program(shadow, "powershell")
    monkeypatch.setenv("PATH", os.pathsep.join(["", os.curdir, str(shadow)]))
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = tmp_path / "junction"

    _restore_junction(junction, str(target))

    assert junction.is_junction()
    assert junction.resolve() == target.resolve()
