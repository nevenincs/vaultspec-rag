"""Hardware anchors: one machine-wide location every account contends for.

An anchor guarding the GPU only excludes anything if every process on the
machine resolves the same file, and if every account can lock it. Both are
proved here against the real resolver and real locks: relocating every variable
a process could change leaves the location where it was, and an anchor this
process may read but not write - the shape another account's anchor has - is
still claimed and still contended.
"""

from __future__ import annotations

import os
import re
import stat
import subprocess
import sys
from contextlib import contextmanager
from typing import TYPE_CHECKING

import pytest

from .. import _gpu_admission
from .._anchor_claim import (
    AnchorOutcome,
    claim_anchor,
    observe_existing_anchor,
    release_anchor_claim,
)
from .._gpu_admission import _claim_load_window

if TYPE_CHECKING:
    from collections.abc import Generator, Iterator
    from pathlib import Path

# The real resolvers are the subject here, so this module opts out of the
# per-test anchor redirect. Nothing in it claims a machine anchor: the
# locations are read, and every lock it takes is on a temporary file.
pytestmark = [pytest.mark.unit, pytest.mark.real_hardware_anchor]

# Every variable a process can set to move a path it resolves: the Windows
# ProgramData and temporary variables, their POSIX counterparts, both homes,
# and both of this project's configured directories.
_RELOCATING_VARIABLES = (
    "ProgramData",
    "PROGRAMDATA",
    "ALLUSERSPROFILE",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "VAULTSPEC_RAG_QDRANT_STORAGE_DIR",
    "VAULTSPEC_RAG_STATUS_DIR",
)


# Each location is resolved in a fresh interpreter, so nothing this process has
# cached - ``gettempdir`` memoises its answer - can hide a resolver that reads
# the environment.
_RESOLVE = (
    "from vaultspec_rag._anchor_claim import hardware_anchor_path; "
    "from vaultspec_rag._gpu_admission import load_window_lock_path; "
    "print(hardware_anchor_path('probe.lock')); print(load_window_lock_path())"
)


def _resolved_under(environment: dict[str, str]) -> list[str]:
    return subprocess.run(
        [sys.executable, "-c", _RESOLVE],
        env=environment,
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    ).stdout.splitlines()


def test_anchor_locations_ignore_every_variable_a_process_can_change(
    tmp_path: Path,
) -> None:
    relocated = dict(os.environ)
    for index, name in enumerate(_RELOCATING_VARIABLES):
        # Created, so a resolver consulting one of them would really use it
        # rather than skip a missing directory and land back where it was.
        # Numbered, because Windows folds the spellings of one variable - and
        # of one directory - together.
        elsewhere = tmp_path / f"relocated-{index}"
        elsewhere.mkdir()
        relocated[name] = str(elsewhere)

    unchanged = _resolved_under(dict(os.environ))

    # Catches a resolver reading any of these variables - such as
    # ``os.environ["ProgramData"]``, or the load window moving back under
    # ``tempfile.gettempdir()`` - where a different TEMP, account or
    # configuration gives a second process an anchor of its own.
    assert _resolved_under(relocated) == unchanged
    assert len(unchanged) == 2


@pytest.fixture
def foreign_anchor(tmp_path: Path) -> Iterator[Path]:
    """An anchor this process may read but not write, as another account's is."""
    anchor = tmp_path / "foreign.lock"
    anchor.write_bytes(b"")
    anchor.chmod(stat.S_IREAD)
    try:
        writable = os.open(anchor, os.O_RDWR)
    except PermissionError:
        pass
    else:
        os.close(writable)
        anchor.chmod(stat.S_IREAD | stat.S_IWRITE)
        pytest.skip("this process's privileges ignore file permissions")
    try:
        yield anchor
    finally:
        anchor.chmod(stat.S_IREAD | stat.S_IWRITE)


def test_a_shared_anchor_another_account_created_is_still_claimed_and_contended(
    foreign_anchor: Path,
) -> None:
    first = claim_anchor(foreign_anchor, shared=True)
    # Catches the read-only fallback being removed: the claim then fails to
    # open the anchor and reports it unavailable instead of held.
    assert first.outcome is AnchorOutcome.HELD, first
    assert first.descriptor is not None
    try:
        assert claim_anchor(foreign_anchor, shared=True).outcome is (
            AnchorOutcome.CONTENDED
        )
        assert observe_existing_anchor(foreign_anchor, shared=True).outcome is (
            AnchorOutcome.CONTENDED
        )
    finally:
        release_anchor_claim(first.descriptor)
    assert observe_existing_anchor(foreign_anchor, shared=True).outcome is (
        AnchorOutcome.FREE
    )


