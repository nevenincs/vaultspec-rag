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
through a hard kill of the owning process, where an atexit hook or a watchdog
thread would lose. A second transcription of these structures is the same
wrong-hex-digit risk the flags were consolidated to remove.
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
    "grant_every_account_access",
    "program_data_directory",
]

#: ``FOLDERID_ProgramData`` (``KnownFolders.h``).
_FOLDERID_PROGRAM_DATA: Final = (
    0x62AB5D82,
    0xFDC1,
    0x4DC3,
    (0xA9, 0xDD, 0x07, 0x0D, 0x1D, 0x49, 0x5D, 0x97),
)

#: New process group: the child does not receive the parent console's CTRL_C.
WIN_CREATE_NEW_PROCESS_GROUP: Final = 0x00000200

#: No console window is allocated for the child.
WIN_CREATE_NO_WINDOW: Final = 0x08000000

#: Detach from the launching shell's Job Object so the child outlives the
#: shell. Restricted Job Objects may deny this, which callers must handle.
WIN_CREATE_BREAKAWAY_FROM_JOB: Final = 0x01000000

#: Sever the child's console association entirely.
WIN_DETACHED_PROCESS: Final = 0x00000008

#: ``SE_FILE_OBJECT``, ``DACL_SECURITY_INFORMATION`` and ``SDDL_REVISION_1``
#: (``accctrl.h``, ``winnt.h``, ``sddl.h``).
_SE_FILE_OBJECT: Final = 1
_DACL_SECURITY_INFORMATION: Final = 0x00000004
_SDDL_REVISION_1: Final = 1

#: The counterpart of POSIX ``0o666`` for a machine-wide anchor: every
#: authenticated account may read and write the file (``FRFW``), while the
#: system and the administrators keep full control (``FA``). Delete and
#: permission-change are deliberately not granted to ``AU``: contending for a
#: lock needs neither, and an anchor another account can delete is an anchor
#: its holder can be silently separated from. Set as explicit ACEs on the file
#: alone, so the inherited ones - which is how the creating account keeps full
#: control - survive beside them.
_SHARED_ANCHOR_SDDL: Final = "D:(A;;FA;;;SY)(A;;FA;;;BA)(A;;FRFW;;;AU)"

#: The same grant for the directory the anchors share. Every authenticated
#: account may list it and create files in it (``FRFW`` on the directory
#: itself), and every file in it - whoever created it, and whenever - inherits
#: read and write for them (``OIIO``). Delete is again withheld, both on the
#: files and as delete-child on the directory, so no account can separate
#: another's holder from its anchor.
_SHARED_ANCHOR_DIRECTORY_SDDL: Final = (
    "D:(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;;FRFW;;;AU)(A;OIIO;FRFW;;;AU)"
)

#: ``ERROR_ACCESS_DENIED`` (``winerror.h``).
_ERROR_ACCESS_DENIED: Final = 5

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

    from ._process_probe import win_kernel32

    # ``win_kernel32()`` returns the same process-global ``kernel32`` object
    # every caller shares; declaring the Job Object signatures on it (rather
    # than on a fresh ``ctypes.windll.kernel32`` reference) keeps every
    # restype/argtype declaration for this DLL in one inventory. Left
    # undeclared, ``CreateJobObjectW``'s return defaults to a 32-bit ``c_int``
    # even though a ``HANDLE`` is pointer-sized - the exact truncation
    # ``win_kernel32`` exists to prevent for ``OpenProcess``.
    kernel32 = win_kernel32()
    kernel32.CreateJobObjectW.argtypes = (wintypes.LPVOID, wintypes.LPCWSTR)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.SetInformationJobObject.restype = wintypes.BOOL

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


