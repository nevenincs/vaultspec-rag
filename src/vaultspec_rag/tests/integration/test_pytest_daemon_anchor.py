"""A hard-killed owner must not strand the processes it spawned.

The fixture teardown, the atexit backstop and any watchdog thread all live
inside the run that dies, so none of them can be the guarantee when that run is
killed rather than ended. Only the kill-on-close Job Object is enforced by the
kernel from outside, and these tests exercise exactly that: the owner is
terminated with ``TerminateProcess``, which runs no cleanup of any kind.
"""

from __future__ import annotations

import ast
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ..._process_probe import pid_alive

pytestmark = pytest.mark.integration


#: The owner: it creates the job, spawns a sleeper into it, reports the
#: sleeper's pid, then parks. Nothing here ever runs cleanup - the test kills
#: this process outright, which is the whole point.
_OWNER = """
import subprocess, sys, time
from vaultspec_rag._win32 import assign_process_to_job, create_kill_on_close_job

job = create_kill_on_close_job(purpose="test")
assert job is not None, "job creation failed"
sleeper = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
handle = __import__("ctypes").windll.kernel32.OpenProcess(0x0101, False, sleeper.pid)
assert handle, "could not open the sleeper"
assert assign_process_to_job(job, handle, sleeper.pid, purpose="test")
print(sleeper.pid, flush=True)
time.sleep(600)
"""


def _wait_gone(pid: int, *, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not pid_alive(pid):
            return True
        time.sleep(0.1)
    return not pid_alive(pid)


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
class TestKillOnCloseSurvivesAHardKill:
    def test_hard_killed_owner_takes_its_spawned_process_with_it(self) -> None:
        owner = subprocess.Popen(
            [sys.executable, "-c", textwrap.dedent(_OWNER)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        sleeper_pid: int | None = None
        try:
            assert owner.stdout is not None
            first = owner.stdout.readline().strip()
            assert first.isdigit(), (
                "owner did not report a sleeper pid; "
                f"stderr={(owner.stderr.read() if owner.stderr else '')!r}"
            )
            sleeper_pid = int(first)
            assert pid_alive(sleeper_pid), "sleeper should be running before the kill"

            # TerminateProcess: no atexit, no finally, no teardown. Exactly the
            # shape that strands a daemon today.
            os.kill(owner.pid, signal.SIGTERM)
            assert _wait_gone(owner.pid, timeout=10.0), "owner survived the kill"

            assert _wait_gone(sleeper_pid, timeout=15.0), (
                f"sleeper {sleeper_pid} outlived its hard-killed owner; the "
                "kill-on-close job did not hold"
            )
        finally:
            if owner.poll() is None:
                owner.kill()
            if sleeper_pid is not None and pid_alive(sleeper_pid):
                with __import__("contextlib").suppress(OSError):
                    os.kill(sleeper_pid, signal.SIGTERM)


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
class TestTheAnchorEstablishesMembership:
    def test_anchoring_a_live_process_succeeds_under_pytest(self) -> None:
        # The two guards either side of this prove the OS primitive holds and
        # that the spawn path calls the anchor. Neither sees the anchor itself
        # silently returning False - a wrong access mask or a failed job
        # creation - which would leave the spawn path calling a no-op.
        from ..._test_isolation import anchor_spawned_process_to_pytest

        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"]
        )
        try:
            assert anchor_spawned_process_to_pytest(sleeper.pid), (
                "the anchor reported no membership for a live process it should "
                "have joined to the pytest job"
            )
        finally:
            sleeper.kill()
            sleeper.wait(timeout=10)


class TestEverySpawnedDaemonIsAnchored:
    def test_spawn_service_anchors_the_process_it_created(self) -> None:
        # The anchor is only a guarantee if the spawn path actually calls it.
        # A source assertion rather than a behavioural one because the failure
        # being guarded is deletion of the call, which no passing service test
        # would notice.
        from ...cli import _process as process_module

        source = Path(process_module.__file__).read_text(encoding="utf-8")
        spawn = next(
            node
            for node in ast.walk(ast.parse(source))
            if isinstance(node, ast.FunctionDef) and node.name == "_spawn_service"
        )
        called = {
            node.func.id
            for node in ast.walk(spawn)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "anchor_spawned_process_to_pytest" in called, (
            "_spawn_service no longer anchors the process it spawned; a "
            "hard-killed pytest run will strand its daemon"
        )
