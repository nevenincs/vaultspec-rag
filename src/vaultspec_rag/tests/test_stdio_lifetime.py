"""Unit tests for the stdio shim lifetime watchdog.

Covers the pure ancestor-walk guards, the env kill switch, and (on Windows)
real handle acquisition against the live test process's own ancestry - no
mocks; the Windows assertions run against genuine kernel32 calls. The
fires-on-death path is exercised end-to-end in the integration suite.
"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import TYPE_CHECKING

import pytest

from ..server import _stdio_lifetime as lifetime

if TYPE_CHECKING:
    from collections.abc import Iterator

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
