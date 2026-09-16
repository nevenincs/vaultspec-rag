"""Unit tests for the stdio shim lifetime watchdog.

Covers the pure ancestor-walk guards, the env kill switch, and each
platform's backstop against real processes - no mocks: the Windows
assertions run against genuine kernel32 calls, and the POSIX ones against a
real reparent and the real liveness probe. Both halves are covered here
because the watchdog is one contract with two implementations, and a suite
that proves only the host's half lets the other reach a release untested.
The Windows fires-on-death path is exercised end-to-end in the integration
suite as well.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from ..server import _stdio_lifetime as lifetime

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]


@pytest.fixture
def watchdog_env() -> Iterator[None]:
    """Restore the watchdog env knob after each test."""
    original = os.environ.get(lifetime.STDIO_WATCHDOG_ENV)
    try:
        yield
    finally:
        if original is None:
            os.environ.pop(lifetime.STDIO_WATCHDOG_ENV, None)
        else:
            os.environ[lifetime.STDIO_WATCHDOG_ENV] = original


class TestWalkAncestorPids:
    def test_walks_a_simple_chain_nearest_first(self) -> None:
        parents = {10: 20, 20: 30, 30: 40}
        assert lifetime._walk_ancestor_pids(10, parents) == [20, 30, 40]

    def test_stops_at_missing_parent_entry(self) -> None:
        assert lifetime._walk_ancestor_pids(10, {10: 20}) == [20]

    def test_stops_at_pid_zero(self) -> None:
        assert lifetime._walk_ancestor_pids(10, {10: 0}) == []

    def test_stops_at_self_parenting(self) -> None:
        assert lifetime._walk_ancestor_pids(10, {10: 10}) == []

    def test_stops_at_cycles_from_pid_reuse(self) -> None:
        parents = {10: 20, 20: 30, 30: 10}
        assert lifetime._walk_ancestor_pids(10, parents) == [20, 30]

    def test_honors_the_depth_bound(self) -> None:
        parents = {n: n + 1 for n in range(10, 100)}
        chain = lifetime._walk_ancestor_pids(10, parents, max_depth=3)
        assert chain == [11, 12, 13]


@pytest.mark.usefixtures("watchdog_env")
class TestWatchdogDisabled:
    @pytest.mark.parametrize("value", ["0", "false", "FALSE", "off", " no "])
    def test_disabling_values(self, value: str) -> None:
        os.environ[lifetime.STDIO_WATCHDOG_ENV] = value
        assert lifetime.watchdog_disabled() is True

    @pytest.mark.parametrize("value", ["", "1", "true", "on", " YES "])
    def test_enabling_values(self, value: str) -> None:
        os.environ[lifetime.STDIO_WATCHDOG_ENV] = value
        assert lifetime.watchdog_disabled() is False

    def test_unset_means_enabled(self) -> None:
        os.environ.pop(lifetime.STDIO_WATCHDOG_ENV, None)
        assert lifetime.watchdog_disabled() is False


@pytest.mark.usefixtures("watchdog_env")
class TestInstall:
    def test_disabled_env_returns_none(self) -> None:
        os.environ[lifetime.STDIO_WATCHDOG_ENV] = "0"
        assert lifetime.install_stdio_lifetime_watchdog() is None

    def test_installs_a_named_daemon_thread(self) -> None:
        os.environ.pop(lifetime.STDIO_WATCHDOG_ENV, None)
        thread = lifetime.install_stdio_lifetime_watchdog(grace_seconds=3600.0)
        assert thread is not None
        assert thread.daemon is True
        assert thread.name == "stdio-lifetime-watchdog"
        assert thread.is_alive()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows handle semantics")
class TestOpenAncestorHandlesWindows:
    def test_discovers_the_real_parent_chain(self) -> None:
        watched = lifetime.open_ancestor_handles()
        try:
            assert watched, "a pytest process always has live ancestors"
            assert watched[0].pid == os.getppid()
            assert all(ancestor.handle for ancestor in watched)
            assert len(watched) <= lifetime._MAX_ANCESTOR_DEPTH
        finally:
            for ancestor in watched:
                lifetime._kernel32.CloseHandle(ancestor.handle)

    def test_chain_targets_are_grace_prunable(self) -> None:
        watched = lifetime.open_ancestor_handles()
        try:
            assert all(ancestor.grace_prunable for ancestor in watched)
        finally:
            for ancestor in watched:
                lifetime._kernel32.CloseHandle(ancestor.handle)

    def test_unwatchable_pid_is_refused_not_fatal(self) -> None:
        # Windows PIDs are multiples of 4, so PID 3 can never name a
        # process; the unopenable target is refused, not fatal.
        assert lifetime.open_watched(3, grace_prunable=False) is None

    def test_creation_times_are_monotonic_up_the_chain(self) -> None:
        watched = lifetime.open_ancestor_handles()
        try:
            times = [lifetime._creation_time(a.handle) for a in watched]
            assert all(t > 0 for t in times)
            assert times == sorted(times, reverse=True)
        finally:
            for ancestor in watched:
                lifetime._kernel32.CloseHandle(ancestor.handle)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pipe semantics")
class TestLayeredAnchors:
    """The layered composition: precise anchors beat the discovered chain."""

    def test_pipe_creator_resolves_to_the_spawning_process(self) -> None:
        # A child spawned with stdin=PIPE must resolve THIS process as the
        # pipe creator - the exact-client anchor at any wrapper depth.
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "from vaultspec_rag.server import _stdio_lifetime as w; "
                "print(w.resolve_stdin_client_pid())",  # absolute-import-ok
            ],
            stdin=subprocess.PIPE,
            capture_output=True,
            text=True,
            check=True,
        )
        assert proc.stdout.strip() == str(os.getpid())

    def test_console_stdin_fails_open(self) -> None:
        # Under pytest, stdin is a captured non-pipe handle or a console;
        # either way resolution must fail open rather than raise. A pipe
        # result is possible when the runner itself was piped - accept int
        # or None, never an exception.
        result = lifetime.resolve_stdin_client_pid()
        assert result is None or isinstance(result, int)

    def test_resolved_client_suppresses_the_chain(self) -> None:
        watched = lifetime._gather_windows_targets(None, os.getppid())
        try:
            assert [target.pid for target in watched] == [os.getppid()]
            assert not watched[0].grace_prunable
        finally:
            for target in watched:
                lifetime._kernel32.CloseHandle(target.handle)

    def test_explicit_and_client_deduplicate(self) -> None:
        ppid = os.getppid()
        watched = lifetime._gather_windows_targets(ppid, ppid)
        try:
            assert [target.pid for target in watched] == [ppid]
            assert not watched[0].grace_prunable
        finally:
            for target in watched:
                lifetime._kernel32.CloseHandle(target.handle)

    def test_no_client_falls_back_to_the_chain(self) -> None:
        # An unopenable client pid (3) leaves no client anchor, so the
        # discovered chain must arm as the fallback.
        watched = lifetime._gather_windows_targets(None, 3)
        try:
            assert watched, "fallback chain must arm when the client cannot"
            assert all(target.grace_prunable for target in watched)
        finally:
            for target in watched:
                lifetime._kernel32.CloseHandle(target.handle)


_OFF_THREAD_RESOLVE = """
import threading
from vaultspec_rag.server import _stdio_lifetime as w  # absolute-import-ok