class _AclHeader(ctypes.Structure):
    """ACL header from winnt.h; no pointer-sized or platform-long fields."""

    revision: int
    ace_count: int
    _fields_ = [
        ("revision", ctypes.c_uint8),
        ("reserved", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
        ("ace_count", ctypes.c_uint16),
        ("reserved2", ctypes.c_uint16),
    ]


class _AceHeader(ctypes.Structure):
    """The common header precedes opaque standard, object and callback ACEs."""

    size: int
    _fields_ = [
        ("type", ctypes.c_uint8),
        ("flags", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
    ]


_ACL_REVISION_DS: Final = 4
_INHERITED_ACE: Final = 0x10
_MAXDWORD: Final = 0xFFFFFFFF


def _anchor_acl_api() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    """Bind the documented ACL calls on private library instances."""
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    pointer = ctypes.c_void_p
    pointer_out = ctypes.POINTER(pointer)
    kernel32.LocalFree.argtypes = (pointer,)
    kernel32.LocalFree.restype = pointer
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        pointer_out,
        pointer_out,
        pointer_out,
        pointer_out,
        pointer_out,
    )
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
        wintypes.LPCWSTR,
        wintypes.DWORD,
        pointer_out,
        ctypes.POINTER(wintypes.ULONG),
    )
    advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    advapi32.GetSecurityDescriptorDacl.argtypes = (
        pointer,
        ctypes.POINTER(wintypes.BOOL),
        pointer_out,
        ctypes.POINTER(wintypes.BOOL),
    )
    advapi32.GetSecurityDescriptorDacl.restype = wintypes.BOOL
    advapi32.GetAce.argtypes = (pointer, wintypes.DWORD, pointer_out)
    advapi32.GetAce.restype = wintypes.BOOL
    advapi32.InitializeAcl.argtypes = (pointer, wintypes.DWORD, wintypes.DWORD)
    advapi32.InitializeAcl.restype = wintypes.BOOL
    advapi32.AddAce.argtypes = (
        pointer,
        wintypes.DWORD,
        wintypes.DWORD,
        pointer,
        wintypes.DWORD,
    )
    advapi32.AddAce.restype = wintypes.BOOL
    advapi32.SetNamedSecurityInfoW.argtypes = (
        wintypes.LPWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        pointer,
        pointer,
        pointer,
        pointer,
    )
    advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    return advapi32, kernel32


def _read_acl_aces(api: ctypes.WinDLL, acl: ctypes.c_void_p) -> tuple[int, list[bytes]]:
    """Copy existing entries without interpreting or rewriting trustee rights."""
    assert acl.value is not None
    header = _AclHeader.from_address(acl.value)
    entries: list[bytes] = []
    for index in range(header.ace_count):
        ace = ctypes.c_void_p()
        if not api.GetAce(acl, index, ctypes.byref(ace)):
            raise ctypes.WinError(ctypes.get_last_error() or 1)
        assert ace.value is not None
        size = _AceHeader.from_address(ace.value).size
        entries.append(ctypes.string_at(ace.value, size))
    return header.revision, entries


def _apply_augmented_acl(
    api: ctypes.WinDLL,
    path: str,
    existing: ctypes.c_void_p,
    grants: ctypes.c_void_p,
) -> int:
    """Preserve each old ACE and append missing grants before inherited entries."""
    revision, old = _read_acl_aces(api, existing)
    _, requested = _read_acl_aces(api, grants)
    seen = set(old)
    added: list[bytes] = []
    for entry in requested:
        if entry not in seen:
            added.append(entry)
            seen.add(entry)
    if not added:
        return 0
    boundary = next(
        (index for index, entry in enumerate(old) if entry[1] & _INHERITED_ACE),
        len(old),
    )
    ordered = old[:boundary] + added + old[boundary:]
    size = ctypes.sizeof(_AclHeader) + sum(map(len, ordered))
    merged = ctypes.create_string_buffer(size)
    revision = max(revision, _ACL_REVISION_DS)
    if not api.InitializeAcl(merged, size, revision):
        raise ctypes.WinError(ctypes.get_last_error() or 1)
    for entry in ordered:
        blob = ctypes.create_string_buffer(entry, len(entry))
        if not api.AddAce(merged, revision, _MAXDWORD, blob, len(entry)):
            raise ctypes.WinError(ctypes.get_last_error() or 1)
    return int(
        api.SetNamedSecurityInfoW(
            path,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            merged,
            None,
        )
    )


def _augment_anchor_dacl(path: str, *, directory: bool) -> int:
    """Merge grants with the existing DACL and return the native status."""
    from ctypes import wintypes

    advapi32, kernel32 = _anchor_acl_api()
    pointer = ctypes.c_void_p
    existing_descriptor = pointer()
    grant_descriptor = pointer()
    existing_acl = pointer()
    try:
        status = advapi32.GetNamedSecurityInfoW(
            path,
            _SE_FILE_OBJECT,
            _DACL_SECURITY_INFORMATION,
            None,
            None,
            ctypes.byref(existing_acl),
            None,
            ctypes.byref(existing_descriptor),
        )
        if status != 0 or not existing_acl.value:
            # A successful read with a null DACL already permits everyone;
            # return its zero status without installing a restrictive ACL.
            # A failed read retains its original native error status.
            return int(status)
        sddl = _SHARED_ANCHOR_DIRECTORY_SDDL if directory else _SHARED_ANCHOR_SDDL
        if not advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl,
            _SDDL_REVISION_1,
            ctypes.byref(grant_descriptor),
            None,
        ):
            return ctypes.get_last_error() or 1
        grant_acl = pointer()
        present = wintypes.BOOL()
        defaulted = wintypes.BOOL()
        if not advapi32.GetSecurityDescriptorDacl(
            grant_descriptor,
            ctypes.byref(present),
            ctypes.byref(grant_acl),
            ctypes.byref(defaulted),
        ):
            return ctypes.get_last_error() or 1
        return _apply_augmented_acl(advapi32, path, existing_acl, grant_acl)
    except OSError as exc:
        return exc.winerror or 1
    finally:
        # ACL pointers are borrowed from these two API-owned descriptors.
        # The rebuilt ACL and opaque ACE copies are Python-owned buffers.
        kernel32.LocalFree(grant_descriptor)
        kernel32.LocalFree(existing_descriptor)


