"""Unit tests for the stdio shim lifetime watchdog (mcp-stdio-lifetime ADR).

Covers the pure ancestor-walk guards, the env kill switch, and (on Windows)
real handle acquisition against the live test process's own ancestry - no
mocks; the Windows assertions run against genuine kernel32 calls. The
fires-on-death path is exercised end-to-end in the integration suite.
"""

from __future__ import annotations

import os
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

    @pytest.mark.parametrize("value", ["", "1", "true", "on"])
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

    def test_explicit_parent_pid_is_watched_first(self) -> None:
        ppid = os.getppid()
        watched = lifetime.open_ancestor_handles((ppid,))
        try:
            assert watched[0].pid == ppid
            assert [ancestor.pid for ancestor in watched].count(ppid) == 1
        finally:
            for ancestor in watched:
                lifetime._kernel32.CloseHandle(ancestor.handle)

    def test_unwatchable_explicit_pid_is_skipped(self) -> None:
        # Windows PIDs are multiples of 4, so PID 3 can never name a
        # process; the unopenable explicit target is skipped, not fatal.
        watched = lifetime.open_ancestor_handles((3,))
        try:
            assert all(ancestor.pid != 3 for ancestor in watched)
        finally:
            for ancestor in watched:
                lifetime._kernel32.CloseHandle(ancestor.handle)

    def test_creation_times_are_monotonic_up_the_chain(self) -> None:
        watched = lifetime.open_ancestor_handles()
        try:
            times = [lifetime._creation_time(a.handle) for a in watched]
            assert all(t > 0 for t in times)
            assert times == sorted(times, reverse=True)
        finally:
            for ancestor in watched:
                lifetime._kernel32.CloseHandle(ancestor.handle)
