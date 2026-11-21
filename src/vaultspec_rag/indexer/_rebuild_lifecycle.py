"""One durable reset of the selected sources, and the epoch that fences it.

An explicit rebuild discards the selected source's index before it writes the
replacement, and every content kind means the same thing by that. This module
is the single owner of the discard: it records intent and retires the source's
publication authority, hard-deletes every collection the source owns, recreates
the canonical collection empty, and only then records the reset complete.
Content producers write nothing before completion.

Each step is recorded in the run ledger before the next begins, so a run that
dies mid-reset is finished by replaying the same rebuild generation: the
completed steps are idempotent and the recorded phase says where to resume.
A different generation starts a new reset and advances the source's epoch.
Every explicit rebuild enters ingestion through one reset keyed by its own
generation, so a crash between intent and completion is finished by the next
attempt and never leaves discarded content where replacement writes land.

The epoch is the fence. A reader or writer captures it before touching
storage and validates it afterwards; any reset recorded in between makes the
work stale, so nothing observed from discarded storage is returned and nothing
an old attempt writes lands in the replacement unnoticed.

A new explicit rebuild and the continuation of one are different operations.
A rebuild carries a :class:`RebuildClaim`: a new request claims nothing and
always resets again, while a resumed, retried, restored or replayed request
claims the generation its durable request recorded and continues only that
generation, keeping the replacement work it confirmed. A claim on a
generation another rebuild has since replaced is refused, never resumed.
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from .._source_types import PublicSourceType, concrete_sources
from .._store_models import other_backend_code_pointer, retire_served_code_pointer
from .._store_writes import workspace_volume_path
from ..job_control import NO_RUN_CONTROL
from ._run_ledger_models import (
    RESUMABLE_STATES,
    SourceResetEpochError,
    SourceResetPhase,
    index_run_ledger_path,
)
from ._run_ledger_runtime import RunLedger
from ._run_ledger_source_resets import read_source_reset

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from .._store_writes import StoreWritePolicy
    from ..job_control import RunControl
    from ..store_runtime import VaultStore
    from ._run_ledger_models import RunSignature, SourceResetState
    from ._run_policy import RunPolicy

__all__ = [
    "NEW_REBUILD",
    "RebuildClaim",
    "RebuildSupersededError",
    "ResetEpochFence",
    "capture_reset_epoch",
    "enter_rebuild_ingestion",
    "rebuild_claim",
    "refuse_superseded_claim",
    "reset_selected_sources",
]

logger = logging.getLogger(__name__)


def _ledger_path(root: pathlib.Path) -> pathlib.Path:
    return index_run_ledger_path(workspace_volume_path(root.resolve()))


class RebuildSupersededError(SourceResetEpochError):
    """A rebuild claims a generation another rebuild has since replaced.

    The replacing rebuild discarded everything the claimed generation wrote,
    so continuing it would certify work that no longer exists. Only a new
    rebuild request may run.
    """


@dataclass(frozen=True, slots=True)
class RebuildClaim:
    """Which rebuild one attempt carries out.

    ``generation_id`` is ``None`` for a new explicit rebuild, which never
    continues a generation an earlier rebuild left and so resets the source
    again. A resumed, retried, restored or replayed request names the
    generation its durable request recorded and continues only that one.

    ``bind`` durably records the generation an attempt opened, before that
    generation's reset is recorded, so every later attempt of the same request
    claims it. A caller without a durable request records nothing.
    """

    generation_id: str | None = None
    bind: Callable[[str], None] | None = None


#: The claim of a request that starts a rebuild rather than continuing one.
NEW_REBUILD: Final = RebuildClaim()

#: The claim of the rebuild running in this context. A durable request binds
#: its own around one attempt; every other caller starts a new rebuild.
rebuild_claim: ContextVar[RebuildClaim] = ContextVar(
    "rebuild_claim", default=NEW_REBUILD
)


def refuse_superseded_claim(
    ledger: RunLedger,
    signature: RunSignature,
    claim: RebuildClaim,
) -> None:
    """Refuse a claim on a generation another rebuild has since replaced.

    Runs before the claimed generation is reopened, so a refusal changes no
    durable state. Every reset invalidates each resumable generation except
    its own owner, so a claimed generation still resumable has not been
    replaced even when the recorded reset belongs to an earlier rebuild: it
    was bound before its own reset was recorded.

    Raises:
        RebuildSupersededError: The source's reset belongs to another
            generation and the claimed one is no longer resumable.
    """
    claimed = claim.generation_id
    if claimed is None:
        return
    reset = ledger.source_reset_state(
        signature.source_type, signature.root_identity, signature.backend_identity
    )
    if reset is None or reset.generation_id == claimed:
        return
    try:
        resumable = ledger.generation(claimed).terminal_state in RESUMABLE_STATES
    except KeyError:
        resumable = False
    if resumable:
        return
    raise RebuildSupersededError(
        f"{signature.source_type.value} rebuild generation {claimed} was replaced "
        f"by the rebuild that reset it at epoch {reset.epoch}; start a new rebuild"
    )


@dataclass(frozen=True, slots=True)
class ResetEpochFence:
    """The reset epoch one reader or writer began under.

    ``epoch`` is ``0`` for a source that was never reset. ``phase`` is the
    phase that epoch had reached at capture, or ``None`` when never reset.
    ``generation_id`` names the rebuild that owns that reset, or ``None`` when
    never reset; once the reset completes, it is the generation the source's
    storage holds until a later publication supersedes it.
    """

    ledger_path: pathlib.Path
    source_type: PublicSourceType
    root_identity: str
    backend_identity: str
    epoch: int
    phase: SourceResetPhase | None
    generation_id: str | None = None

    @classmethod
    def capture(
        cls,
        ledger: RunLedger,
        source: PublicSourceType,
        root_identity: str,
        backend_identity: str,
    ) -> ResetEpochFence:
        """Fence work to *source*'s latest reset as *ledger* records it now."""
        state = ledger.source_reset_state(source, root_identity, backend_identity)
        return cls(
            ledger_path=ledger.path,
            source_type=source,
            root_identity=root_identity,
            backend_identity=backend_identity,
            epoch=0 if state is None else state.epoch,
            phase=None if state is None else state.phase,
            generation_id=None if state is None else state.generation_id,
        )

    @classmethod
    def of(cls, root: pathlib.Path, state: SourceResetState) -> ResetEpochFence:
        """Fence work to the reset *state* records, read where it was recorded.

        A reset records into the ledger of the store's *root*, so the fence
        reads that same ledger rather than the ledger of whoever runs the work.
        """
        return cls(
            ledger_path=_ledger_path(root),
            source_type=state.source_type,
            root_identity=state.root_identity,
            backend_identity=state.backend_identity,
            epoch=state.epoch,
            phase=state.phase,
            generation_id=state.generation_id,
        )

    @property
    def serving(self) -> bool:
        """Whether the source's storage held one epoch's content at capture.

        A source never reset, or whose latest reset completed, holds content
        written under that epoch only. Between intent and completion its
        storage is being discarded, so a read there can observe old content
        or a partial deletion of it.
        """
        return self.phase is None or self.phase is SourceResetPhase.COMPLETE

    def validate(self) -> None:
        """Raise when the source was reset after this fence was captured.

        Finishing the reset that was in transition at capture keeps the epoch,
        so it does not invalidate the fence; only a later reset does.

        Raises:
            SourceResetEpochError: a later reset recorded its intent, or the
                ledger that recorded this fence's reset is gone.
        """
        if not self.ledger_path.is_file():
            if self.epoch == 0:
                return
            raise SourceResetEpochError(
                f"{self.source_type.value} reset epoch {self.epoch} is no "
                "longer recorded"
            )
        current = read_source_reset(
            self.ledger_path,
            self.source_type,
            self.root_identity,
            self.backend_identity,
        )
        epoch = 0 if current is None else current.epoch
        if epoch != self.epoch:
            raise SourceResetEpochError(
                f"{self.source_type.value} was reset (epoch {epoch}) after this "
                f"work began under epoch {self.epoch}"
            )


