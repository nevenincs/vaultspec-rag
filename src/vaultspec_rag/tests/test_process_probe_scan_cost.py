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

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING, Any

import pytest

from .._process_probe import iter_process_info, pid_alive

if TYPE_CHECKING:
    from collections.abc import Mapping

pytestmark = [pytest.mark.unit]


def _spawn_marked_sleeper(marker: str) -> subprocess.Popen[bytes]:
    """Spawn a harmless sleeper carrying *marker* in its command line."""
    argv = [sys.executable, "-c", "import time; time.sleep(30)", marker]
    if sys.platform == "win32":
        return subprocess.Popen(argv, creationflags=0x00000200)
    return subprocess.Popen(argv, start_new_session=True)


def _scan_for(marker: str) -> Mapping[str, Any] | None:
    """Return the scan entry whose command line carries *marker*.

    Reads ONLY ``cmdline`` while searching, which is the whole point: the
    returned entry must not have materialised ``ppid`` yet.
    """
    for info in iter_process_info(["pid", "ppid", "cmdline"]):
        raw = info.get("cmdline")
        if not isinstance(raw, list):
            continue
        parts: list[object] = raw
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