def grant_every_account_access(path: str, *, directory: bool = False) -> bool:
    """Let every authenticated account read and write the file at *path*.

    With *directory*, *path* is the directory the machine's anchors share:
    every account may create files in it, and every file in it inherits the
    same read and write. Windows pushes an inheritable grant down to the files
    already there, so an anchor created before its directory was shared - by an
    older release, or by hand - becomes writable too.

    Windows has no umask and no mode bits, so a file created under a shared
    directory carries only what it inherits: on a default ``ProgramData`` tree
    that is full control for the system, the administrators and the creating
    account, and read-only for everyone else. A machine-wide anchor created by
    one account is then unwritable by the next, which cannot publish its owner
    record and loses every loan it tries to write - while still holding the
    lock, so the fault surfaces as a borrower being refused rather than as a
    permission error anyone reads.

    Existing creator, inherited, custom and deny entries are preserved; only
    the new read/write grants are merged into the current DACL. A null DACL
    remains unrestricted.

    Named rather than taking the caller's descriptor, because changing an
    access list needs a handle opened for ``WRITE_DAC`` and the descriptor a
    caller has is opened for reading and writing data. The name cannot be
    re-pointed underneath this call: the caller holds the file open without
    sharing delete, so nothing can rename or replace it meanwhile.

    Returns whether the grant was applied. A failure is logged and reported,
    never raised: the anchor still locks, and a caller that created it for its
    own account is no worse off than before. Only a path's owner may change its
    access list, so a refusal on another account's directory is expected and
    logged quietly: that account applies the grant the next time it claims.
    """
    if sys.platform != "win32":
        return False
    status = _augment_anchor_dacl(path, directory=directory)
    if status == _ERROR_ACCESS_DENIED:
        logger.debug("%s belongs to another account, which alone may widen it", path)
        return False
    if status != 0:
        logger.warning(
            "could not widen a machine-wide anchor to every account "
            "(the access-list call reported %d); another account will be "
            "unable to publish its owner record on it",
            status,
        )
        return False
    return True


def program_data_directory() -> str:
    """Return the machine's ProgramData directory as the shell records it.

    Asked of the known-folder API rather than read from the ``ProgramData``
    environment variable, because a variable is one assignment away from
    pointing somewhere else: a directory chosen to be the same for every
    process on the machine must not be relocatable by the process asking.

    Raises:
        OSError: Off Windows, or when the shell cannot resolve the folder.
    """
    if sys.platform != "win32":
        raise OSError("the ProgramData known folder exists only on Windows")
    from ctypes import wintypes

    class _Guid(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    data1, data2, data3, data4 = _FOLDERID_PROGRAM_DATA
    folder = _Guid(data1, data2, data3, (ctypes.c_ubyte * 8)(*data4))
    # A private library handle, so these declarations cannot collide with any
    # other module's use of the process-global ``ctypes.windll`` cache.
    shell32 = ctypes.WinDLL("shell32")
    shell32.SHGetKnownFolderPath.argtypes = (
        ctypes.POINTER(_Guid),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    )
    shell32.SHGetKnownFolderPath.restype = ctypes.HRESULT
    ole32 = ctypes.WinDLL("ole32")
    ole32.CoTaskMemFree.argtypes = (ctypes.c_void_p,)
    ole32.CoTaskMemFree.restype = None
    resolved = ctypes.c_wchar_p()
    try:
        # An HRESULT restype raises OSError on failure by itself.
        shell32.SHGetKnownFolderPath(
            ctypes.byref(folder), 0, None, ctypes.byref(resolved)
        )
        if not resolved.value:
            raise OSError("the shell returned no ProgramData path")
        return resolved.value
    finally:
        ole32.CoTaskMemFree(resolved)


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
    from ctypes import wintypes

    from ._process_probe import win_kernel32

    kernel32 = win_kernel32()
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    if kernel32.AssignProcessToJobObject(job, process_handle):
        return True
    logger.error(
        "AssignProcessToJobObject failed for %s pid %d; the kill-on-close "
        "orphan guard is DISABLED for this process, which may outlive its owner",
        purpose,
        pid,
    )
    return False
