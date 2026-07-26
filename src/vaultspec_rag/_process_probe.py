"""The one home for asking the OS about a process, and for signalling one.

Every liveness check, incarnation witness, image lookup, listener check,
process-table scan and termination signal in this codebase resolves here.
Before this module there were four independent liveness implementations, three
separate ``ctypes`` declarations of the same kernel32 calls, two start-time
comparisons with DIFFERENT tolerances, and two image checks using different
mechanisms. They drifted exactly as duplicated behaviour does: a blanket
``suppress(OSError)`` that hid a refused kill was fixed in the CLI copy while
the identical swallow survived in the reap copy, and the ``HANDLE`` truncation
fixed in one ``ctypes`` block stayed wrong in the others.

Two rules hold everything here together, because the whole class of bugs this
module exists to prevent comes from breaking one of them:

- **"Cannot tell" is never "no".** A process this one lacks permission to open
  still exists. Windows reports that as ``ERROR_ACCESS_DENIED`` and POSIX as
  ``EPERM``, and reading either as absence is what lets a caller delete a live
  service's state or authorise a second writer. Unknown is returned as unknown
  (``None`` / a documented fail-closed value), never as a negative fact.
- **A pid is not an identity.** Pids are recycled. Anything that kills, or that
  concludes an owner is gone, pairs the pid with its creation time.
"""

from __future__ import annotations

import contextlib
import logging
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator

logger = logging.getLogger(__name__)

__all__ = [
    "PROCESS_QUERY_LIMITED_INFORMATION",
    "START_TIME_TOLERANCE_SECONDS",
    "bounded_call",
    "iter_process_info",
    "pid_alive",
    "pid_cmdline",
    "pid_image_matches",
    "pid_image_path",
    "pid_is_zombie",
    "pid_listens_on_loopback_port",
    "pid_matches_start_time",
    "pid_start_time",
    "reap_if_child",
    "send_signal",
    "wait_for_exit",
    "win_kernel32",
]

#: ``PROCESS_QUERY_LIMITED_INFORMATION`` - the least access that answers "does
#: this pid exist and what is its image", and the only one grantable across
#: integrity levels, so a probe of a higher-privilege process fails with
#: ``ERROR_ACCESS_DENIED`` (which means alive) rather than not at all.
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

#: Two reads of one process's creation time must agree exactly; the clock is a
#: recorded property of the process, not a sample. Callers whose recorded value
#: survived a serialisation round-trip pass their own wider tolerance.
START_TIME_TOLERANCE_SECONDS = 1e-6

_ERROR_ACCESS_DENIED = 5
_STILL_ACTIVE = 259


def win_kernel32() -> Any:
    """Return ``kernel32`` with its process-handle signatures declared once.

    ``ctypes.windll.kernel32`` is a process-global cache shared by every module
    that touches it, and its function objects default to a 32-bit ``c_int``
    return. A Windows ``HANDLE`` is pointer-sized, so the default TRUNCATES it,
    and the truncated value handed back to ``GetExitCodeProcess`` or
    ``CloseHandle`` is sign-extended into a different, invalid handle: the call
    fails, a live process reads as dead, and the real kernel object leaks.
    Declaring the widths here, once, is what keeps every caller correct - the
    alternative is each site remembering, and the sites that forgot are what
    made this function necessary.
    """
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.GetExitCodeProcess.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.QueryFullProcessImageNameW.argtypes = (
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    )
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    return kernel32


def bounded_call[T](
    operation: Callable[[], T],
    *,
    timeout: float | None,
    fallback: T,
    label: str,
) -> T:
    """Run a potentially blocking local inspection inside an optional budget.

    A process-table read can stall on Windows for a protected or wedged
    process, and an enclosing deadline loop cannot interrupt a call already
    blocked mid-iteration - only a bound on the call itself can.
    """
    if timeout is None:
        return operation()
    if timeout <= 0.0:
        return fallback

    import queue
    import threading

    outcomes: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def run() -> None:
        try:
            outcomes.put((True, operation()))
        except BaseException as exc:
            outcomes.put((False, exc))

    threading.Thread(target=run, daemon=True, name=f"vaultspec-{label}").start()
    try:
        succeeded, value = outcomes.get(timeout=timeout)
    except queue.Empty:
        logger.debug("%s exceeded its %.3fs probe budget", label, timeout)
        return fallback
    if not succeeded:
        raise cast("BaseException", value)
    return cast("T", value)


