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
A rebuild entering ingestion finishes any reset left unfinished under the
generation that recorded it, so a crash between intent and completion never
leaves discarded content where replacement writes land.

The epoch is the fence. A reader or writer captures it before touching
storage and validates it afterwards; any reset recorded in between makes the
work stale, so nothing observed from discarded storage is returned and nothing
an old attempt writes lands in the replacement unnoticed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._source_types import PublicSourceType
from .._store_models import retire_served_code_pointer
from .._store_writes import workspace_volume_path
from ..job_control import NO_RUN_CONTROL
from ._run_ledger_models import (
    SourceResetEpochError,
    SourceResetPhase,
    index_run_ledger_path,
)
from ._run_ledger_runtime import RunLedger
from ._run_ledger_source_resets import read_source_reset

if TYPE_CHECKING:
    import pathlib

    from ..job_control import RunControl
    from ..store_runtime import VaultStore
    from ._run_ledger_models import SourceResetState

__all__ = [
    "CONCRETE_SOURCES",
    "ResetEpochFence",
    "capture_reset_epoch",
    "enter_rebuild_ingestion",
    "reset_selected_sources",
]

logger = logging.getLogger(__name__)

#: The sources a reset acts on, in the order a combined selection resets them.
CONCRETE_SOURCES: tuple[PublicSourceType, ...] = (
    PublicSourceType.VAULT,
    PublicSourceType.CODE,
    PublicSourceType.DOCUMENT,
)


def _selected(selection: PublicSourceType) -> tuple[PublicSourceType, ...]:
    if selection is PublicSourceType.COMBINED:
        return CONCRETE_SOURCES
    return (selection,)


def _ledger_path(root: pathlib.Path) -> pathlib.Path:
    return index_run_ledger_path(workspace_volume_path(root.resolve()))


@dataclass(frozen=True, slots=True)
class ResetEpochFence:
    """The reset epoch one reader or writer began under.

    ``epoch`` is ``0`` for a source that was never reset. ``phase`` is the
    phase that epoch had reached at capture, or ``None`` when never reset.
    """

    ledger_path: pathlib.Path
    source_type: PublicSourceType
    root_identity: str
    backend_identity: str
    epoch: int
    phase: SourceResetPhase | None

    @property
    def in_transition(self) -> bool:
        """Whether a reset had begun but not completed at capture.

        The source's storage is then being discarded or recreated, and holds
        nothing a read may return.
        """
        return self.phase is not None and self.phase is not SourceResetPhase.COMPLETE

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
    state = (
        RunLedger(path).source_reset_state(source, str(resolved), backend_identity)
        if path.is_file()
        else None
    )
    return ResetEpochFence(
        ledger_path=path,
        source_type=source,
        root_identity=str(resolved),
        backend_identity=backend_identity,
        epoch=0 if state is None else state.epoch,
        phase=None if state is None else state.phase,
    )


def _reset_one(
    store: VaultStore,
    ledger: RunLedger,
    source: PublicSourceType,
    generation_id: str,
    run_control: RunControl,
) -> SourceResetState:
    root_identity = str(store.root_dir.resolve())
    state = ledger.begin_source_reset(
        source, root_identity, store.backend_identity, generation_id
    )
    if state.complete:
        return state
    with run_control.protected():
        # Discarding again on a replay is idempotent and costs nothing on
        # absent storage; skipping it would trust that nothing recreated a
        # collection between the recorded deletion and this replay.
        store.discard_source_storage(source)
        if source is PublicSourceType.CODE:
            # The only code collection a reset recreates is the derived one,
            # so a pointer or a binding naming anything else would address a
            # collection that no longer exists.
            retire_served_code_pointer(store.root_dir)
            store.CODE_TABLE_NAME = store.DERIVED_CODE_TABLE_NAME
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

    Returns:
        Each selected source's completed reset, in reset order.
    """
    sources = _selected(selection)
    for source in sources:
        store.owned_source_collections(source)
    run_control.checkpoint()
    ledger = RunLedger(_ledger_path(store.root_dir))
    return tuple(
        _reset_one(store, ledger, source, generation_id, run_control)
        for source in sources
    )


def enter_rebuild_ingestion(
    store: VaultStore,
    source: PublicSourceType,
    *,
    began_under: ResetEpochFence,
    run_control: RunControl = NO_RUN_CONTROL,
) -> None:
    """Admit an explicit rebuild of *source* to write into its storage.

    The caller holds the source's writer lease and captured *began_under*
    before it planned the rebuild. Three things happen, in order, before the
    first replacement write:

    - A reset recorded since *began_under* rejects the rebuild. It planned
      against storage that reset discarded, and writing now would land work
      from before the reset in the replacement.
    - A reset left unfinished by a crash is finished under the generation
      that recorded it. Until then the source may still hold discarded
      content, or no collection at all.
    - An in-place publication left open by an interrupted incremental run is
      discarded by a reset of its own, keyed by that receipt, so a replay
      after the receipt is retired resets nothing further.

    A root with no run ledger has nothing to fence, recover, or discard, and
    entering creates none.

    Raises:
        SourceResetEpochError: *source* was reset after *began_under*.
    """
    began_under.validate()
    path = _ledger_path(store.root_dir)
    if not path.is_file():
        return
    ledger = RunLedger(path)
    root_identity = str(store.root_dir.resolve())
    interrupted = ledger.source_reset_state(
        source, root_identity, store.backend_identity
    )
    if interrupted is not None and not interrupted.complete:
        logger.warning(
            "Finishing %s reset interrupted at %s for %s",
            source.value,
            interrupted.phase.value,
            root_identity,
        )
        run_control.checkpoint()
        _reset_one(store, ledger, source, interrupted.generation_id, run_control)
    receipt = ledger.recoverable_publication_receipt(
        source_type=source,
        root_identity=root_identity,
        backend_identity=store.backend_identity,
    )
    if receipt is None or not receipt.state.is_open:
        return
    reset_selected_sources(
        store, source, generation_id=receipt.receipt_id, run_control=run_control
    )
