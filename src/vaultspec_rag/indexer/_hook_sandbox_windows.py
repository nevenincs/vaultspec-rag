"""Windows AppContainer containment backend for preprocess hooks.

Launches a hook child inside a low-privilege AppContainer: default-deny for the
filesystem (except an ACL-granted read of the staged scratch dir), default-deny
for the network including loopback (we grant no capability SIDs), and no
registry or cross-process access. The child is additionally assigned to a
kill-on-close Job Object so its whole process tree is torn down when the launch
handle closes - closing the orphaned-grandchild and fork-bomb threats the
timeout alone cannot.

The AppContainer profile is per-launch and deleted on cleanup. The staged dir is
granted read+execute for the derived AppContainer SID via ``icacls`` (far
simpler and more auditable than an in-process ``SetEntriesInAcl``), and the
child's stdout/stderr are captured over inheritable pipes whose write ends are
the only handles the child inherits (``PROC_THREAD_ATTRIBUTE_HANDLE_LIST``).

All Win32 access is ctypes, mirroring the Job Object idiom already in
``qdrant_runtime/_supervise.py``. The module is import-guarded to win32 by its
sole caller (:func:`.._hook_sandbox._probe_backend`) and stays torch-free.
"""

from __future__ import annotations

import ctypes
import logging
import os
import subprocess
import sys
from ctypes import wintypes
from typing import IO, TYPE_CHECKING, cast

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Sequence

    from ._hook_sandbox import HookSandbox, SandboxHandle

logger = logging.getLogger(__name__)

# --- Win32 constants -------------------------------------------------------
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_CREATE_NO_WINDOW = 0x08000000
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_CREATE_SUSPENDED = 0x00000004
_STARTF_USESTDHANDLES = 0x00000100
_HANDLE_FLAG_INHERIT = 0x00000001
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_PROC_THREAD_ATTRIBUTE_HANDLE_LIST = 0x00020002
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION = 9
_INFINITE = 0xFFFFFFFF
_WAIT_TIMEOUT = 0x00000102
_STILL_ACTIVE = 259

#: A stable AppContainer name; the profile is created idempotently and the SID
#: derived from it is what the child runs under and what the staged-dir ACE
#: grants. Per-launch isolation comes from the fresh scratch dir and Job Object,
#: not a unique profile name, so deriving a stable SID keeps launch cheap.
_APPCONTAINER_NAME = "VaultspecRagPreprocessHook"
_APPCONTAINER_DISPLAY = "vaultspec-rag preprocess hook sandbox"


