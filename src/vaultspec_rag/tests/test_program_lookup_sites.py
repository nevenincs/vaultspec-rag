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

from tools.monitor.pins import GeneratedPins

from .._process_probe import _windows_image_matches
from .._python_child import inline_command
from ..commands._mcp_topology import _restore_junction
from ..commands._models import InstallReport
from ..commands._tool_torch import _run_repair
from ..commands._uv_sync import _run_uv_sync_torch
from ..config._types import EnvVar
from ..monitor_runtime._assets import MONITOR_PROGRAM
from ..monitor_runtime._pins import PinProvenance
from ..monitor_runtime._resolve import managed_monitor_path
from ..native_binary._install import file_sha256
from ..native_binary._targets import host_target
from ..operator_state._hardware import read_hardware
from ..qdrant_runtime._resolve import reap_qdrant_orphan
from ._planted_programs import (
    plant_marking_program,
    plant_native_program,
    plant_waiting_program,
    ran_marker,
    stock_search_state,
)
from ._ports import free_loopback_port
from ._separate_installation import INSTALLED_FROM_A_WHEEL, build_installation
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


_VERSION = "9.9.9"

#: Run in a separate installation: start the monitor the way a service start
#: does, and report which file was resolved and which file the started process
#: was created from. The image is read while the process lives.
_START_THE_MONITOR = """
import json
import sys
import threading
import time

from vaultspec_rag._process_probe import pid_image_path
from vaultspec_rag.monitor_process import MonitorProcess
from vaultspec_rag.monitor_runtime._resolve import monitor_for_launch

monitor = MonitorProcess(json.loads(sys.argv[1])[0])
resolved = monitor_for_launch()
images = []
done = threading.Event()


def read_the_image():
    while not done.is_set():
        started = monitor.process
        if started is not None:
            images.append(pid_image_path(started.pid))
            return
        time.sleep(0.005)


reader = threading.Thread(target=read_the_image, name="started-image")
reader.start()
refused = None
try:
    monitor.start(timeout=3)
except Exception as exc:
    refused = str(exc)
finally:
    done.set()
    reader.join(timeout=10)
    monitor.stop()
print(json.dumps({
    "resolved": str(resolved.path),
    "image": images[0] if images else None,
    "refused": refused,
}))
"""


def _install_managed_monitor() -> tuple[Path, GeneratedPins]:
    """Install a program where a release's managed monitor install belongs.

    The managed directory is machine-wide and keyed by release and target
    alone, so it is the one place every environment of a release resolves
    through - the managed service runtime's interpreter included, which has
    no monitor of its own beside it.

    The program is a stock one that outlives its start and answers nothing:
    what is under test is which file a process is created from. The digests
    are made from the bytes installed, as a release's are made from the bytes
    it published.

    Returns:
        The installed executable and the digests of the release that
        published it.
    """
    target = host_target()
    directory = managed_monitor_path(_VERSION, target).parent
    directory.mkdir(parents=True, exist_ok=True)
    installed = plant_waiting_program(directory, MONITOR_PROGRAM)
    pins = GeneratedPins(
        provenance=PinProvenance.RELEASE,
        version=_VERSION,
        tag=f"vaultspec-rag-v{_VERSION}",
        archives={target: "0" * 64},
        executables={target: file_sha256(installed)},
    )
    assert installed == managed_monitor_path(_VERSION, target)
    return installed, pins


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
    checkout: Path, isolated_singleton_dirs: Path, tmp_path: Path
) -> None:
    """The monitor that starts is the file resolution named, not the plant.

    The monitor is started on every service start, and what admits one is a
    digest, so a program of the right name proves nothing. This drives the
    real start against a real managed install - the tier a daemon started
    from the managed service runtime always resolves through, because the
    runtime's own interpreter has no monitor beside it - and asks which file
    the started process was created from. The plants are both shapes a
    lookup could answer with: a command script, which the standard lookup
    finds through ``PATHEXT``, and a native program, which a bare name handed
    to process creation starts. Where no extension is completed there is one
    file of that name, and it answers to both.

    A native program is the image of the process created from it, so on
    Windows that image is what is read. A script is run by its interpreter,
    whose image names nothing planted, so elsewhere each plant is asked what
    it left behind when it ran: the working directory's must have left
    nothing, and the installed one must have left its marker.

    The start runs in an installation of its own: an installed release whose
    generated digests are those of the program installed here, started from
    the working directory the plants are in. A checkout carries digests only
    for the monitor it compiled, and those admit nothing else, so the digests
    that admit this program are written into that installation by the
    generator and read by the shipped reader.

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
    started. Restored; passes. On Linux the same change starts nothing: a bare
    name is looked for from the child's own directory, which the start sets,
    and the plant is in this one. It failed on the assertion that the resolved
    monitor was started. Dropping the child's directory as well started the
    plant, and it failed on the assertion that the working directory's
    monitor was not. Restored; passes.
    """
    del isolated_singleton_dirs
    ran = plant_marking_program(checkout, "vaultspec-rag-monitor")
    planted = plant_waiting_program(checkout, "vaultspec-rag-monitor")
    installed, pins = _install_managed_monitor()
    installation = build_installation(
        tmp_path / "installation",
        version=_VERSION,
        direct_url=INSTALLED_FROM_A_WHEEL,
        pins=pins,
    )

    with managed_env(
        **{
            EnvVar.MONITOR_BINARY.value: None,
            EnvVar.MONITOR_BINARY_SHA256.value: None,
        }
    ):
        started = installation.run(
            _START_THE_MONITOR, free_loopback_port(), cwd=checkout
        )

    resolved = str(started["resolved"])
    image = started["image"]
    refused = started["refused"]
    assert os.path.normcase(resolved) == os.path.normcase(str(installed))
    assert not ran.exists(), "the working directory's monitor was started"
    if sys.platform == "win32":
        assert image is not None, "nothing started could be identified"
        assert os.path.normcase(str(image)) == os.path.normcase(resolved), (
            f"{image} was started; {resolved} was resolved"
        )
        assert os.path.normcase(str(image)) != os.path.normcase(str(planted))
    else:
        assert ran_marker(installed.parent, MONITOR_PROGRAM).exists(), (
            "the resolved monitor was not started"
        )
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
