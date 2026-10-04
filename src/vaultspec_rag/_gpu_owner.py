"""One process per machine owns the GPU, and every model load asks it first.

vaultspec-rag brings exactly one model stack up per machine: the resident
service's. Everything else - the CLI, the MCP adapters, other releases, other
worktrees - is a client of that service. Nothing below this module enforced
that. The service's own singleton lock lives beside its configured storage, so
a second storage directory made a second singleton, and the device admission
gate asks whether the card has room, never who holds it.

So ownership has an anchor of its own: a hardware anchor, one file every process
on the machine resolves identically whatever it was configured with, claimed
without blocking by the first process that loads a model and held until that
process exits. Every model load funnels through ``load_accelerator``, which asks
here before torch is even imported, so there is one check and no path around it.

Three answers let a load proceed:

- **Owned here.** This process holds the anchor. The resident service claims it
  on its first model load and keeps it across a pause, so ownership never lapses
  while the service lives.
- **Lent here.** Another process holds the anchor, and its record lends the GPU
  to this process or one of its ancestors. The service lends only to a borrower
  whose pause it has verified and bound, and reclaims on resume. The owner never
  lets go, so a borrow has no gap for a stranger to win, and the loan covers the
  borrower's whole process tree - the test daemons a GPU test lane starts
  included.
- **Free.** Nobody holds the anchor, and no service - one still loading, or one
  from a release that predates this anchor - holds a storage-scoped service
  lock. This process then claims the anchor.

Anything else refuses with :class:`GpuOwnedError`, including an anchor that
cannot be opened: an owner that cannot be verified is not permission to
allocate.

Every function takes an optional *anchor* so the claim, loan and refusal
behaviour stay exercisable against a private file, without contending for the
machine's own anchor, which a live service may legitimately be holding.
"""

from __future__ import annotations

import contextlib
import functools
import logging
import os
import threading
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping
    from pathlib import Path

    from ._process_probe import LineageEntry

logger = logging.getLogger(__name__)

__all__ = [
    "GpuOwnedError",
    "GpuOwnerState",
    "GpuOwnership",
    "gpu_owned_message",
    "gpu_owned_remediation",
    "gpu_owner_anchor_path",
    "gpu_owner_wire",
    "lend_gpu",
    "observe_gpu_owner",
    "reclaim_gpu",
    "require_gpu_ownership",
]

_ANCHOR_NAME = "gpu-owner.lock"

#: Every owner record on the anchor is exactly this wide. It holds an owner pid,
#: a lent pid and that process's start time; a constant width is what lets the
#: owner rewrite its record in place without a reader ever seeing a torn one.
_OWNER_RECORD_WIDTH = 128

#: How closely a loan's recorded start time must match the process claiming it.
#: Both sides read the figure from the same kernel field and JSON carries a
#: float exactly, so the margin absorbs rounding only - far below the interval
#: in which a pid could be recycled into a different process.
_LOAN_START_TOLERANCE_SECONDS = 1e-3

#: A claim refused by a holder that is not alive is retried, briefly. The only
#: such holder is a momentary observer - a pre-flight probing the anchor - and
#: it lets go within its own next instructions; refusing on it would turn a
#: status check into a failed service start.
_STALE_CONTENTION_RETRIES = 5
_STALE_CONTENTION_WAIT_SECONDS = 0.05


class GpuOwnerState(StrEnum):
    """Who owns the GPU, from the point of view of the process asking."""

    OWNED_HERE = "owned_here"
    LENT_HERE = "lent_here"
    FREE = "free"
    OWNED_ELSEWHERE = "owned_elsewhere"
    SERVICE_HOLDS_MACHINE = "service_holds_machine"
    UNVERIFIABLE = "unverifiable"

    @property
    def permits_compute(self) -> bool:
        """Whether the asking process may bring a model stack up."""
        return self in {
            GpuOwnerState.OWNED_HERE,
            GpuOwnerState.LENT_HERE,
            GpuOwnerState.FREE,
        }


@dataclass(frozen=True, slots=True)
class GpuOwnership:
    """One answer about the GPU's owner.

    ``holder_pid`` names the owning process when it is known and alive, and is
    0 otherwise - an owner that cannot publish its pid still owns. ``detail``
    says why an owner could not be verified, and is empty for every other state.
    """

    state: GpuOwnerState
    holder_pid: int
    detail: str = ""


class GpuOwnedError(RuntimeError):
    """This process may not load models, because it does not own the GPU."""

    def __init__(self, ownership: GpuOwnership) -> None:
        """Carry the answer that refused the load, and render its message."""
        self.ownership = ownership
        super().__init__(gpu_owned_message(ownership))