def test_an_unshared_anchor_this_process_cannot_write_is_unavailable(
    foreign_anchor: Path,
) -> None:
    claim = claim_anchor(foreign_anchor)

    # The read-only fallback belongs to shared anchors only: an identity anchor
    # whose owner record must be written is refused rather than half-claimed.
    assert claim.outcome is AnchorOutcome.UNAVAILABLE
    assert isinstance(claim.fault, PermissionError)


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_observing_a_private_anchor_through_the_shared_path_keeps_its_mode(
    tmp_path: Path,
) -> None:
    private = tmp_path / "service.lock"
    private.write_bytes(b"")
    private.chmod(0o600)

    observe_existing_anchor(private, pid_record=True, shared=True)
    held = claim_anchor(private, pid_record=True, shared=True)
    if held.descriptor is not None:
        release_anchor_claim(held.descriptor, pid_record=True)

    # Catches the shared path widening a file it did not create: a service's
    # own lock, observed by a peer, would become writable by every account.
    assert stat.S_IMODE(private.stat().st_mode) == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
def test_a_shared_anchor_this_process_creates_is_writable_by_every_account(
    tmp_path: Path,
) -> None:
    anchor = tmp_path / "gpu-owner.lock"

    held = claim_anchor(anchor, pid_record=True, create_parent=True, shared=True)
    assert held.descriptor is not None
    release_anchor_claim(held.descriptor, pid_record=True)

    # Catches creation losing the widening past the umask: a second account
    # could then lock the anchor only read-only and never publish its pid.
    assert stat.S_IMODE(anchor.stat().st_mode) == 0o666


def test_an_unresolvable_load_window_degrades_rather_than_refusing_every_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Substituted because a host with no directory every account shares cannot
    # be staged here: the suite can neither remove the machine's shared
    # directories nor make the Windows known-folder API fail.
    def unresolvable() -> Path:
        raise OSError("no machine-wide anchor directory")

    monkeypatch.setattr(_gpu_admission, "load_window_lock_path", unresolvable)

    claim = _claim_load_window(None)

    assert claim.outcome is AnchorOutcome.UNAVAILABLE
    assert isinstance(claim.fault, OSError)


#: ``FILE_WRITE_DATA``, and the SDDL right mnemonics that include it
#: (``winnt.h``, ``sddl.h``).
_FILE_WRITE_DATA = 0x0002
_WRITING_MNEMONICS = ("FA", "FW", "GA", "GW")

#: ``S-1-5-11``, every account that authenticated to this machine, as SDDL
#: abbreviates it.
_AUTHENTICATED_USERS = "AU"


def _dacl_sddl(path: Path) -> str:
    """Return *path*'s discretionary access list as the OS renders it."""
    import ctypes
    from ctypes import wintypes

    advapi32 = ctypes.WinDLL("advapi32")
    advapi32.GetNamedSecurityInfoW.argtypes = (
        wintypes.LPCWSTR,
        ctypes.c_int,
        wintypes.DWORD,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    )
    advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.argtypes = (
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_wchar_p),
        ctypes.POINTER(wintypes.ULONG),
    )
    advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW.restype = (
        wintypes.BOOL
    )
    kernel32 = ctypes.WinDLL("kernel32")
    kernel32.LocalFree.argtypes = (ctypes.c_void_p,)
    kernel32.LocalFree.restype = ctypes.c_void_p
    descriptor = ctypes.c_void_p()
    rendered = ctypes.c_wchar_p()
    try:
        status = advapi32.GetNamedSecurityInfoW(
            str(path), 1, 4, None, None, None, None, ctypes.byref(descriptor)
        )
        assert status == 0, f"could not read the access list of {path}: {status}"
        assert advapi32.ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, 4, ctypes.byref(rendered), None
        )
        return rendered.value or ""
    finally:
        kernel32.LocalFree(ctypes.cast(rendered, ctypes.c_void_p))
        kernel32.LocalFree(descriptor)


def _authenticated_users_may_write(path: Path) -> bool:
    """Whether *path*'s access list lets any authenticated account write it."""
    for ace in re.findall(r"\(([^)]*)\)", _dacl_sddl(path)):
        fields = ace.split(";")
        if len(fields) < 6 or fields[0] != "A" or fields[5] != _AUTHENTICATED_USERS:
            continue
        rights = fields[2]
        if rights.startswith("0x"):
            return bool(int(rights, 16) & _FILE_WRITE_DATA)
        return any(mnemonic in rights for mnemonic in _WRITING_MNEMONICS)
    return False


