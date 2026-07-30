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
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

__all__ = [
    "AnchorClaim",
    "AnchorOutcome",
    "claim_anchor",
    "observe_existing_anchor",
    "probe_existing_anchor_holder",
    "record_claim_owner",
    "release_anchor_claim",
]

# The byte an anchor carrying a pid record is locked at. One value serves both
# platforms: Windows permits locking a byte past end-of-file, and POSIX
# ``flock`` is whole-file and ignores the offset entirely. It sits far enough
# past the start that no plausible pid document reaches it.
_PID_RECORD_LOCK_OFFSET = 1 << 20


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


def _recorded_owner(anchor: Path) -> int:
    """Return the pid recorded in *anchor*, or 0 when it cannot be read.

    Informational, for a refusal message only; the OS lock is the authority, so
    an absent, truncated, or non-JSON record costs a refused caller the pid it
    would have named and nothing more.
    """
    try:
        recorded = json.loads(anchor.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    match recorded:
        case {"pid": int() as pid}:
            return pid
        case _:
            return 0


def claim_anchor(
    anchor: Path,
    *,
    pid_record: bool = False,
    create_parent: bool = False,
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
            may not exist yet; a system temp directory always does.

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
        fd = os.open(anchor, os.O_RDWR | os.O_CREAT, 0o600)
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
) -> AnchorClaim:
    """Observe one existing anchor without creating or retaining it.

    This narrowly serves an already-chosen identity path. It never creates a
    parent or anchor, writes no PID record, and releases any momentary
    successful lock before returning. ``ABSENT`` is therefore a trustworthy
    refusal after deletion; ``CONTENDED`` carries the readable current holder
    PID when ``pid_record`` is set; and ``UNAVAILABLE`` preserves a real open
    failure rather than treating it as absence.
    """
    from ._fd_lock import lock_fd_exclusive

    try:
        fd = os.open(anchor, os.O_RDWR)
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
    payload = json.dumps({"pid": pid}, separators=(",", ":")).encode("utf-8")
    os.ftruncate(descriptor, 0)
    os.lseek(descriptor, 0, os.SEEK_SET)
    written = os.write(descriptor, payload)
    if written != len(payload):
        raise OSError("could not write the complete anchor owner PID record")
    os.fsync(descriptor)
    os.lseek(descriptor, 0, os.SEEK_SET)
    recorded: object = json.loads(os.read(descriptor, len(payload) + 1))
    if recorded != {"pid": pid}:
        raise OSError("could not read back the anchor owner PID record")


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