def _holder_phrase(pid: int) -> str:
    return f" (pid {pid})" if pid > 0 else ""


def gpu_owned_message(ownership: GpuOwnership) -> str:
    """Say, in one paragraph, why this process may not load models."""
    holder = _holder_phrase(ownership.holder_pid)
    match ownership.state:
        case GpuOwnerState.SERVICE_HOLDS_MACHINE:
            return (
                f"A vaultspec-rag service{holder} holds this machine, so this "
                "process will not load a second model stack beside it. The "
                "service is either still loading its models or from a release "
                "that predates GPU ownership."
            )
        case GpuOwnerState.UNVERIFIABLE:
            return (
                "Could not establish which process owns this machine's GPU "
                f"({ownership.detail}). vaultspec-rag will not load a model stack "
                "it cannot prove is the only one on the device."
            )
        case _:
            return (
                f"Another vaultspec-rag process{holder} owns this machine's GPU. "
                "vaultspec-rag runs one model stack per machine, so this process "
                "will not load a second one."
            )


def gpu_owned_remediation(
    ownership: GpuOwnership, *, starting_service: bool = False
) -> tuple[str, ...]:
    """Return the next actions that can actually resolve *ownership*.

    What resolves a refusal depends on what was refused. Local compute is
    resolved by using the service instead, or by borrowing its GPU; a service
    start is resolved only by the owner going away, so it is never told to
    change search flags.
    """
    from ._operator_commands import (
        server_start_command,
        server_status_command,
        server_stop_command,
    )

    holder = _holder_phrase(ownership.holder_pid)
    match ownership.state:
        case GpuOwnerState.UNVERIFIABLE:
            return (
                "Make sure this account can create and lock "
                f"{_describe_anchor()}, then retry.",
            )
        case GpuOwnerState.SERVICE_HOLDS_MACHINE if starting_service:
            return (
                f"Stop that service{holder} with {server_stop_command()}, run "
                "with the storage directory it was started with.",
                f"Then start this one: {server_start_command()}.",
            )
        case GpuOwnerState.SERVICE_HOLDS_MACHINE:
            return (
                "Search and index through the running service rather than "
                "locally: drop --allow-fallback and unset VAULTSPEC_RAG_LOCAL_ONLY.",
                "If it is from another release, which this client cannot use, "
                f"replace it with this one first: {server_stop_command()}, then "
                f"{server_start_command()}.",
            )
        case _ if starting_service:
            return (
                f"Stop the process that owns the GPU{holder}, or let it finish. "
                "A vaultspec-rag service configured with another storage "
                f"directory stops with {server_stop_command()} run under that "
                "configuration.",
                f"Then start this one: {server_start_command()}.",
            )
        case _:
            return (
                "Search and index through the running service rather than "
                "locally: drop --allow-fallback and unset VAULTSPEC_RAG_LOCAL_ONLY.",
                "For explicit local GPU work, borrow the GPU from the service: "
                "rerun the index with --borrow-gpu.",
                f"If the owner is not the service, wait for it to exit; "
                f"{server_status_command()} shows the service.",
            )


def gpu_owner_wire(ownership: GpuOwnership) -> dict[str, object]:
    """Project one ownership answer into the shape every envelope carries.

    A refused search and a refused start report the same condition, so both
    carry this one object under the same key, whichever part of their own
    envelope holds a command's detail.
    """
    return {
        "state": ownership.state.value,
        "holder_pid": ownership.holder_pid,
        "detail": ownership.detail,
    }


def _describe_anchor() -> str:
    try:
        return str(gpu_owner_anchor_path())
    except OSError:
        return "the machine's GPU owner anchor"


@functools.cache
def gpu_owner_anchor_path() -> Path:
    """Return the machine's GPU owner anchor.

    Cached: the location is a property of the machine, and every model load
    asks for it, where resolving it can mean a call into the Windows shell.

    Raises:
        OSError: The machine's hardware-anchor directory could not be resolved.
    """
    from ._anchor_claim import hardware_anchor_path

    return hardware_anchor_path(_ANCHOR_NAME)


# The anchors this process holds, by path, each for the rest of its life. A
# descriptor kept reachable here is what keeps the OS lock held. The guard
# serialises claims so a second thread of this process is never refused by
# the first thread's own hold and read as a foreign owner.
_held: dict[str, int] = {}
_guard = threading.RLock()

# This process's own lineage, read once. A process's own pid, its ancestors'
# pids and their start times do not change while it lives, and reading them
# walks the process table - a quarter of a second on a loaded Windows host - on
# a path a borrowed GPU takes at every model load.
_lineage: tuple[LineageEntry, ...] | None = None


