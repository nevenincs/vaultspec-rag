"""Termination must recognize a zombie without exhausting child-cleanup time.

The process states these tests need - an acknowledged child exit, a non-child
zombie, a reused PID - cannot be produced on demand, so the probes that report
them are substituted. Most substitutes are tripwires that fail the test when a
forbidden probe or sleep is reached.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from .. import _process_probe as probe
from ..cli import _process as process

if TYPE_CHECKING:
    from ..qdrant_runtime._resolve import QdrantIdentity

pytestmark = [pytest.mark.unit]


def _present(_pid: int) -> bool:
    return True


def _absent(_pid: int) -> bool:
    return False


def test_child_reap_acknowledges_its_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    def waitpid(pid: int, _flags: int) -> tuple[int, int]:
        return pid, 0

    monkeypatch.setattr(probe, "sys", SimpleNamespace(platform="linux"))
    monkeypatch.setattr(probe, "os", SimpleNamespace(waitpid=waitpid, WNOHANG=1))
    assert probe.reap_if_child(2_000_000_000)


def test_reaped_child_does_not_probe_a_reused_pid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ignoring waitpid's exit acknowledgment must reach the forbidden probe."""

    def reused_pid(_pid: int) -> bool:
        pytest.fail("confirmed child exit must not inspect a reused PID")

    monkeypatch.setattr(probe, "reap_if_child", _present)
    monkeypatch.setattr(probe, "pid_alive", reused_pid)
    assert probe.wait_for_exit(2_000_000_000, timeout=45.0)


def test_child_that_exits_between_reap_and_check_is_still_reaped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A child turning zombie after the first reap must not be left unreaped.

    Mutation proof: returning on the zombie check without reaping made this
    fail with one reap attempt; reaping before returning made it pass.
    """
    attempts: list[int] = []

    def reap(pid: int) -> bool:
        attempts.append(pid)
        return len(attempts) > 1

    monkeypatch.setattr(probe, "reap_if_child", reap)
    monkeypatch.setattr(probe, "pid_alive", _present)
    monkeypatch.setattr(probe, "pid_is_zombie", _present)
    assert probe.wait_for_exit(2_000_000_000, timeout=45.0)
    assert attempts == [2_000_000_000, 2_000_000_000]


def test_non_child_zombie_exits_without_sleeping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Removing zombie recognition must reach the forbidden wait assertion."""
    monkeypatch.setattr(probe, "pid_alive", _present)
    monkeypatch.setattr(probe, "pid_is_zombie", _present)

    def sleep(_seconds: float) -> None:
        pytest.fail("a terminated zombie must not consume the exit-wait budget")

    monkeypatch.setattr(
        probe, "time", SimpleNamespace(monotonic=lambda: 100.0, sleep=sleep)
    )
    assert probe.wait_for_exit(2_000_000_000, timeout=45.0)


def test_unconfirmed_survivor_does_not_authorize_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(probe, "pid_alive", _present)
    monkeypatch.setattr(probe, "pid_is_zombie", _absent)
    assert not probe.wait_for_exit(2_000_000_000, timeout=0.0)


def test_zombie_termination_preserves_owned_child_cleanup_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def signal_allowed(_pid: int, _signal: int) -> bool:
        return False

    monkeypatch.setattr(probe, "pid_alive", _present)
    monkeypatch.setattr(probe, "pid_is_zombie", _present)
    monkeypatch.setattr(process, "send_signal", signal_allowed)

    def sleep(_seconds: float) -> None:
        pytest.fail("the zombie consumed time reserved for owned-child cleanup")

    clock = SimpleNamespace(monotonic=lambda: 100.0, sleep=sleep)
    monkeypatch.setattr(probe, "time", clock)
    monkeypatch.setattr(process, "time", clock)

    def identity(_pid: int, *, deadline: float) -> None:
        assert deadline == 145.0

    deadlines: list[float] = []

    def cleanup(_identity: QdrantIdentity | None, *, deadline: float) -> None:
        deadlines.append(deadline)

    monkeypatch.setattr(process, "_owned_qdrant_identity", identity)
    monkeypatch.setattr(process, "_reap_owned_qdrant", cleanup)
    result = process._terminate_pid(2_000_000_000, timeout=45.0, graceful_drain=20.0)
    assert not result.alive
    assert not result.signal_denied
    assert deadlines == [145.0]