class _SidAndAttributes(ctypes.Structure):
    _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", ctypes.c_void_p),
        ("Capabilities", ctypes.POINTER(_SidAndAttributes)),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _StartupInfoEx(ctypes.Structure):
    class _StartupInfo(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    _fields_ = [
        ("StartupInfo", _StartupInfo),
        ("lpAttributeList", ctypes.c_void_p),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", ctypes.c_void_p),
        ("bInheritHandle", wintypes.BOOL),
    ]


def _kernel32() -> ctypes.CDLL:
    if sys.platform != "win32":
        raise RuntimeError("the AppContainer hook sandbox is win32-only")
    return ctypes.WinDLL("kernel32", use_last_error=True)


def _userenv() -> ctypes.CDLL:
    if sys.platform != "win32":
        raise RuntimeError("the AppContainer hook sandbox is win32-only")
    return ctypes.WinDLL("userenv", use_last_error=True)


def _advapi32() -> ctypes.CDLL:
    if sys.platform != "win32":
        raise RuntimeError("the AppContainer hook sandbox is win32-only")
    return ctypes.WinDLL("advapi32", use_last_error=True)


def _derive_appcontainer_sid() -> tuple[ctypes.c_void_p, str]:
    """Create the AppContainer profile (idempotent) and return (PSID, SID str).

    Raises OSError on failure; the caller treats that as "backend unavailable".
    """
    userenv = _userenv()
    advapi32 = _advapi32()

    sid = ctypes.c_void_p()
    # CreateAppContainerProfile fails with HRESULT 0x800700B7 (ALREADY_EXISTS)
    # when the profile is present from a prior run; that is success for us.
    hr = userenv.CreateAppContainerProfile(
        ctypes.c_wchar_p(_APPCONTAINER_NAME),
        ctypes.c_wchar_p(_APPCONTAINER_DISPLAY),
        ctypes.c_wchar_p(_APPCONTAINER_DISPLAY),
        None,
        0,
        ctypes.byref(sid),
    )
    already_exists = hr & 0xFFFF == 0xB7
    if hr != 0 and not already_exists:
        raise OSError(f"CreateAppContainerProfile failed (hr=0x{hr & 0xFFFFFFFF:08X})")
    if already_exists or not sid:
        sid = ctypes.c_void_p()
        hr2 = userenv.DeriveAppContainerSidFromAppContainerName(
            ctypes.c_wchar_p(_APPCONTAINER_NAME),
            ctypes.byref(sid),
        )
        if hr2 != 0 or not sid:
            raise OSError(
                f"DeriveAppContainerSidFromAppContainerName failed "
                f"(hr=0x{hr2 & 0xFFFFFFFF:08X})"
            )

    str_ptr = ctypes.c_wchar_p()
    if not advapi32.ConvertSidToStringSidW(sid, ctypes.byref(str_ptr)):
        raise OSError("ConvertSidToStringSidW failed")
    sid_str = str(str_ptr.value)
    _kernel32().LocalFree(str_ptr)
    return sid, sid_str


#: (sid, resolved-path) pairs already granted in this process. The AppContainer
#: SID is stable across launches, so a static read path (the interpreter prefix,
#: the project root) is granted at most once per worker instead of re-walked with
#: ``icacls /T`` on every file - the difference between O(files) and
#: O(files x tree) ACL work over a large corpus.
_GRANTED: set[tuple[str, str]] = set()


def _grant_appcontainer_read(path: pathlib.Path, sid_str: str, *, cache: bool) -> None:
    """Grant the AppContainer SID read+execute on ``path`` via icacls.

    Uses the ``*<SID>`` form so no name resolution is needed; object- and
    container-inherit so nested files are readable. ``cache=True`` records the
    grant and skips a repeat for the same (sid, path) - used for the static
    interpreter and project-root paths so they are ACL-walked once per worker,
    not once per file. The per-launch scratch dir passes ``cache=False`` (it is
    fresh each time and tiny). Raises on failure so a missing grant surfaces as a
    per-file skip rather than a silently unreadable child.
    """
    key = (sid_str, str(path))
    if cache and key in _GRANTED:
        return
    result = subprocess.run(
        [
            "icacls",
            str(path),
            "/grant",
            f"*{sid_str}:(OI)(CI)(RX)",
            "/T",
            "/C",
            "/Q",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise OSError(
            f"icacls grant for the AppContainer SID failed on {path}: "
            f"{result.stdout.strip()} {result.stderr.strip()}"
        )
    if cache:
        _GRANTED.add(key)


def _make_inheritable_pipe() -> tuple[wintypes.HANDLE, wintypes.HANDLE]:
    """Create a pipe whose WRITE end is inheritable and READ end is not."""
    kernel32 = _kernel32()
    read_h = wintypes.HANDLE()
    write_h = wintypes.HANDLE()
    sa = _SecurityAttributes()
    sa.nLength = ctypes.sizeof(sa)
    sa.lpSecurityDescriptor = None
    sa.bInheritHandle = True
    if not kernel32.CreatePipe(
        ctypes.byref(read_h), ctypes.byref(write_h), ctypes.byref(sa), 0
    ):
        raise OSError("CreatePipe failed")
    # The read end must NOT be inherited by the child.
    kernel32.SetHandleInformation(read_h, _HANDLE_FLAG_INHERIT, 0)
    return read_h, write_h


class _AppContainerHandle:
    """A ``SandboxHandle`` over a CreateProcessW child in an AppContainer."""

    def __init__(
        self,
        *,
        h_process: wintypes.HANDLE,
        h_thread: wintypes.HANDLE,
        h_job: wintypes.HANDLE | None,
        pid: int,
        stdout: IO[bytes],
        stderr: IO[bytes],
    ) -> None:
        self._h_process = h_process
        self._h_thread = h_thread
        self._h_job = h_job
        self.pid = pid
        self.stdout: IO[bytes] | None = stdout
        self.stderr: IO[bytes] | None = stderr
        self.returncode: int | None = None

    def wait(self, timeout: float | None = None) -> int:
        kernel32 = _kernel32()
        ms = _INFINITE if timeout is None else int(timeout * 1000)
        rc = kernel32.WaitForSingleObject(self._h_process, ms)
        if rc == _WAIT_TIMEOUT:
            raise subprocess.TimeoutExpired(cmd="<hook>", timeout=timeout or 0.0)
        code = wintypes.DWORD()
        kernel32.GetExitCodeProcess(self._h_process, ctypes.byref(code))
        self.returncode = int(code.value)
        return self.returncode

    def kill(self) -> None:
        _kernel32().TerminateProcess(self._h_process, 1)

    def close_process_handles(self) -> None:
        kernel32 = _kernel32()
        for pipe in (self.stdout, self.stderr):
            if pipe is not None:
                try:
                    pipe.close()
                except OSError:  # pragma: no cover - close is best-effort
                    logger.debug("closing hook pipe failed", exc_info=True)
        self.stdout = None
        self.stderr = None
        # Closing the last job handle triggers KILL_ON_JOB_CLOSE, reaping the
        # child and any grandchildren it spawned - the process-tree teardown.
        if self._h_job:
            kernel32.CloseHandle(self._h_job)
            self._h_job = None
        if self._h_thread:
            kernel32.CloseHandle(self._h_thread)
            self._h_thread = wintypes.HANDLE()
        if self._h_process:
            kernel32.CloseHandle(self._h_process)
            self._h_process = wintypes.HANDLE()


class AppContainerSandbox:
    """AppContainer + Job Object containment backend (see module docstring)."""

    name = "windows-appcontainer"

    def __init__(self, sid: ctypes.c_void_p, sid_str: str) -> None:
        self._sid = sid
        self._sid_str = sid_str

    def _build_attr_list(
        self, out_w: wintypes.HANDLE, err_w: wintypes.HANDLE
    ) -> tuple[ctypes.c_void_p, object, object, object]:
        """Build the STARTUPINFOEX attribute list for the AppContainer launch.

        Two attributes: the security capabilities (AppContainer SID, zero
        capability SIDs) and the handle list restricting inheritance to the two
        pipe write ends. Returns the list plus the backing buffers, which the
        caller must keep alive until ``CreateProcessW`` returns. Deletes the
        partially-built list and raises on any failure.
        """
        kernel32 = _kernel32()
        attr_size = ctypes.c_size_t(0)
        kernel32.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(attr_size))
        attr_buf = (ctypes.c_byte * attr_size.value)()
        attr_list = ctypes.cast(attr_buf, ctypes.c_void_p)
        if not kernel32.InitializeProcThreadAttributeList(
            attr_list, 2, 0, ctypes.byref(attr_size)
        ):
            raise OSError("InitializeProcThreadAttributeList failed")
        try:
            caps = _SecurityCapabilities()
            caps.AppContainerSid = self._sid
            # No capability SIDs: a NULL array so the child gets zero capabilities
            # (no network, no broker access) - the crux of the default-deny.
            caps.Capabilities = ctypes.POINTER(_SidAndAttributes)()
            caps.CapabilityCount = 0
            caps.Reserved = 0
            if not kernel32.UpdateProcThreadAttribute(
                attr_list,
                0,
                ctypes.c_size_t(_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES),
                ctypes.byref(caps),
                ctypes.sizeof(caps),
                None,
                None,
            ):
                raise OSError("UpdateProcThreadAttribute(security capabilities) failed")
            handle_arr = (wintypes.HANDLE * 2)(out_w, err_w)
            if not kernel32.UpdateProcThreadAttribute(
                attr_list,
                0,
                ctypes.c_size_t(_PROC_THREAD_ATTRIBUTE_HANDLE_LIST),
                handle_arr,
                ctypes.sizeof(handle_arr),
                None,
                None,
            ):
                raise OSError("UpdateProcThreadAttribute(handle list) failed")
        except OSError:
            kernel32.DeleteProcThreadAttributeList(attr_list)
            raise
        return attr_list, attr_buf, caps, handle_arr

    def launch(
        self,
        argv: Sequence[str],
        *,
        scratch_dir: pathlib.Path,
        env: dict[str, str],
        read_paths: Sequence[pathlib.Path],
    ) -> SandboxHandle:
        if sys.platform != "win32":
            raise RuntimeError("the AppContainer hook sandbox is win32-only")
        kernel32 = _kernel32()

        # The scratch dir is fresh per launch, so grant it every time; the
        # static read paths (interpreter prefixes, project root) are granted once
        # per worker via the cache to avoid re-walking large trees per file.
        _grant_appcontainer_read(scratch_dir, self._sid_str, cache=False)
        for path in read_paths:
            if path != scratch_dir:
                _grant_appcontainer_read(path, self._sid_str, cache=True)

        out_r, out_w = _make_inheritable_pipe()
        err_r, err_w = _make_inheritable_pipe()
        attr_list: ctypes.c_void_p | None = None
        created = 0
        try:
            attr_list, _attr_buf, _caps, _handle_arr = self._build_attr_list(
                out_w, err_w
            )

            si = _StartupInfoEx()
            si.StartupInfo.cb = ctypes.sizeof(_StartupInfoEx)
            si.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            si.StartupInfo.hStdInput = None
            si.StartupInfo.hStdOutput = out_w
            si.StartupInfo.hStdError = err_w
            si.lpAttributeList = attr_list

            pi = _ProcessInformation()
            cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
            env_block = _env_block(env)

            # Create suspended so the child is assigned to the kill-on-close Job
            # Object before its first instruction runs - otherwise a fast child
            # could spawn a breakaway grandchild before assignment.
            created = kernel32.CreateProcessW(
                None,
                cmdline,
                None,
                None,
                True,
                _EXTENDED_STARTUPINFO_PRESENT
                | _CREATE_NO_WINDOW
                | _CREATE_UNICODE_ENVIRONMENT
                | _CREATE_SUSPENDED,
                ctypes.byref(env_block),
                ctypes.c_wchar_p(str(scratch_dir)),
                ctypes.byref(si),
                ctypes.byref(pi),
            )
            err = ctypes.get_last_error()
            if not created:
                raise OSError(f"CreateProcessW (AppContainer) failed (err={err})")
        finally:
            if attr_list is not None:
                kernel32.DeleteProcThreadAttributeList(attr_list)
            # The child holds its own copies of the write ends now; close ours so
            # a closed pipe (child exit) yields EOF to the readers.
            kernel32.CloseHandle(out_w)
            kernel32.CloseHandle(err_w)
            if not created:
                # Launch failed: the read ends never reach the handle, so
                # release them here rather than leaking one pair per skip.
                kernel32.CloseHandle(out_r)
                kernel32.CloseHandle(err_r)

        h_job = self._assign_job(pi.hProcess)
        try:
            kernel32.ResumeThread(pi.hThread)
            stdout = _fdopen_read(out_r)
            stderr = _fdopen_read(err_r)
        except OSError:
            # Building the handle failed after the child was created; tear the
            # process down and release every handle so nothing leaks (no handle
            # object exists yet, so cleanup() would never run).
            kernel32.TerminateProcess(pi.hProcess, 1)
            if h_job:
                kernel32.CloseHandle(h_job)
            kernel32.CloseHandle(pi.hThread)
            kernel32.CloseHandle(pi.hProcess)
            kernel32.CloseHandle(out_r)
            kernel32.CloseHandle(err_r)
            raise
        return _AppContainerHandle(
            h_process=pi.hProcess,
            h_thread=pi.hThread,
            h_job=h_job,
            pid=int(pi.dwProcessId),
            stdout=stdout,
            stderr=stderr,
        )

    def _assign_job(self, h_process: wintypes.HANDLE) -> wintypes.HANDLE | None:
        """Assign the child to a kill-on-close Job Object.

        Returns the job handle so the caller can hold it for the child's
        lifetime and close it in ``cleanup`` - closing the last handle is what
        triggers ``KILL_ON_JOB_CLOSE`` and tears down the whole process tree.
        Returns ``None`` (best-effort) if the job could not be created or
        assigned; containment still holds via the AppContainer token, only the
        process-tree teardown is lost.
        """
        kernel32 = _kernel32()
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            logger.warning("CreateJobObjectW failed; hook process-tree guard disabled")
            return None

        class _Basic(ctypes.Structure):
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

        class _Io(ctypes.Structure):
            _fields_ = [
                (n, ctypes.c_uint64)
                for n in (
                    "ReadOperationCount",
                    "WriteOperationCount",
                    "OtherOperationCount",
                    "ReadTransferCount",
                    "WriteTransferCount",
                    "OtherTransferCount",
                )
            ]

        class _Ext(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _Basic),
                ("IoInfo", _Io),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        info = _Ext()
        info.BasicLimitInformation.LimitFlags = _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        kernel32.SetInformationJobObject(
            job,
            _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION,
            ctypes.byref(info),
            ctypes.sizeof(info),
        )
        if not kernel32.AssignProcessToJobObject(job, h_process):
            logger.warning("AssignProcessToJobObject failed; hook tree guard disabled")
            kernel32.CloseHandle(job)
            return None
        return wintypes.HANDLE(job)

    def cleanup(self, handle: SandboxHandle) -> None:
        if isinstance(handle, _AppContainerHandle):
            handle.close_process_handles()


def _env_block(env: dict[str, str]) -> ctypes.Array[ctypes.c_wchar]:
    """Build a UTF-16 double-null-terminated environment block buffer.

    A ``c_wchar_p`` cannot carry the embedded NULs an environment block needs
    (ctypes truncates at the first), so an explicit wide buffer is required.
    """
    items = [f"{k}={v}" for k, v in env.items() if k]
    block = "\x00".join(items) + "\x00\x00"
    # Build char-by-char: assigning ``.value`` (what create_unicode_buffer(str)
    # does) truncates at the first embedded NUL, malforming the block.
    buf = (ctypes.c_wchar * len(block))()
    for i, ch in enumerate(block):
        buf[i] = ch
    return buf


def _fdopen_read(handle: wintypes.HANDLE) -> IO[bytes]:
    """Wrap a Win32 read-pipe handle as a Python binary file object.

    The handle's integer value is taken via ``.value`` (a bare ``int()`` on the
    ctypes HANDLE yields its raw bytes, not the address). ``open_osfhandle``
    transfers ownership of the OS handle to the returned fd, so the file object's
    ``close`` releases it - the caller must not also ``CloseHandle`` it.
    """
    if sys.platform != "win32":
        raise RuntimeError("the AppContainer hook sandbox is win32-only")
    import msvcrt

    raw = cast("int", handle.value)
    fd = msvcrt.open_osfhandle(raw, os.O_RDONLY)
    return os.fdopen(fd, "rb", buffering=0)


def probe_appcontainer() -> HookSandbox | None:
    """Return an :class:`AppContainerSandbox` if the host supports it, else None.

    Success criterion: we can create/derive the AppContainer profile and
    stringify its SID. If any step fails (unsupported OS build, group policy,
    missing userenv export) the backend is unavailable and the caller applies
    the fail-closed policy.
    """
    if sys.platform != "win32":
        return None
    try:
        sid, sid_str = _derive_appcontainer_sid()
    except OSError as exc:
        logger.warning("AppContainer sandbox unavailable: %s", exc)
        return None
    return AppContainerSandbox(sid, sid_str)