captured = []
thread = threading.Thread(target=lambda: captured.append(w.resolve_stdin_client_pid()))
thread.start()
thread.join(30)
print(w.resolve_stdin_client_pid(), captured[0] if captured else "HUNG")
"""


@pytest.mark.skipif(sys.platform != "win32", reason="Windows pipe semantics")
class TestOrphanRearm:
    """Losing every anchor re-arms and eventually reaps, never disarms."""

    def test_pipe_resolution_is_refused_off_the_main_thread(self) -> None:
        """Guard: a pipe query from the watchdog thread would deadlock.

        Querying the stdin pipe is I/O on a synchronous file object, so
        once the transport's reader has a ``ReadFile`` pending on that
        handle the query blocks behind it for the life of the process -
        measured, and silent, which is why the guard exists rather than a
        comment. The child resolves once on the main thread (proving the
        pipe IS resolvable here) and once on a worker thread, which must
        decline.

        Mutation: dropping the ``current_thread() is main_thread()`` check
        makes the second value the spawning PID instead of ``None``, and
        this assertion fails on the inequality.
        """
        proc = subprocess.run(
            [sys.executable, "-c", _OFF_THREAD_RESOLVE],
            stdin=subprocess.PIPE,
            capture_output=True,
            text=True,
            check=True,
        )
        assert proc.stdout.split() == [str(os.getpid()), "None"], proc.stdout

    def test_live_ancestor_pids_reports_the_running_chain(self) -> None:
        pids = lifetime.live_ancestor_pids()
        assert pids, "a pytest process always has a live ancestor"
        assert pids[0] == os.getppid()

    def test_rediscovered_targets_are_never_grace_prunable(self) -> None:
        # Anything alive past the grace window is not a transient spawn
        # helper, so a re-armed target's death must reap immediately.
        watched = lifetime._rediscover_targets()
        try:
            assert watched, "the live chain must be re-discoverable"
            assert not any(target.grace_prunable for target in watched)
        finally:
            for target in watched:
                lifetime._kernel32.CloseHandle(target.handle)

    def test_grace_prune_names_the_nearest_dead_ancestor(self) -> None:
        # The reap event has to name a dead ancestor even though the whole
        # chain went; the nearest pruned target is that name.
        doomed = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
        # Opened while it lives: our own handle keeps the process object
        # (and so the signalled wait) valid after it exits.
        target = lifetime.open_watched(doomed.pid, grace_prunable=True)
        assert target is not None
        doomed.wait(timeout=30)
        survivors, nearest_dead = lifetime._grace_prune([target], 0.0)
        assert survivors == []
        assert nearest_dead is not None
        assert nearest_dead.pid == doomed.pid


#: Spawned by the intermediary below, then orphaned by it. Arms the real
#: backstop on its real parent and polls fast enough for a test to wait on.
_POSIX_ORPHAN_CHILD = """
import os
import pathlib
import sys

