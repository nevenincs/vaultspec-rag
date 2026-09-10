"""Bridge bounded document slices to the shared storage-confirmed ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar

from .. import store_schema
from .._source_types import PublicSourceType
from ._checkpoint_common import RunCheckpointBase
from ._content_policy import ContentKind
from ._index_schema import DOCUMENT_EMBED_SCHEMA
from ._run_ledger_models import (
    CommitUnit,
    CommitUnitKind,
    RunAuthority,
    RunOperation,
    RunTerminalState,
)
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
    backend_identity: str
    authority: RunAuthority


@dataclass(slots=True)
class DocumentRunCheckpoint(RunCheckpointBase):
    """One document generation's durable storage and publication authority."""

    _content_kind: ClassVar[ContentKind | None] = ContentKind.DOCUMENT
    _kind_label: ClassVar[str] = "document"
    _collection_identity: ClassVar[str] = store_schema.DOCUMENT_COLLECTION
    _source_type: ClassVar[PublicSourceType] = PublicSourceType.DOCUMENT
    _embedding_schema: ClassVar[int] = DOCUMENT_EMBED_SCHEMA

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

    def mark_failed(self, detail: str) -> None:
        """Keep an unresolved generation resumable without certifying metadata."""
        if self.generation.terminal_state is RunTerminalState.RUNNING:
            self.generation = self.ledger.finish_generation(
                self.generation_id,
                RunTerminalState.FAILED,
                detail=detail,
            )
