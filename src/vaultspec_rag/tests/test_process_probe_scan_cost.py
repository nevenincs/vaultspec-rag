"""The process-table scan must read expensive attributes on demand only.

``ppid`` and ``create_time`` have no cheap path on Windows: psutil falls back to
a full-system process snapshot for each one, measured at 46ms and 20ms per
process against a ~1700-process table. Materialising them for every process
turns a scan that keeps a handful into a quadratic walk - 72-86s, against well
under a second when only the matches pay. Every caller filters on the command
line first, so the laziness is what keeps the orphan reap and the late-spawn
scan bounded, and losing it is a silent minutes-long regression that no other
test would name.
"""

from __future__ import annotations

import contextlib
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, cast

import psutil
import pytest

from .._process_probe import iter_process_info, pid_alive
from ..cli._process import _may_carry_launch_witness, _resolve_daemon_interpreter

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = [pytest.mark.unit]


def _spawn_marked_sleeper(marker: str) -> subprocess.Popen[bytes]:
    """Spawn a harmless sleeper carrying *marker* in its command line."""
    argv = [sys.executable, "-c", "import time; time.sleep(30)", marker]
    if sys.platform == "win32":
        return subprocess.Popen(argv, creationflags=0x00000200)
    return subprocess.Popen(argv, start_new_session=True)


def _scan_for(marker: str) -> Mapping[str, object] | None:
    """Return the scan entry whose command line carries *marker*.

    Reads ONLY ``cmdline`` while searching, which is the whole point: the
    returned entry must not have materialised ``ppid`` yet.
    """
    for info in iter_process_info(["pid", "ppid", "cmdline"]):
        raw = info.get("cmdline")
        if not isinstance(raw, list):
            continue
        parts = cast("list[object]", raw)
        if any(marker == str(item) for item in parts):
            return info
    return None


class TestScanReadsAttributesOnDemand:
    def test_an_unread_attribute_is_not_captured_at_scan_time(self) -> None:
        """A value never asked for during the scan was never paid for.

        The discriminator is a read that happens AFTER the process exits. A lazy
        scan has nothing stored for ``ppid``, so it goes to the OS and correctly
        reports "could not tell" (``None``). An eager scan - one that
        materialises every requested attribute for every process, as
        ``psutil.process_iter(attrs)`` does - would hand back the parent pid it
        captured while the process was alive, which is exactly the implementation
        that cost 72-86s per walk.
        """
        marker = f"vaultspec-scan-cost-witness-{time.monotonic_ns()}"
        proc = _spawn_marked_sleeper(marker)
        try:
            info = None
            for _ in range(100):
                info = _scan_for(marker)
                if info is not None:
                    break
                time.sleep(0.1)
            assert info is not None, "the spawned witness never enumerated"

            # Only cmdline has been read. End the process and confirm it is
            # fully gone before asking for the attribute nobody requested yet.
            proc.kill()
            proc.wait(timeout=10)
            for _ in range(100):
                if not pid_alive(proc.pid):
                    break
                time.sleep(0.1)
            assert not pid_alive(proc.pid), "the witness did not exit"

            # Assert on OUR parent link, not on ``None``. The witness is dead,
            # so a lazy read reports "could not tell" - but the OS may reuse a
            # freed pid, and under a parallel run it often does, handing back
            # some unrelated process's ppid and failing a ``is None`` check for
            # a reason that has nothing to do with laziness. Only an EAGER scan
            # can return this process's pid here, because only a read taken
            # while the witness was alive saw that link.
            assert info.get("ppid") != os.getpid(), (
                "ppid was materialised during the scan instead of on demand; "
                "an eager scan pays a full-system snapshot per process and "
                "takes tens of seconds on a busy host"
            )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_a_read_attribute_is_still_answered_from_the_scan(self) -> None:
        """Laziness must not cost the scan its answers.

        The failure mode opposite to the one above: a scan cheap because it
        reports nothing is worse than a slow one, since a reap reading zero
        matches concludes the machine is clear. This pins that a live process's
        witness attributes are all readable through the same entry.
        """
        marker = f"vaultspec-scan-cost-live-{time.monotonic_ns()}"
        proc = _spawn_marked_sleeper(marker)
        try:
            info = None
            for _ in range(100):
                info = _scan_for(marker)
                if info is not None:
                    break
                time.sleep(0.1)
            assert info is not None, "the spawned witness never enumerated"
            assert info.get("pid") == proc.pid, (
                "the scan must report the witness's own pid"
            )
            assert isinstance(info.get("ppid"), int), (
                "a LIVE process must still answer ppid; the pair-detection the "
                "orphan reap does is built on it"
            )
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)


