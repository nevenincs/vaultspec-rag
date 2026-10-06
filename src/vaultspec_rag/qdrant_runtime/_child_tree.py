"""Ending a supervised server together with every process it started.

The supervisor's child is whatever file the binary settings name. The pinned
release is one process. An operator's binary may be a launcher whose real
server is a process the launcher starts, and ending the launcher alone leaves
that server holding the port and the store while every surface reports it
stopped. So the unit that is ended is the tree.

Windows
    The child is assigned to a job, and what it starts joins that job, so the
    tree is the job's membership. Nothing asks a console-less process to stop,
    so ending it is a termination, as it always was for the child alone.

Elsewhere
    The child is started in a session of its own, which makes it the leader of
    a process group named by its pid, and what it starts stays in that group.
    The group is asked to stop, then killed.

    A group is signalled by number, and a number can be given to another
    process once the last member of the group is gone and the leader has been
    reaped. So the leader is never reaped until its group has been dealt with:
    its exit is observed without releasing its pid, and while that pid is held
    the group's number cannot belong to anything else. Every signal here is
    sent inside that window.
"""

from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import time
from typing import TYPE_CHECKING, cast

from .._process_probe import (
    iter_process_info,
    pid_alive,
    pid_is_zombie,
    send_group_signal,
)
from .._win32 import job_member_count, terminate_job

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["end_tree", "exited"]

logger = logging.getLogger(__name__)

#: How long a killed tree is given to disappear before it is reported as
#: still running. A kill cannot be refused, so this bounds the operating
#: system's own bookkeeping, not a process's cooperation.
_KILL_CONFIRM_SECONDS = 5.0

#: How long a terminated job is given to take the child down with it before
#: the child is terminated directly. Termination through a job is immediate,
#: so a child still running after this was never a member.
_JOB_GRACE_SECONDS = 2.0

_POLL_SECONDS = 0.05


def exited(proc: subprocess.Popen[bytes]) -> bool:
    """Return whether *proc* has exited, without releasing its pid.

    The liveness question the supervisor asks between a spawn and a stop. On
    POSIX an ordinary poll would reap the child, and its group could then no
    longer be signalled safely; see the module docstring.
    """
    if proc.returncode is not None:
        return True
    if sys.platform == "win32":
        # The process handle keeps the pid from being reused, and a job is
        # addressed by handle, so reaping costs nothing here.
        return proc.poll() is not None
    try:
        status = os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
    except ChildProcessError:
        return True
    return status is not None


def end_tree(proc: subprocess.Popen[bytes], job: int | None, *, timeout: float) -> bool:
    """End *proc* and everything it started; return whether all of it is gone.

    Safe to call for a child that has already exited: what it left running is
    ended the same way.

    Args:
        proc: The supervised child.
        job: The Windows job the child was assigned to, or ``None``.
        timeout: Seconds the tree is given to stop when asked, before it is
            killed.
    """
    if sys.platform == "win32":
        return _end_job(proc, job, timeout=timeout)
    return _end_group(proc, timeout=timeout)


def _exits_within(proc: subprocess.Popen[bytes], seconds: float) -> bool:
    """Wait up to *seconds* for *proc* to exit; return whether it did."""
    try:
        proc.wait(timeout=seconds)
    except subprocess.TimeoutExpired:
        return False
    return True


def _end_job(proc: subprocess.Popen[bytes], job: int | None, *, timeout: float) -> bool:
    """End the job's members, the child directly if it never joined, and confirm.

    The child is not terminated a second time when the job took it. A process
    that is already dying refuses another termination, and the standard
    library then records its exit code at once, before the process is gone,
    so the wait that follows returns while the server still holds its port
    and its store. For the same reason the end is confirmed on the process
    itself and not on the exit code recorded for it.
    """
    taken = terminate_job(job, purpose="qdrant") and _exits_within(
        proc, _JOB_GRACE_SECONDS
    )
    if not taken and proc.poll() is None:
        try:
            proc.terminate()
        except OSError as exc:
            logger.debug("qdrant terminate failed: %s", exc)
    if not _exits_within(proc, timeout):
        logger.error("qdrant pid=%d survived termination", proc.pid)
        return False

    def gone() -> bool:
        # The open process handle keeps the pid from being reused, so this
        # asks about the child and nothing else. An unreadable count is the
        # job that could not be created or joined: the child alone was the
        # tree that could be governed.
        return not pid_alive(proc.pid) and job_member_count(job) in {0, None}

    if _holds_within(gone, _KILL_CONFIRM_SECONDS):
        return True
    logger.error("qdrant pid=%d or a process it started survived termination", proc.pid)
    return False


def _other_members(group: int) -> list[int] | None:
    """Return the live processes in *group* other than its leader.

    Asked only while the leader's pid is held, so every process found is one
    the leader's tree started. ``None`` when the process table could not be
    read, which is not the same as finding nobody.
    """
    if sys.platform == "win32":
        return []
    members: list[int] = []
    try:
        for info in iter_process_info(["pid"]):
            pid = cast("int", info["pid"])
            if pid == group:
                continue
            try:
                if os.getpgid(pid) != group:
                    continue
            except OSError:
                continue
            if not pid_is_zombie(pid):
                members.append(pid)
    except OSError as exc:
        logger.debug("process group %d could not be listed: %s", group, exc)
        return None
    return members


def _holds_within(check: Callable[[], bool], seconds: float) -> bool:
    """Poll *check* until it holds or *seconds* pass; return its last answer."""
    deadline = time.monotonic() + seconds
    while not check():
        if time.monotonic() >= deadline:
            return False
        time.sleep(_POLL_SECONDS)
    return True


def _end_group(proc: subprocess.Popen[bytes], *, timeout: float) -> bool:
    """Ask the child's process group to stop, kill what remains, then reap."""
    if sys.platform == "win32":
        return False
    if proc.returncode is not None:
        # Reaped by an earlier call, which dealt with the group before it
        # released the pid. The number may be someone else's by now.
        return True
    group = proc.pid

    def settled() -> bool:
        # A group that cannot be listed is not known to be empty.
        return exited(proc) and _other_members(group) == []

    # Sent whether or not the leader still runs: one that already exited may
    # have left a server behind, and that server has not been asked yet.
    send_group_signal(group, signal.SIGTERM)
    if not _holds_within(settled, timeout):
        logger.warning(
            "qdrant pid=%d or a process it started did not stop in %.0fs; killing",
            proc.pid,
            timeout,
        )
        send_group_signal(group, signal.SIGKILL)
        _holds_within(settled, _KILL_CONFIRM_SECONDS)
    if not exited(proc):
        logger.error("qdrant pid=%d survived kill", proc.pid)
        return False
    survivors = _other_members(group)
    # The pid is released only here, after the last signal to its group.
    proc.wait()
    if survivors is None:
        # Reached only after the group was killed, which no member can
        # refuse, so what could not be listed has been ended all the same.
        logger.warning(
            "the processes started by qdrant pid=%d could not be listed after "
            "its process group was killed",
            proc.pid,
        )
        return True
    if survivors:
        logger.error(
            "processes started by qdrant pid=%d survived kill: %s",
            proc.pid,
            ", ".join(str(pid) for pid in survivors),
        )
        return False
    return True