def _set_dacl_sddl(path: Path, sddl: str) -> None:
    """Seed and restore a real test object's DACL without changing its owner."""
    import ctypes
    from ctypes import wintypes

    from .._win32 import _anchor_acl_api

    advapi32, kernel32 = _anchor_acl_api()
    descriptor = ctypes.c_void_p()
    try:
        assert advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
            sddl, 1, ctypes.byref(descriptor), None
        )
        acl = ctypes.c_void_p()
        present = wintypes.BOOL()
        defaulted = wintypes.BOOL()
        assert advapi32.GetSecurityDescriptorDacl(
            descriptor,
            ctypes.byref(present),
            ctypes.byref(acl),
            ctypes.byref(defaulted),
        )
        assert (
            advapi32.SetNamedSecurityInfoW(
                str(path), 1, 4 | 0x80000000, None, None, acl, None
            )
            == 0
        )
    finally:
        kernel32.LocalFree(descriptor)


@contextmanager
def _temporary_dacl(
    path: Path, sddl: str, *, retain_existing: bool = False
) -> Generator[None]:
    """Restore a test file's original permissions even when its guard fails."""
    path.parent.mkdir(mode=0o700, exist_ok=True)
    path.write_bytes(b"")
    initial = _dacl_sddl(path)
    if retain_existing:
        sddl += "".join(re.findall(r"\([^)]*\)", initial))
    try:
        _set_dacl_sddl(path, sddl)
        yield
    finally:
        _set_dacl_sddl(path, initial)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows access lists")
