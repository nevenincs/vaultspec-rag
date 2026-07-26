"""Win32 process-creation flags and the kill-on-close Job Object primitives.

These are values and calls from the Windows API (``processthreadsapi.h``,
``jobapi2.h``), not project policy. ``subprocess`` defines the same numbers, but
only on Windows: importing them at module scope would break every POSIX import
of the modules that need them, so they are restated here once as ordinary ints
that any platform can import and that the win32-only branches then use.

Restated *once*. Two spawn sites - the detached daemon and the supervised
Qdrant child - previously carried their own copies of the same two flags, which
is a transcription risk with no upside: a Win32 flag is a single wrong hex digit
away from meaning something else entirely, and a wrong `creationflags` value
fails as strange process behaviour rather than as an error anyone can read.

The flags a call site combines remain that call site's decision, and the two
differ deliberately: the daemon breaks away from the launching shell's Job
Object so it survives the shell, while the Qdrant child must stay inside the
daemon's Job Object because that membership is the no-orphan guarantee.

The kill-on-close job itself lives here for the same reason the flags do. It is
the only no-orphan guarantee Windows enforces without a live supervisor: the
kernel destroys every member the moment the last job handle closes, so it holds
through a hard kill of the owning process, where an atexit hook, a fixture
teardown, or a watchdog thread all lose. Two owners need exactly that - the
daemon over its Qdrant child, and a pytest run over the daemons it spawns - and
a second transcription of these structures is the same wrong-hex-digit risk the
flags were consolidated to remove.
"""

from __future__ import annotations

import ctypes
import logging
import sys
from typing import Final

logger = logging.getLogger(__name__)

__all__ = [
    "WIN_CREATE_BREAKAWAY_FROM_JOB",
    "WIN_CREATE_NEW_PROCESS_GROUP",
    "WIN_CREATE_NO_WINDOW",
    "WIN_DETACHED_PROCESS",
    "assign_process_to_job",
    "create_kill_on_close_job",
]

#: New process group: the child does not receive the parent console's CTRL_C.
WIN_CREATE_NEW_PROCESS_GROUP: Final = 0x00000200

#: No console window is allocated for the child.
WIN_CREATE_NO_WINDOW: Final = 0x08000000

#: Detach from the launching shell's Job Object so the child outlives the
#: shell. Restricted Job Objects may deny this, which callers must handle.
WIN_CREATE_BREAKAWAY_FROM_JOB: Final = 0x01000000

#: Sever the child's console association entirely.
WIN_DETACHED_PROCESS: Final = 0x00000008

#: Job Object constants (``winnt.h``).
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE: Final = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION: Final = 9


def create_kill_on_close_job(*, purpose: str) -> int | None:
    """Create a Job Object that kills its members when its last handle closes.

    The returned handle IS the guarantee, so the caller must hold it for as
    long as the members should live and must never close it early. Letting it
    be reclaimed at process exit is the intended shape: that is precisely the
    event that should take the members down.

    Returns the handle, or ``None`` off-Windows or when the OS refuses. A
    refusal is logged and returned rather than raised, because every caller has
    a weaker fallback (a supervisor, a fixture teardown) and losing the strong
    guarantee must not also lose the work it was guarding.
    """
    if sys.platform != "win32":
        return None
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32

    class _IoCounters(ctypes.Structure):
        _fields_ = [
            ("ReadOperationCount", ctypes.c_uint64),
            ("WriteOperationCount", ctypes.c_uint64),
            ("OtherOperationCount", ctypes.c_uint64),
            ("ReadTransferCount", ctypes.c_uint64),
            ("WriteTransferCount", ctypes.c_uint64),
            ("OtherTransferCount", ctypes.c_uint64),
        ]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
            ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        logger.warning("CreateJobObjectW failed; %s orphan guard disabled", purpose)
        return None
    info = _ExtendedLimits()
    info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if not kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
    ):
        logger.warning(
            "SetInformationJobObject failed; %s orphan guard disabled", purpose
        )
        kernel32.CloseHandle(job)
        return None
    return int(job)


def assign_process_to_job(
    job: int | None, process_handle: int, pid: int, *, purpose: str
) -> bool:
    """Make the process behind *process_handle* a member of *job*.

    Takes a raw handle rather than a ``Popen`` so a caller that discovered its
    target (and opened it with ``PROCESS_SET_QUOTA | PROCESS_TERMINATE``) uses
    the same implementation as one that spawned it. Returns whether membership
    was established; a failure is logged at error level naming the guarantee
    that was lost, never raised.
    """
    if sys.platform != "win32" or job is None:
        return False
    if ctypes.windll.kernel32.AssignProcessToJobObject(job, process_handle):
        return True
    logger.error(
        "AssignProcessToJobObject failed for %s pid %d; the kill-on-close "
        "orphan guard is DISABLED for this process, which may outlive its owner",
        purpose,
        pid,
    )
    return False
