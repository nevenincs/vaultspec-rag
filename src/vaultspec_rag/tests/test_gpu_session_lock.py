"""Guard: one GPU test session per machine, enforced across processes.

Two test sessions that each load the embedding and reranker stacks onto one card
exhaust its memory and take the host down together. Nothing else in the harness
can see that coming: a scheduling group reaches only inside one process, and
every configured singleton path is redirected into a per-session temporary tree
so sessions cannot observe each other. So the claim is an OS advisory lock on a
machine-global anchor, and these tests exercise it with real processes taking
real locks - a claim that only appears to be held proves nothing.

The claiming mechanism is driven at a temporary anchor rather than the real one,
so running this suite never reserves the machine's actual device and never
collides with a concurrent session. That the production anchor is machine-global
is a separate assertion below. The mutation each test catches is named in its
own docstring.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from typing import TYPE_CHECKING

import pytest

from .._test_isolation import (
    ManagedSingletonIsolationError,
    enforce_pytest_singleton_containment,
)
from ._gpu_session import (
    GpuSessionLease,
    acquire_gpu_session_lock,
    gpu_session_lock_path,
    gpu_session_refusal,
    release_gpu_session_lock,
)

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

pytestmark = [pytest.mark.unit]

#: Claims the anchor named in argv, reports the owning pid, and holds until its
#: input closes. Run in a real interpreter so the claim is held by a real
#: process the operating system can be observed releasing.
_HOLDER_PROGRAM = (
    "import pathlib, sys\n"
    "from vaultspec_rag.tests._gpu_session import acquire_gpu_session_lock\n"
    "lease, holder = acquire_gpu_session_lock(pathlib.Path(sys.argv[1]))\n"
    "assert lease is not None, f'anchor already claimed by {holder}'\n"
    "print(lease.pid, flush=True)\n"
    "sys.stdin.readline()\n"
)


@pytest.fixture
def anchor(tmp_path: Path) -> Iterator[Path]:
    """A private anchor, with this process holding no claim either side."""
    release_gpu_session_lock()
    try:
        yield tmp_path / "gpu-session.lock"
    finally:
        release_gpu_session_lock()


class _Holder:
    """A live process holding a claim on one anchor."""

    def __init__(self, anchor: Path) -> None:
        self._proc = subprocess.Popen(
            [sys.executable, "-c", _HOLDER_PROGRAM, str(anchor)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert self._proc.stdout is not None
        # Reading one line either yields the pid or returns empty because the
        # holder died, so this cannot wait on a process that never claimed.
        reported = self._proc.stdout.readline().strip()
        if not reported:
            _, stderr = self._proc.communicate(timeout=30)
            pytest.fail(f"the holder process never claimed the anchor: {stderr}")
        self.pid = int(reported)

    def kill(self) -> None:
        """Kill the holder without giving it any chance to release."""
        self._proc.kill()
        self._proc.wait(timeout=30)


def _claim_once_free(anchor: Path, *, timeout: float = 15.0) -> GpuSessionLease | None:
    """Claim *anchor* as soon as it is observably free, or fail at the deadline.

    A killed holder's lock is released by the kernel while the process is torn
    down, and that teardown is not finished when waiting on the process returns:
    the process object is signalled once its threads are gone, before its handle
    table is dismantled, so a claim attempted immediately can still lose to a
    holder the operating system has not finished disposing of. Retrying until
    the release is *observed* takes that off the clock entirely - no duration is
    ever assumed - while a lock that genuinely never frees still fails the test
    at the deadline instead of passing on a favourable schedule.
    """
    deadline = time.monotonic() + timeout
    while True:
        lease, _ = acquire_gpu_session_lock(anchor)
        if lease is not None:
            return lease
        if time.monotonic() >= deadline:
            return None
        time.sleep(0.01)


class TestTheAnchorIsMachineGlobal:
    """Where the claim lives decides whether it can be seen at all."""

    def test_the_anchor_escapes_the_session_containment_root(self) -> None:
        """The device is machine hardware, not per-session state.

        Asserted through the harness's own containment check rather than by
        comparing paths against an environment variable: that variable is only
        transport for child processes, any test is free to rewrite it, and a gate
        reading it would be asserting against whatever the previous test happened
        to leave there. The containment check refusing this path IS the exemption,
        stated in the harness's own terms and immune to what ran before.

        Mutation it catches: anchoring the claim through configuration, every
        value of which this harness redirects into a per-session temporary tree.
        Each session would then claim an anchor only it could see, both would be
        admitted, and both would load onto the one card.
        """
        with pytest.raises(ManagedSingletonIsolationError):
            enforce_pytest_singleton_containment(
                gpu_session_lock_path(),
                operation="claim this machine's GPU for one test session",
            )

    def test_another_process_derives_the_same_anchor(self) -> None:
        """Two sessions must derive one path or they contend on nothing.

        Mutation it catches: deriving the anchor from anything process-specific -
        a pid, a session temporary directory, a value made per run. Every
        session would claim its own file, every claim would be granted, and the
        gate would report a protection it never provided.
        """
        probe = (
            "from vaultspec_rag.tests._gpu_session import gpu_session_lock_path\n"
            "print(gpu_session_lock_path())\n"
        )

        proc = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        assert proc.stdout.strip() == str(gpu_session_lock_path())


class TestASecondSessionIsRefused:
    """The refusal is the whole point; admitting is the failure."""

    def test_a_live_holder_refuses_this_session_and_is_named(
        self, anchor: Path
    ) -> None:
        """Mutation it catches: reporting success when the claim was not taken.

        A second GPU session would proceed to load its own model stack onto a
        card already carrying one, which is the collision this claim prevents.
        The holder's pid is asserted too: an operator told only that something
        holds the device cannot act on it.
        """
        holder = _Holder(anchor)
        try:
            refusal = gpu_session_refusal(anchor)
        finally:
            holder.kill()

        assert refusal is not None
        assert "refusing to start a second GPU test session" in refusal
        assert f"process {holder.pid}" in refusal

    def test_an_unclaimed_anchor_admits_this_session(self, anchor: Path) -> None:
        """Mutation it catches: refusing unconditionally.

        That is loud on its own, but it pins the admitting direction so the
        refusal above cannot be satisfied by a gate that always refuses - which
        would make the GPU tiers unrunnable.
        """
        assert gpu_session_refusal(anchor) is None


class TestTheClaimOutlivesNothing:
    """A claim no process holds must not survive to block the next session."""

    def test_killing_the_holder_frees_the_anchor(self, anchor: Path) -> None:
        """Mutation it catches: treating the recorded pid as the authority.

        A killed session never releases anything of its own, so a claim proven
        by file contents rather than by an OS lock would strand the machine's
        GPU behind a dead process until someone deleted a file by hand.
        """
        holder = _Holder(anchor)
        holder.kill()

        lease = _claim_once_free(anchor)

        assert lease is not None
        assert lease.pid == os.getpid()

    def test_releasing_hands_the_anchor_to_the_next_session(self, anchor: Path) -> None:
        """Session teardown must not leave the machine reserved.

        Mutation it catches: releasing the claim record while leaving the OS
        lock held. The next session on this machine would be refused by a
        process that has finished with the device.
        """
        first, _ = acquire_gpu_session_lock(anchor)
        assert first is not None

        release_gpu_session_lock()

        assert gpu_session_refusal(anchor) is None

    def test_claiming_twice_reserves_one_anchor(self, anchor: Path) -> None:
        """Mutation it catches: opening a second descriptor per call.

        The extra descriptor is never released, so the claim would survive its
        own release and the anchor would stay reserved for the process lifetime.
        """
        first, _ = acquire_gpu_session_lock(anchor)
        second, _ = acquire_gpu_session_lock(anchor)

        assert first is second

        release_gpu_session_lock()

        assert gpu_session_refusal(anchor) is None
