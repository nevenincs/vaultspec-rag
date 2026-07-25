"""Bridge bounded code segments to storage-confirmed run-ledger evidence."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .. import store_schema
from ._checkpoint_common import (
    classify_interrupted_generation,
    configuration_fingerprint,
)
from ._code_meta import CODE_EMBED_SCHEMA, publish_meta_from_file_states
from ._content_policy import AdmissionDisposition, AdmissionReason, ContentKind
from ._file_state import FileState, FileStateKind
from ._run_ledger import (
    INDEX_RUN_LEDGER_FILENAME,
    CommitUnit,
    CommitUnitKind,
    FinalizationPhase,
    RunGeneration,
    RunLedger,
    RunLedgerCompatibilityError,
    RunLedgerStateError,
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)
from ._run_policy import DurableProgressKind, RunPolicy

if TYPE_CHECKING:
    from collections.abc import Generator, Iterable, Mapping
    from pathlib import Path

    from ._resolved_policy import ResolvedIndexPolicy
    from ._streaming import CodeFileSegment

__all__ = [
    "CODE_RUN_LEDGER_FILENAME",
    "CodeRunCheckpoint",
    "CodeRunConfiguration",
]

CODE_RUN_LEDGER_FILENAME = INDEX_RUN_LEDGER_FILENAME


@dataclass(frozen=True, slots=True)
class CodeRunConfiguration:
    """Closed compatibility inputs that shape code commit units and writes."""

    segment_max_chunks: int
    segment_max_bytes: int
    queue_max_chunks: int
    queue_max_bytes: int
    slice_max_chunks: int
    slice_max_bytes: int
    sparse_enabled: bool
    sparse_dimension: int
    encode_batch_size: int
    flush_slices: int

    def __post_init__(self) -> None:
        for name in (
            "segment_max_chunks",
            "segment_max_bytes",
            "queue_max_chunks",
            "queue_max_bytes",
            "slice_max_chunks",
            "slice_max_bytes",
            "sparse_dimension",
            "encode_batch_size",
            "flush_slices",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.sparse_enabled, bool):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("sparse_enabled must be a bool")


@dataclass(slots=True)
class CodeRunCheckpoint:
    """One code generation's durable segment and publication authority."""

    ledger: RunLedger
    generation: RunGeneration
    policy: ResolvedIndexPolicy
    run_policy: RunPolicy
    resumed_units: int = 0

    @classmethod
    def open(
        cls,
        *,
        data_root: Path,
        root_dir: Path,
        policy: ResolvedIndexPolicy,
        run_policy: RunPolicy,
        operation: RunOperation,
        clean: bool,
        model_identity: str,
        dense_dimensions: int,
        configuration: CodeRunConfiguration,
    ) -> CodeRunCheckpoint:
        """Open or resume the compatible code generation for one attempt."""
        kind_fingerprints = policy.fingerprints_for(ContentKind.CODE)
        signature = RunSignature(
            root_identity=str(root_dir.resolve()),
            collection_identity=store_schema.CODE_COLLECTION,
            source_type=ContentKind.CODE,
            operation=operation,
            clean=clean,
            model_identity=model_identity,
            dense_dimensions=dense_dimensions,
            embedding_schema=int(CODE_EMBED_SCHEMA),
            payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
            content_epoch=kind_fingerprints.content,
            membership_epoch=kind_fingerprints.membership,
            preprocessing_identity=policy.fingerprints.execution,
            configuration_fingerprint=configuration_fingerprint(configuration),
            policy_fingerprint=policy.fingerprints.snapshot,
        )
        ledger = RunLedger(index_run_ledger_path(data_root))
        generation = ledger.start_generation(signature)
        if (
            operation in (RunOperation.INCREMENTAL, RunOperation.SCOPED_INCREMENTAL)
            and generation.parent_generation_id is None
        ):
            raise RunLedgerCompatibilityError(
                "incremental indexing requires a compatible published manifest; "
                "run a full reconciliation"
            )
        return cls(
            ledger=ledger,
            generation=generation,
            policy=policy,
            run_policy=run_policy,
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

    def unit_for(self, segment: CodeFileSegment, source_digest: str) -> CommitUnit:
        """Project one deterministic streaming segment into ledger evidence."""
        return CommitUnit(
            rel_path=segment.path,
            kind=CommitUnitKind.UPSERT,
            source_digest=source_digest,
            segment_ordinal=segment.ordinal,
            is_file_end=segment.is_file_end,
            point_ids=tuple(chunk.id for chunk in segment.chunks),
        )

    def pending_segments(
        self,
        segments: Iterable[CodeFileSegment],
        source_digest: str,
    ) -> Iterable[CodeFileSegment]:
        """Yield only units not already confirmed by a compatible attempt."""
        for segment in segments:
            unit = self.unit_for(segment, source_digest)
            if self.ledger.unit_committed(self.generation_id, unit):
                self.resumed_units += 1
                if segment.is_file_end:
                    self._record_indexed_file(segment.path, source_digest)
                continue
            yield segment

    def record_confirmed_segment(
        self,
        segment: CodeFileSegment,
        source_digest: str,
    ) -> bool:
        """Checkpoint exactly one matching storage mutation after it returns."""
        unit = self.unit_for(segment, source_digest)
        inserted = self.ledger.record_storage_confirmed_unit(
            self.generation_id,
            unit,
        )
        if inserted:
            self.run_policy.record_durable_progress(
                kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
                label=f"code segment {segment.path}#{segment.ordinal}",
            )
        if segment.is_file_end:
            self._record_indexed_file(segment.path, source_digest)
        return inserted

    def record_confirmed_segments(
        self,
        segments: tuple[CodeFileSegment, ...],
        source_digests: dict[str, str],
    ) -> int:
        """Atomically checkpoint every segment in one confirmed store mutation."""
        if not segments:
            raise ValueError("a confirmed code store mutation must contain segments")
        units = tuple(
            self.unit_for(segment, source_digests[segment.path]) for segment in segments
        )
        inserted = self.ledger.record_storage_confirmed_units(
            self.generation_id,
            units,
        )
        if inserted:
            self.run_policy.record_durable_progress(
                kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
                label=(
                    f"code store mutation with {len(segments)} segment(s) "
                    f"and {inserted} new ledger unit(s)"
                ),
            )
        for segment in segments:
            if segment.is_file_end:
                self._record_indexed_file(
                    segment.path,
                    source_digests[segment.path],
                )
        return inserted

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
                label=f"code deletion {rel_path}",
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
                label=f"stale code deletion {rel_path}",
            )
        return inserted

    def drifted_indexed_paths(
        self,
        current_digests: Mapping[str, str],
    ) -> dict[str, str]:
        """Return resumed indexed paths whose source has since changed.

        Maps each affected path to the digest recorded when it was indexed,
        which is the evidence the caller must supersede. A path is reported
        only when this generation recorded it indexed and the digest observed
        now differs, so a fresh generation reports nothing and a faithful
        resume reports only what actually moved.
        """
        recorded = self.ledger.indexed_digests_for_paths(
            self.generation_id,
            tuple(current_digests),
        )
        return {
            rel_path: digest
            for rel_path, digest in recorded.items()
            if current_digests[rel_path] != digest
        }

    def reopen_drifted_path(self, rel_path: str, superseded_digest: str) -> int:
        """Clear stale indexed evidence so one path can be ingested again."""
        removed = self.ledger.reopen_drifted_path(
            self.generation_id,
            rel_path,
            superseded_digest=superseded_digest,
        )
        if removed:
            self.run_policy.record_durable_progress(
                kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
                label=f"code re-open {rel_path} superseding {removed} unit(s)",
            )
        return removed

    def record_empty_source(
        self,
        rel_path: str,
        *,
        content_hash: str | None = None,
    ) -> None:
        """Converge a source that carried no content to index."""
        self.ledger.record_file_state(
            self.generation_id,
            FileState.policy_rejected(
                rel_path,
                AdmissionDisposition(
                    kind=ContentKind.CODE,
                    admitted=False,
                    reason=AdmissionReason.SOURCE_EMPTY,
                ),
                content_hash=content_hash,
            ),
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
        self.ledger.record_file_state(
            self.generation_id,
            FileState.failed(
                rel_path,
                state,
                ContentKind.CODE,
                detail,
                content_hash=content_hash,
            ),
        )

    def publish_metadata(self, meta_path: Path, *, published_points: int) -> int:
        """Publish exact converged ledger rows and advance the durable phase.

        ``published_points`` is the collection point count as observed by the
        caller after storage reconciliation, so the sidecar records the breadth
        it actually describes rather than an estimate.
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
        fingerprints = self.policy.fingerprints_for(ContentKind.CODE)
        count = publish_meta_from_file_states(
            meta_path,
            self.ledger.iter_file_states(self.generation_id),
            generation_id=self.generation_id,
            membership_epoch=fingerprints.membership,
            content_epoch=fingerprints.content,
            published_points_count=published_points,
        )
        self.generation = self.ledger.advance_finalization(
            self.generation_id,
            FinalizationPhase.METADATA_PUBLISHED,
        )
        self.run_policy.record_durable_progress(
            kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
            label="code metadata publication",
        )
        return count

    def publish_generation(self) -> RunGeneration:
        """Certify generation publication and compact prior compatible rows."""
        phase = self.generation.finalization_phase
        if phase in (
            FinalizationPhase.INGESTING,
            FinalizationPhase.STALE_RECONCILED,
        ):
            raise RunLedgerStateError(
                "metadata must be durably published before generation publication"
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
            label="code generation publication",
        )
        return self.generation

    def _record_indexed_file(self, rel_path: str, source_digest: str) -> None:
        self.ledger.record_file_state(
            self.generation_id,
            FileState.indexed(rel_path, ContentKind.CODE, source_digest),
        )
