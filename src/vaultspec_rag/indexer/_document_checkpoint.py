"""Bridge bounded document slices to the shared storage-confirmed ledger."""

from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

from .. import store_schema
from ._content_policy import ContentKind
from ._document_meta import (
    DOCUMENT_EMBED_SCHEMA,
    publish_document_meta_from_file_states,
)
from ._file_state import FileState, FileStateKind
from ._run_ledger import (
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
    from collections.abc import Generator
    from pathlib import Path

    from ._resolved_policy import ResolvedIndexPolicy

__all__ = ["DocumentRunCheckpoint", "DocumentRunConfiguration"]


@dataclass(frozen=True, slots=True)
class DocumentRunConfiguration:
    """Closed compatibility inputs that shape document commit units."""

    slice_max_chunks: int
    source_bytes: int
    generated_chunks: int
    weighted_bytes: int
    sparse_enabled: bool
    sparse_dimension: int
    encode_batch_size: int

    def __post_init__(self) -> None:
        for name in (
            "slice_max_chunks",
            "source_bytes",
            "generated_chunks",
            "weighted_bytes",
            "sparse_dimension",
            "encode_batch_size",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if not isinstance(self.sparse_enabled, bool):
            raise TypeError("sparse_enabled must be a bool")


@dataclass(slots=True)
class DocumentRunCheckpoint:
    """One document generation's durable storage and publication authority."""

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
        configuration: DocumentRunConfiguration,
    ) -> DocumentRunCheckpoint:
        """Open or resume the compatible document generation for one attempt."""
        fingerprints = policy.fingerprints_for(ContentKind.DOCUMENT)
        signature = RunSignature(
            root_identity=str(root_dir.resolve()),
            collection_identity=store_schema.DOCUMENT_COLLECTION,
            source_type=ContentKind.DOCUMENT,
            operation=operation,
            clean=clean,
            model_identity=model_identity,
            dense_dimensions=dense_dimensions,
            embedding_schema=DOCUMENT_EMBED_SCHEMA,
            payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
            content_epoch=fingerprints.content,
            membership_epoch=fingerprints.membership,
            preprocessing_identity=policy.fingerprints.execution,
            configuration_fingerprint=_configuration_fingerprint(configuration),
            policy_fingerprint=policy.fingerprints.snapshot,
        )
        ledger = RunLedger(index_run_ledger_path(data_root))
        generation = ledger.start_generation(signature)
        if (
            operation in (RunOperation.INCREMENTAL, RunOperation.SCOPED_INCREMENTAL)
            and generation.parent_generation_id is None
        ):
            raise RunLedgerCompatibilityError(
                "incremental document indexing requires a compatible published "
                "manifest; run a full reconciliation"
            )
        return cls(ledger, generation, policy, run_policy)

    @property
    def generation_id(self) -> str:
        """Return the stable active generation identifier."""
        return self.generation.generation_id

    @property
    def ingestion_complete(self) -> bool:
        """Return whether this attempt should resume finalization only."""
        return self.generation.finalization_phase is not FinalizationPhase.INGESTING

    @contextmanager
    def preserve_incomplete_generation(self) -> Generator[None]:
        """Persist interruption state while preserving the original exception."""
        try:
            yield
        except BaseException as exc:
            if self.generation.terminal_state is RunTerminalState.RUNNING:
                terminal_state = (
                    RunTerminalState.REBUILD_INCOMPLETE
                    if self.generation.destructive_intent
                    else RunTerminalState.FAILED
                )
                detail = f"{type(exc).__name__}: {exc}".rstrip()
                self.generation = self.ledger.finish_generation(
                    self.generation_id,
                    terminal_state,
                    detail=detail,
                )
            raise

    def unit_for(
        self,
        rel_path: str,
        source_digest: str,
        ordinal: int,
        *,
        is_file_end: bool,
        point_ids: tuple[str, ...],
    ) -> CommitUnit:
        """Project one deterministic document slice into ledger evidence."""
        return CommitUnit(
            rel_path=rel_path,
            kind=CommitUnitKind.UPSERT,
            source_digest=source_digest,
            segment_ordinal=ordinal,
            is_file_end=is_file_end,
            point_ids=point_ids,
        )

    def slice_committed(self, unit: CommitUnit) -> bool:
        """Return whether an exact destination slice is already confirmed."""
        committed = self.ledger.unit_committed(self.generation_id, unit)
        if committed:
            self.resumed_units += 1
        if committed and unit.is_file_end:
            assert unit.source_digest is not None
            self._record_indexed_file(unit.rel_path, unit.source_digest)
        return committed

    def record_confirmed_slice(self, unit: CommitUnit) -> bool:
        """Checkpoint one document slice after its store mutation returns."""
        inserted = self.ledger.record_storage_confirmed_unit(
            self.generation_id,
            unit,
        )
        if inserted:
            self.run_policy.record_durable_progress(
                kind=DurableProgressKind.LEDGER_UNIT_COMMITTED,
                label=f"document slice {unit.rel_path}#{unit.segment_ordinal}",
            )
        if unit.is_file_end:
            assert unit.source_digest is not None
            self._record_indexed_file(unit.rel_path, unit.source_digest)
        return inserted

    def record_confirmed_deletion(
        self,
        rel_path: str,
        point_ids: tuple[str, ...],
    ) -> bool:
        """Checkpoint one idempotent document-path deletion."""
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
                label=f"document deletion {rel_path}",
            )
        self.ledger.record_path_deleted(self.generation_id, rel_path)
        return inserted

    def record_confirmed_stale_deletion(
        self,
        rel_path: str,
        point_ids: tuple[str, ...],
    ) -> bool:
        """Checkpoint obsolete document points while retaining their path."""
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
                label=f"stale document deletion {rel_path}",
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
        """Replace carried convergence with an explicit document failure."""
        self.ledger.record_file_state(
            self.generation_id,
            FileState.failed(
                rel_path,
                state,
                ContentKind.DOCUMENT,
                detail,
                content_hash=content_hash,
            ),
        )

    def current_files(self) -> dict[str, tuple[str, tuple[str, ...]]]:
        """Return the current indexed manifest reconstructed from ledger rows."""
        from ._file_state import FileStateKind

        result: dict[str, tuple[str, tuple[str, ...]]] = {}
        for state in self.ledger.iter_file_states(self.generation_id):
            if state.state is not FileStateKind.INDEXED:
                continue
            assert state.content_hash is not None
            ids = tuple(
                self.ledger.iter_retained_point_ids(
                    self.generation_id,
                    rel_path=state.rel_path,
                )
            )
            result[state.rel_path] = (state.content_hash, ids)
        return result

    def mark_failed(self, detail: str) -> None:
        """Keep an unresolved generation resumable without certifying metadata."""
        if self.generation.terminal_state is RunTerminalState.RUNNING:
            self.generation = self.ledger.finish_generation(
                self.generation_id,
                RunTerminalState.FAILED,
                detail=detail,
            )

    def publish_metadata(self, meta_path: Path) -> int:
        """Publish converged document rows and advance the durable phase."""
        phase = self.generation.finalization_phase
        if phase is FinalizationPhase.INGESTING:
            self.generation = self.ledger.advance_finalization(
                self.generation_id,
                FinalizationPhase.STALE_RECONCILED,
            )
            phase = self.generation.finalization_phase
        if phase is not FinalizationPhase.STALE_RECONCILED:
            return 0
        fingerprints = self.policy.fingerprints_for(ContentKind.DOCUMENT)
        count = publish_document_meta_from_file_states(
            meta_path,
            self.ledger.iter_file_states(self.generation_id),
            point_ids_for_path=lambda path: self.ledger.iter_retained_point_ids(
                self.generation_id,
                rel_path=path,
            ),
            generation_id=self.generation_id,
            membership_fingerprint=fingerprints.membership,
            content_fingerprint=fingerprints.content,
            policy_snapshot=self.policy.fingerprints.snapshot,
        )
        self.generation = self.ledger.advance_finalization(
            self.generation_id,
            FinalizationPhase.METADATA_PUBLISHED,
        )
        self.run_policy.record_durable_progress(
            kind=DurableProgressKind.FINALIZATION_PHASE_COMMITTED,
            label="document metadata publication",
        )
        return count

    def publish_generation(self) -> RunGeneration:
        """Certify document publication and compact prior compatible rows."""
        phase = self.generation.finalization_phase
        if phase in (FinalizationPhase.INGESTING, FinalizationPhase.STALE_RECONCILED):
            raise RunLedgerStateError(
                "document metadata must be durable before generation publication"
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
            label="document generation publication",
        )
        return self.generation

    def _record_indexed_file(self, rel_path: str, source_digest: str) -> None:
        self.ledger.record_file_state(
            self.generation_id,
            FileState.indexed(rel_path, ContentKind.DOCUMENT, source_digest),
        )


def _configuration_fingerprint(configuration: DocumentRunConfiguration) -> str:
    payload = json.dumps(asdict(configuration), sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(payload.encode("utf-8")).hexdigest()