def test_a_created_shared_anchor_admits_every_account_on_windows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Windows has no mode bits, so the widening is an access list.

    Without it the anchor carries only what it inherits - full control for
    whoever created it, read-only for everyone else - and the next account to
    claim it holds the lock but cannot publish its owner record or write a
    loan, which reaches an operator as a borrower refused for no stated reason.

    Mutation: returned from the creation path before the grant, the shape this
    had on Windows. Observed this assertion fail on the anchor admitting no
    authenticated account; restoring the grant passed.

    Replacing the directory's ACL instead of merging also drops its creator's
    explicit full-control entry. Comparing actual entries catches that loss
    even when an administrator token masks the resulting filesystem refusal.
    Mutations: copying no original entries fails creator preservation; dropping
    an original deny fails deny preservation; installing an empty ACL over a
    null DACL fails unrestricted preservation. Each restored path passes.
    """
    original_entries = set(re.findall(r"\(([^)]*)\)", _dacl_sddl(tmp_path)))
    assert any(
        fields[2] == "FA" and fields[5] not in {"SY", "BA", "AU"}
        for entry in original_entries
        if len(fields := entry.split(";")) == 6
    ), "the private temporary directory must carry its creator's full control"
    anchor = tmp_path / "gpu-owner.lock"

    held = claim_anchor(anchor, pid_record=True, create_parent=True, shared=True)
    assert held.descriptor is not None
    release_anchor_claim(held.descriptor, pid_record=True)

    shared_entries = set(re.findall(r"\(([^)]*)\)", _dacl_sddl(tmp_path)))
    assert original_entries <= shared_entries, "sharing must preserve creator access"
    assert _authenticated_users_may_write(anchor)

    from .. import _win32
    from .._win32 import grant_every_account_access

    # Windows can coalesce duplicate entries, so compare the actual native
    # write count as well as the resulting ACL. Mutation: bypassing the
    # deduplication fails the no-rewrite assertion; restoring it passes.
    shared = _dacl_sddl(tmp_path)
    api, kernel32 = _win32._anchor_acl_api()
    set_named = api.SetNamedSecurityInfoW
    repeat_writes: list[str] = []

    def record_write(*args: object) -> int:
        repeat_writes.append("applied")
        return int(set_named(*args))

    with monkeypatch.context() as tracking:
        tracking.setattr(api, "SetNamedSecurityInfoW", record_write)
        tracking.setattr(_win32, "_anchor_acl_api", lambda: (api, kernel32))
        assert grant_every_account_access(str(tmp_path), directory=True)
    assert not repeat_writes, "repeating a shared ACL must not rewrite permissions"
    assert _dacl_sddl(tmp_path) == shared

    denied = tmp_path / "private" / "denied-anchor.lock"
    # FILE_WRITE_DATA denies the actual write without also denying
    # READ_CONTROL, which FILE_GENERIC_WRITE includes. Keep the original
    # creator permissions so inspection and finally restoration remain usable.
    with _temporary_dacl(denied, "D:P(D;;0x2;;;AU)", retain_existing=True):
        denied_entries = set(re.findall(r"\(([^)]*)\)", _dacl_sddl(denied)))
        assert not _authenticated_users_may_write(denied)
        with pytest.raises(PermissionError):
            denied.write_bytes(b"baseline forbidden write")
        assert grant_every_account_access(str(denied))
        granted_entries = set(re.findall(r"\(([^)]*)\)", _dacl_sddl(denied)))
        assert denied_entries <= granted_entries, "sharing must preserve explicit deny"
        with pytest.raises(PermissionError):
            denied.write_bytes(b"forbidden write after sharing")

    unrestricted = tmp_path / "unrestricted-anchor.lock"
    with _temporary_dacl(unrestricted, "D:NO_ACCESS_CONTROL"):
        assert "NO_ACCESS_CONTROL" in _dacl_sddl(unrestricted)
        assert grant_every_account_access(str(unrestricted))
        assert "NO_ACCESS_CONTROL" in _dacl_sddl(unrestricted)
        unrestricted.write_bytes(b"unrestricted write remains permitted")


@pytest.mark.skipif(sys.platform != "win32", reason="Windows access lists")
def test_an_anchor_this_process_did_not_create_keeps_its_access_list(
    tmp_path: Path,
) -> None:
    """Only a file this call created is widened.

    A service's own lock, observed through the shared path, must not become
    writable by every account on the machine because a peer looked at it.
    """
    private = tmp_path / "service.lock"
    private.write_bytes(b"")
    before = _dacl_sddl(private)

    held = claim_anchor(private, pid_record=True, shared=True)
    if held.descriptor is not None:
        release_anchor_claim(held.descriptor, pid_record=True)

    assert _dacl_sddl(private) == before
    assert not _authenticated_users_may_write(private)


#: SDDL rights that would let an account delete a file, or delete a child of a
#: directory (``sddl.h``).
_DELETING_MNEMONICS = ("FA", "GA", "SD", "DC")
_DELETE = 0x00010000
_FILE_DELETE_CHILD = 0x00000040


def _authenticated_users_may_delete(path: Path) -> bool:
    """Whether any entry lets every authenticated account delete *path* or in it."""
    for ace in re.findall(r"\(([^)]*)\)", _dacl_sddl(path)):
        fields = ace.split(";")
        if len(fields) < 6 or fields[0] != "A" or fields[5] != _AUTHENTICATED_USERS:
            continue
        rights = fields[2]
        if rights.startswith("0x"):
            if int(rights, 16) & (_DELETE | _FILE_DELETE_CHILD):
                return True
        elif any(mnemonic in rights for mnemonic in _DELETING_MNEMONICS):
            return True
    return False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows access lists")
def test_a_shared_anchor_directory_admits_every_account_to_every_file_in_it(
    tmp_path: Path,
) -> None:
    """Whoever creates a file in the shared directory, every account writes it.

    A file another account creates there - or anything not created through
    the anchor path - otherwise inherits read-only for everyone but its
    creator, and an account holding it read-only cannot record a loan.

    Mutations, each observed failing here and passing once restored: skipping
    the directory grant in ``claim_anchor`` failed on the directory admitting
    no authenticated account; dropping the grant's inheritable entry failed on
    the later file; widening the grant to full control failed on the
    directory's delete check.
    """
    directory = tmp_path / "vaultspec-rag"
    held = claim_anchor(
        directory / "gpu-owner.lock", pid_record=True, create_parent=True, shared=True
    )
    assert held.descriptor is not None
    release_anchor_claim(held.descriptor, pid_record=True)

    later = directory / "gpu-load-window.lock"
    later.write_bytes(b"")

    assert _authenticated_users_may_write(directory)
    assert _authenticated_users_may_write(later)
    # Catches the grant widening to delete: an account that can unlink an
    # anchor can separate its holder from it.
    assert not _authenticated_users_may_delete(directory)
    assert not _authenticated_users_may_delete(later)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows access lists")
def test_sharing_the_directory_repairs_an_anchor_created_before_it(
    tmp_path: Path,
) -> None:
    """An anchor from before the directory was shared becomes writable too.

    This is the machine an older release left behind: a directory its creator
    alone may write in, holding a GPU owner anchor no other account can write,
    so a CI service running as another account holds the GPU read-only and
    every loan it records is refused.

    Mutation: dropped the inheritable entry from the directory grant. Observed
    this fail on the old anchor admitting no authenticated account; restoring
    it passed.
    """
    directory = tmp_path / "vaultspec-rag"
    directory.mkdir()
    stale = directory / "gpu-owner.lock"
    stale.write_bytes(b"")
    assert not _authenticated_users_may_write(stale)

    held = claim_anchor(
        directory / "gpu-load-window.lock", create_parent=True, shared=True
    )
    assert held.descriptor is not None
    release_anchor_claim(held.descriptor)

    assert _authenticated_users_may_write(stale)
    assert not _authenticated_users_may_delete(stale)
