"""Lifetime watchdog for the stdio MCP shim.

The stdio transport's protocol-blessed exit path is stdin EOF, but agent
clients on Windows routinely abandon a shim generation while staying alive,
or "terminate" it by killing only the direct child ``uv.exe`` - the worker's
inherited stdin pipe survives both, EOF never arrives, and the blocked anyio
stdin reader (a non-daemon thread) cannot be cancelled in-process. The only
reliable backstop is to notice that the process chain above us broke and
hard-exit.

This module discovers the shim's ancestor chain at startup, takes
``SYNCHRONIZE`` handles immediately (a handle taken while the ancestor is
alive stays valid across PID reuse), and arms a watchdog thread that treats
any watched ancestor's death as termination intent. It must stay
stdlib-only and must never import ``mcp``, torch, or the store: the shim is
a thin service client, and this watchdog also guards nothing in HTTP daemon
mode, where outliving the spawner is by design.

One deliberate blind spot: ancestors that die during the startup grace
window are pruned as transient spawn helpers, so a client that crashes
within those first seconds can empty the survivor set and disarm the
backstop for the process lifetime (stdin EOF remains). The
empty-survivors disarm is that accepted trade-off, not a bug.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

from ..config import EnvVar

logger = logging.getLogger("vaultspec_rag.server")

STDIO_WATCHDOG_ENV = EnvVar.STDIO_WATCHDOG.value

#: Ancestors beyond this depth are noise (session managers, init); the
#: spawning client is always within a few hops (client -> uv -> launcher).
_MAX_ANCESTOR_DEPTH = 8

#: Seconds before the watchdog arms. Transient spawn helpers (``cmd /c``
#: wrappers) exit within moments of spawning the chain; ancestors that die
#: during the grace window are dropped instead of treated as termination.
_GRACE_SECONDS = 10.0

#: Coarse POSIX reparent-poll interval; the backstop does not need to be
#: fast, only eventual.
_POSIX_POLL_SECONDS = 15.0


def watchdog_disabled() -> bool:
    """True when the operator escape hatch disables the watchdog."""
    return os.environ.get(STDIO_WATCHDOG_ENV, "").strip().lower() in {
        "0",
        "false",
        "off",
        "no",
    }


def _walk_ancestor_pids(
    start_pid: int,
    parents: dict[int, int],
    max_depth: int = _MAX_ANCESTOR_DEPTH,
) -> list[int]:
    """Ancestor PIDs of ``start_pid``, nearest first, bounded and cycle-safe.

    ``parents`` maps pid -> parent pid as observed in one snapshot. The walk
    stops at the depth bound, at a missing entry, at pid 0/self-parenting,
    and at any pid already seen (snapshot cycles happen when PIDs were
    reused between rows).
    """
    chain: list[int] = []
    seen: set[int] = {start_pid}
    pid = start_pid
    for _ in range(max_depth):
        ppid = parents.get(pid)
        if ppid is None or ppid == 0 or ppid == pid or ppid in seen:
            break
        chain.append(ppid)
        seen.add(ppid)
        pid = ppid
    return chain


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _TH32CS_SNAPPROCESS = 0x00000002
    _SYNCHRONIZE = 0x00100000
    _PROCESS_QUERY_LIMITED_INFORMATION = 0x00001000
    _INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_TIMEOUT = 0x00000102
    _INFINITE = 0xFFFFFFFF

    class _PROCESSENTRY32(ctypes.Structure):
        _fields_ = (
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        )

    class _FILETIME(ctypes.Structure):
        _fields_ = (
            ("dwLowDateTime", wintypes.DWORD),
            ("dwHighDateTime", wintypes.DWORD),
        )

    # Undeclared ctypes signatures fail SILENTLY (a watchdog that waits on
    # garbage never fires), so every binding declares argtypes and restype.
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.CreateToolhelp32Snapshot.argtypes = (wintypes.DWORD, wintypes.DWORD)
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32First.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESSENTRY32),
    )
    _kernel32.Process32First.restype = wintypes.BOOL
    _kernel32.Process32Next.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_PROCESSENTRY32),
    )
    _kernel32.Process32Next.restype = wintypes.BOOL
    _kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.GetProcessTimes.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME),
    )
    _kernel32.GetProcessTimes.restype = wintypes.BOOL
    _kernel32.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _kernel32.WaitForSingleObject.restype = wintypes.DWORD
    _kernel32.WaitForMultipleObjects.argtypes = (
        wintypes.DWORD,
        ctypes.POINTER(wintypes.HANDLE),
        wintypes.BOOL,
        wintypes.DWORD,
    )
    _kernel32.WaitForMultipleObjects.restype = wintypes.DWORD

    class WatchedAncestor:
        """An ancestor process we hold a SYNCHRONIZE handle on."""

        __slots__ = ("exe", "handle", "pid")

        def __init__(self, pid: int, exe: str, handle: int) -> None:
            self.pid = pid
            self.exe = exe
            self.handle = handle

    def _snapshot_processes() -> tuple[dict[int, int], dict[int, str]]:
        """One Toolhelp32 pass: pid -> ppid and pid -> exe name."""
        snap = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if snap is None or snap == _INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        parents: dict[int, int] = {}
        names: dict[int, str] = {}
        try:
            entry = _PROCESSENTRY32()
            entry.dwSize = ctypes.sizeof(_PROCESSENTRY32)
            ok = bool(_kernel32.Process32First(snap, ctypes.byref(entry)))
            while ok:
                pid = int(entry.th32ProcessID)
                parents[pid] = int(entry.th32ParentProcessID)
                names[pid] = entry.szExeFile.decode(errors="replace")
                ok = bool(_kernel32.Process32Next(snap, ctypes.byref(entry)))
        finally:
            _kernel32.CloseHandle(snap)
        return parents, names

    def _creation_time(handle: int) -> int:
        """Process creation time as a FILETIME integer; 0 when unreadable."""
        created = _FILETIME()
        exited = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        ok = _kernel32.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        )
        if not ok:
            return 0
        return (int(created.dwHighDateTime) << 32) | int(created.dwLowDateTime)

    def _open_process(pid: int) -> int | None:
        handle = _kernel32.OpenProcess(
            _SYNCHRONIZE | _PROCESS_QUERY_LIMITED_INFORMATION, False, pid
        )
        return int(handle) if handle else None

    def open_ancestor_handles(
        extra_pids: tuple[int, ...] = (),
    ) -> list[WatchedAncestor]:
        """SYNCHRONIZE handles on the live ancestor chain, PID-reuse safe.

        Walks the snapshot parent chain from this process, opening each
        ancestor's handle immediately and enforcing creation-time
        monotonicity: a genuine ancestor existed before its child, so a
        "parent" younger than the child is a reused PID and ends the walk.
        ``extra_pids`` (an explicit ``--parent-pid`` override) are watched
        ahead of discovery when alive.
        """
        watched: list[WatchedAncestor] = []
        parents, names = _snapshot_processes()
        for pid in extra_pids:
            handle = _open_process(pid)
            if handle is None:
                logger.warning(
                    "stdio watchdog: explicit parent pid %d not watchable", pid
                )
                continue
            watched.append(WatchedAncestor(pid, names.get(pid, "?"), handle))
        my_handle = _open_process(os.getpid())
        child_ctime = _creation_time(my_handle) if my_handle is not None else 0
        if my_handle is not None:
            _kernel32.CloseHandle(my_handle)
        already = {ancestor.pid for ancestor in watched}
        for pid in _walk_ancestor_pids(os.getpid(), parents):
            handle = _open_process(pid)
            if handle is None:
                break
            ancestor_ctime = _creation_time(handle)
            if child_ctime and (ancestor_ctime == 0 or ancestor_ctime > child_ctime):
                _kernel32.CloseHandle(handle)
                break
            if pid in already:
                _kernel32.CloseHandle(handle)
                continue
            watched.append(WatchedAncestor(pid, names.get(pid, "?"), handle))
            child_ctime = ancestor_ctime
        return watched

    def _windows_watchdog(watched: list[WatchedAncestor], grace_seconds: float) -> None:
        """Grace-prune, then wait-any on the survivors; hard-exit on death.

        Runs on a daemon thread. Ancestors that die during the grace window
        are transient spawn helpers, not termination intent, and are
        dropped. A failed wait disarms the backstop (stdin EOF remains)
        rather than killing a live session.
        """
        time.sleep(grace_seconds)
        survivors: list[WatchedAncestor] = []
        for ancestor in watched:
            if _kernel32.WaitForSingleObject(ancestor.handle, 0) == _WAIT_TIMEOUT:
                survivors.append(ancestor)
            else:
                _kernel32.CloseHandle(ancestor.handle)
                logger.info(
                    "stdio watchdog: dropping ancestor %d (%s) gone during grace",
                    ancestor.pid,
                    ancestor.exe,
                )
        if not survivors:
            logger.warning(
                "stdio watchdog: no ancestors survived the grace window; "
                "backstop disarmed, stdin EOF is the only exit path"
            )
            return
        handles = (wintypes.HANDLE * len(survivors))(
            *[ancestor.handle for ancestor in survivors]
        )
        result = int(
            _kernel32.WaitForMultipleObjects(len(survivors), handles, False, _INFINITE)
        )
        index = result - _WAIT_OBJECT_0
        if not 0 <= index < len(survivors):
            logger.error(
                "stdio watchdog: wait failed (result 0x%x, error %d); "
                "backstop disarmed, stdin EOF is the only exit path",
                result,
                ctypes.get_last_error(),
            )
            for ancestor in survivors:
                _kernel32.CloseHandle(ancestor.handle)
            return
        _exit_on_ancestor_death(survivors[index].pid, survivors[index].exe)


def _exit_on_ancestor_death(pid: int, exe: str) -> None:
    """Log one structured line and hard-exit.

    ``os._exit`` is deliberate: the anyio stdin reader blocks a non-daemon
    thread that nothing in-process can cancel, so a graceful shutdown can
    hang forever. Exit code 0 because self-reaping after the spawning chain
    broke is the intended outcome, not a crash a broker should retry.
    """
    print(
        json.dumps(
            {
                "event": "stdio_watchdog_exit",
                "dead_ancestor_pid": pid,
                "dead_ancestor_exe": exe,
                "shim_pid": os.getpid(),
            }
        ),
        file=sys.stderr,
        flush=True,
    )
    os._exit(0)


def _posix_watchdog(initial_ppid: int, extra_pids: tuple[int, ...]) -> None:
    """Coarse reparent poll: exit when orphaned or an explicit pid dies."""
    while True:
        time.sleep(_POSIX_POLL_SECONDS)
        ppid = os.getppid()
        if ppid != initial_ppid:
            _exit_on_ancestor_death(initial_ppid, "parent")
        for pid in extra_pids:
            if not _pid_alive(pid):
                _exit_on_ancestor_death(pid, "explicit-parent")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        logger.exception("stdio watchdog: liveness probe failed for pid %d", pid)
        return True
    return True


def install_stdio_lifetime_watchdog(
    parent_pid: int | None = None,
    grace_seconds: float = _GRACE_SECONDS,
) -> threading.Thread | None:
    """Arm the lifetime backstop for the stdio shim; returns its thread.

    Never raises: a watchdog that cannot install must not take down a shim
    whose stdin EOF path still works. Returns ``None`` when disabled via
    ``VAULTSPEC_RAG_STDIO_WATCHDOG`` or when installation failed.
    """
    if watchdog_disabled():
        logger.info(
            "stdio watchdog disabled via %s; stdin EOF is the only exit path",
            STDIO_WATCHDOG_ENV,
        )
        return None
    extra_pids = (parent_pid,) if parent_pid is not None else ()
    try:
        if sys.platform == "win32":
            watched = open_ancestor_handles(extra_pids)
            if not watched:
                logger.warning(
                    "stdio watchdog: no watchable ancestors; "
                    "backstop disarmed, stdin EOF is the only exit path"
                )
                return None
            logger.info(
                "stdio watchdog armed on ancestors: %s",
                ", ".join(f"{a.pid}({a.exe})" for a in watched),
            )
            thread = threading.Thread(
                target=_windows_watchdog,
                args=(watched, grace_seconds),
                name="stdio-lifetime-watchdog",
                daemon=True,
            )
            try:
                thread.start()
            except Exception:
                for ancestor in watched:
                    _kernel32.CloseHandle(ancestor.handle)
                raise
        else:
            thread = threading.Thread(
                target=_posix_watchdog,
                args=(os.getppid(), extra_pids),
                name="stdio-lifetime-watchdog",
                daemon=True,
            )
            thread.start()
    except Exception:
        logger.exception(
            "stdio watchdog failed to install; stdin EOF is the only exit path"
        )
        return None
    return thread
