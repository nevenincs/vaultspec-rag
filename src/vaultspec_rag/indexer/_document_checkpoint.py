"""Bridge bounded document slices to the shared storage-confirmed ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from .. import store_schema
from ._checkpoint_common import RunCheckpointBase, configuration_fingerprint
from ._content_policy import ContentKind
from ._document_meta import (
    DOCUMENT_EMBED_SCHEMA,
    publish_document_meta_from_file_states,
)
from ._file_state import FileStateKind
from ._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    RunOperation,
    RunSignature,
    RunTerminalState,
    index_run_ledger_path,
)
from ._run_ledger_runtime import RunLedger
from ._run_policy import DurableProgressKind, RunPolicy

if TYPE_CHECKING:
    from pathlib import Path

    from ._resolved_policy import ResolvedIndexPolicy

__all__ = [
    "DocumentRunCheckpoint",
    "DocumentRunConfiguration",
    "DocumentRunOpenRequest",
]


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
        if not isinstance(self.sparse_enabled, bool):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("sparse_enabled must be a bool")


@dataclass(frozen=True, slots=True)
class DocumentRunOpenRequest:
    """All compatibility inputs for opening one document generation.

    One grouped shape rather than a spread of keywords, so a field added
    here is declared once and every call site is re-checked against its
    real type.
    """

    data_root: Path
    root_dir: Path
    policy: ResolvedIndexPolicy
    run_policy: RunPolicy
    operation: RunOperation
    clean: bool
    model_identity: str
    dense_dimensions: int
    configuration: DocumentRunConfiguration


@dataclass(slots=True)
class DocumentRunCheckpoint(RunCheckpointBase):
    """One document generation's durable storage and publication authority."""

    _content_kind: ClassVar[ContentKind] = ContentKind.DOCUMENT
    _kind_label: ClassVar[str] = "document"

    @classmethod
    def open(cls, request: DocumentRunOpenRequest, /) -> DocumentRunCheckpoint:
        """Open or resume the compatible document generation for one attempt."""
        fingerprints = request.policy.fingerprints_for(ContentKind.DOCUMENT)
        signature = RunSignature(
            root_identity=str(request.root_dir.resolve()),
            collection_identity=store_schema.DOCUMENT_COLLECTION,
            source_type=ContentKind.DOCUMENT,
            operation=request.operation,
            clean=request.clean,
            model_identity=request.model_identity,
            dense_dimensions=request.dense_dimensions,
            embedding_schema=DOCUMENT_EMBED_SCHEMA,
            payload_schema=store_schema.STORAGE_SCHEMA_VERSION,
            content_epoch=fingerprints.content,
            membership_epoch=fingerprints.membership,
            preprocessing_identity=request.policy.fingerprints.execution,
            configuration_fingerprint=configuration_fingerprint(request.configuration),
            policy_fingerprint=request.policy.fingerprints.snapshot,
        )
        ledger = RunLedger(index_run_ledger_path(request.data_root))
        generation = cls.start_compatible_generation(ledger, signature)
        return cls(ledger, generation, request.policy, request.run_policy)

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

    def current_files(self) -> dict[str, tuple[str, tuple[str, ...]]]:
        """Return the current indexed manifest reconstructed from ledger rows."""
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
        return self.publish_metadata_transition(
            lambda fingerprints: publish_document_meta_from_file_states(
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
        )
