"""Lifetime watchdog for the stdio MCP shim.

The stdio transport's protocol-blessed exit path is stdin EOF, but agent
clients on Windows routinely abandon a shim generation while staying alive,
or "terminate" it by killing only the direct child ``uv.exe`` - the worker's
inherited stdin pipe survives both, EOF never arrives, and the blocked anyio
stdin reader (a non-daemon thread) cannot be cancelled in-process. The only
reliable backstop is to notice that the process chain above us broke and
hard-exit.

This module anchors the shim's lifetime through layered anchors, matching
the companion vaultspec-core watchdog so both servers behave identically:
the primary anchor resolves the stdin pipe creator (the exact client at any
wrapper depth) and is never grace-pruned, so an already-dead client reaps
the shim at arm time; the discovered ancestor chain (handles taken at
startup so PID reuse cannot retarget the wait, creation-time monotonicity,
a grace window dropping transient spawn helpers) arms only when no client
resolves. The module must stay stdlib-only and must never import ``mcp``,
torch, or the store: the shim is a thin service client, and this watchdog
guards nothing in HTTP daemon mode, where outliving the spawner is by
design.

One deliberate blind spot remains in the FALLBACK shape only: discovered
ancestors that die during the startup grace window are pruned as transient
spawn helpers, so with no resolvable client an entire chain dying inside
the grace disarms the backstop (stdin EOF remains). Precise anchors are
exempt from pruning, so the common pipe-spawned case has no such window.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

from .._process_probe import pid_alive
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
    _kernel32.GetNamedPipeServerProcessId.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    _kernel32.GetNamedPipeServerProcessId.restype = wintypes.BOOL
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
        """A process we hold a SYNCHRONIZE handle on.

        ``grace_prunable`` separates the two anchor precisions: discovered
        ancestors may be transient spawn helpers and are dropped when they
        die inside the grace window; precise anchors (the resolved stdin
        pipe creator, an explicit ``--parent-pid``) signal exit immediately,
        so an already-dead client reaps the shim at arm time instead of
        silently disarming the backstop.
        """

        __slots__ = ("exe", "grace_prunable", "handle", "pid")

        def __init__(
            self, pid: int, exe: str, handle: int, *, grace_prunable: bool = True
        ) -> None:
            self.pid = pid
            self.exe = exe
            self.handle = handle
            self.grace_prunable = grace_prunable

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

    def resolve_stdin_client_pid() -> int | None:
        """Resolve the PID of the process that created this process's stdin pipe.

        Anonymous pipes are named pipes under the hood on Windows, so
        ``GetNamedPipeServerProcessId`` on the inherited stdin handle yields
        the pipe-creating process: the MCP client itself, regardless of how
        many wrapper processes (``uv``, venv launchers) sit in between.

        Returns:
            The client PID, or ``None`` when stdin is not a pipe (console or
            redirected-file stdin), the handle is unavailable, or the
            resolved PID is this process itself. Fails open on anything
            unexpected.
        """
        try:
            import msvcrt

            try:
                handle = msvcrt.get_osfhandle(sys.stdin.fileno())
            except OSError:
                logger.debug("stdio watchdog: no stdin OS handle")
                return None

            server_pid = ctypes.c_ulong(0)
            ok = _kernel32.GetNamedPipeServerProcessId(handle, ctypes.byref(server_pid))
            if not ok:
                logger.debug(
                    "stdio watchdog: stdin is not a pipe (error %d)",
                    ctypes.get_last_error(),
                )
                return None

            pid = int(server_pid.value)
            if pid == 0 or pid == os.getpid():
                logger.debug(
                    "stdio watchdog: pipe creator is self or unresolved (%d)", pid
                )
                return None
            return pid
        except Exception:
            logger.debug("stdio watchdog: client resolution failed", exc_info=True)
            return None

    def open_watched(pid: int, *, grace_prunable: bool) -> WatchedAncestor | None:
        """Open one explicit PID as a watched target; ``None`` when refused."""
        handle = _open_process(pid)
        if handle is None:
            logger.warning(
                "stdio watchdog: cannot open process %d (error %d)",
                pid,
                ctypes.get_last_error(),
            )
            return None
        try:
            _, names = _snapshot_processes()
            exe = names.get(pid, "?")
        except OSError:
            exe = "?"
        return WatchedAncestor(pid, exe, handle, grace_prunable=grace_prunable)

    def open_ancestor_handles() -> list[WatchedAncestor]:
        """SYNCHRONIZE handles on the live ancestor chain, PID-reuse safe.

        Walks the snapshot parent chain from this process, opening each
        ancestor's handle immediately and enforcing creation-time
        monotonicity: a genuine ancestor existed before its child, so a
        "parent" younger than the child is a reused PID and ends the walk.
        Discovered ancestors are grace-prunable; precise anchors come from
        ``open_watched`` instead.
        """
        watched: list[WatchedAncestor] = []
        parents, names = _snapshot_processes()
        my_handle = _open_process(os.getpid())
        child_ctime = _creation_time(my_handle) if my_handle is not None else 0
        if my_handle is not None:
            _kernel32.CloseHandle(my_handle)
        for pid in _walk_ancestor_pids(os.getpid(), parents):
            handle = _open_process(pid)
            if handle is None:
                break
            ancestor_ctime = _creation_time(handle)
            if child_ctime and (ancestor_ctime == 0 or ancestor_ctime > child_ctime):
                _kernel32.CloseHandle(handle)
                break
            watched.append(
                WatchedAncestor(pid, names.get(pid, "?"), handle, grace_prunable=True)
            )
            child_ctime = ancestor_ctime
        return watched

    def _gather_windows_targets(
        parent_pid: int | None, client_pid: int | None
    ) -> list[WatchedAncestor]:
        """Compose the layered anchor set for the Windows watchdog.

        Explicit override first, then the resolved stdin pipe creator (both
        precise); the discovered ancestor chain only when no client anchor
        landed - watching processes above a known client would reap a live
        session when its hosting terminal dies.
        """
        watched: list[WatchedAncestor] = []
        if parent_pid is not None:
            explicit = open_watched(parent_pid, grace_prunable=False)
            if explicit is not None:
                watched.append(explicit)
        resolved = client_pid if client_pid is not None else resolve_stdin_client_pid()
        client_watched = False
        if resolved is not None:
            if any(target.pid == resolved for target in watched):
                client_watched = True
            else:
                client = open_watched(resolved, grace_prunable=False)
                if client is not None:
                    watched.append(client)
                    client_watched = True
        if not client_watched:
            known = {target.pid for target in watched}
            for target in open_ancestor_handles():
                if target.pid in known:
                    # An explicit override on the chain: drop the duplicate
                    # without leaking its fresh handle.
                    _kernel32.CloseHandle(target.handle)
                else:
                    watched.append(target)
        return watched

    def _windows_watchdog(watched: list[WatchedAncestor], grace_seconds: float) -> None:
        """Grace-prune the prunable targets, then wait-any; hard-exit on death.

        Runs on a daemon thread. Only discovered-chain targets are grace
        prunable; the resolved client and an explicit override signal exit
        immediately, preserving the instant reap of an already-dead client.
        A failed wait disarms the backstop (stdin EOF remains) rather than
        killing a live session.
        """
        if any(ancestor.grace_prunable for ancestor in watched):
            time.sleep(grace_seconds)
        survivors: list[WatchedAncestor] = []
        for ancestor in watched:
            if not ancestor.grace_prunable:
                survivors.append(ancestor)
                continue
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
            if not pid_alive(pid):
                _exit_on_ancestor_death(pid, "explicit-parent")


def install_stdio_lifetime_watchdog(
    parent_pid: int | None = None,
    grace_seconds: float = _GRACE_SECONDS,
    client_pid: int | None = None,
) -> threading.Thread | None:
    """Arm the lifetime backstop for the stdio shim; returns its thread.

    On Windows the primary anchor is the stdin pipe creator resolved by
    ``resolve_stdin_client_pid`` (or the injected ``client_pid``) - exact
    client semantics at any wrapper depth, never grace-pruned, so an
    already-dead client reaps immediately. The discovered ancestor chain
    arms ONLY when no client resolves (console runs, exotic spawners):
    watching processes above a known client would reap a live session when
    its hosting terminal dies. An explicit ``parent_pid`` is watched ahead
    of discovery in either shape.

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
    try:
        if sys.platform == "win32":
            watched = _gather_windows_targets(parent_pid, client_pid)
            if not watched:
                logger.warning(
                    "stdio watchdog: no watchable targets; "
                    "backstop disarmed, stdin EOF is the only exit path"
                )
                return None
            logger.info(
                "stdio watchdog armed on: %s",
                ", ".join(
                    f"{a.pid}({a.exe}{'' if a.grace_prunable else ', precise'})"
                    for a in watched
                ),
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
            extra_pids = (parent_pid,) if parent_pid is not None else ()
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
