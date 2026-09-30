"""The crash-safe claim on one anchor file, one layer above the lock call.

An anchor claim is a non-blocking exclusive OS advisory lock on a file that
exists in order to be claimed: holding it means this process owns whatever the
anchor stands for, and being refused it means another process already does.
Three things in this project are owned that way - the machine's resident
service, the model-load window, and the machine's GPU test session - and each
had its own copy of the same sequence, which is how the copy that never receives
a fix becomes the one that ships the bug.

What the operating system guarantees is why the shape is worth naming: the lock
is released when the holding process dies, however it dies, so a crashed holder
strands nothing and no stale-file reclaim heuristic is needed. The file's
existence is never the authority, which is also why a claim is never unlinked -
a contender that acquired in the unlock-to-unlink window would have its freshly
locked file deleted underneath it, and the next claim would create a fresh inode
and take it uncontended, leaving two holders of one thing.

An anchor may carry a readable record of the owning pid, so a refused contender
can name who holds it. That record decides which byte is locked: a Windows lock
is mandatory rather than advisory, so a locked byte cannot be READ by another
process and the lock byte has to sit past the record. Locking byte zero of a
file whose body a contender must read costs that contender the pid it came for,
so one parameter governs both and neither is chosen on its own.

That record is published IN PLACE, which is the one thing about it worth
stating up front. The usual atomic-file move - write a temporary and rename it
over the target - is unavailable, because the OS lock making this anchor
authoritative is bound to this file and would not survive being replaced; a
rename would destroy the very claim the record describes. Atomicity therefore
comes from a fixed-width record written before anything is removed, so a
concurrent reader sees the previous owner or the new one and never a file with
no owner in it. Truncate-then-write would leave the anchor momentarily empty,
and an empty record read as "nobody owns this" is how a live holder gets
reported as nothing running.

An anchor standing for a piece of machine hardware - the GPU - is SHARED: it
lives in one directory every process on the machine resolves identically
(:func:`hardware_anchor_path`), and every account must be able to contend for
it. On Windows that directory is shared too, so every file in it is writable
by every account whichever account created it. A process still refused write
access to such an anchor locks it read-only instead: the lock is what
excludes, and a read-only holder simply cannot publish its pid.

Claims return ``HELD``, ``CONTENDED``, or ``UNAVAILABLE``. Existing-anchor
observations add ``ABSENT`` and ``FREE`` without ever retaining a descriptor.
``UNAVAILABLE`` is not an ownership answer: the anchor could not be opened, or
the platform ships neither advisory-lock primitive, so it carries the
coordination exception. A caller guarding something whose second holder would
corrupt state raises that fault; a caller for which losing cross-process
coordination costs less than refusing all work degrades and proceeds. Choosing
between those here would be wrong in one direction or the other for every
caller.
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "AnchorClaim",
    "AnchorOutcome",
    "claim_anchor",
    "hardware_anchor_path",
    "observe_existing_anchor",
    "probe_existing_anchor_holder",
    "publish_anchor_record",
    "read_anchor_record",
    "record_claim_owner",
    "release_anchor_claim",
]

# The byte an anchor carrying a pid record is locked at. One value serves both
# platforms: Windows permits locking a byte past end-of-file, and POSIX
# ``flock`` is whole-file and ignores the offset entirely. It sits far enough
# past the start that no plausible pid document reaches it.
_PID_RECORD_LOCK_OFFSET = 1 << 20

# Every owner record occupies exactly this many bytes, padded with spaces that
# JSON ignores. A constant width is what makes an in-place replacement whole: a
# record can never be shorter than the one it overwrites, so no tail of a
# previous owner can survive to be parsed alongside the current one.
_OWNER_RECORD_WIDTH = 64

# How long a reader waits for an owner record on an anchor that is locked but
# still zero length. That state has exactly one cause - a holder between
# creating the anchor and publishing its first record - so the wait is bounded
# by the holder's own next few instructions, well under a millisecond on an
# idle machine but tens of milliseconds on a loaded one, where the create, the
# lock, the write and the flush can each be descheduled. The bound is three
# orders of magnitude above the idle case deliberately: nothing but that one
# in-flight state ever waits at all, so overshooting costs an already-refused
# contender some idle time, while undershooting reports a live holder as
# absent - which is the whole failure this exists to prevent.
_OWNER_RECORD_WAIT_SECONDS = 1.0
_OWNER_RECORD_POLL_SECONDS = 0.002

# Every hardware anchor's name carries this prefix, as a directory on Windows
# and as a filename prefix where the anchors share a machine-wide directory.
_HARDWARE_ANCHOR_PREFIX = "vaultspec-rag"

# A shared anchor's mode: every account may open it for writing, so whichever
# account creates it first does not lock the others out of publishing a pid.
_SHARED_ANCHOR_MODE = 0o666

# The shared anchor directories this process has already widened. Widening is
# idempotent, but the model-load window claims on every load, and rewriting a
# directory's access list pushes it down to every file inside.
_shared_directories: set[str] = set()
_shared_directories_guard = threading.Lock()


def hardware_anchor_path(name: str) -> Path:
    """Return where the anchor *name* for a piece of machine hardware lives.

    The directory is the same for every process on the machine, whatever it
    was configured with, whichever account runs it, and whatever its
    temporary directory is: a hardware anchor resolved through anything a
    process can change would be private to whoever changed it and would
    exclude nothing. Windows asks the shell for the ProgramData folder, whose
    default permissions let every account create files beneath it.

    Elsewhere the directory must be one every account shares, which a POSIX
    host marks the same way everywhere: world-writable with the sticky bit.
    ``/dev/shm`` (Linux) and ``/Users/Shared`` (macOS) are preferred because
    the age-based cleaners that empty temporary directories leave them alone,
    so an anchor held for weeks is never deleted from under its holder - which
    would let the next claimant create a fresh file and hold it alongside. The
    temporary directory is the last resort, for a host - a container, say -
    that mounts neither; it is accepted only when it too is shared by every
    account, because a per-account ``TMPDIR`` would give each account a lock of
    its own.

    Raises:
        OSError: No machine-shared directory exists, or the shell could not
            resolve ProgramData.
    """
    if sys.platform == "win32":
        from ._win32 import program_data_directory

        return Path(program_data_directory()) / _HARDWARE_ANCHOR_PREFIX / name
    import tempfile

    for directory in (
        Path("/dev/shm"),
        Path("/Users/Shared"),
        Path(tempfile.gettempdir()),
    ):
        if _shared_by_every_account(directory):
            return directory / f"{_HARDWARE_ANCHOR_PREFIX}-{name}"
    raise OSError("this host has no directory every account shares for an anchor")


def _shared_by_every_account(directory: Path) -> bool:
    """Whether *directory* is a POSIX directory every account may create in."""
    import stat

    try:
        mode = directory.stat().st_mode
    except OSError:
        return False
    return (
        stat.S_ISDIR(mode) and bool(mode & stat.S_IWOTH) and bool(mode & stat.S_ISVTX)
    )


def _share_directory(directory: Path) -> None:
    """Let every account create and write anchors in *directory*, on Windows.

    The directory's creator otherwise decides who may write in it. A file
    another account then creates there, or one an older release created before
    this grant existed, carries full control for its creator and read-only for
    everyone else - and an account holding such an anchor through a read-only
    descriptor cannot record a loan, so a borrower is refused with no reason
    anyone can act on. Sharing the directory with an inheritable grant makes
    every file in it writable by every account, including the files already
    there; delete stays withheld, so no account can unlink an anchor from
    under its holder.

    Applied once per process, and only by an account allowed to change the
    directory's access list - its owner or an administrator. Another account's
    attempt is refused quietly, and the owner applies it on its next claim.
    POSIX needs nothing here: the hardware anchors share a sticky,
    world-writable directory rather than a directory of their own.
    """
    if sys.platform != "win32":
        return
    key = os.path.normcase(str(directory))
    with _shared_directories_guard:
        if key in _shared_directories:
            return
        _shared_directories.add(key)
    from ._win32 import grant_every_account_access

    grant_every_account_access(str(directory), directory=True)


def _open_anchor(anchor: Path, *, create: bool, shared: bool) -> int:
    """Open *anchor* for claiming, read-only when a shared one refuses writes.

    A shared anchor created by another account can be denied to this one for
    writing - by the creator's permissions, or on Linux by the protected-files
    rule that refuses ``O_CREAT`` on another account's file in a sticky
    directory. A lock needs only a readable descriptor, so the claim falls back
    to one rather than reading "not writable" as "cannot contend". The mode is
    widened after creation because the process umask narrows the one passed to
    ``open``; widening someone else's anchor is refused and needs no widening.

    Raises:
        OSError: The anchor could not be opened at all.
        ValueError: The path is not a usable filename.
    """
    if create and shared:
        created = _create_shared_anchor(anchor)
        if created is not None:
            return created
    flags = os.O_RDWR | (os.O_CREAT if create else 0)
    try:
        return os.open(anchor, flags, _SHARED_ANCHOR_MODE if shared else 0o600)
    except PermissionError:
        if not shared:
            raise
        return os.open(anchor, os.O_RDONLY)


def _create_shared_anchor(anchor: Path) -> int | None:
    """Create *anchor* writable by every account, or ``None`` if it exists.

    Only a file this call created is widened. An existing file keeps the mode
    its creator gave it: a shared anchor already carries it, and a private one
    - a service lock observed through the shared path - must not be made
    writable by other accounts merely because someone looked at it. ``None``
    also covers a directory this account cannot create in, which the ordinary
    open then reports.

    Windows carries the same widening as an access list rather than a mode:
    the file otherwise inherits full control for its creator and read-only for
    everyone else, and the next account to claim it holds the lock but cannot
    publish a record. The directory is widened separately, by
    :func:`_share_directory`; this grant covers an anchor whose directory
    belongs to an account that has not shared it yet.
    """
    try:
        fd = os.open(anchor, os.O_RDWR | os.O_CREAT | os.O_EXCL, _SHARED_ANCHOR_MODE)
    except (FileExistsError, PermissionError):
        return None
    if sys.platform == "win32":
        from ._win32 import grant_every_account_access

        grant_every_account_access(str(anchor))
        return fd
    with contextlib.suppress(OSError):
        os.fchmod(fd, _SHARED_ANCHOR_MODE)
    return fd


class AnchorOutcome(Enum):
    """What one attempt on an anchor produced."""

    HELD = "held"
    CONTENDED = "contended"
    ABSENT = "absent"
    FREE = "free"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class AnchorClaim:
    """The result of one attempt to claim an anchor.

    ``descriptor`` is an open, locked file descriptor exactly when ``outcome``
    is ``HELD``, and the claim lasts for as long as it stays open. ``FREE`` is
    an observation that acquired and released an existing anchor before it was
    returned. ``holder_pid`` is the pid this attempt found in possession - this
    process when the claim was taken, the recorded owner when it was refused -
    and is 0 whenever that cannot be established. ``fault`` carries the
    exception that made the mechanism unusable, and is set exactly when
    ``outcome`` is ``UNAVAILABLE``.
    """

    outcome: AnchorOutcome
    anchor: Path
    descriptor: int | None
    holder_pid: int
    fault: Exception | None


def read_anchor_record(anchor: Path) -> object | None:
    """Return the leading JSON document published in *anchor*, or ``None``.

    Parses the leading JSON document and ignores whatever follows it, so
    neither the pad a fixed-width record carries nor a tail left by a longer
    foreign body can turn a perfectly good record into no record at all.

    A ZERO-LENGTH anchor is waited out to a bound rather than read as no
    record, because it is not evidence of no owner: a holder creates the
    anchor and locks it before it can publish anything, so an empty file under
    a refused lock is a record in flight. Reading that as "nobody owns this"
    is precisely what lets a live holder be reported as absent. A body that is
    present but unparseable gets no wait - no writer is going to turn it into
    a record - and neither does an anchor nobody holds.
    """
    deadline = time.monotonic() + _OWNER_RECORD_WAIT_SECONDS
    while True:
        try:
            settled = anchor.stat().st_size != 0
        except OSError:
            return None
        # Emptiness decides whether to wait, and it is checked BEFORE the read
        # rather than after it. Reading first and judging emptiness afterwards
        # mistakes the publication landing between the two for a settled body
        # that will never carry a record, and gives up on the very record it
        # was waiting for.
        if settled or time.monotonic() >= deadline:
            break
        time.sleep(_OWNER_RECORD_POLL_SECONDS)
    try:
        body = anchor.read_text(encoding="utf-8")
    except (OSError, ValueError):
        return None
    try:
        recorded, _ = json.JSONDecoder().raw_decode(body.lstrip())
    except ValueError:
        return None
    return recorded


def _recorded_owner(anchor: Path) -> int:
    """Return the pid recorded in *anchor*, or 0 when none is published.

    Informational, for a refusal message only; the OS lock is the authority, so
    a non-JSON or pid-less record costs a refused caller the pid it would have
    named and nothing more. A boolean is rejected rather than admitted as the
    integer it subclasses.
    """
    match read_anchor_record(anchor):
        case {"pid": int() as pid} if type(pid) is int and pid > 0:
            return pid
        case _:
            return 0


def claim_anchor(
    anchor: Path,
    *,
    pid_record: bool = False,
    create_parent: bool = False,
    shared: bool = False,
) -> AnchorClaim:
    """Attempt one non-blocking exclusive claim on *anchor*. Never raises.

    Args:
        anchor: The file to claim. Created if absent, never removed.
        pid_record: The anchor's body carries a readable owner pid. Locks the
            byte past that record so a mandatory platform lock leaves it
            readable, and reads it when the claim is refused so the caller can
            name the holder. An anchor with no such record is locked at byte
            zero and reports no holder.
        create_parent: Create the anchor's directory first. A configured root
            may not exist yet; a system temp directory always does. With
            *shared*, the directory is shared with every account as well.
        shared: Every account on the machine contends for this anchor. It is
            created writable by all of them, and locked through a read-only
            descriptor when another account's copy refuses this one writes.

    Returns:
        A ``HELD`` claim carrying the locked descriptor, a ``CONTENDED`` claim
        naming the recorded holder, or an ``UNAVAILABLE`` claim carrying the
        exception that made the claim impossible to attempt.
    """
    from ._fd_lock import lock_fd_exclusive

    offset = _PID_RECORD_LOCK_OFFSET if pid_record else 0
    try:
        if create_parent:
            anchor.parent.mkdir(parents=True, exist_ok=True)
            if shared:
                _share_directory(anchor.parent)
        fd = _open_anchor(anchor, create=True, shared=shared)
    except (OSError, ValueError) as exc:
        return AnchorClaim(
            outcome=AnchorOutcome.UNAVAILABLE,
            anchor=anchor,
            descriptor=None,
            holder_pid=0,
            fault=exc,
        )
    try:
        lock_fd_exclusive(fd, offset=offset)
    except OSError:
        # A refused non-blocking lock call on a descriptor that opened cleanly
        # is another holder in every practical case, and reading it as one is
        # the safe direction: it refuses this caller rather than admitting it
        # alongside a holder the call failed to name.
        holder = _recorded_owner(anchor) if pid_record else 0
        os.close(fd)
        return AnchorClaim(
            outcome=AnchorOutcome.CONTENDED,
            anchor=anchor,
            descriptor=None,
            holder_pid=holder,
            fault=None,
        )
    except ImportError as exc:
        os.close(fd)
        return AnchorClaim(
            outcome=AnchorOutcome.UNAVAILABLE,
            anchor=anchor,
            descriptor=None,
            holder_pid=0,
            fault=exc,
        )
    return AnchorClaim(
        outcome=AnchorOutcome.HELD,
        anchor=anchor,
        descriptor=fd,
        holder_pid=os.getpid(),
        fault=None,
    )


def observe_existing_anchor(
    anchor: Path,
    *,
    pid_record: bool = False,
    shared: bool = False,
) -> AnchorClaim:
    """Observe one existing anchor without creating or retaining it.

    This narrowly serves an already-chosen identity path. It never creates a
    parent or anchor, writes no PID record, and releases any momentary
    successful lock before returning. ``ABSENT`` is therefore a trustworthy
    refusal after deletion; ``CONTENDED`` carries the readable current holder
    PID when ``pid_record`` is set; and ``UNAVAILABLE`` preserves a real open
    failure rather than treating it as absence. A *shared* anchor another
    account created is observed through a read-only descriptor, as it is
    claimed.
    """
    from ._fd_lock import lock_fd_exclusive

    try:
        fd = _open_anchor(anchor, create=False, shared=shared)
    except FileNotFoundError:
        return AnchorClaim(
            outcome=AnchorOutcome.ABSENT,
            anchor=anchor,
            descriptor=None,
            holder_pid=0,
            fault=None,
        )
    except (OSError, ValueError) as exc:
        return AnchorClaim(
            outcome=AnchorOutcome.UNAVAILABLE,
            anchor=anchor,
            descriptor=None,
            holder_pid=0,
            fault=exc,
        )
    try:
        lock_fd_exclusive(fd, offset=_PID_RECORD_LOCK_OFFSET if pid_record else 0)
    except OSError:
        # A refused non-blocking lock is fail-closed as a contender even when
        # the owner record disappeared between lock refusal and this read.
        holder = _recorded_owner(anchor) if pid_record else 0
        with contextlib.suppress(OSError):
            os.close(fd)
        return AnchorClaim(
            outcome=AnchorOutcome.CONTENDED,
            anchor=anchor,
            descriptor=None,
            holder_pid=holder,
            fault=None,
        )
    except ImportError as exc:
        with contextlib.suppress(OSError):
            os.close(fd)
        return AnchorClaim(
            outcome=AnchorOutcome.UNAVAILABLE,
            anchor=anchor,
            descriptor=None,
            holder_pid=0,
            fault=exc,
        )
    release_anchor_claim(fd, pid_record=pid_record)
    return AnchorClaim(
        outcome=AnchorOutcome.FREE,
        anchor=anchor,
        descriptor=None,
        holder_pid=0,
        fault=None,
    )


def probe_existing_anchor_holder(
    anchor: Path,
    *,
    pid_record: bool = False,
) -> int | None:
    """Return a positive PID only for a contended no-create observation."""
    observation = observe_existing_anchor(anchor, pid_record=pid_record)
    if observation.outcome is AnchorOutcome.CONTENDED and observation.holder_pid > 0:
        return observation.holder_pid
    return None


def publish_anchor_record(
    descriptor: int,
    record: Mapping[str, object],
    *,
    width: int = _OWNER_RECORD_WIDTH,
) -> None:
    """Durably replace a held anchor's record in place, never leaving it empty.

    The record is published IN PLACE because the OS lock making the anchor
    authoritative is bound to this file: a write-temp-and-rename would destroy
    the very claim the record describes. Order is the whole guarantee here.
    The complete fixed-width frame goes down first, so from the instant that
    write returns the anchor begins with a readable record and never passes
    through a state a concurrent reader could read as unowned. Only then is a
    longer foreign body cut back, and because every record written to one
    anchor shares its *width* that truncation can never be what removes the
    record's own tail.

    *width* must therefore be constant per anchor file. The pad is trailing
    spaces inside the file after the same JSON document the record has always
    been, so a reader that simply parses the whole file still recovers it.
    """
    payload = json.dumps(dict(record), separators=(",", ":")).encode("utf-8")
    if len(payload) > width:
        raise OSError("the anchor record exceeds its fixed width")
    frame = payload.ljust(width, b" ")
    os.lseek(descriptor, 0, os.SEEK_SET)
    written = os.write(descriptor, frame)
    if written != len(frame):
        raise OSError("could not write the complete anchor record")
    os.ftruncate(descriptor, len(frame))
    os.fsync(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    recorded: object = json.loads(os.read(descriptor, len(frame)))
    if recorded != dict(record):
        raise OSError("could not read back the anchor record")


def record_claim_owner(descriptor: int) -> None:
    """Durably replace a held pid-record anchor's current owner witness.

    The caller must release its claim when this operation fails. A contended
    process relies on this record to correlate the live lock holder with the
    machine discovery pointer, so accepting a lock without its PID witness
    would admit an unverifiable resident service.
    """
    pid = os.getpid()
    if pid <= 0:
        raise OSError("the current process has no positive PID to record")
    publish_anchor_record(descriptor, {"pid": pid})


def release_anchor_claim(descriptor: int, *, pid_record: bool = False) -> None:
    """Release and close one held claim, best effort.

    *pid_record* must match the value the claim was taken with, because it
    decides which byte was locked and a release naming another byte leaves the
    claim held. Nothing is raised: the descriptor is being closed or the
    process is exiting on every path that reaches here, and a failed release
    has no remedy a caller could apply.
    """
    from ._fd_lock import unlock_fd

    try:
        unlock_fd(descriptor, offset=_PID_RECORD_LOCK_OFFSET if pid_record else 0)
    finally:
        with contextlib.suppress(OSError):
            os.close(descriptor)