from vaultspec_rag.server import _stdio_lifetime as w  # absolute-import-ok

w._POSIX_POLL_SECONDS = 0.05
initial = os.getppid()
pathlib.Path(sys.argv[1]).write_text(str(initial), encoding="utf-8")
w._posix_watchdog(initial, ())
"""

#: Spawns the watchdog child, reports both pids, and exits once the child has
#: armed - the handshake matters, because an intermediary that exits before
#: the child reads ``getppid`` leaves the child already reparented and its
#: anchor can never be seen to break.
#:
#: The child gets its own stdout and stderr rather than inheriting this
#: process's. An orphan holding the write end of the pipe the test is reading
#: keeps that pipe open past its parent's exit, so the test would block on EOF
#: until the child died - waiting on the very death it is supposed to be
#: measuring, and stranding the child when it never comes.
_POSIX_ORPHAN_PARENT = """
import os
import subprocess
import sys
import time

armed, child_source, stderr_path = sys.argv[1], sys.argv[2], sys.argv[3]
with open(stderr_path, "wb") as err:
    child = subprocess.Popen(
        [sys.executable, "-c", child_source, armed],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=err,
    )
print(os.getpid(), child.pid, flush=True)
deadline = time.monotonic() + 60
while not os.path.exists(armed) and time.monotonic() < deadline:
    time.sleep(0.02)
"""

#: Watches one explicitly named pid while its own parent stays alive, which
#: isolates the explicit-anchor branch from the reparent branch.
_POSIX_EXPLICIT_CHILD = """
import os
import sys

from vaultspec_rag.server import _stdio_lifetime as w  # absolute-import-ok

