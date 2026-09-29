"""Which processes a process is running inside (real process trees, no mocks).

A lineage is only worth asking for if it names the real ancestors, in order,
and stops rather than guessing when a pid can no longer be read. Both are
proved against processes this test starts itself: a child that starts a
grandchild, where the grandchild reports its own lineage and the child and the
test process must both appear in it, nearest first.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest

from .._process_probe import LineageEntry, pid_start_time, process_lineage

pytestmark = [pytest.mark.unit]

_GRANDCHILD = (
    "import json; from vaultspec_rag._process_probe import process_lineage; "
    "print(json.dumps([[e.pid, e.start_time] for e in process_lineage()]))"
)

# The child reports its own pid before relaying the grandchild's lineage, so
# the test knows which entry must be the intermediate ancestor. On Windows a
# venv interpreter is itself started through a launcher process, so the chain
# may carry extra launcher entries between the three; order is what is proved.
_CHILD = (
    "import os, subprocess, sys; "
    "print(os.getpid(), flush=True); "
    f"subprocess.run([sys.executable, '-c', {_GRANDCHILD!r}], check=True)"
)


def _is_subsequence(needles: list[int], haystack: list[int]) -> bool:
    remaining = iter(haystack)
    return all(any(pid == needle for pid in remaining) for needle in needles)


def test_lineage_names_the_real_ancestors_nearest_first() -> None:
    output = subprocess.run(
        [sys.executable, "-c", _CHILD],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.splitlines()
    child_pid = int(output[0])
    lineage = [LineageEntry(pid, start) for pid, start in json.loads(output[1])]
    pids = [entry.pid for entry in lineage]

    assert pids[0] != child_pid, "the walk must start at the asking process"
    # The child and this test process must both be found above the grandchild,
    # in that order; a walk that stopped early, or skipped a generation, fails
    # here rather than passing on a lineage of one.
    assert _is_subsequence([child_pid, os.getpid()], pids[1:]), pids
    assert len(set(pids)) == len(pids), "a lineage never repeats a process"


def test_lineage_entries_carry_the_start_time_that_pins_each_pid() -> None:
    lineage = process_lineage()

    assert lineage[0].pid == os.getpid()
    for entry in lineage:
        assert entry.start_time > 0.0
    assert lineage[0].start_time == pid_start_time(os.getpid())


# Windows allocates pids in multiples of four and Linux caps them at 2**22, so
# this odd value above both can never name a process on either platform.
_NEVER_A_PID = 2**31 - 1


@pytest.mark.parametrize("pid", [_NEVER_A_PID, 0, -4])
def test_lineage_of_an_unreadable_pid_is_empty_not_a_guess(pid: int) -> None:
    assert process_lineage(pid) == ()