class TestTheImageGateAdmitsEveryDaemon:
    """The cheap image discriminator must never rule out a real daemon.

    Both scans ask a process's image before its command line, because reading
    a command line costs a second on a permanently protected process and the
    image costs nothing. That trade is only sound while every process a daemon
    launch produces passes the gate - a launcher the gate rejects is an orphan
    the reap cannot see, which is the one failure the reap exists to prevent.
    So the gate is held against the interpreter the production launcher
    actually resolves, and against the process tree spawning it actually
    creates, rather than against an assumption about how a venv is laid out.
    """

    def test_a_spawned_daemon_runs_under_an_image_the_scans_admit(self) -> None:
        """Every process of a real daemon spawn passes the image gate.

        The launcher is not the only one that has to: a Windows venv
        ``python.exe`` is a shim that re-execs the base interpreter, so one
        logical daemon is a launcher plus a worker and the reap has to see the
        pair. The name asserted on is the one the SCAN reads - psutil's, not
        the path's basename - because a shim on Windows and ``comm``
        truncation on POSIX both sit between the two.

        Mutation proving this can fail: narrowing
        ``_LAUNCH_WITNESS_IMAGE_PREFIX`` to an image no interpreter is named
        (``pythonw``) rejects the launcher and reds this by name.
        """
        interpreter = _resolve_daemon_interpreter()
        argv = [interpreter, "-c", "import time; time.sleep(30)"]
        if sys.platform == "win32":
            proc = subprocess.Popen(argv, creationflags=0x00000200)
        else:
            proc = subprocess.Popen(argv, start_new_session=True)
        try:
            parent = psutil.Process(proc.pid)
            # The shim's worker appears a moment after the launcher does.
            deadline = time.monotonic() + 30.0
            while time.monotonic() < deadline and not parent.children(recursive=True):
                if sys.platform != "win32":
                    break
                time.sleep(0.05)
            spawned = [parent, *parent.children(recursive=True)]
            rejected = [
                process.name()
                for process in spawned
                if not _may_carry_launch_witness(process.name())
            ]
            assert not rejected, (
                f"the image gate rules out {rejected}, which a daemon spawned "
                f"through {interpreter!r} runs under; the scans would not see "
                "that daemon, and an orphan reap would report a clean machine"
            )
        finally:
            for child in psutil.Process(proc.pid).children(recursive=True):
                with contextlib.suppress(psutil.Error):
                    child.kill()
            if proc.poll() is None:
                proc.kill()
                proc.wait(timeout=5)

    def test_an_unreadable_image_is_not_ruled_out(self) -> None:
        """An image the scan could not read is not an image it ruled out.

        The scan reports ``None`` for an attribute it could not read. Treating
        that as a non-match would convert a process the scan failed to describe
        into one it had cleared, so the gate admits it and lets the command
        line - the authority on what a process is - answer.
        """
        assert _may_carry_launch_witness(None)

    def test_a_foreign_image_is_ruled_out(self) -> None:
        """And the gate must actually be a gate, or it saves nothing.

        The images named here are the ones measured to cost a second each:
        psutil retries their command-line read for a full second before
        converting it to ``AccessDenied``. If they were admitted the scan would
        be back to paying for them.
        """
        for image in ("LsaIso.exe", "NgcIso.exe", "vmmemWSL", "svchost.exe"):
            assert not _may_carry_launch_witness(image), image
        for image in ("python.exe", "python", "python3.13", "Python", "python3"):
            assert _may_carry_launch_witness(image), image