def capture_reset_epoch(
    root: pathlib.Path,
    source: PublicSourceType,
    backend_identity: str,
) -> ResetEpochFence:
    """Capture *source*'s current reset epoch before touching its storage.

    A root without a run ledger was never reset, and capturing creates none:
    a read must not leave durable state behind.
    """
    if source is PublicSourceType.COMBINED:
        raise ValueError("a reset epoch belongs to one concrete source")
    resolved = root.resolve()
    path = _ledger_path(resolved)
    if path.is_file():
        return ResetEpochFence.capture(
            RunLedger(path), source, str(resolved), backend_identity
        )
    return ResetEpochFence(
        ledger_path=path,
        source_type=source,
        root_identity=str(resolved),
        backend_identity=backend_identity,
        epoch=0,
        phase=None,
    )


@dataclass(frozen=True, slots=True)
class _ResetControl:
    """The owning job's control over one reset, and its no-progress budget."""

    run_control: RunControl
    write_policy: StoreWritePolicy | None


def _reset_one(
    store: VaultStore,
    ledger: RunLedger,
    source: PublicSourceType,
    generation_id: str,
    control: _ResetControl,
) -> SourceResetState:
    root_identity = str(store.root_dir.resolve())
    # Every lock the reset takes is held before its intent is recorded, so a
    # reset queued behind another holder answers pause, cancel and its
    # deadline while nothing has been discarded yet.
    # The protected span is entered before the intent is recorded: its entry is
    # where a cancel or latched deadline that arrived while the locks were being
    # taken is delivered, and a delivery after the intent would leave the proof
    # and receipts deleted over storage that was never touched.
    with (
        store.held_for_reset(source, control.write_policy),
        control.run_control.protected(),
    ):
        state = ledger.begin_source_reset(
            source, root_identity, store.backend_identity, generation_id
        )
        if state.complete:
            return state
        stale = (
            other_backend_code_pointer(store.root_dir, store.DERIVED_CODE_TABLE_NAME)
            if source is PublicSourceType.CODE
            else None
        )
        # Discarding again on a replay is idempotent and costs nothing on
        # absent storage; skipping it would trust that nothing recreated a
        # collection between the recorded deletion and this replay.
        store.discard_source_storage(source)
        if source is PublicSourceType.CODE:
            # The only code collection a reset recreates is the derived
            # one, so a pointer or a binding naming anything else would
            # address a collection that no longer exists.
            retire_served_code_pointer(store.root_dir)
            store.CODE_TABLE_NAME = store.DERIVED_CODE_TABLE_NAME
            if stale is not None:
                logger.warning(
                    "Retired %s's served code pointer naming %s, its code "
                    "collection under the other backend; that collection "
                    "was left untouched",
                    root_identity,
                    stale,
                )
        state = ledger.advance_source_reset(state, SourceResetPhase.DISCARDED)
        store.recreate_empty_source(source)
        state = ledger.advance_source_reset(state, SourceResetPhase.COMPLETE)
    logger.info(
        "Reset %s for %s at epoch %d",
        source.value,
        root_identity,
        state.epoch,
    )
    return state


