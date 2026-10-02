"""Real retained process objects cannot become live discovered ancestors."""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ..server import _stdio_lifetime as lifetime
from ._child_signal import CHILD_PROCESS_TIMEOUT_SECONDS

if TYPE_CHECKING:
    from pathlib import Path

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(
        sys.platform != "win32", reason="Windows process handle semantics"
    ),
]

_PROBE = '''
import hashlib, json, os, subprocess, sys, sysconfig, time
from pathlib import Path
from vaultspec_rag.server import _stdio_lifetime as w

root = Path(sys.argv[1])
base = getattr(sys, "_base_executable", sys.executable)
env = dict(
    os.environ,
    PYTHONPATH=os.pathsep.join(
        [str(Path("src").resolve()), sysconfig.get_paths()["purelib"]]
    ),
    PYTHONWARNINGS="error",
)
grandchild = r"""
import json,os,sys,time
from pathlib import Path
from vaultspec_rag.server import _stdio_lifetime as w
root=Path(sys.argv[1])
staged=root/'ready.tmp';staged.write_text(str(os.getpid()));staged.replace(root/'ready')
deadline=time.monotonic()+10
while not(root/'go').exists():
 assert time.monotonic()<deadline, 'parent handoff missing'
 time.sleep(.01)
handles=w.open_ancestor_handles()
try:
 payload=[dict(pid=a.pid,exe=a.exe,
               wait=int(w._kernel32.WaitForSingleObject(a.handle,0)))
          for a in handles]
finally:
 for a in handles:w._kernel32.CloseHandle(a.handle)
staged=root/'result.tmp';staged.write_text(json.dumps(payload),encoding='utf-8')
staged.replace(root/'result.json')
"""
parent_source = r"""
import os,subprocess,sys,time
from pathlib import Path
root=Path(sys.argv[3])
child=subprocess.Popen(
    [sys.argv[1],'-c',sys.argv[2],sys.argv[3]],
    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
try:
    deadline=time.monotonic()+10
    while not(root/'ready').exists():
        assert time.monotonic()<deadline, 'native probe child readiness missing'
        time.sleep(.01)
except BaseException:
    if child.poll() is None:child.kill()
    child.wait(timeout=10)
    raise
# The fixture deliberately leaves an orphan, retaining the object until death.
os._exit(0)
"""
with (root / "parent.stderr").open("wb") as parent_errors:
    parent = subprocess.Popen(
        [base, "-c", parent_source, base, grandchild, str(root.resolve())],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=parent_errors,
    )
try:
    parent_exit = parent.wait(timeout=10)
    assert parent_exit == 0
    parent_output = (root / "parent.stderr").read_text(encoding="utf-8")
    assert parent_output == "", parent_output
    reopened = w._open_process(parent.pid)
    assert reopened is not None
    try:
        dead_wait = int(w._kernel32.WaitForSingleObject(reopened, 0))
        assert dead_wait == w._WAIT_OBJECT_0
    finally:
        w._kernel32.CloseHandle(reopened)
    deadline = time.monotonic() + 10
    while not (root / "ready").exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    (root / "go").touch()
    while not (root / "result.json").exists():
        assert time.monotonic() < deadline
        time.sleep(0.01)
    ancestry = json.loads((root / "result.json").read_text(encoding="utf-8"))
    child_pid = int((root / "ready").read_text())
    while w.pid_alive(child_pid):
        assert time.monotonic() < deadline, "probe child did not exit"
        time.sleep(0.01)
    assert ancestry == [], "already-dead ancestor became a precise anchor: " + str(
        ancestry
    )
finally:
    if parent.poll() is None:
        parent.kill()
    parent.wait(timeout=10)
live = subprocess.Popen(
    [base, "-c", "import time;time.sleep(60)"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)
handle = None
try:
    target = w.open_watched(live.pid, grace_prunable=False)
    assert target is not None
    handle = target.handle
    before = int(w._kernel32.WaitForSingleObject(handle, 0))
    assert before == w._WAIT_TIMEOUT
    live.terminate()
    live_exit = live.wait(timeout=10)
    after = int(w._kernel32.WaitForSingleObject(handle, 0))
    assert after == w._WAIT_OBJECT_0
    precise_dead = w.open_watched(live.pid, grace_prunable=False)
    assert precise_dead is not None
    try:
        assert (
            w._kernel32.WaitForSingleObject(precise_dead.handle, 0) == w._WAIT_OBJECT_0
        )
    finally:
        w._kernel32.CloseHandle(precise_dead.handle)
finally:
    if live.poll() is None:
        live.kill()
    live.wait(timeout=10)
    if handle is not None:
        w._kernel32.CloseHandle(handle)

print(json.dumps(dict(dead_discovery=ancestry, live_before=before, live_after=after)))
'''


def test_retained_dead_ancestor_is_rejected_but_precise_death_still_signals(
    tmp_path: Path,
) -> None:
    """Old discovery accepted the dead retained handle; the native guard rejects it.

    The live precise control stays unsignaled until death, and a precise anchor
    may still open that retained dead object. No process APIs are substituted.
    Discarding the launcher child failed the captured-stderr assertion with a
    real ResourceWarning; restoring retention passed the same native case.
    """
    result = subprocess.run(
        [sys.executable, "-W", "error", "-c", _PROBE, str(tmp_path)],
        env=dict(os.environ, PYTHONWARNINGS="error"),
        capture_output=True,
        text=True,
        timeout=CHILD_PROCESS_TIMEOUT_SECONDS,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == "", result.stderr


def test_failed_native_wait_closes_previously_accumulated_ancestor_handles() -> None:
    """An actual invalid handle must preserve its native error and close prior owners.

    Removing accumulated-handle cleanup failed the invalid-handle assertion;
    restoration passed the same real native case.
    """
    with subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ) as child:
        watched = lifetime.open_watched(child.pid, grace_prunable=True)
        invalid = lifetime._open_process(child.pid)
        assert watched is not None and invalid is not None
        assert lifetime._kernel32.CloseHandle(invalid)
        try:
            with pytest.raises(OSError) as raised:
                lifetime._discovered_handle_is_live(invalid, [watched])
            assert raised.value.winerror == 6
            assert (
                lifetime._kernel32.WaitForSingleObject(watched.handle, 0) == 0xFFFFFFFF
            )
            assert ctypes.get_last_error() == 6
        finally:
            lifetime._kernel32.CloseHandle(watched.handle)
            child.kill()
            child.wait(timeout=10)
