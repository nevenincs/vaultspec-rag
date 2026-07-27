"""Run-ledger value objects, schema contract, and durable identity rules."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from ._content_policy import ContentKind
from ._file_state import validate_rel_path

__all__ = [
    "INDEX_RUN_LEDGER_FILENAME",
    "CommitUnit",
    "CommitUnitKind",
    "FinalizationPhase",
    "RunGeneration",
    "RunLedgerCompatibilityError",
    "RunLedgerCorruptionError",
    "RunLedgerError",
    "RunLedgerIndexedPathCollisionError",
    "RunLedgerStateError",
    "RunOperation",
    "RunSignature",
    "RunTerminalState",
    "index_run_ledger_path",
]

SCHEMA_VERSION: Final = 6
FETCH_BATCH: Final = 256
_DIGEST_REPR_LENGTH: Final = 128
INDEX_RUN_LEDGER_FILENAME: Final = "index_runs.sqlite3"
_LEGACY_CODE_RUN_LEDGER_FILENAME: Final = "code_index_runs.sqlite3"
REQUIRED_SCHEMA: Final = {
    "generations": frozenset(
        {
            "generation_id",
            "source_type",
            "collection_identity",
            "signature_fingerprint",
            "signature_json",
            "finalization_phase",
            "terminal_state",
            "destructive_intent",
            "created_at",
            "updated_at",
            "terminal_detail",
            "parent_generation_id",
            "consecutive_failures",
        }
    ),
    "commit_units": frozenset(
        {
            "generation_id",
            "unit_id",
            "rel_path",
            "unit_kind",
            "source_digest",
            "segment_ordinal",
            "is_file_end",
            "point_ids_json",
            "committed_at",
        }
    ),
    "commit_point_ids": frozenset(
        {"generation_id", "unit_id", "point_ordinal", "point_id"}
    ),
    "file_states": frozenset(
        {
            "generation_id",
            "rel_path",
            "state",
            "content_kind",
            "content_hash",
            "admission_reason",
            "error_kind",
            "detail",
            "evidence_generation_id",
        }
    ),
}


def index_run_ledger_path(data_root: Path) -> Path:
    """Return one shared per-root ledger path with legacy continuity."""
    root = Path(data_root)
    current = root / INDEX_RUN_LEDGER_FILENAME
    legacy = root / _LEGACY_CODE_RUN_LEDGER_FILENAME
    if current.exists() or not legacy.is_file():
        return current
    return legacy


class RunLedgerError(RuntimeError):
    """Base class for durable run-ledger failures."""


class RunLedgerCompatibilityError(RunLedgerError):
    """The ledger schema or requested generation is incompatible."""


class RunLedgerCorruptionError(RunLedgerError):
    """SQLite reported corrupt durable state."""


class RunLedgerStateError(RunLedgerError):
    """A requested transition violates immutable generation state."""


class RunLedgerIndexedPathCollisionError(RunLedgerStateError):
    """An upsert unit arrived for a path this generation already indexed.

    Refusing the write is not negotiable: chunk identity embeds a content
    digest, so recording the unit would publish the new content alongside the
    old rather than replacing it. What the bare state error cannot express is
    that the cause is usually benign - a resumed generation carries the indexed
    states of the attempt that failed, and a file edited since then arrives
    under a fresh digest. That is a repairable path, not a broken invariant,
    and only a distinct type lets a caller tell the two apart instead of
    failing the whole run.

    Subclasses the general state error so existing handlers keep catching it.
    The digests are carried because they are what separates the two cases and
    what a repair needs: an ``indexed_digest`` differing from ``unit_digest``
    is drift, while equal digests mean the caller re-submitted content the
    generation already committed.
    """

    def __init__(
        self,
        message: str,
        *,
        generation_id: str,
        rel_path: str,
        indexed_digest: str | None,
        unit_digest: str,
    ) -> None:
        super().__init__(message)
        self.generation_id = generation_id
        self.rel_path = rel_path
        self.indexed_digest = indexed_digest
        self.unit_digest = unit_digest

    @property
    def is_drift(self) -> bool:
        """Whether the incoming content differs from what was indexed."""
        return (
            self.indexed_digest is not None and self.indexed_digest != self.unit_digest
        )


class RunOperation(StrEnum):
    """Closed indexing operation vocabulary stored in generation identity."""

    FULL = "full"
    INCREMENTAL = "incremental"
    SCOPED_INCREMENTAL = "scoped_incremental"


class CommitUnitKind(StrEnum):
    """Idempotent external mutation represented by one ledger unit."""

    UPSERT = "upsert"
    DELETE_PATH = "delete_path"
    DELETE_STALE = "delete_stale"


class FinalizationPhase(StrEnum):
    """Ordered externally-confirmed generation publication phases."""

    INGESTING = "ingesting"
    STALE_RECONCILED = "stale_reconciled"
    METADATA_PUBLISHED = "metadata_published"
    GENERATION_PUBLISHED = "generation_published"
    COMPACTED = "compacted"


FINALIZATION_ORDER: Final = tuple(FinalizationPhase)


class RunTerminalState(StrEnum):
    """Stable terminal classifications for one generation."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    INVALIDATED = "invalidated"
    REBUILD_INCOMPLETE = "rebuild_incomplete"