w._POSIX_POLL_SECONDS = 0.05
w._posix_watchdog(os.getppid(), (int(sys.argv[1]),))
"""


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX reparent semantics")
class TestPosixWatchdog:
    """The POSIX backstop: a coarse reparent poll with explicit-pid anchors.

    Windows gets the layered handle machinery and the tests above; POSIX gets
    this loop, and it carries the same duty - a shim whose client is gone must
    reap itself rather than survive on an inherited stdin pipe that will never
    reach EOF.

    Both cases run the loop in a real child process against real anchors, and
    read the verdict off that child's exit status and the event it emits.
    Nothing is substituted, and that is not a preference: the loop never
    returns and ends by calling ``os._exit``, so in-process it could only be
    driven by replacing the clock it polls on and the exit it terminates with
    - the two things these tests exist to observe.
    """

    def test_an_orphaned_shim_reaps_itself_when_its_parent_dies(
        self, tmp_path: Path
    ) -> None:
        """A real reparent, end to end: the parent exits, the child follows.

        Mutation: dropping the ``ppid != initial_ppid`` comparison leaves the
        child polling forever and this test fails waiting for the event.
        """
        armed = tmp_path / "armed"
        stderr_path = tmp_path / "orphan-stderr"
        handshake = subprocess.run(
            [
                sys.executable,
                "-c",
                _POSIX_ORPHAN_PARENT,
                str(armed),
                _POSIX_ORPHAN_CHILD,
                str(stderr_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=120,
        )
        parent_pid, child_pid = (int(part) for part in handshake.stdout.split())
        try:
            event = _await_watchdog_event(stderr_path)
        finally:
            _reap_stray(child_pid)

        assert event == {
            "event": "stdio_watchdog_exit",
            "dead_ancestor_pid": parent_pid,
            "dead_ancestor_exe": "parent",
            "shim_pid": child_pid,
        }

    def test_an_explicit_anchor_reaps_the_shim_only_once_it_dies(
        self, tmp_path: Path
    ) -> None:
        """Death is the trigger, not the poll.

        The two halves are each other's control: a watchdog that never reaps
        passes the live half, and one that reaps on its first round passes the
        dead half. The child's own parent stays alive throughout, so only the
        explicit anchor can end it.

        Mutation: dropping the ``pid_alive`` check leaves the child running
        after the anchor dies; reaping unconditionally kills it while the
        anchor still lives.
        """
        stderr_path = tmp_path / "watchdog-stderr"
        anchor = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(120)"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        with stderr_path.open("wb") as err:
            watchdog = subprocess.Popen(
                [sys.executable, "-c", _POSIX_EXPLICIT_CHILD, str(anchor.pid)],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=err,
            )
        try:
            with pytest.raises(subprocess.TimeoutExpired):
                watchdog.wait(timeout=2.0)
            anchor.terminate()
            # Reaped, not merely signalled: an unreaped zombie still answers a
            # liveness probe, so the anchor is not dead until this returns.
            anchor.wait(timeout=60)
            assert watchdog.wait(timeout=60) == 0
        finally:
            _terminate(anchor)
            _terminate(watchdog)

        assert _await_watchdog_event(stderr_path) == {
            "event": "stdio_watchdog_exit",
            "dead_ancestor_pid": anchor.pid,
            "dead_ancestor_exe": "explicit-parent",
            "shim_pid": watchdog.pid,
        }


def _await_watchdog_event(stderr_path: Path, timeout: float = 60.0) -> object:
    """Return a watchdog child's exit event, waiting for it to be written."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if stderr_path.exists():
            for line in stderr_path.read_text(encoding="utf-8").splitlines():
                if "stdio_watchdog_exit" in line:
                    return json.loads(line)
        time.sleep(0.05)
    pytest.fail(f"no watchdog event within {timeout}s: {stderr_path.read_bytes()!r}")


def _terminate(process: subprocess.Popen[bytes]) -> None:
    """Make sure a test's child is gone, however the test ended."""
    if process.poll() is not None:
        return
    process.kill()
    process.wait(timeout=60)


def _reap_stray(pid: int) -> None:
    """Kill a watchdog child that outlived its test, so nothing is stranded.

    The signal is the number rather than ``signal.SIGKILL`` because this module
    is imported on Windows too, where that name does not exist; the caller is
    POSIX-gated, so 9 is always SIGKILL where this runs.
    """
    try:
        os.kill(pid, 9)
    except OSError:
        return
