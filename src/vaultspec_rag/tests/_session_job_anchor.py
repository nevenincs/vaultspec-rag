"""Bind a daemon this test session spawned to the lifetime of the session.

The session's startup sweep for leftover roots already exists because a run
killed externally never reaches its teardown. The daemons that run cost more
than the directory does - they hold ports, a machine lock, and the GPU - and
every mechanism that could stop them lives inside the run that just died: the
fixture teardown, the atexit backstop, any watchdog thread. So a hard-killed
run strands a daemon with nothing left to reap it, and the daemon is built to
survive exactly that: it breaks away from the launching Job Object on Windows
and calls ``start_new_session`` on POSIX, both deliberately, so it outlives the
operator's shell.

A kill-on-close Job Object is the one guarantee that does not live inside the
dying process: the kernel destroys every member when the last handle closes,
and a handle closes however the owner dies. Membership is established after the
spawn returns rather than during it, because the daemon must break away from
whatever job it was born into first - and because establishing it here keeps
the production spawn path free of any knowledge of the test session.

Every test that starts the real service therefore starts it through
:func:`spawn_anchored_service`, never through the production spawn directly.
The launcher is what joins the job: the service worker it starts watches its
launcher and exits with it.

The job handle is created on first use and then held for the run. The handle IS
the guarantee, so it is deliberately never closed: process exit closes it, which
is exactly the event that must take the daemons down.
"""

from __future__ import annotations

import os
import threading
from typing import TYPE_CHECKING, Unpack

if TYPE_CHECKING:
    from pathlib import Path

    from ..cli._process import _ServiceSpawnOptions

__all__ = ["anchor_spawned_process_to_session", "spawn_anchored_service"]

_session_process_job: int | None = None
_session_job_lock = threading.Lock()

#: ``PROCESS_SET_QUOTA | PROCESS_TERMINATE`` - the access
#: ``AssignProcessToJobObject`` requires on the target.
_PROCESS_SET_QUOTA_AND_TERMINATE = 0x0100 | 0x0001


def anchor_spawned_process_to_session(pid: int) -> bool:
    """Make *pid* a member of this session's kill-on-close job.

    Returns whether the anchor was established. ``False`` is not a failure to
    propagate - off Windows, or when the OS refuses - so callers spawn
    regardless and the fixture teardown remains the guarantee it has always
    been. POSIX has no equivalent the owner can enforce from outside the
    target: ``prctl(PDEATHSIG)`` is the child's own call and does not survive
    the ``start_new_session`` this daemon needs, so this says so rather than
    implying a containment that is not in force.
    """
    if os.name != "nt":
        return False

    from .._process_probe import win_kernel32
    from .._win32 import assign_process_to_job, create_kill_on_close_job

    global _session_process_job
    with _session_job_lock:
        if _session_process_job is None:
            _session_process_job = create_kill_on_close_job(purpose="pytest-spawned")
        job = _session_process_job
    if job is None:
        return False

    # Through the probe module's kernel32, whose OpenProcess carries the
    # pointer-sized HANDLE restype; a fresh declaration truncates the handle.
    kernel32 = win_kernel32()
    handle = kernel32.OpenProcess(_PROCESS_SET_QUOTA_AND_TERMINATE, False, pid)
    if not handle:
        return False
    try:
        return assign_process_to_job(job, int(handle), pid, purpose="pytest-spawned")
    finally:
        kernel32.CloseHandle(handle)


def spawn_anchored_service(
    port: int,
    log_path: Path,
    **options: Unpack[_ServiceSpawnOptions],
) -> int:
    """Start the real service and bind its launcher to this session's job.

    Returns the launcher pid the production spawn returns.
    """
    from ..cli._process import _spawn_service

    pid = _spawn_service(port, log_path, **options)
    anchor_spawned_process_to_session(pid)
    return pid
