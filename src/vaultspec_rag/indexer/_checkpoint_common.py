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
from ._publication_proof import PathDelta, PathOutcome, ProofEvidence
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    ProofReceiptState,
    RunAuthority,
    RunLedgerCompatibilityError,
    RunLedgerStateError,
    RunOperation,
    RunTerminalState,
)
from ._run_policy import DurableProgressKind

if TYPE_CHECKING:
    from collections.abc import Generator

    from _typeshed import DataclassInstance

    from ..job_control import RunControl
    from ._content_policy import ContentKind
    from ._resolved_policy import ResolvedIndexPolicy
    from ._run_ledger_models import PublicationReceipt, RunGeneration, RunSignature
    from ._run_ledger_runtime import RunLedger
    from ._run_policy import RunPolicy
    from ._streaming_types import StoreMutationLifecycle

__all__ = [
    "PublicationExecution",
    "RunCheckpointBase",
    "classify_interrupted_generation",
    "configuration_fingerprint",
]


@dataclass(frozen=True, slots=True)
class PublicationExecution:
    """Explicit permission and cooperative control for one publication."""

    authority: RunAuthority
    run_control: RunControl


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
    policy: ResolvedIndexPolicy | None
    run_policy: RunPolicy
    authority: RunAuthority
    receipt: PublicationReceipt | None
    resumed_units: int = 0

    _content_kind: ClassVar[ContentKind | None]
    _kind_label: ClassVar[str]

    @classmethod
    def start_compatible_generation(
        cls,
        ledger: RunLedger,
        signature: RunSignature,
    ) -> RunGeneration:
        """Start one attempt's generation, refusing a parentless incremental.

        An incremental reconciles a difference against a committed proof.
        Without a compatible parent there is no proof to differ from, so
        every file the run believed unchanged would be skipped and an index
        nobody wrote would be certified. Refusing is what lets the caller
        escalate to a full failure-safe reconciliation instead.

        Both source types refuse on the same evidence, which is why the
        refusal lives here rather than beside each signature: a copy that
        drifted would leave one source type failing every incremental where
        the other recovers.

        This is also where the ledger's deep integrity scan belongs. It is far
        too expensive to run per open - it reads every page the root's content
        kinds have ever written - but a generation carrying committed units is
        about to be trusted to *skip* storage work on that evidence's word.
        Verifying exactly there costs a fresh run nothing and still refuses to
        resume onto damaged durable state.
        """
        generation = ledger.start_generation(signature)
        if (
            signature.operation
            in (RunOperation.INCREMENTAL, RunOperation.SCOPED_INCREMENTAL)
            and generation.parent_generation_id is None
        ):
            raise RunLedgerCompatibilityError(
                f"incremental {cls._kind_label} indexing requires a compatible "
                "committed proof; run a full reconciliation"
            )
        if ledger.committed_unit_count(generation.generation_id) > 0:
            ledger.verify_integrity()
        return generation

    @classmethod
    def open_publication_receipt(
        cls,
        ledger: RunLedger,
        generation: RunGeneration,
        authority: RunAuthority,
    ) -> PublicationReceipt | None:
        """Bind an incremental generation to its canonical parent revision."""
        from ._run_ledger_publication import compatibility_for_signature

        signature = generation.signature
        if authority is RunAuthority.REBUILD:
            if signature.operation is not RunOperation.FULL:
                raise PermissionError("rebuild authority requires a full run")
            return None
        if authority is not RunAuthority.PUBLICATION:
            raise PermissionError("audit authority cannot open publication work")
        key = compatibility_for_signature(signature)
        proof = ledger.publication_proof(key)
        if proof.generation_id == generation.generation_id:
            return None
        if generation.parent_generation_id != proof.generation_id:
            raise RunLedgerCompatibilityError(
                "incremental generation does not descend from canonical proof"
            )
        active = ledger.active_publication_receipt(key)
        if active is not None:
            if active.generation_id != generation.generation_id:
                raise RunLedgerStateError(
                    "canonical proof has a receipt owned by another generation"
                )
            return active
        return ledger.reserve_publication_receipt(
            key,
            generation.generation_id,
            expected_parent_revision=proof.revision,
        )

    def mutation_lifecycle(self, unit: CommitUnit) -> StoreMutationLifecycle | None:
        """Return durable receipt callbacks for one external mutation."""
        return self.mutation_lifecycle_for_units((unit,))

    def mutation_lifecycle_for_units(
        self,
        units: tuple[CommitUnit, ...],
    ) -> StoreMutationLifecycle | None:
        """Bracket one atomic store call containing exact bounded units."""
        if self.receipt is None:
            return None
        from ._publication_proof import ProofMutationState
        from ._streaming_types import StoreMutationLifecycle

        receipt_id = self.receipt.receipt_id

        def prepare() -> bool:
            pending = False
            for unit in units:
                mutation = self.ledger.prepare_publication_mutation(receipt_id, unit)
                if mutation.state is ProofMutationState.APPLIED:
                    self.ledger.confirm_publication_mutation(receipt_id, unit)
                elif mutation.state is ProofMutationState.PREPARED:
                    pending = True
            return pending

        def mark_applied() -> None:
            for unit in units:
                self.ledger.mark_publication_mutation_applied(receipt_id, unit)

        def confirm() -> None:
            for unit in units:
                self.ledger.confirm_publication_mutation(receipt_id, unit)

        return StoreMutationLifecycle(
            prepare=prepare,
            mark_applied=mark_applied,
            confirm=confirm,
            confirm_after_acknowledgement=True,
        )

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

    def publish_proof_transition(self) -> int:
        """Commit canonical proof before advancing the publication phase."""
        phase = self.generation.finalization_phase
        if phase not in {
            FinalizationPhase.INGESTING,
            FinalizationPhase.STALE_RECONCILED,
        }:
            return 0
        changed = 0
        if phase is FinalizationPhase.INGESTING:
            changed = self._seal_publication_proof()
            self.generation = self.ledger.advance_finalization(
                self.generation_id,
                FinalizationPhase.STALE_RECONCILED,
            )
        if self.receipt is not None:
            receipt = self.ledger.active_publication_receipt(
                self.receipt.compatibility_key
            )
            if receipt is not None and receipt.state is ProofReceiptState.SEALED:
                self.ledger.commit_publication_receipt(receipt.receipt_id)
        self.generation = self.ledger.advance_finalization(
            self.generation_id,
            FinalizationPhase.METADATA_PUBLISHED,
        )
        return changed

    def _seal_publication_proof(self) -> int:
        if self.authority is RunAuthority.REBUILD:
            evidence = self._verified_evidence()
            self.ledger.establish_verified_publication(
                self.generation_id,
                self.authority,
                tuple(evidence),
            )
            return len(evidence)
        if self.receipt is not None:
            return self._seal_incremental_proof()
        from ._run_ledger_publication import compatibility_for_signature

        proof = self.ledger.publication_proof(
            compatibility_for_signature(self.generation.signature)
        )
        if proof.generation_id != self.generation_id:
            raise RunLedgerStateError(
                "incremental publication has neither receipt nor committed proof"
            )
        return 0

    def _verified_evidence(self) -> list[ProofEvidence]:
        evidence: list[ProofEvidence] = []
        for state in self.ledger.iter_file_states(self.generation_id):
            if state.state is not FileStateKind.INDEXED:
                continue
            assert state.content_hash is not None
            point_ids = tuple(
                sorted(
                    self.ledger.iter_retained_point_ids(
                        self.generation_id,
                        rel_path=state.rel_path,
                    )
                )
            )
            if point_ids:
                evidence.append(
                    ProofEvidence(state.rel_path, state.content_hash, point_ids)
                )
        return evidence

    def _seal_incremental_proof(self) -> int:
        if self.receipt is None:
            raise RunLedgerStateError("incremental publication has no receipt")
        receipt = self.ledger.active_publication_receipt(self.receipt.compatibility_key)
        if receipt is None or receipt.receipt_id != self.receipt.receipt_id:
            raise RunLedgerStateError("incremental publication receipt disappeared")
        paths = tuple(sorted({item.unit.rel_path for item in receipt.mutations}))
        old_by_path: dict[str, ProofEvidence] = {}
        for start in range(0, len(paths), FETCH_BATCH):
            old_by_path.update(
                self.ledger.publication_evidence_for_paths(
                    receipt.compatibility_key,
                    paths[start : start + FETCH_BATCH],
                )
            )
        deltas: list[PathDelta] = []
        for rel_path in paths:
            upserts = tuple(
                mutation.unit
                for mutation in receipt.mutations
                if mutation.unit.rel_path == rel_path
                and mutation.unit.kind is CommitUnitKind.UPSERT
            )
            old = old_by_path.get(rel_path)
            new = self._new_evidence(rel_path, upserts)
            if old == new:
                continue
            outcome = (
                PathOutcome.ADD
                if old is None
                else PathOutcome.DELETE
                if new is None
                else PathOutcome.MODIFY
            )
            deltas.append(
                PathDelta(outcome, receipt.parent_revision, rel_path, old=old, new=new)
            )
        if not deltas:
            if receipt.mutations:
                raise RunLedgerStateError(
                    "storage mutations produced no canonical proof change"
                )
            self.ledger.begin_publication_rollback(receipt.receipt_id)
            self.ledger.roll_back_publication_receipt(
                receipt.receipt_id,
                compensated_units=(),
            )
            return 0
        self.ledger.seal_publication_receipt(receipt.receipt_id, tuple(deltas))
        return len(deltas)

    @staticmethod
    def _new_evidence(
        rel_path: str,
        upserts: tuple[CommitUnit, ...],
    ) -> ProofEvidence | None:
        if not upserts:
            return None
        digests = {unit.source_digest for unit in upserts}
        if len(digests) != 1 or None in digests:
            raise RunLedgerStateError(f"publication units disagree for {rel_path!r}")
        digest = digests.pop()
        assert digest is not None
        points = tuple(sorted({point for unit in upserts for point in unit.point_ids}))
        return ProofEvidence(rel_path, digest, points)

    def record_confirmed_deletion(
        self,
        rel_path: str,
        point_ids: tuple[str, ...],
    ) -> bool:
        """Checkpoint one idempotent path deletion after storage confirmation."""
        unit = self._deletion_unit(rel_path, CommitUnitKind.DELETE_PATH, point_ids)
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
        unit = self._deletion_unit(rel_path, CommitUnitKind.DELETE_STALE, point_ids)
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

    def deletion_lifecycle(
        self,
        rel_path: str,
        kind: CommitUnitKind,
        point_ids: tuple[str, ...],
    ) -> StoreMutationLifecycle | None:
        """Return receipt transitions for one exact deletion store call."""
        return self.mutation_lifecycle(self._deletion_unit(rel_path, kind, point_ids))

    @staticmethod
    def _deletion_unit(
        rel_path: str,
        kind: CommitUnitKind,
        point_ids: tuple[str, ...],
    ) -> CommitUnit:
        """Build the one canonical ledger unit for a confirmed deletion."""
        return CommitUnit(
            rel_path=rel_path,
            kind=kind,
            source_digest=None,
            segment_ordinal=0,
            is_file_end=True,
            point_ids=tuple(sorted(point_ids)),
        )

    def record_processing_failure(
        self,
        rel_path: str,
        state: FileStateKind,
        detail: str,
        *,
        content_hash: str | None = None,
    ) -> None:
        """Replace carried convergence with one explicit unresolved outcome."""
        if self._content_kind is None:
            raise RunLedgerStateError("processing failures require content kind")
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
        if self._content_kind is None:
            raise RunLedgerStateError("indexed files require content kind")
        self.ledger.record_file_state(
            self.generation_id,
            FileState.indexed(rel_path, self._content_kind, source_digest),
        )