def _forget_inherited_state() -> None:
    """Drop what a forked child inherited but does not itself own.

    A child shares its parent's open lock rather than holding one of its own,
    and its lineage is not its parent's, so both are forgotten and asked again.
    Its copies of the parent's descriptors are closed rather than abandoned:
    the parent's own descriptor keeps the lock, and a child that held on to the
    copies would keep it alive past the parent for no owner at all.
    """
    global _lineage
    for descriptor in _held.values():
        with contextlib.suppress(OSError):
            os.close(descriptor)
    _held.clear()
    _lineage = None


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_forget_inherited_state)


def require_gpu_ownership(*, anchor: Path | None = None) -> GpuOwnership:
    """Return this process's permission to load models, claiming the GPU if free.

    Raises:
        GpuOwnedError: Another process owns the GPU and has not lent it here,
            or no owner can be verified.
    """
    ownership = _claim_or_observe(anchor, claim=True)
    if not ownership.state.permits_compute:
        raise GpuOwnedError(ownership)
    return ownership


def observe_gpu_owner(*, anchor: Path | None = None) -> GpuOwnership:
    """Report who owns the GPU without claiming it. Never raises.

    For a pre-flight that must refuse early and legibly - a service start, a
    local search - without taking ownership merely by asking.
    """
    return _claim_or_observe(anchor, claim=False)


def lend_gpu(borrower_pid: int, *, anchor: Path | None = None) -> bool:
    """Lend this process's GPU to *borrower_pid* and every process it starts.

    Returns whether the loan was recorded. Nothing is lent by a process that
    does not own the GPU, to a process whose start time cannot be read, or
    through an anchor this process holds without write access; each of those
    leaves the borrower refused, which is the safe direction.
    """
    from ._process_probe import pid_start_time

    start = pid_start_time(borrower_pid)
    if start <= 0.0:
        logger.warning("cannot lend the GPU to pid %d: it cannot be read", borrower_pid)
        return False
    with _guard:
        descriptor = _held_descriptor(anchor)
        if descriptor is None:
            return False
        return _publish(
            descriptor,
            {"pid": os.getpid(), "lent_to": borrower_pid, "lent_start": start},
        )


def reclaim_gpu(*, anchor: Path | None = None) -> None:
    """End any loan this process's GPU is on. A no-op for a non-owner."""
    with _guard:
        descriptor = _held_descriptor(anchor)
        if descriptor is not None:
            _publish(descriptor, {"pid": os.getpid()})


def _held_descriptor(anchor: Path | None) -> int | None:
    try:
        path = anchor or gpu_owner_anchor_path()
    except OSError:
        return None
    return _held.get(str(path))


def _claim_or_observe(anchor: Path | None, *, claim: bool) -> GpuOwnership:
    try:
        path = anchor or gpu_owner_anchor_path()
    except OSError as exc:
        return GpuOwnership(
            GpuOwnerState.UNVERIFIABLE, 0, f"no machine-wide anchor directory: {exc}"
        )
    with _guard:
        if str(path) in _held:
            return GpuOwnership(GpuOwnerState.OWNED_HERE, os.getpid())
        if claim:
            return _claim(path)
    return _observe(path)


def _take(path: Path) -> int | GpuOwnership:
    """Lock *path*, or answer who holds it; retry only a momentary observer."""
    from ._anchor_claim import AnchorOutcome, claim_anchor

    attempt = 0
    while True:
        taken = claim_anchor(path, pid_record=True, create_parent=True, shared=True)
        if taken.outcome is AnchorOutcome.UNAVAILABLE:
            return _unverifiable(path, taken.fault)
        if taken.descriptor is not None:
            return taken.descriptor
        contended = _contended(path)
        if (
            contended.state is GpuOwnerState.LENT_HERE
            or contended.holder_pid > 0
            or attempt >= _STALE_CONTENTION_RETRIES
        ):
            return contended
        attempt += 1
        time.sleep(_STALE_CONTENTION_WAIT_SECONDS)


