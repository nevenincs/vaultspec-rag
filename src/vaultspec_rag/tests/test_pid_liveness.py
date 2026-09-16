"""Liveness must separate "cannot open" from "does not exist".

On Windows ``OpenProcess`` returns a null handle for two opposite facts: a pid
nothing occupies, and a pid occupied by a process running at a privilege the
caller cannot open. Reading both as dead reports a live higher-privilege
daemon dead, and callers that delete state only for a confirmed-dead holder
then destroy a running service's discovery file.

These bind to real processes rather than a substituted ``OpenProcess``,
because a fake returns whichever handle the fake was told to return and would
pass against the very conflation this guards.

MUTATION PROOF, run in one uninterrupted sequence: replacing the
``GetLastError`` comparison in ``_process_probe.py:pid_alive`` with a
bare ``return False`` - the behaviour before this guard existed - fails
``test_a_process_we_cannot_open_counts_as_alive`` on its own
``assert pid_alive(...) is True``, and fails nothing else in this file;
restoring the comparison turns all six green again. Re-run that mutation
before loosening any assertion here, because a guard that cannot fail is
worse than no guard.
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys

import pytest

from .._process_probe import pid_alive

pytestmark = [pytest.mark.unit]

#: The Windows kernel object every session hosts, owned by the kernel and
#: never openable by an ordinary user token. A stable real subject for the
#: access-denied branch that needs no privileged setup of its own.
_SYSTEM_PID = 4

_ERROR_ACCESS_DENIED = 5
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def _open_process_last_error(pid: int) -> int | None:
    """Return the error code ``OpenProcess`` sets for *pid*, or None if it opened."""
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if handle:
        kernel32.CloseHandle(handle)
        return None
    return int(kernel32.GetLastError())


@pytest.mark.skipif(sys.platform != "win32", reason="OpenProcess is Windows-only")
class TestWindowsLiveness:
    """The access-denied branch, against processes that really exist."""

    def test_a_process_we_cannot_open_counts_as_alive(self) -> None:
        """A live process at a privilege we cannot open is alive, not dead.

        This is the whole defect: the service daemon runs at a privilege the
        querying CLI cannot open, so conflating the two null-handle causes
        reported a running daemon dead and let its discovery file be deleted.
        """
        observed = _open_process_last_error(_SYSTEM_PID)
        if observed != _ERROR_ACCESS_DENIED:
            # An elevated runner can open pid 4, which removes the condition
            # under test. Skipping is honest; passing here would prove nothing.
            pytest.skip(
                f"pid {_SYSTEM_PID} is openable here (last error {observed}), "
                "so the access-denied branch is not reachable in this session",
            )
        assert pid_alive(_SYSTEM_PID) is True

    def test_an_unoccupied_pid_counts_as_dead(self) -> None:
        """A pid nothing occupies stays dead, so the fix is not "always alive"."""
        child = subprocess.Popen(
            [sys.executable, "-c", "pass"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        child.wait(timeout=60)
        reaped = child.pid
        assert _open_process_last_error(reaped) != _ERROR_ACCESS_DENIED, (
            "the exited child is still openable, so it is not a dead-pid subject"
        )
        assert pid_alive(reaped) is False


@pytest.mark.skipif(sys.platform == "win32", reason="os.kill signalling is POSIX")
class TestPosixLiveness:
    """The same conflation, in POSIX spelling.

    ``os.kill(pid, 0)`` raises ``PermissionError`` for a process that exists
    but belongs to another user, and ``ProcessLookupError`` for one that does
    not exist. Reading the first as dead is the same defect the Windows class
    above guards, and left untested on this side the rule could be right on
    one platform and wrong on the other - which is exactly how the original
    bug survived two implementations.
    """

    def test_a_process_we_cannot_signal_counts_as_alive(self) -> None:
        # pid 1 exists for the life of the host and is not this user's to
        # signal, so it is the POSIX twin of the Windows system process.
        try:
            os.kill(1, 0)
        except PermissionError:
            pass
        except ProcessLookupError:  # pragma: no cover - namespace without init
            pytest.skip("pid 1 is absent here, so there is no unsignallable subject")
        else:
            # A root session may signal pid 1, which removes the condition
            # under test. Skipping is honest; passing here would prove nothing.
            pytest.skip(
                "pid 1 is signallable in this session, so the permission "
                "branch is not reachable"
            )
        assert pid_alive(1) is True


class TestLivenessEverywhere:
    """Platform-independent expectations."""

    def test_our_own_process_counts_as_alive(self) -> None:
        assert pid_alive(os.getpid()) is True

    @pytest.mark.parametrize("pid", [0, -1])
    def test_a_non_positive_pid_counts_as_dead(self, pid: int) -> None:
        assert pid_alive(pid) is False

    def test_an_unassigned_pid_counts_as_dead(self) -> None:
        """A positive pid no process holds is dead, not merely unopenable."""
        assert pid_alive(99999999) is False


def test_service_liveness_has_no_second_implementation() -> None:
    """The CLI calls the one liveness function, under its own name.

    A second copy is what let the access-denied rule be right on one path and
    wrong on the other for the whole time the defect was live. The CLI used to
    bind ``_is_pid_alive = pid_alive`` and route every caller through the
    package attribute, so a second body could be introduced under the old name
    without a single caller changing. Nothing ever substituted that seam, so
    it bought no testability and carried that risk for free.
    """
    from ..cli import _process

    assert _process.pid_alive is pid_alive
    assert not hasattr(_process, "_is_pid_alive")