def pid_alive(pid: int) -> bool:
    """Return whether *pid* is a live process (cross-platform, best-effort).

    Tells a live storage owner from a dead one when classifying an orphan, and
    a live daemon from a dead one before its discovery file is removed. A
    permission error means the process exists but is not ours to signal, which
    still counts as alive.
    """
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes

        kernel32 = win_kernel32()
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            # A null handle carries two opposite facts, and the error code is
            # the only thing that separates them. ERROR_ACCESS_DENIED means the
            # process exists and runs at a privilege this one cannot open -
            # alive, and the case the POSIX branch below already got right.
            # Every other code (ERROR_INVALID_PARAMETER for a pid nothing
            # occupies) means genuinely absent. Reading them as one reports a
            # live higher-privilege daemon dead, and callers that delete state
            # for a confirmed-dead holder then destroy a running service's.
            # GetLastError is read before any other FFI call so nothing
            # overwrites the thread's last-error value.
            return kernel32.GetLastError() == _ERROR_ACCESS_DENIED
        try:
            code = ctypes.c_ulong()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return False
            return code.value == _STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def pid_image_path(pid: int) -> str | None:
    """Return *pid*'s full executable path, or ``None`` when unreadable.

    ``None`` is genuinely "could not tell" - the process is gone, or runs at a
    privilege this process cannot open - and is never evidence about what the
    image IS. Callers deciding whether to trust or kill a pid must treat it as
    unknown, not as a mismatch.
    """
    if pid <= 0:
        return None
    if sys.platform != "win32":
        try:
            return os.readlink(f"/proc/{pid}/exe")
        except OSError as exc:
            logger.debug("image path unreadable for pid %d: %s", pid, exc)
            return None
    import ctypes
    from ctypes import wintypes

    kernel32 = win_kernel32()
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        logger.debug(
            "cannot open pid %d for image inspection: error %d",
            pid,
            kernel32.GetLastError(),
        )
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            logger.debug("image name query failed for pid %d", pid)
            return None
        return buf.value
    finally:
        kernel32.CloseHandle(handle)


def pid_cmdline(pid: int) -> str | None:
    """Return *pid*'s command line, or ``None`` when it cannot be read.

    POSIX-only in practice: Windows has no equivalent world-readable view, and
    every Windows caller wants the image path instead. ``None`` means unknown,
    never "no match".
    """
    if pid <= 0 or sys.platform == "win32":
        return None
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
    except (OSError, ValueError) as exc:
        logger.debug("cmdline unreadable for pid %d: %s", pid, exc)
        return None