def _claim(path: Path) -> GpuOwnership:
    """Claim *path* for this process, or report who holds it. Guard held.

    The anchor is asked first, so a process lent the GPU is answered by the loan
    even while the lending service holds its storage lock. The owner record is
    published the moment the anchor is taken, before the service lock is read,
    so a contender racing this claim reads a live pid rather than waiting out
    an empty record.
    """
    from ._anchor_claim import release_anchor_claim

    descriptor = _take(path)
    if isinstance(descriptor, GpuOwnership):
        return descriptor
    # A holder that cannot write its record - another account's anchor, locked
    # read-only - still owns; it just cannot be named by the processes it
    # refuses.
    _publish(descriptor, {"pid": os.getpid()})
    try:
        service_pid = _service_holding_machine()
    except (ImportError, OSError, RuntimeError) as exc:
        release_anchor_claim(descriptor, pid_record=True)
        return GpuOwnership(
            GpuOwnerState.UNVERIFIABLE, 0, f"the service lock could not be read: {exc}"
        )
    if service_pid is not None:
        # Named for anyone who read this claim while it stood: the service is
        # the reason nothing may load, not the process that briefly held it.
        _publish(descriptor, {"pid": service_pid})
        release_anchor_claim(descriptor, pid_record=True)
        return GpuOwnership(GpuOwnerState.SERVICE_HOLDS_MACHINE, service_pid)
    _held[str(path)] = descriptor
    return GpuOwnership(GpuOwnerState.OWNED_HERE, os.getpid())


def _observe(path: Path) -> GpuOwnership:
    from ._anchor_claim import AnchorOutcome, observe_existing_anchor

    seen = observe_existing_anchor(path, pid_record=True, shared=True)
    if seen.outcome is AnchorOutcome.UNAVAILABLE:
        return _unverifiable(path, seen.fault)
    if seen.outcome is AnchorOutcome.CONTENDED:
        return _contended(path)
    try:
        service_pid = _service_holding_machine()
    except (ImportError, OSError, RuntimeError) as exc:
        return GpuOwnership(
            GpuOwnerState.UNVERIFIABLE, 0, f"the service lock could not be read: {exc}"
        )
    if service_pid is not None:
        return GpuOwnership(GpuOwnerState.SERVICE_HOLDS_MACHINE, service_pid)
    return GpuOwnership(GpuOwnerState.FREE, 0)


def _unverifiable(path: Path, fault: Exception | None) -> GpuOwnership:
    return GpuOwnership(
        GpuOwnerState.UNVERIFIABLE, 0, f"{path} could not be opened: {fault}"
    )


def _contended(path: Path) -> GpuOwnership:
    """Read the record of an anchor someone else holds: lent here, or not."""
    from ._anchor_claim import read_anchor_record
    from ._process_probe import pid_alive

    record = read_anchor_record(path)
    owner, lent_to, lent_start = _parse_record(record)
    holder = owner if owner > 0 and pid_alive(owner) else 0
    if holder and lent_to > 0 and _in_own_lineage(lent_to, lent_start):
        return GpuOwnership(GpuOwnerState.LENT_HERE, holder)
    return GpuOwnership(GpuOwnerState.OWNED_ELSEWHERE, holder)


def _parse_record(record: object) -> tuple[int, int, float]:
    """Return ``(owner pid, lent pid, lent start time)``, zeros where absent.

    Booleans are refused where integers are expected; JSON admits them and
    Python's ``bool`` is an ``int``, which would otherwise read ``true`` as pid 1.
    """
    if not isinstance(record, dict):
        return (0, 0, 0.0)
    fields = cast("Mapping[str, object]", record)

    def whole(name: str) -> int:
        value = fields.get(name)
        if isinstance(value, bool) or not isinstance(value, int):
            return 0
        return max(value, 0)

    start = fields.get("lent_start")
    if isinstance(start, bool) or not isinstance(start, (int, float)):
        return (whole("pid"), whole("lent_to"), 0.0)
    return (whole("pid"), whole("lent_to"), float(start))


def _in_own_lineage(pid: int, start_time: float) -> bool:
    """Whether *pid*, started at *start_time*, is this process or an ancestor."""
    global _lineage
    if _lineage is None:
        from ._process_probe import process_lineage

        _lineage = process_lineage()
    return any(
        entry.pid == pid
        and abs(entry.start_time - start_time) <= _LOAN_START_TOLERANCE_SECONDS
        for entry in _lineage
    )


def _service_holding_machine() -> int | None:
    """Return the pid of a service holding the configured service lock.

    ``None`` when no other process holds it. This is how a service is seen
    between claiming its machine and loading its first model, before it holds
    the GPU anchor itself.

    Raises:
        ImportError: The platform ships no advisory-lock primitive.
        OSError: The service lock could not be read.
    """
    from ._machine_lock import probe_machine_lock

    probe = probe_machine_lock()
    if probe.held and probe.holder_pid != os.getpid():
        return probe.holder_pid
    return None


def _publish(descriptor: int, record: Mapping[str, object]) -> bool:
    """Rewrite the owner record in place; ``False`` when it cannot be written."""
    from ._anchor_claim import publish_anchor_record

    try:
        publish_anchor_record(descriptor, record, width=_OWNER_RECORD_WIDTH)
    except OSError as exc:
        logger.warning("could not publish the GPU owner record: %s", exc)
        return False
    return True
