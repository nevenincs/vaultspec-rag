"""Run-checkpoint logic shared by the code and document indexers.

The two indexers keep separate checkpoint classes on purpose: their commit
units differ, so the per-unit bookkeeping around them genuinely differs too.
What does not differ is the run-level reasoning that has nothing to do with
what a unit is - and that is what lives here.

The distinction worth holding is which duplications are dangerous. A duplicated
one-line property reads wrong once and is corrected in place. A duplicated
*decision* is different: it is the copy that never gets the fix. If someone
corrects how an interrupted run is classified in one indexer and not the other,
one source type silently mis-classifies interruptions on resume - no test
compares the two implementations against each other, so nothing announces the
divergence. That is why the classification is centralised here, and why
:class:`RunCheckpointBase` centralises the other run-level decisions carrying
the same risk: deletion checkpointing, unresolved-failure recording and
generation publication. Only what actually depends on the shape of a unit -
how one is built, how it is committed, how metadata is published from it -
stays on the two subclasses.

:class:`RunCheckpointBase` never grows drift-supersede behaviour. That
mechanism is deliberately code-only (the ``document-index-drift-parity``
decision); it stays a ``CodeRunCheckpoint`` concern, not a base-class one.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, ClassVar

from ._file_state import FileState, FileStateKind
from ._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunLedgerStateError,
    RunTerminalState,
)
from ._run_policy import DurableProgressKind

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

    from _typeshed import DataclassInstance

    from . import _config_epoch
    from ._content_policy import ContentKind
    from ._resolved_policy import ResolvedIndexPolicy
    from ._run_ledger_models import RunGeneration
    from ._run_ledger_runtime import RunLedger
    from ._run_policy import RunPolicy

__all__ = [
    "RunCheckpointBase",
    "classify_interrupted_generation",
    "configuration_fingerprint",
]


def configuration_fingerprint(configuration: DataclassInstance) -> str:
    """Fingerprint a run configuration into its run-signature identity.

    Sorted keys and separator-tight JSON make the digest depend on the
    configuration's values alone, never on field declaration order or on how
    the encoder happens to space its output - the fingerprint has to be stable
    across processes for a resumed run to recognise its own parent generation.
    """
    payload = json.dumps(asdict(configuration), sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(payload.encode("utf-8")).hexdigest()


def classify_interrupted_generation(
    ledger: RunLedger,
    generation: RunGeneration,
    exc: BaseException,
) -> RunGeneration:
    """Finish an interrupted generation under the terminal state it earned.

    A generation that is no longer ``RUNNING`` has already reached a terminal
    state and is returned untouched, so a failure raised after the run finished
    cannot overwrite the outcome it already recorded.

    The destructive/non-destructive split is the load-bearing part. An
    interrupted rebuild has already dropped data it did not finish replacing,
    so it is ``REBUILD_INCOMPLETE`` - a state a later run must not treat as a
    usable parent. An interrupted incremental run left the published data
    intact and is merely ``FAILED``.

    Returns the finished generation; the caller reassigns it and re-raises, so
    the original exception continues to propagate unchanged.
    """
    if generation.terminal_state is not RunTerminalState.RUNNING:
        return generation
    terminal_state = (
        RunTerminalState.REBUILD_INCOMPLETE
        if generation.destructive_intent
        else RunTerminalState.FAILED
    )
    detail = f"{type(exc).__name__}: {exc}".rstrip()
    return ledger.finish_generation(
        generation.generation_id,
        terminal_state,
        detail=detail,
    )


@dataclass(slots=True)
class RunCheckpointBase:
    """Run-level checkpoint decisions shared by every source type.

    A subclass sets ``_content_kind`` and ``_kind_label`` and inherits the
    deletion-checkpointing and generation-publication decisions unchanged;
    everything that depends on how a unit is built or what a slice of that
    source type looks like stays on the subclass.
    """

    ledger: RunLedger
    generation: RunGeneration
    policy: ResolvedIndexPolicy
    run_policy: RunPolicy
    resumed_units: int = 0

    _content_kind: ClassVar[ContentKind]
    _kind_label: ClassVar[str]

    @property
    def generation_id(self) -> str:
        """Return the stable active generation identifier."""
        return self.generation.generation_id

    @property
    def ingestion_complete(self) -> bool:
        """Return whether this generation must resume finalization, not ingestion."""
        return self.generation.finalization_phase is not FinalizationPhase.INGESTING

    @contextmanager
    def preserve_incomplete_generation(self) -> Generator[None]:
        """Classify an interrupted attempt without hiding its original failure."""
        try:
            yield
        except BaseException as exc:
            self.generation = classify_interrupted_generation(
                self.ledger,
                self.generation,
                exc,
            )
            raise

    def publish_metadata_transition(
        self,
        publish: Callable[[_config_epoch.ContentKindFingerprints], int],
    ) -> int:
        """Advance the durable finalization phase around one metadata publish.

        The phase walk is identical for every source type and both subclasses
        carried a copy of it. Only *publish* differs - the code sidecar records
        published point and file counts, the document sidecar records retained
        point ids and a policy snapshot - so that is the one thing passed in.

        The transition is DURABLE: it moves the generation from
        ``STALE_RECONCILED`` to ``METADATA_PUBLISHED`` and that survives a
        restart. Two copies of it could disagree about when metadata is
        publishable and the disagreement would persist across runs.

        Returns the row count *publish* reported, or ``0`` when this generation
        is not in a publishable phase.
        """
        phase = self.generation.finalization_phase
        if phase is FinalizationPhase.INGESTING:
            self.generation = self.ledger.advance_finalization(
                self.generation_id,
                FinalizationPhase.STALE_RECONCILED,
            )
            phase = self.generation.finalization_phase
        if phase is not FinalizationPhase.STALE_RECONCILED:
            return 0
        count = publish(self.policy.fingerprints_for(self._content_kind))
        self.generation = self.ledger.advance_finalization(
            self.generation_id,
            FinalizationPhase.METADATA_PUBLISHED,
        )
        self.run_policy.record_durable_progress(
            kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
            label=f"{self._kind_label} metadata publication",
        )
        return count

    def record_confirmed_deletion(
        self,
        rel_path: str,
        point_ids: tuple[str, ...],
    ) -> bool:
        """Checkpoint one idempotent path deletion after storage confirmation."""
        unit = CommitUnit(
            rel_path=rel_path,
            kind=CommitUnitKind.DELETE_PATH,
            source_digest=None,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=tuple(sorted(point_ids)),
        )
        inserted = self.ledger.record_storage_confirmed_unit(
            self.generation_id,
            unit,
        )
        if inserted:
            self.run_policy.record_durable_progress(
                kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
                label=f"{self._kind_label} deletion {rel_path}",
            )
        self.ledger.record_path_deleted(self.generation_id, rel_path)
        return inserted

    def record_confirmed_stale_deletion(
        self,
        rel_path: str,
        point_ids: tuple[str, ...],
    ) -> bool:
        """Checkpoint removal of superseded points while retaining the path."""
        unit = CommitUnit(
            rel_path=rel_path,
            kind=CommitUnitKind.DELETE_STALE,
            source_digest=None,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=tuple(sorted(point_ids)),
        )
        inserted = self.ledger.record_storage_confirmed_unit(
            self.generation_id,
            unit,
        )
        if inserted:
            self.run_policy.record_durable_progress(
                kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
                label=f"stale {self._kind_label} deletion {rel_path}",
            )
        return inserted

    def record_processing_failure(
        self,
        rel_path: str,
        state: FileStateKind,
        detail: str,
        *,
        content_hash: str | None = None,
    ) -> None:
        """Replace carried convergence with one explicit unresolved outcome."""
        self.ledger.record_file_state(
            self.generation_id,
            FileState.failed(
                rel_path,
                state,
                self._content_kind,
                detail,
                content_hash=content_hash,
            ),
        )

    def publish_generation(self) -> RunGeneration:
        """Certify generation publication and compact prior compatible rows."""
        phase = self.generation.finalization_phase
        if phase in (
            FinalizationPhase.INGESTING,
            FinalizationPhase.STALE_RECONCILED,
        ):
            raise RunLedgerStateError(
                f"{self._kind_label} metadata must be durably published "
                "before generation publication"
            )
        if phase is FinalizationPhase.METADATA_PUBLISHED:
            self.generation = self.ledger.advance_finalization(
                self.generation_id,
                FinalizationPhase.GENERATION_PUBLISHED,
            )
        if self.generation.terminal_state is RunTerminalState.RUNNING:
            self.generation = self.ledger.finish_generation(
                self.generation_id,
                RunTerminalState.SUCCEEDED,
            )
        if self.generation.finalization_phase is not FinalizationPhase.COMPACTED:
            self.ledger.compact(self.generation_id)
        self.generation = self.ledger.generation(self.generation_id)
        self.run_policy.record_durable_progress(
            kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
            label=f"{self._kind_label} generation publication",
        )
        return self.generation

    def _record_indexed_file(self, rel_path: str, source_digest: str) -> None:
        self.ledger.record_file_state(
            self.generation_id,
            FileState.indexed(rel_path, self._content_kind, source_digest),
        )
