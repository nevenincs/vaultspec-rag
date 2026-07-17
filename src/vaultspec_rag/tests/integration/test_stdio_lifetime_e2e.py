"""End-to-end integration tests for the stdio lifetime watchdog.

The research mandate (finding W2): the fires-on-death path must be proven
in real subprocesses, because a silently mis-bound wait primitive passes
every in-process test while never firing. Two real-process scenarios:

- chain-kill: a worker armed with a short grace watches a real
  intermediary; killing the intermediary must hard-exit the worker (the
  orphaned-shim leak shape - research L5).
- EOF-still-primary: the real stdio shim entry point exits cleanly when
  stdin closes, watchdog armed (research L3 must keep holding).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [pytest.mark.integration]

_WORKER_SCRIPT = """
import sys
from pathlib import Path

from vaultspec_rag.server import _stdio_lifetime  # absolute-import-ok

pid_file = Path(sys.argv[1])
thread = _stdio_lifetime.install_stdio_lifetime_watchdog(grace_seconds=0.5)
assert thread is not None
pid_file.write_text(str(__import__("os").getpid()), encoding="utf-8")
__import__("time").sleep(120)
"""

_INTERMEDIARY_SCRIPT = """
import subprocess
import sys
import time

worker = subprocess.Popen([sys.executable, sys.argv[1], sys.argv[2]])
time.sleep(120)
"""


def _pid_alive(pid: int) -> bool:
    if sys.platform == "win32":
        from ...server._stdio_lifetime import _kernel32, _open_process

        handle = _open_process(pid)
        if handle is None:
            return False
        try:
            # 0x102 = WAIT_TIMEOUT: still running.
            return _kernel32.WaitForSingleObject(handle, 0) == 0x102
        finally:
            _kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_worker_reaps_itself_when_an_ancestor_dies(tmp_path: Path) -> None:
    """Killing the middle of a real spawn chain hard-exits the worker."""
    worker_py = tmp_path / "worker.py"
    worker_py.write_text(_WORKER_SCRIPT, encoding="utf-8")
    intermediary_py = tmp_path / "intermediary.py"
    intermediary_py.write_text(_INTERMEDIARY_SCRIPT, encoding="utf-8")
    pid_file = tmp_path / "worker.pid"

    intermediary = subprocess.Popen(
        [sys.executable, str(intermediary_py), str(worker_py), str(pid_file)]
    )
    try:
        deadline = time.monotonic() + 30
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.2)
        assert pid_file.exists(), "worker never armed its watchdog"
        worker_pid = int(pid_file.read_text(encoding="utf-8"))
        assert _pid_alive(worker_pid)

        # An ancestor death INSIDE the grace window is deliberately pruned
        # as spawn-helper noise; the kill must land after the watchdog arms.
        time.sleep(2)
        intermediary.kill()
        intermediary.wait(timeout=15)

        deadline = time.monotonic() + 20
        while _pid_alive(worker_pid) and time.monotonic() < deadline:
            time.sleep(0.5)
        assert not _pid_alive(worker_pid), (
            "worker survived its ancestor's death; the watchdog never fired"
        )
    finally:
        if intermediary.poll() is None:
            intermediary.kill()
        if pid_file.exists():
            worker_pid = int(pid_file.read_text(encoding="utf-8"))
            if _pid_alive(worker_pid) and sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(worker_pid)],
                    capture_output=True,
                    check=False,
                )


def test_stdin_eof_still_exits_the_real_shim_cleanly() -> None:
    """The protocol-blessed EOF path keeps working with the watchdog armed."""
    shim = subprocess.Popen(
        [sys.executable, "-c", "from vaultspec_rag.server import main; main()"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert shim.stdin is not None
        # Give the shim a moment to reach the stdio read loop, then EOF.
        time.sleep(5)
        shim.stdin.close()
        returncode = shim.wait(timeout=60)
        assert returncode == 0
    finally:
        if shim.poll() is None:
            shim.kill()
