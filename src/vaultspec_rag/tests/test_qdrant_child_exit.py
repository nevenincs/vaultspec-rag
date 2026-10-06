"""The supervisor's liveness question, asked of a real child.

Between a spawn and a stop the supervisor asks only whether its child has
exited. Where the platform allows it, the answer is read without collecting
the child's exit status, because a collected child's pid can be given to
another process and the child's process group is signalled by that number.
Where it does not, the answer is read by collecting the status, and the stop
gives up signalling the group from then on.

Which of the two a platform gets is decided by what its ``os`` module offers.
Windows offers no such wait and holds the pid by handle instead, so the cases
that run there exercise the collecting read.

MUTATION PROOF, run on Windows in one uninterrupted sequence and restored:
with the collecting read inverted to ``proc.poll() is None`` on the Windows
branch, ``test_a_running_child_has_not_exited_and_an_ended_one_has`` fails on
``assert not exited(child)``; restoring it passes. The case that collects an
exit status after observing it runs only where the status can be left
uncollected, and has not been run on Windows.
"""

from __future__ import annotations

import subprocess
import sys
import time

import pytest

from .._process_probe import kill_child_tree
from ..qdrant_runtime._child_tree import _exit_is_peekable, exited

pytestmark = [pytest.mark.unit]


def _child(script: str) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _exits_within(child: subprocess.Popen[bytes], seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while not exited(child):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def test_a_running_child_has_not_exited_and_an_ended_one_has() -> None:
    child = _child("import time; time.sleep(30)")
    try:
        assert not exited(child), "a child that is still sleeping read as exited"

        child.kill()

        assert _exits_within(child, 30.0), "a killed child never read as exited"
    finally:
        kill_child_tree(child, confirm_seconds=10.0)


@pytest.mark.skipif(
    not _exit_is_peekable(),
    reason="an exit is learned here by collecting it, so nothing is left to collect",
)
def test_observing_an_exit_leaves_its_status_to_be_collected() -> None:
    """The exit is seen, and the child is still this process's to wait for.

    A wait that reported the exit and collected it anyway would leave nothing
    behind: the collecting wait below would find no child, and the standard
    library records that as an exit status of zero.
    """
    child = _child("raise SystemExit(7)")
    try:
        assert _exits_within(child, 30.0), "premise: the child has exited"
        # Asked again: an observation that collected would not answer twice
        # from the child itself.
        assert exited(child)
        assert child.returncode is None, "observing the exit collected it"

        assert child.wait(timeout=10.0) == 7
    finally:
        kill_child_tree(child, confirm_seconds=10.0)