def reset_selected_sources(
    store: VaultStore,
    selection: PublicSourceType,
    *,
    generation_id: str,
    run_control: RunControl = NO_RUN_CONTROL,
    write_policy: StoreWritePolicy | None = None,
) -> tuple[SourceResetState, ...]:
    """Discard and recreate empty every source *selection* names.

    The caller holds the selected sources' mutation authority. Ownership of
    every selected source is established before anything is recorded, so a
    refusal - code's served pointer unverifiable - leaves every source as it
    was. Sources reset independently: a combined selection is not one
    transaction, and a failure leaves earlier sources reset.

    Args:
        store: The root's store; its collections are discarded and recreated.
        selection: One concrete source, or combined for all three.
        generation_id: The rebuild that owns the reset. Replaying the same
            generation resumes its unfinished reset and never repeats a
            completed one.
        run_control: Control for the owning job. A pending pause or cancel is
            delivered before the reset begins; once it begins it is protected
            until the empty replacement is recorded.
        write_policy: The owning run's no-progress budget. With it, waiting
            for the locks the reset takes delivers *run_control* and expires
            at the deadline; without it that wait is unbounded.

    Returns:
        Each selected source's completed reset, in reset order.
    """
    sources = concrete_sources(selection)
    for source in sources:
        store.owned_source_collections(source)
    run_control.checkpoint()
    ledger = RunLedger(_ledger_path(store.root_dir))
    control = _ResetControl(run_control, write_policy)
    return tuple(
        _reset_one(store, ledger, source, generation_id, control) for source in sources
    )


def enter_rebuild_ingestion(
    store: VaultStore,
    source: PublicSourceType,
    *,
    began_under: ResetEpochFence,
    generation_id: str,
    run_policy: RunPolicy | None = None,
) -> SourceResetState:
    """Reset *source* for the rebuild *generation_id* before it writes anything.

    The caller holds the source's writer lease, captured *began_under* before
    it planned the rebuild, and has opened the rebuild's generation. Every
    explicit rebuild of every content kind passes through here, so the old
    index is discarded and the canonical collection is empty before the first
    replacement write, and the rebuild then writes into that one collection.

    - A reset recorded since *began_under* rejects the rebuild. It planned
      against storage that reset discarded, and writing now would land work
      from before the reset in the replacement.
    - The generation's own completed reset is never repeated, so a resumed
      rebuild keeps the replacement work it already confirmed.
    - A reset its own generation left unfinished resumes from its recorded
      phase; any other generation's reset, finished or not, is superseded by
      a new one, which also retires every receipt and proof the source held.
    - The context's :data:`rebuild_claim` records *generation_id* before any
      reset intent, so the next attempt of the same request continues this
      generation instead of starting a new rebuild.

    *run_policy* is the owning attempt's control and no-progress budget. The
    reset delivers its pause and cancel, and expires at its deadline, while it
    waits for the locks it takes.

    Raises:
        SourceResetEpochError: *source* was reset after *began_under*.
    """
    began_under.validate()
    claim = rebuild_claim.get()
    if claim.bind is not None and claim.generation_id != generation_id:
        claim.bind(generation_id)
    (state,) = reset_selected_sources(
        store,
        source,
        generation_id=generation_id,
        run_control=NO_RUN_CONTROL if run_policy is None else run_policy,
        write_policy=None if run_policy is None else run_policy.store_write_policy,
    )
    return state