def pid_image_matches(pid: int, needle: str, *, timeout: float | None = None) -> bool:
    """Return whether live *pid*'s EXECUTABLE IMAGE contains *needle*.

    The recycled-pid guard in front of every hard kill: a reap target's pid
    comes from a now-dead owner's record, and on a busy machine that pid may
    belong to something unrelated. Matching the image - never the cmdline -
    keeps a process whose argv merely mentions *needle* (a test run, an install
    command) from being killed.

    Windows consults the handle-based image path first because it is precise
    and needs no subprocess, and falls back to ``tasklist`` only when the
    handle cannot be opened: that is the access-denied case, where refusing to
    fall back would silently shrink reap coverage to processes this one can
    already open. Both mechanisms live here so they cannot drift apart.
    """
    if not pid_alive(pid):
        return False
    lowered = needle.lower()
    image = pid_image_path(pid)
    if image is not None:
        return lowered in Path(image).name.lower()
    if sys.platform != "win32":
        # The exe symlink is the authoritative image; comm (the image name,
        # world-readable) is the fallback when exe is unreadable.
        try:
            comm = Path(f"/proc/{pid}/comm").read_text(encoding="utf-8")
        except OSError:
            return False
        return lowered in comm.strip().lower()
    import subprocess

    if timeout is not None and timeout <= 0.0:
        return False
    try:
        result = subprocess.run(  # fixed argv, no shell, trusted pid
            ["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        logger.debug("image inspection for pid %d exceeded %.3fs", pid, timeout)
        return False
    return lowered in result.stdout.lower()


def pid_start_time(pid: int, *, timeout: float | None = None) -> float:
    """Return *pid*'s process creation time (epoch seconds), or ``0.0``.

    The pid-reuse witness: two processes that share a recycled pid have
    different creation times, so comparing this against a recorded value tells
    a surviving original owner from an unrelated process that inherited its
    pid. ``0.0`` means the time could not be read (no such process, or no
    permission) and the caller must not treat it as a match.
    """
    if pid <= 0:
        return 0.0

    def inspect() -> float:
        import psutil

        try:
            return float(psutil.Process(pid).create_time())
        except Exception as exc:  # psutil raises NoSuchProcess/AccessDenied/etc.
            logger.debug("could not read start time for pid %d: %s", pid, exc)
            return 0.0

    return bounded_call(
        inspect, timeout=timeout, fallback=0.0, label=f"pid-{pid}-start-time"
    )


def pid_matches_start_time(
    pid: int,
    expected_start_time: float,
    *,
    timeout: float | None = None,
    tolerance: float = START_TIME_TOLERANCE_SECONDS,
) -> bool:
    """Return whether *pid* is the exact witnessed process incarnation.

    ``tolerance`` is a parameter because callers legitimately differ: a value
    compared against a fresh read must match exactly, while one recovered from
    a persisted record has survived a serialisation round-trip. It is NOT a
    knob to loosen when a comparison fails - a mismatch means the pid was
    recycled, which is precisely what this exists to catch.
    """
    if expected_start_time <= 0.0:
        return False
    live_start = pid_start_time(pid, timeout=timeout)
    return live_start > 0.0 and abs(live_start - expected_start_time) <= tolerance


def pid_is_zombie(pid: int) -> bool:
    """Return whether *pid* is a POSIX zombie awaiting reaping.

    A zombie answers a bare liveness probe as alive despite being dead. Windows
    has no zombie state, so this is always ``False`` there.
    """
    if pid <= 0 or sys.platform == "win32":
        return False
    import psutil

    try:
        return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False
    except psutil.Error as exc:
        logger.debug("zombie check failed for pid %d: %s", pid, exc)
        return False


def pid_listens_on_loopback_port(
    pid: int,
    port: int,
    *,
    timeout: float | None = None,
) -> bool:
    """Return whether this exact process owns the loopback listening port."""
    if pid <= 0 or port <= 0:
        return False

    def inspect() -> bool:
        import psutil

        try:
            connections = psutil.Process(pid).net_connections(kind="tcp")
        except Exception as exc:
            logger.debug(
                "could not inspect TCP listener ownership for pid %d port %d: %s",
                pid,
                port,
                exc,
            )
            return False
        for connection in connections:
            if connection.status != psutil.CONN_LISTEN:
                continue
            address = connection.laddr
            if int(address.port) == port and str(address.ip) in {"127.0.0.1", "::1"}:
                return True
        return False

    return bounded_call(
        inspect, timeout=timeout, fallback=False, label=f"pid-{pid}-listener"
    )


def iter_process_info(attrs: list[str]) -> Iterator[dict[str, Any]]:
    """Yield ``psutil`` info dicts for every process this one can inspect.

    Skips the two conditions that are NORMAL while walking a live process
    table - a process exiting mid-scan, and another user's process that is not
    inspectable - and lets everything else propagate. Skipping one process is
    correct; skipping the whole scan is not, and a scan that fails silently
    returns no matches, which is indistinguishable from a clean machine.

    Raises:
        OSError: The process table could not be enumerated at all.
    """
    import psutil

    try:
        processes = list(psutil.process_iter(attrs))
    except Exception as exc:
        logger.warning("could not enumerate processes: %s", exc)
        raise OSError(f"could not enumerate processes: {exc}") from exc
    for process in processes:
        try:
            yield dict(process.info)
        except (psutil.NoSuchProcess, psutil.AccessDenied) as exc:
            logger.debug("process scan skipped a process: %s", exc)
            continue


def send_signal(pid: int, sig: int) -> bool:
    """Deliver *sig* to *pid*; return whether PERMISSION was refused.

    Separates the three ways a kill can fail to land, which a blanket
    ``suppress(OSError)`` collapses into one silent pass:

    - ``ProcessLookupError`` - the target already exited. Not a denial; the
      caller's liveness check resolves it as success.
    - ``PermissionError`` - the target runs at a privilege this process cannot
      signal (a daemon launched from an elevated shell, or owned by another
      user). Reported so the caller can say so and name the remedy.
    - any other ``OSError`` - notably a Windows ``CTRL_BREAK_EVENT`` aimed at a
      pid that leads no console group, which is expected for a
      console-detached daemon and is meant to fall through to an escalation.

    Every branch is debug-logged so a swallowed signal stays observable.
    """
    try:
        os.kill(pid, sig)
    except ProcessLookupError as exc:
        logger.debug("pid %s already gone when signalling %s: %s", pid, sig, exc)
    except PermissionError as exc:
        logger.debug("pid %s refused signal %s: %s", pid, sig, exc)
        return True
    except OSError as exc:
        logger.debug("signal %s to pid %s failed: %s", sig, pid, exc)
    return False


def reap_if_child(pid: int) -> None:
    """Collapse a zombie child we parent so liveness stops reading it as alive.

    When the target happens to be a direct child of this process - the only
    case in which a signalled process lingers as an un-reaped zombie -
    ``waitpid`` clears its process-table entry, so a subsequent liveness probe
    correctly reports it gone. When the target is not our child (the normal
    case: an orphan reparented to init), ``waitpid`` raises
    ``ChildProcessError`` (ECHILD), which is expected. ``WNOHANG`` never
    blocks.
    """
    if sys.platform == "win32":
        return
    with contextlib.suppress(ChildProcessError, OSError):
        os.waitpid(pid, os.WNOHANG)


def wait_for_exit(pid: int, *, timeout: float, poll_seconds: float = 0.05) -> bool:
    """Wait boundedly for *pid* to exit, reaping a POSIX child when applicable.

    Returns whether the process is gone by the deadline.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        reap_if_child(pid)
        if not pid_alive(pid):
            return True
        time.sleep(poll_seconds)
    return not pid_alive(pid)