# Consecutive failed attempts against one signature before a generation stops
# being resumable. Three rides out the transient causes worth retrying - a
# momentary allocator failure, a disk blip, a file caught mid-write - while
# bounding a deterministic fault to minutes. Unbounded resumption is what
# turned a single transient failure into a sustained outage: every later
# attempt inherited the same poisoned state and failed identically, with
# nothing in the system able to stop trying.
MAX_RESUME_FAILURES: Final = 3

RESUMABLE_STATES: Final = (
    RunTerminalState.RUNNING,
    RunTerminalState.FAILED,
    RunTerminalState.CANCELLED,
    RunTerminalState.REBUILD_INCOMPLETE,
)


@dataclass(frozen=True, slots=True)
class RunSignature:
    """Canonical compatibility identity for one resumable generation."""

    root_identity: str
    collection_identity: str
    source_type: ContentKind
    operation: RunOperation
    clean: bool
    model_identity: str
    dense_dimensions: int
    embedding_schema: int
    payload_schema: int
    content_epoch: str
    membership_epoch: str
    preprocessing_identity: str
    configuration_fingerprint: str
    policy_fingerprint: str

    def __post_init__(self) -> None:
        for name in (
            "root_identity",
            "collection_identity",
            "model_identity",
            "content_epoch",
            "membership_epoch",
            "preprocessing_identity",
            "configuration_fingerprint",
            "policy_fingerprint",
        ):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(self.source_type, ContentKind):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("source_type must be a ContentKind")
        if not isinstance(self.operation, RunOperation):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("operation must be a RunOperation")
        for name in ("dense_dimensions", "embedding_schema", "payload_schema"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")

    @property
    def canonical_json(self) -> str:
        """Return deterministic serialized compatibility evidence."""
        payload = asdict(self)
        payload["source_type"] = self.source_type.value
        payload["operation"] = self.operation.value
        return json.dumps(payload, sort_keys=True, separators=(",", ":"))

    @property
    def fingerprint(self) -> str:
        """Return a stable digest suitable for indexed lookup."""
        return hashlib.blake2b(self.canonical_json.encode("utf-8")).hexdigest()

    @property
    def content_compatibility_fingerprint(self) -> str:
        """Return identity for safely carrying a published file manifest."""
        payload = asdict(self)
        payload.pop("operation")
        payload.pop("clean")
        # Pipeline sizing shapes resumable commit-unit boundaries, so it must
        # remain part of the exact generation fingerprint.  It does not shape
        # deterministic chunk identities or published file content, however,
        # and must not prevent a new attempt from carrying a completed manifest.
        payload.pop("configuration_fingerprint")
        payload["source_type"] = self.source_type.value
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class CommitUnit:
    """One bounded storage mutation confirmed before ledger insertion."""

    rel_path: str
    kind: CommitUnitKind
    segment_ordinal: int
    is_file_end: bool
    point_ids: tuple[str, ...]
    source_digest: str | None = None

    def __post_init__(self) -> None:
        validate_rel_path(self.rel_path)
        if not isinstance(self.kind, CommitUnitKind):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("kind must be a CommitUnitKind")
        if isinstance(self.segment_ordinal, bool) or self.segment_ordinal < 0:
            raise ValueError("segment_ordinal must be a non-negative integer")
        if not isinstance(self.is_file_end, bool):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("is_file_end must be a bool")
        if not self.point_ids or any(not point_id for point_id in self.point_ids):
            raise ValueError("point_ids must contain non-empty identifiers")
        if len(set(self.point_ids)) != len(self.point_ids):
            raise ValueError("point_ids must be unique within a commit unit")
        if self.kind is not CommitUnitKind.UPSERT and self.point_ids != tuple(
            sorted(self.point_ids)
        ):
            raise ValueError("deletion point_ids must be in canonical order")
        if self.kind is CommitUnitKind.UPSERT:
            if not _is_digest(self.source_digest):
                raise ValueError("upsert units require a lowercase BLAKE2b-512 digest")
        elif self.source_digest is not None:
            raise ValueError("deletion units must not carry a source digest")
        if self.kind is not CommitUnitKind.UPSERT and (
            self.segment_ordinal != 0 or not self.is_file_end
        ):
            raise ValueError("a deletion is exactly one commit unit")

    @property
    def identity(self) -> str:
        """Return deterministic idempotency identity for this unit."""
        payload = {
            "kind": self.kind.value,
            "path": self.rel_path,
            "source_digest": self.source_digest,
            "segment_ordinal": self.segment_ordinal,
            "is_file_end": self.is_file_end,
            "point_ids": self.point_ids,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class RunGeneration:
    """Immutable projection of one durable generation row."""

    generation_id: str
    signature: RunSignature
    finalization_phase: FinalizationPhase
    terminal_state: RunTerminalState
    destructive_intent: bool
    created_at: float
    updated_at: float
    terminal_detail: str | None = None
    parent_generation_id: str | None = None

    @property
    def complete(self) -> bool:
        """Return whether the generation is immutably successful."""
        return self.terminal_state is RunTerminalState.SUCCEEDED


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_REPR_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )
