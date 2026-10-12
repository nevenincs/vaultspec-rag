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

Interrupted publication recovery is shared by every source. Its replay
context restores only affected paths through each source's ordinary pipeline;
code's within-run drift owner remains a separate ``CodeRunCheckpoint`` concern.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass
from functools import partial
from typing import TYPE_CHECKING, ClassVar, Protocol, Self

from .. import store_schema
from .._job_errors import JobError, JobErrorKind
from .._operator_commands import IndexCommandOptions, index_command
from .._store_writes import workspace_volume_path
from ._file_state import FileState, FileStateKind
from ._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofEvidence,
    ProofMutationState,
    ProofReceiptState,
    ProofUnverifiableError,
)
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunAuthority,
    RunLedgerCompatibilityError,
    RunLedgerCorruptionError,
    RunLedgerRebuildRequiredError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
    expected_publication_deletion,
    index_run_ledger_path,
    ledger_connection,
    validate_publication_mutation_group,
)
from ._run_ledger_runtime import RunLedger
from ._run_policy import DurableProgressKind

if TYPE_CHECKING:
    from collections.abc import Callable, Generator
    from pathlib import Path

    from _typeshed import DataclassInstance

    from .._source_types import PublicSourceType
    from ..job_control import RunControl
    from ..store_runtime import VaultStore
    from ._content_policy import ContentKind
    from ._resolved_policy import ResolvedIndexPolicy
    from ._run_ledger_models import PublicationReceipt, RunGeneration
    from ._run_policy import RunPolicy, RunPolicySnapshot
    from ._streaming_types import StoreMutationLifecycle

    type CheckpointProgressObserver = Callable[
        [RunCheckpointBase, RunPolicySnapshot | None], None
    ]


_CHECKPOINT_PROGRESS_OBSERVER: ContextVar[CheckpointProgressObserver | None] = (
    ContextVar("checkpoint_progress_observer", default=None)
)

__all__ = [
    "PublicationExecution",
    "RunCheckpointBase",
    "RunOpenRequest",
    "classify_interrupted_generation",
    "configuration_fingerprint",
    "observe_checkpoint_progress",
]


@dataclass(frozen=True, slots=True)
class _PublicationReplay:
    receipt: PublicationReceipt
    paths: frozenset[str]
    delete_points: Callable[[list[str]], None]


_PUBLICATION_REPLAY: ContextVar[_PublicationReplay | None] = ContextVar(
    "publication_replay", default=None
)


def publication_replay_paths() -> frozenset[str]:
    """Paths that this writer must replace even when source hashes reverted."""
    replay = _PUBLICATION_REPLAY.get()
    return replay.paths if replay is not None else frozenset()


@contextmanager
def observe_checkpoint_progress(
    observer: CheckpointProgressObserver,
) -> Generator[None]:
    """Bind newly opened checkpoints to one exact attempt's observation.

    The initial notification carries no progress snapshot: it registers the
    actual checkpoint. Subsequent notifications follow confirmed durable work.
    """
    token = _CHECKPOINT_PROGRESS_OBSERVER.set(observer)
    try:
        yield
    finally:
        _CHECKPOINT_PROGRESS_OBSERVER.reset(token)


class RunOpenRequest(Protocol):
    """The compatibility inputs every source type opens a generation from.

    Structural rather than a base class: each source declares its own frozen
    request with its own configuration shape, and this names only the fields
    the shared open path actually reads.
    """

    @property
    def data_root(self) -> Path: ...
    @property
    def root_dir(self) -> Path: ...
    @property
    def policy(self) -> ResolvedIndexPolicy: ...
    @property
    def run_policy(self) -> RunPolicy: ...
    @property
    def operation(self) -> RunOperation: ...
    @property
    def clean(self) -> bool: ...
    @property
    def model_identity(self) -> str: ...
    @property
    def dense_dimensions(self) -> int: ...
    @property
    def configuration(self) -> DataclassInstance: ...
    @property
    def backend_identity(self) -> str: ...
    @property
    def authority(self) -> RunAuthority: ...


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
    _collection_identity: ClassVar[str]
    _source_type: ClassVar[PublicSourceType]
    _embedding_schema: ClassVar[int]

    def __post_init__(self) -> None:
        observer = _CHECKPOINT_PROGRESS_OBSERVER.get()
        if observer is not None:
            self.run_policy.set_durable_progress_observer(partial(observer, self))
            observer(self, None)

    @staticmethod
    def recover_pending_publication(
        root: Path,
        source: PublicSourceType,
        *,
        store: VaultStore,
        run_control: RunControl,
        replay_source: Callable[[], object],
    ) -> None:
        """Settle recorded publication work under the caller's writer lease.

        An empty reservation has touched no storage. A sealed, confirmed
        receipt already records the exact complete delta and its ingest
        barriers. Neither needs source discovery or a reader snapshot.
        Complete recorded streams finish from durable evidence. Uncertain or
        partial streams retain the read fence while their affected points are
        removed and ordinary indexing rereads current source bytes.
        """
        backend_identity = store.backend_identity
        delete_points = partial(store.delete_publication_points, source)
        replay = _PUBLICATION_REPLAY.get()
        if replay is not None:
            key = replay.receipt.compatibility_key
            if (key.root_identity, key.source_type, key.backend_identity) == (
                str(root.resolve()),
                source,
                backend_identity,
            ):
                return
        path = index_run_ledger_path(workspace_volume_path(root.resolve()))
        if not path.is_file():
            return
        try:
            ledger = RunLedger(path)
            receipt = ledger.recoverable_publication_receipt(
                source_type=source,
                root_identity=str(root.resolve()),
                backend_identity=backend_identity,
            )
            if receipt is not None:
                RunCheckpointBase._assert_recovery_storage(ledger, receipt, store)
                RunCheckpointBase._settle_pending_publication(
                    ledger, receipt, run_control, delete_points, replay_source
                )
        except (
            ProofUnverifiableError,
            RunLedgerCompatibilityError,
            RunLedgerCorruptionError,
            RunLedgerRebuildRequiredError,
            RunLedgerStateError,
        ) as exc:
            rebuild = index_command(source, IndexCommandOptions(rebuild=True))
            raise JobError(
                JobErrorKind.FULL_REINDEX_REQUIRED,
                f"interrupted publication cannot recover safely ({exc}); run {rebuild}",
            ) from exc

    @staticmethod
    def _assert_recovery_storage(
        ledger: RunLedger, receipt: PublicationReceipt, store: VaultStore
    ) -> None:
        """Pending path repairs cannot replace missing untouched parent storage."""
        from .._source_types import PublicSourceType

        paths = tuple(
            sorted(
                {item.unit.rel_path for item in receipt.mutations}
                | {delta.rel_path for delta in receipt.deltas}
                | set(ledger.publication_replay_paths(receipt.receipt_id))
            )
        )
        proof = ledger.publication_proof(receipt.compatibility_key)
        touched = 0
        for start in range(0, len(paths), FETCH_BATCH):
            evidence = ledger.publication_evidence_for_paths(
                receipt.compatibility_key, paths[start : start + FETCH_BATCH]
            )
            touched += sum(len(item.point_ids) for item in evidence.values())
        count = {
            PublicSourceType.CODE: store.count_code,
            PublicSourceType.DOCUMENT: store.count_document,
            PublicSourceType.VAULT: store.count,
        }[receipt.compatibility_key.source_type]()
        if count < proof.aggregate.retained_points - touched:
            raise RunLedgerStateError(
                "storage no longer backs untouched publication proof paths"
            )

    @staticmethod
    def _settle_pending_publication(
        ledger: RunLedger,
        receipt: PublicationReceipt,
        run_control: RunControl,
        delete_points: Callable[[list[str]], None],
        replay_source: Callable[[], object],
    ) -> None:
        """Choose rollback or forward completion only from exact durable evidence."""
        run_control.checkpoint()
        generation = ledger.generation(receipt.generation_id)
        from ._run_ledger_publication_identity import compatibility_for_signature

        proof = ledger.publication_proof(receipt.compatibility_key)
        if receipt.state is ProofReceiptState.COMMITTED:
            if (
                proof.generation_id != generation.generation_id
                or proof.revision != receipt.target_revision
                or proof.reservation_sequence != receipt.reservation_sequence
                or compatibility_for_signature(generation.signature)
                != receipt.compatibility_key
                or generation.signature.clean
            ):
                raise RunLedgerCompatibilityError(
                    "unfinished publication does not match its committed receipt"
                )
            RunCheckpointBase._recover_confirmed_publication(
                ledger, receipt, generation, run_control
            )
            return
        if (
            compatibility_for_signature(generation.signature)
            != receipt.compatibility_key
            or generation.parent_generation_id != proof.generation_id
        ):
            raise RunLedgerCompatibilityError(
                "pending publication generation does not descend from canonical proof"
            )
        if (
            not receipt.mutations
            and not ledger.publication_replay_paths(receipt.receipt_id)
            and ledger.committed_unit_count(generation.generation_id) == 0
        ):
            ledger.begin_publication_rollback(receipt.receipt_id)
            ledger.roll_back_publication_receipt(
                receipt.receipt_id, compensated_units=()
            )
            if generation.terminal_state is RunTerminalState.RUNNING:
                ledger.finish_generation(
                    generation.generation_id,
                    RunTerminalState.INVALIDATED,
                    detail="abandoned publication reservation touched no storage",
                )
            return
        receipt = RunCheckpointBase._recover_unsealed_publication(
            ledger, receipt, run_control, delete_points
        )
        if receipt.state is not ProofReceiptState.SEALED or any(
            item.state is not ProofMutationState.CONFIRMED for item in receipt.mutations
        ):
            if receipt.state not in {
                ProofReceiptState.RESERVED,
                ProofReceiptState.SEALED,
            }:
                raise RunLedgerStateError(
                    "unfinished rollback cannot restart ingestion"
                )
            RunCheckpointBase._replay_interrupted_publication(
                ledger, receipt, run_control, delete_points, replay_source
            )
            return
        RunCheckpointBase._recover_confirmed_publication(
            ledger, receipt, generation, run_control
        )

    @staticmethod
    def _replay_interrupted_publication(
        ledger: RunLedger,
        receipt: PublicationReceipt,
        run_control: RunControl,
        delete_points: Callable[[list[str]], None],
        replay_source: Callable[[], object],
    ) -> None:
        from .._publication_state import publication_recovery_reads

        paths = tuple(
            sorted(
                {item.unit.rel_path for item in receipt.mutations}
                | set(ledger.publication_replay_paths(receipt.receipt_id))
            )
        )
        points = {point for item in receipt.mutations for point in item.unit.point_ids}
        for start in range(0, len(paths), FETCH_BATCH):
            evidence = ledger.publication_evidence_for_paths(
                receipt.compatibility_key, paths[start : start + FETCH_BATCH]
            )
            points.update(
                point for item in evidence.values() for point in item.point_ids
            )
        ledger.resume_publication_generation(receipt.receipt_id)
        ledger.begin_publication_storage_reset(receipt.receipt_id, paths)
        ordered_points = sorted(points)
        for start in range(0, len(ordered_points), FETCH_BATCH):
            run_control.checkpoint()
            delete_points(ordered_points[start : start + FETCH_BATCH])
        receipt = ledger.reopen_publication_after_storage_reset(
            receipt.receipt_id, paths
        )
        token = _PUBLICATION_REPLAY.set(
            _PublicationReplay(receipt, frozenset(paths), delete_points)
        )
        try:
            with publication_recovery_reads(receipt):
                replay_source()
        finally:
            _PUBLICATION_REPLAY.reset(token)
        pending = ledger.active_publication_receipt(receipt.compatibility_key)
        if pending is not None:
            if pending.mutations:
                raise RunLedgerStateError("publication source replay did not finish")
            # A new path may have disappeared before replay and leave no delta.
            RunCheckpointBase._assert_replayed_parent_paths(
                ledger, pending, frozenset(paths)
            )
            ledger.clear_publication_replay_markers(receipt.receipt_id)
            ledger.begin_publication_rollback(receipt.receipt_id)
            ledger.roll_back_publication_receipt(
                receipt.receipt_id, compensated_units=()
            )
            ledger.finish_generation(
                receipt.generation_id, RunTerminalState.INVALIDATED
            )

    @staticmethod
    def _assert_replayed_parent_paths(
        ledger: RunLedger, receipt: PublicationReceipt, paths: frozenset[str]
    ) -> None:
        """Never certify parent points removed for a replay that skipped its file."""
        ordered = tuple(sorted(paths))
        for start in range(0, len(ordered), FETCH_BATCH):
            parents = ledger.publication_evidence_for_paths(
                receipt.compatibility_key, ordered[start : start + FETCH_BATCH]
            )
            for rel_path, parent in parents.items():
                mutations = [
                    item for item in receipt.mutations if item.unit.rel_path == rel_path
                ]
                if not mutations or any(
                    item.state is not ProofMutationState.CONFIRMED for item in mutations
                ):
                    raise RunLedgerStateError(
                        f"publication replay has unresolved parent path {rel_path!r}"
                    )
                upserts = [
                    item.unit
                    for item in mutations
                    if item.unit.kind is CommitUnitKind.UPSERT
                ]
                new = RunCheckpointBase._new_evidence(rel_path, tuple(upserts))
                if new is not None:
                    validate_publication_mutation_group(
                        (CommitUnitKind.UPSERT, rel_path),
                        upserts,
                        expected_points=frozenset(new.point_ids),
                        expected_content=new.content_identity,
                    )
                else:
                    deleted = [
                        item.unit
                        for item in mutations
                        if item.unit.kind is CommitUnitKind.DELETE_PATH
                    ]
                    validate_publication_mutation_group(
                        (CommitUnitKind.DELETE_PATH, rel_path),
                        deleted,
                        expected_points=frozenset(parent.point_ids),
                        expected_content=None,
                    )

    @staticmethod
    def _complete_mutation_streams(
        receipt: PublicationReceipt, deltas: tuple[PathDelta, ...]
    ) -> bool:
        # The same validator used by receipt sealing rejects truncated or gapped
        # file streams before recovery writes anything or certifies partial bytes.
        for delta in deltas:
            if delta.new is None:
                continue
            units = [
                item.unit
                for item in receipt.mutations
                if item.unit.kind is CommitUnitKind.UPSERT
                and item.unit.rel_path == delta.new.rel_path
            ]
            try:
                validate_publication_mutation_group(
                    (CommitUnitKind.UPSERT, delta.new.rel_path),
                    units,
                    expected_points=frozenset(delta.new.point_ids),
                    expected_content=delta.new.content_identity,
                )
            except ValueError:
                return False
        return True

    @staticmethod
    def _recover_unsealed_publication(
        ledger: RunLedger,
        receipt: PublicationReceipt,
        run_control: RunControl,
        delete_points: Callable[[list[str]], None],
    ) -> PublicationReceipt:
        """Finish complete recorded file streams without consulting source bytes."""
        if receipt.state not in {ProofReceiptState.RESERVED, ProofReceiptState.SEALED}:
            return receipt
        if _PUBLICATION_REPLAY.get() is None and ledger.publication_replay_paths(
            receipt.receipt_id
        ):
            return receipt
        if any(
            mutation.unit.kind is CommitUnitKind.UPSERT
            and mutation.state is ProofMutationState.PREPARED
            for mutation in receipt.mutations
        ):
            return receipt
        paths = tuple(sorted({item.unit.rel_path for item in receipt.mutations}))
        old_by_path: dict[str, ProofEvidence] = {}
        for start in range(0, len(paths), FETCH_BATCH):
            old_by_path.update(
                ledger.publication_evidence_for_paths(
                    receipt.compatibility_key, paths[start : start + FETCH_BATCH]
                )
            )
        deltas = (
            receipt.deltas
            if receipt.state is ProofReceiptState.SEALED
            else tuple(
                RunCheckpointBase._publication_deltas(receipt, paths, old_by_path)
            )
        )
        if not RunCheckpointBase._complete_mutation_streams(receipt, deltas):
            return receipt
        if not deltas:
            return receipt
        ledger.resume_publication_generation(receipt.receipt_id)
        for delta in deltas:
            deletion = expected_publication_deletion(delta)
            if deletion is None:
                continue
            kind, rel_path, point_ids = deletion
            unit = RunCheckpointBase._deletion_unit(
                rel_path, kind, tuple(sorted(point_ids))
            )
            mutation = ledger.prepare_publication_mutation(receipt.receipt_id, unit)
            if mutation.state is ProofMutationState.PREPARED:
                run_control.checkpoint()
                delete_points(list(unit.point_ids))
                ledger.mark_publication_mutation_applied(receipt.receipt_id, unit)
            ledger.confirm_publication_mutation(receipt.receipt_id, unit)
        for mutation in receipt.mutations:
            if mutation.state is ProofMutationState.APPLIED:
                ledger.confirm_publication_mutation(receipt.receipt_id, mutation.unit)
        return ledger.seal_publication_receipt(receipt.receipt_id, deltas)

    @staticmethod
    def _recover_confirmed_publication(
        ledger: RunLedger,
        receipt: PublicationReceipt,
        generation: RunGeneration,
        run_control: RunControl,
    ) -> None:
        """Replay durable outcomes, then commit the recorded sealed delta."""
        ledger.resume_publication_generation(receipt.receipt_id)
        from .._source_types import PublicSourceType
        from ._content_policy import ContentKind

        for mutation in receipt.mutations:
            run_control.checkpoint()
            unit = mutation.unit
            if generation.finalization_phase is not FinalizationPhase.INGESTING:
                if not ledger.unit_committed(generation.generation_id, unit):
                    raise RunLedgerStateError(
                        "finalizing receipt lacks its storage-confirmed checkpoint unit"
                    )
                continue
            ledger.record_storage_confirmed_unit(generation.generation_id, unit)
            if unit.kind is CommitUnitKind.DELETE_PATH:
                ledger.record_path_deleted(generation.generation_id, unit.rel_path)
            elif (
                unit.kind is CommitUnitKind.UPSERT
                and unit.is_file_end
                and generation.signature.source_type is not PublicSourceType.VAULT
            ):
                assert unit.source_digest is not None
                ledger.record_file_state(
                    generation.generation_id,
                    FileState.indexed(
                        unit.rel_path,
                        ContentKind(generation.signature.source_type.value),
                        unit.source_digest,
                    ),
                )
        current = ledger.generation(generation.generation_id)
        if current.finalization_phase is FinalizationPhase.INGESTING:
            ledger.advance_finalization(
                generation.generation_id, FinalizationPhase.STALE_RECONCILED
            )
        ledger.commit_publication_receipt(receipt.receipt_id)
        if current.finalization_phase in {
            FinalizationPhase.INGESTING,
            FinalizationPhase.STALE_RECONCILED,
        }:
            ledger.advance_finalization(
                generation.generation_id, FinalizationPhase.METADATA_PUBLISHED
            )
        with ledger_connection(ledger.path) as connection:
            connection.execute("BEGIN")
            ledger.assert_generation_proof_committed(
                connection, generation.generation_id
            )
        ledger.advance_finalization(
            generation.generation_id, FinalizationPhase.GENERATION_PUBLISHED
        )
        ledger.finish_generation(generation.generation_id, RunTerminalState.SUCCEEDED)

    @classmethod
    def open_generation(cls, request: RunOpenRequest, /) -> Self:
        """Open or resume the compatible generation for one attempt.

        One body for every source type: the four facts that differ are
        the class constants above, so a change to how a generation is
        opened cannot reach one source and miss the other.
        """
        assert cls._content_kind is not None
        fingerprints = request.policy.fingerprints_for(cls._content_kind)
        signature = RunSignature(
            root_identity=str(request.root_dir.resolve()),
            collection_identity=cls._collection_identity,
            source_type=cls._source_type,
            operation=request.operation,
            clean=request.clean,
            model_identity=request.model_identity,
            dense_dimensions=request.dense_dimensions,
            embedding_schema=cls._embedding_schema,
            payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
            content_epoch=fingerprints.content,
            membership_epoch=fingerprints.membership,
            preprocessing_identity=request.policy.fingerprints.execution,
            configuration_fingerprint=configuration_fingerprint(request.configuration),
            policy_fingerprint=request.policy.fingerprints.snapshot,
            backend_identity=request.backend_identity,
        )
        ledger = RunLedger(index_run_ledger_path(request.data_root))
        generation = cls.start_compatible_generation(
            ledger, signature, request.authority, request.run_policy
        )
        receipt = cls.open_publication_receipt(ledger, generation, request.authority)
        return cls(
            ledger=ledger,
            generation=generation,
            policy=request.policy,
            run_policy=request.run_policy,
            authority=request.authority,
            receipt=receipt,
        )

    @classmethod
    def start_compatible_generation(
        cls,
        ledger: RunLedger,
        signature: RunSignature,
        authority: RunAuthority,
        run_policy: RunPolicy,
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
        if authority is RunAuthority.REBUILD:
            cls._recover_publication_for_rebuild(ledger, signature, run_policy)
        replay = _PUBLICATION_REPLAY.get()
        if replay is not None and authority is RunAuthority.PUBLICATION:
            from ._run_ledger_publication_identity import compatibility_for_signature

            if (
                compatibility_for_signature(signature)
                != replay.receipt.compatibility_key
            ):
                raise RunLedgerCompatibilityError(
                    "source replay policy differs from its publication"
                )
            signature = ledger.generation(replay.receipt.generation_id).signature
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
    def _recover_publication_for_rebuild(
        cls,
        ledger: RunLedger,
        signature: RunSignature,
        run_policy: RunPolicy,
    ) -> None:
        """Finish only exact recorded work before admitting a replacement build."""
        receipt = ledger.rebuild_recovery_receipt(signature, RunAuthority.REBUILD)
        if receipt is None:
            return
        run_policy.checkpoint("recover unfinished publication")
        if (
            not receipt.mutations
            and not receipt.deltas
            and ledger.committed_unit_count(receipt.generation_id) == 0
        ):
            ledger.begin_publication_rollback(receipt.receipt_id)
            ledger.roll_back_publication_receipt(
                receipt.receipt_id, compensated_units=()
            )
            run_policy.record_durable_progress(
                kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
                label="publication receipt rollback recovery",
            )
            return
        if receipt.state is not ProofReceiptState.SEALED or any(
            mutation.state is not ProofMutationState.CONFIRMED
            for mutation in receipt.mutations
        ):
            raise RunLedgerStateError(
                "unfinished publication requires exact recorded-unit recovery "
                "before rebuild"
            )
        ledger.verify_integrity()
        ledger.commit_publication_receipt(
            receipt.receipt_id,
            authority=RunAuthority.REBUILD,
            rebuild_signature=signature,
        )
        run_policy.record_durable_progress(
            kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
            label="publication proof recovery",
        )

    @classmethod
    def open_publication_receipt(
        cls,
        ledger: RunLedger,
        generation: RunGeneration,
        authority: RunAuthority,
    ) -> PublicationReceipt | None:
        """Bind an incremental generation to its canonical parent revision."""
        from ._run_ledger_publication_identity import compatibility_for_signature

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
        completed = ledger.publication_receipt_for_generation(generation.generation_id)
        if completed is not None and ledger.publication_noop_completed(
            generation.generation_id, completed.receipt_id
        ):
            return completed
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
            confirm_when_stored=True,
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
        """Preserve interrupted work and scope an idle ledger handle to the attempt.

        The idle handle avoids last-connection WAL cleanup after each writer
        transaction. It holds no read transaction, and independent writers still
        commit normally. The context closes the handle on every exit.
        """
        try:
            with ledger_connection(self.ledger.path):
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
        self.run_policy.checkpoint(f"{self._kind_label} proof publication entry")
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
        self.run_policy.record_durable_progress(
            kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
            label=f"{self._kind_label} proof publication",
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
            return self.seal_incremental_proof()
        from ._run_ledger_publication_identity import compatibility_for_signature

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

    @staticmethod
    def _publication_deltas(
        receipt: PublicationReceipt,
        paths: tuple[str, ...],
        old_by_path: dict[str, ProofEvidence],
    ) -> list[PathDelta]:
        """Derive changed heads from confirmed mutations and the exact parent proof."""
        deltas: list[PathDelta] = []
        upserts_by_path: dict[str, list[CommitUnit]] = {}
        for mutation in receipt.mutations:
            if mutation.unit.kind is CommitUnitKind.UPSERT:
                upserts_by_path.setdefault(mutation.unit.rel_path, []).append(
                    mutation.unit
                )
        for rel_path in paths:
            upserts = tuple(upserts_by_path.get(rel_path, ()))
            old = old_by_path.get(rel_path)
            new = RunCheckpointBase._new_evidence(rel_path, upserts)
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
        return deltas

    def seal_incremental_proof(self) -> int:
        """Freeze an incremental receipt's exact delta before stale deletion."""
        if self.receipt is None:
            raise RunLedgerStateError("incremental publication has no receipt")
        if self.ledger.publication_noop_completed(
            self.generation_id, self.receipt.receipt_id
        ):
            return 0
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
        deltas = self._publication_deltas(receipt, paths, old_by_path)
        if _PUBLICATION_REPLAY.get() is not None:
            receipt = self._finish_replayed_source(receipt, deltas, old_by_path)
            if receipt.state is ProofReceiptState.SEALED:
                return len(deltas)
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

    def _finish_replayed_source(
        self,
        receipt: PublicationReceipt,
        deltas: list[PathDelta],
        old_by_path: dict[str, ProofEvidence],
    ) -> PublicationReceipt:
        """Close source replay only after exact confirmation of every current path."""
        replay = _PUBLICATION_REPLAY.get()
        assert replay is not None
        self._assert_replayed_parent_paths(self.ledger, receipt, replay.paths)
        unchanged = tuple(
            sorted(
                {item.unit.rel_path for item in receipt.mutations}
                - {delta.rel_path for delta in deltas}
            )
        )
        if unchanged:
            for rel_path in unchanged:
                units = [
                    item.unit
                    for item in receipt.mutations
                    if item.unit.rel_path == rel_path
                    and item.unit.kind is CommitUnitKind.UPSERT
                ]
                old = old_by_path.get(rel_path)
                if old is None or self._new_evidence(rel_path, tuple(units)) != old:
                    raise RunLedgerStateError(
                        "replayed no-op does not restore its parent"
                    )
                validate_publication_mutation_group(
                    (CommitUnitKind.UPSERT, rel_path),
                    units,
                    expected_points=frozenset(old.point_ids),
                    expected_content=old.content_identity,
                )
            receipt = self.ledger.discard_restored_publication_paths(
                receipt.receipt_id, unchanged
            )
        # A vanished new path has no parent membership to delete. Its replay
        # marker has served its purpose once this complete scan has returned.
        self.ledger.clear_publication_replay_markers(receipt.receipt_id)
        if deltas:
            recovered = self._recover_unsealed_publication(
                self.ledger,
                receipt,
                self.run_policy,
                replay.delete_points,
            )
            if recovered.state is not ProofReceiptState.SEALED:
                raise RunLedgerStateError(
                    "replayed source has incomplete file evidence"
                )
            # Deletions synthesized from the parent proof use the same
            # durable checkpoint bookkeeping as ordinary ingestion.
            for item in recovered.mutations:
                if item.unit.kind is CommitUnitKind.DELETE_PATH:
                    self.record_confirmed_deletion(
                        item.unit.rel_path, item.unit.point_ids
                    )
                elif item.unit.kind is CommitUnitKind.DELETE_STALE:
                    self.record_confirmed_stale_deletion(
                        item.unit.rel_path, item.unit.point_ids
                    )
            return recovered
        return receipt

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
        self.run_policy.checkpoint(f"{self._kind_label} generation publication entry")
        phase = self.generation.finalization_phase
        if phase in (
            FinalizationPhase.INGESTING,
            FinalizationPhase.STALE_RECONCILED,
        ):
            raise RunLedgerStateError(
                f"{self._kind_label} metadata must be durably published "
                "before generation publication"
            )
        if self.generation.terminal_state is RunTerminalState.RUNNING:
            with ledger_connection(self.ledger.path) as connection:
                connection.execute("BEGIN")
                self.ledger.assert_generation_proof_committed(
                    connection, self.generation_id
                )
        if phase is FinalizationPhase.METADATA_PUBLISHED:
            self.generation = self.ledger.advance_finalization(
                self.generation_id,
                FinalizationPhase.GENERATION_PUBLISHED,
            )
            self.run_policy.record_durable_progress(
                kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
                label=f"{self._kind_label} generation publication phase",
            )
        if self.generation.terminal_state is RunTerminalState.RUNNING:
            self.run_policy.checkpoint(f"{self._kind_label} terminal publication")
            self.generation = self.ledger.finish_generation(
                self.generation_id,
                RunTerminalState.SUCCEEDED,
            )
        if self.generation.terminal_state is RunTerminalState.SUCCEEDED:
            self.run_policy.complete(label=f"{self._kind_label} terminal publication")
        if self.generation.finalization_phase is not FinalizationPhase.COMPACTED:
            self.ledger.compact(self.generation_id)
        self.generation = self.ledger.generation(self.generation_id)
        return self.generation

    def _record_indexed_file(self, rel_path: str, source_digest: str) -> None:
        if self._content_kind is None:
            raise RunLedgerStateError("indexed files require content kind")
        self.ledger.record_file_state(
            self.generation_id,
            FileState.indexed(rel_path, self._content_kind, source_digest),
        )
