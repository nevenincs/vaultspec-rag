"""A hard-killed owner must not strand the processes it spawned.

The fixture teardown, the atexit backstop and any watchdog thread all live
inside the run that dies, so none of them can be the guarantee when that run is
killed rather than ended. Only the kill-on-close Job Object is enforced by the
kernel from outside, and these tests exercise exactly that: the owner is
terminated with ``TerminateProcess``, which runs no cleanup of any kind.
"""

from __future__ import annotations

import ast
import contextlib
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
#:
#: Executed as a standalone script in a subprocess rather than imported, so its
#: import must be absolute - a relative import has no package to resolve
#: against and raises at startup.
_OWNER = """
import subprocess, sys, time
from vaultspec_rag._win32 import (  # absolute-import-ok
    assign_process_to_job,
    create_kill_on_close_job,
)

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
            with contextlib.ExitStack() as cleanup:
                for stream in (owner.stdout, owner.stderr):
                    if stream is not None:
                        cleanup.callback(stream.close)
                try:
                    if owner.poll() is None:
                        owner.kill()
                    try:
                        owner.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        owner.kill()
                        owner.wait(timeout=10)
                finally:
                    if sleeper_pid is not None and pid_alive(sleeper_pid):
                        with contextlib.suppress(OSError):
                            os.kill(sleeper_pid, signal.SIGTERM)


@pytest.mark.skipif(sys.platform != "win32", reason="Job Objects are Windows-only")
class TestTheAnchorEstablishesMembership:
    def test_anchoring_a_live_process_succeeds(self) -> None:
        # The two guards either side of this prove the OS primitive holds and
        # that every test spawn goes through the anchor. Neither sees the
        # anchor itself silently returning False - a wrong access mask or a
        # failed job creation - which would leave every spawn calling a no-op.
        from ...cli._process import WIN_DAEMON_SPAWN_FLAGS
        from .._session_job_anchor import anchor_spawned_process_to_session

        sleeper = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(60)"],
            creationflags=WIN_DAEMON_SPAWN_FLAGS,
        )
        try:
            assert anchor_spawned_process_to_session(sleeper.pid), (
                "the anchor reported no membership for a live process it should "
                "have joined to the session job"
            )
        finally:
            sleeper.kill()
            sleeper.wait(timeout=10)


#: The one test module allowed to call the production spawn directly.
_ANCHORING_MODULE = "_session_job_anchor.py"


def _direct_spawn_calls(source: Path) -> list[int]:
    """Return the lines of *source* that call the production spawn directly."""
    module = ast.parse(source.read_text(encoding="utf-8"))
    lines: list[int] = []
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.id if isinstance(func, ast.Name) else None
        if isinstance(func, ast.Attribute):
            name = func.attr
        if name == "_spawn_service":
            lines.append(node.lineno)
    return lines


class TestEverySpawnedDaemonIsAnchored:
    def test_tests_spawn_the_service_only_through_the_anchor(self) -> None:
        # The anchor is only a guarantee if every spawn takes it, and production
        # knows nothing about the test session, so the spawn sites are here. A
        # source assertion rather than a behavioural one because the failure
        # being guarded is a new test calling the production spawn directly,
        # which no passing service test would notice. Program text a test runs
        # in a child process is a string, not a call, and is not counted: that
        # child is its own owner.
        #
        # Mutation check: replacing one `spawn_anchored_service(` call in
        # test_watcher_control.py with the production `_spawn_service(` failed
        # this test on its assertion, naming that file and line; restoring the
        # call passed it.
        tests_root = Path(__file__).resolve().parents[1]
        offenders = [
            f"{path.relative_to(tests_root).as_posix()}:{line}"
            for path in sorted(tests_root.rglob("*.py"))
            if path.name != _ANCHORING_MODULE
            for line in _direct_spawn_calls(path)
        ]
        assert not offenders, (
            "these tests start the real service without binding it to the "
            "session job, so a hard-killed run would strand the daemon; use "
            f"spawn_anchored_service: {offenders}"
        )
