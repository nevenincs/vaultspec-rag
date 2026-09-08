"""Run-ledger value objects, schema contract, and durable identity rules."""

from __future__ import annotations

import hashlib
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict

from ._content_policy import ContentKind
from ._file_state import validate_rel_path
from ._publication_proof import (
    PathDelta,
    PathOutcome,
    ProofAggregate,
    ProofCompatibilityKey,
    ProofMutationState,
    ProofProvenance,
    ProofReceiptState,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

__all__ = [
    "INDEX_RUN_LEDGER_FILENAME",
    "LEDGER_BUSY_TIMEOUT_SECONDS",
    "LEDGER_CONTENTION_ATTEMPTS",
    "PUBLICATION_PROOF_SCHEMA",
    "CommitUnit",
    "CommitUnitKind",
    "FileStateTombstoneRow",
    "FinalizationPhase",
    "PublicationEvidenceRow",
    "PublicationMutationPointRow",
    "PublicationMutationUnit",
    "PublicationMutationUnitRow",
    "PublicationPointRow",
    "PublicationProof",
    "PublicationProofRow",
    "PublicationReceipt",
    "PublicationReceiptDeltaRow",
    "PublicationReceiptPointRow",
    "PublicationReceiptRow",
    "RunGeneration",
    "RunLedgerCompatibilityError",
    "RunLedgerConcurrencyError",
    "RunLedgerContentionError",
    "RunLedgerCorruptionError",
    "RunLedgerError",
    "RunLedgerIndexedPathCollisionError",
    "RunLedgerRebuildRequiredError",
    "RunLedgerStateError",
    "RunOperation",
    "RunSignature",
    "RunTerminalState",
    "column_int",
    "column_text",
    "fetch_all",
    "fetch_one",
    "in_ledger_transaction",
    "index_run_ledger_path",
    "ledger_connection",
    "ledger_transaction",
    "open_ledger_connection",
    "raise_if_lock_contention",
    "with_contention_retry",
]


def fetch_one[T](
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> T | None:
    """Execute *sql* and return its first row, typed by the caller's context.

    ``sqlite3.Cursor.fetchone`` is typed ``Any`` in typeshed: the driver
    cannot know a query's result shape ahead of running it. Every row read in
    the ledger goes through this (or :func:`fetch_all`) instead of repeating
    that ``Any`` at each of the dozens of call sites that would otherwise
    each re-produce it; the caller supplies the expected row shape through
    the assignment target's annotation, e.g. ``row: GenerationRow | None =
    fetch_one(connection, sql, params)``.
    """
    return connection.execute(sql, parameters).fetchone()


def fetch_all[T](
    connection: sqlite3.Connection,
    sql: str,
    parameters: tuple[object, ...] = (),
) -> list[T]:
    """Execute *sql* and return every row, typed by the caller's context."""
    return connection.execute(sql, parameters).fetchall()


#: How long a caller waits for a lock a peer already holds. ``sqlite3.connect``
#: takes this as the busy budget directly, so it is set once at open rather than
#: repeated as a PRAGMA.
#:
#: Sized against the replay budget rather than in isolation. Each replay attempt
#: can spend this whole budget before raising, so the worst case is roughly
#: attempts x timeout - and that total has to stay under the deadline at which a
#: job without a progress tick is called degraded. Generous enough to absorb a
#: peer's commit, small enough that exhausting every attempt does not itself
#: read as a stall.
LEDGER_BUSY_TIMEOUT_SECONDS: Final = 10.0


def open_ledger_connection(
    path: Path,
    *,
    read_only_preflight: Callable[[sqlite3.Connection], None] | None = None,
    before_journal_mode: Callable[[sqlite3.Connection], None] | None = None,
) -> sqlite3.Connection:
    """Open one ledger connection under the durable-state concurrency contract.

    Write-ahead logging is the load-bearing part. Under a rollback journal a
    commit must escalate its reserved lock to an exclusive one, and no reader
    can be holding a shared lock at that moment; a read that outlasts the busy
    budget therefore fails an unrelated writer's commit rather than merely
    delaying it. A root's ledger is shared by every content kind, so that
    starvation crosses content kinds: opening the ledger for a document run can
    fail a code run's commit. Write-ahead logging admits many readers alongside
    one writer and removes the escalation entirely.

    A caller that gates durable format supplies ``read_only_preflight``. Existing
    files are then inspected through a side-effect-free read-only connection
    before a writable handle can create or alter journal sidecars. Immutable mode
    protects WAL shared memory; an active rollback journal instead needs SQLite's
    locked read-only snapshot. ``before_journal_mode`` may atomically initialize a
    preflight-approved empty file before the normal WAL conversion. The returned
    connection always uses WAL for durable files.

    The journal mode is a property of the database file, not of the connection.
    A file that will not hold the conversion cannot honour the contract - a
    network filesystem is the usual reason - and this raises rather than
    returning a connection that would quietly reintroduce the starvation.
    """
    if read_only_preflight is not None and path != Path(":memory:") and path.exists():
        # Immutable mode cannot update WAL shared memory. With a live rollback
        # journal, however, it could observe the writer's uncommitted in-place
        # pages, so a normal read-only connection must honor the journal locks.
        query = "mode=ro"
        if not Path(f"{path}-journal").exists():
            query += "&immutable=1"
        preflight_connection = sqlite3.connect(
            f"{path.resolve().as_uri()}?{query}",
            uri=True,
            timeout=LEDGER_BUSY_TIMEOUT_SECONDS,
        )
        try:
            preflight_connection.row_factory = sqlite3.Row
            read_only_preflight(preflight_connection)
        finally:
            preflight_connection.close()

    connection = sqlite3.connect(path, timeout=LEDGER_BUSY_TIMEOUT_SECONDS)
    try:
        connection.row_factory = sqlite3.Row
        if before_journal_mode is not None:
            before_journal_mode(connection)
        if path != Path(":memory:"):
            mode = _request_write_ahead_logging(connection)
            if mode != "wal":
                raise RunLedgerConcurrencyError(
                    f"run ledger {path} reports journal mode {mode!r} after requesting "
                    "write-ahead logging; this filesystem cannot support concurrent "
                    "indexing safely - a network-mounted data root is the usual cause"
                )
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


def _request_write_ahead_logging(connection: sqlite3.Connection) -> str:
    """Switch the file to write-ahead logging and return the resulting mode.

    Converting away from a rollback journal needs a moment with no other
    connection on the file, so a peer's read can make the first attempt report
    the old mode back rather than the requested one. That is transient and
    self-clearing, so it is retried briefly before being judged: treating the
    first contended answer as the filesystem's verdict would permanently fail a
    root over a condition that lasts milliseconds.

    A lock error raised outright is left to propagate. The callers translate it
    into transient contention, which is what it is.
    """
    mode = ""
    for attempt in range(_JOURNAL_MODE_ATTEMPTS):
        row: sqlite3.Row | None = fetch_one(connection, "PRAGMA journal_mode = WAL")
        mode = column_text(row, 0).lower() if row is not None else "none"
        if mode == "wal":
            return mode
        if attempt < _JOURNAL_MODE_ATTEMPTS - 1:
            time.sleep(_JOURNAL_MODE_RETRY_SECONDS)
    return mode


@contextmanager
def ledger_connection(
    path: Path,
    *,
    read_only_preflight: Callable[[sqlite3.Connection], None] | None = None,
    before_journal_mode: Callable[[sqlite3.Connection], None] | None = None,
) -> Generator[sqlite3.Connection]:
    """Yield a ledger connection and close it when the block ends.

    ``sqlite3.Connection`` is itself a context manager, but that manager scopes
    a *transaction*, not the handle: its ``__exit__`` commits or rolls back and
    leaves the connection open. A read taken through it strands a live handle
    until the collector happens to reclaim it. This scopes the handle, which is
    what the call sites mean.
    """
    connection = open_ledger_connection(
        path,
        read_only_preflight=read_only_preflight,
        before_journal_mode=before_journal_mode,
    )
    try:
        yield connection
    finally:
        connection.close()


@contextmanager
def ledger_transaction(path: Path) -> Generator[sqlite3.Connection]:
    """Yield a connection inside one immediate transaction, then close it.

    ``BEGIN IMMEDIATE`` takes the write lock up front rather than on first
    write, so two writers resolve their ordering before either has done any
    work instead of one discovering halfway through that it cannot proceed.
    """
    with ledger_connection(path) as connection:
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise


#: How many times an idempotent ledger write replays before it gives up. The
#: busy budget already absorbs an ordinary peer commit, so reaching this at all
#: means sustained contention rather than a single unlucky overlap.
LEDGER_CONTENTION_ATTEMPTS: Final = 4

#: Seconds to wait before each replay. Short and bounded: the caller is holding
#: an indexing run open, and the condition either clears quickly or is not the
#: transient one this retry is for.
_CONTENTION_BACKOFF_SECONDS: Final = (0.1, 0.25, 0.5)

#: Attempts to convert the journal mode before believing the answer, and the
#: pause between them. Short: what blocks the conversion is another connection
#: being open at that instant, not sustained load.
_JOURNAL_MODE_ATTEMPTS: Final = 3
_JOURNAL_MODE_RETRY_SECONDS: Final = 0.05


def raise_if_lock_contention(exc: sqlite3.OperationalError, *, path: Path) -> None:
    """Re-raise *exc* as transient contention, or return for a real fault.

    Exists because the durable-state layer's own error vocabulary would
    otherwise swallow the distinction. ``sqlite3.OperationalError`` subclasses
    ``DatabaseError``, so a handler written to turn database errors into
    corruption catches a held lock too, and reports a condition that clears in
    milliseconds as damaged durable state the caller cannot recover from.
    """
    if "locked" in str(exc).lower():
        raise RunLedgerContentionError(f"run ledger {path} is locked: {exc}") from exc


def with_contention_retry[T](operation: Callable[[], T], *, path: Path) -> T:
    """Run an idempotent ledger write, replaying it while a peer holds the lock.

    Only safe for operations that are idempotent by construction, which the
    ledger's write methods are: a contended transaction rolls back whole, and
    an exact replay of an already-recorded unit is a no-op that reports zero
    insertions. Replay therefore either lands the work or observes that it is
    already landed.

    The point is what happens on exhaustion. Contention is transient and the
    run's storage-confirmed work is intact, so this raises a typed error whose
    text carries SQLite's own wording. That keeps the condition classifiable as
    retryable at the service boundary instead of falling through as an
    unclassified fault that discards the generation.
    """
    last: sqlite3.OperationalError | None = None
    for attempt in range(LEDGER_CONTENTION_ATTEMPTS):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            if "locked" not in str(exc).lower():
                raise
            last = exc
            if attempt < len(_CONTENTION_BACKOFF_SECONDS):
                time.sleep(_CONTENTION_BACKOFF_SECONDS[attempt])
    raise RunLedgerContentionError(
        f"run ledger {path} stayed locked across "
        f"{LEDGER_CONTENTION_ATTEMPTS} attempts: {last}"
    ) from last


def in_ledger_transaction[T](
    path: Path,
    body: Callable[[sqlite3.Connection], T],
) -> T:
    """Run *body* in one transaction, replaying the whole thing on contention.

    The composition of the two helpers above, for the write paths that need
    both. A contended transaction rolls back whole and these bodies have no
    effect outside it, so replaying one either lands the work or observes it
    already landed.

    Acquisition is not separately retried. The busy budget on the connection
    already waits out a peer before ``BEGIN IMMEDIATE`` reports failure, so a
    retry loop there would multiply against this one and turn a contended write
    into a wait long enough to read as a stalled job.
    """

    def attempt() -> T:
        with ledger_transaction(path) as connection:
            return body(connection)

    return with_contention_retry(attempt, path=path)


def column_text(row: sqlite3.Row, key: int | str) -> str:
    """Return one SQLite result column as text, narrowed from the driver's Any.

    ``sqlite3.Row.__getitem__`` is typed ``Any`` - the driver cannot know a
    query's column affinity ahead of running it. Every PRAGMA and
    schema-introspection read goes through this (or :func:`column_int`) rather
    than trusting a bare ``str()``/``int()`` conversion of that ``Any``, which
    would silently accept a value that merely stringifies instead of proving the
    driver returned text.
    """
    value = row[key]
    if not isinstance(value, str):
        raise RunLedgerCorruptionError(f"run ledger result column {key!r} was not text")
    return value


def column_int(row: sqlite3.Row, key: int | str) -> int:
    """Return one SQLite result column as an integer, narrowed from Any."""
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise RunLedgerCorruptionError(
            f"run ledger result column {key!r} was not an integer"
        )
    return value


class GenerationRow(TypedDict):
    """The ``generations`` row columns :func:`RunLedger._generation_from_row` reads.

    Shared across the ledger's runtime and its mixins: every one of them reads
    or forwards a ``generations`` row and types it against this one shape
    rather than the untyped ``sqlite3.Row`` the cursor actually returns.
    """

    generation_id: str
    source_type: str
    collection_identity: str
    signature_fingerprint: str
    signature_json: str
    finalization_phase: str
    terminal_state: str
    destructive_intent: int
    created_at: float
    updated_at: float
    terminal_detail: str | None
    parent_generation_id: str | None
    consecutive_failures: int


class PublicationProofRow(TypedDict):
    """Flattened durable header for one current publication proof."""

    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    storage_schema: int
    payload_schema: int
    embedding_schema_identity: str
    chunking_schema_identity: str
    membership_identity: str
    content_identity: str
    policy_identity: str
    generation_id: str
    revision: int
    reservation_sequence: int
    indexed_identities: int
    retained_points: int
    provenance: str
    committed_at: float
    verified_at: float | None


class PublicationEvidenceRow(TypedDict):
    """One normalized path evidence row in the current proof."""

    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    rel_path: str
    content_identity: str
    evidence_generation_id: str


class PublicationPointRow(TypedDict):
    """One retained point identity belonging to normalized path evidence."""

    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    rel_path: str
    point_ordinal: int
    point_id: str


class PublicationReceiptRow(TypedDict):
    """Durable state-machine header for one publication attempt."""

    receipt_id: str
    reservation_sequence: int
    source_type: str
    root_identity: str
    backend_identity: str
    collection_identity: str
    storage_schema: int
    payload_schema: int
    embedding_schema_identity: str
    chunking_schema_identity: str
    membership_identity: str
    content_identity: str
    policy_identity: str
    generation_id: str
    parent_revision: int
    target_revision: int
    state: str
    reserved_at: float
    sealed_at: float | None
    committed_at: float | None
    rolled_back_at: float | None


class PublicationMutationUnitRow(TypedDict):
    """One receipt-bound deterministic storage mutation and its durable state."""

    receipt_id: str
    mutation_ordinal: int
    sealed_ordinal: int | None
    unit_id: str
    rel_path: str
    unit_kind: str
    source_digest: str | None
    segment_ordinal: int
    is_file_end: int
    state: str
    prepared_at: float
    applied_at: float | None
    confirmed_at: float | None


class PublicationMutationPointRow(TypedDict):
    """One exact point identity carried by a receipt mutation unit."""

    receipt_id: str
    mutation_ordinal: int
    point_ordinal: int
    point_id: str


class PublicationReceiptDeltaRow(TypedDict):
    """Deterministically ordered path transition retained for receipt replay."""

    receipt_id: str
    delta_ordinal: int
    outcome: str
    rel_path: str
    target_rel_path: str | None
    old_content_identity: str | None
    new_content_identity: str | None


class PublicationReceiptPointRow(TypedDict):
    """Exact old or new retained point membership for one receipt delta."""

    receipt_id: str
    delta_ordinal: int
    evidence_side: str
    point_ordinal: int
    point_id: str


class FileStateTombstoneRow(TypedDict):
    """One generation-local deletion that shadows inherited file state."""

    generation_id: str
    rel_path: str


SCHEMA_VERSION: Final = 7
FETCH_BATCH: Final = 256
_DIGEST_REPR_LENGTH: Final = 128
INDEX_RUN_LEDGER_FILENAME: Final = "index_runs.sqlite3"
_BASE_LEDGER_SCHEMA: Final = {
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

PUBLICATION_PROOF_SCHEMA: Final = {
    "publication_proofs": frozenset(PublicationProofRow.__annotations__),
    "publication_evidence": frozenset(PublicationEvidenceRow.__annotations__),
    "publication_points": frozenset(PublicationPointRow.__annotations__),
    "publication_receipts": frozenset(PublicationReceiptRow.__annotations__),
    "publication_mutation_units": frozenset(PublicationMutationUnitRow.__annotations__),
    "publication_mutation_points": frozenset(
        PublicationMutationPointRow.__annotations__
    ),
    "publication_receipt_deltas": frozenset(PublicationReceiptDeltaRow.__annotations__),
    "publication_receipt_points": frozenset(PublicationReceiptPointRow.__annotations__),
    "file_state_tombstones": frozenset(FileStateTombstoneRow.__annotations__),
}

REQUIRED_SCHEMA: Final = {**_BASE_LEDGER_SCHEMA, **PUBLICATION_PROOF_SCHEMA}

# Named indexes are part of the durable schema contract, not optional tuning.
# Each tuple is ``(table, ordered columns, unique, partial)`` and is verified on
# every open of the exact current format.
REQUIRED_INDEXES: Final[dict[str, tuple[str, tuple[str, ...], bool, bool]]] = {
    "generations_active": (
        "generations",
        ("source_type", "terminal_state", "created_at"),
        False,
        False,
    ),
    "commit_units_path": (
        "commit_units",
        ("generation_id", "rel_path", "segment_ordinal"),
        False,
        False,
    ),
    "commit_point_ids_point": (
        "commit_point_ids",
        ("point_id",),
        False,
        False,
    ),
    "file_states_state": (
        "file_states",
        ("generation_id", "state", "rel_path"),
        False,
        False,
    ),
    "publication_proofs_generation": (
        "publication_proofs",
        ("generation_id",),
        False,
        False,
    ),
    "publication_evidence_generation": (
        "publication_evidence",
        ("evidence_generation_id",),
        False,
        False,
    ),
    "publication_points_point": (
        "publication_points",
        ("point_id",),
        False,
        False,
    ),
    "publication_receipts_generation": (
        "publication_receipts",
        ("generation_id", "state"),
        False,
        False,
    ),
    "publication_receipts_open": (
        "publication_receipts",
        (
            "source_type",
            "root_identity",
            "backend_identity",
            "collection_identity",
        ),
        True,
        True,
    ),
    "publication_mutation_units_state": (
        "publication_mutation_units",
        ("receipt_id", "state", "mutation_ordinal"),
        False,
        False,
    ),
    "publication_mutation_units_sealed": (
        "publication_mutation_units",
        ("receipt_id", "sealed_ordinal"),
        True,
        True,
    ),
    "publication_mutation_points_point": (
        "publication_mutation_points",
        ("point_id",),
        False,
        False,
    ),
    "publication_receipt_deltas_path": (
        "publication_receipt_deltas",
        ("receipt_id", "rel_path"),
        True,
        False,
    ),
    "publication_receipt_points_point": (
        "publication_receipt_points",
        ("point_id",),
        False,
        False,
    ),
    "file_state_tombstones_path": (
        "file_state_tombstones",
        ("rel_path", "generation_id"),
        False,
        False,
    ),
}

REQUIRED_INDEX_PREDICATES: Final = {
    "publication_receipts_open": "where state in ('reserved', 'sealed')",
    "publication_mutation_units_sealed": "where sealed_ordinal is not null",
}


def index_run_ledger_path(data_root: Path) -> Path:
    """Return the one shared per-root ledger path."""
    return Path(data_root) / INDEX_RUN_LEDGER_FILENAME


class RunLedgerError(RuntimeError):
    """Base class for durable run-ledger failures."""


class RunLedgerCompatibilityError(RunLedgerError):
    """The ledger schema or requested generation is incompatible."""


class RunLedgerRebuildRequiredError(RunLedgerCompatibilityError):
    """The persisted ledger format must be replaced by an explicit rebuild."""


class RunLedgerCorruptionError(RunLedgerError):
    """SQLite reported corrupt durable state."""


class RunLedgerConcurrencyError(RunLedgerError):
    """The ledger file cannot honour the durable-state concurrency contract."""


class RunLedgerContentionError(RunLedgerError):
    """A peer held the ledger lock past this operation's retry budget.

    Transient rather than terminal: the generation's storage-confirmed work is
    untouched and the run resumes from its last checkpoint.
    """


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
    backend_identity: str = "legacy:unknown"

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
            "backend_identity",
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
    """One deterministic bounded storage mutation suitable for replay."""

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


def _require_timestamp(value: float, *, name: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
        raise TypeError(f"{name} must be a timestamp")
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be a finite non-negative timestamp")


def _require_non_empty_text(value: str, *, name: str) -> None:
    if not isinstance(value, str) or not value.strip():  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
        raise ValueError(f"{name} must be non-empty")


@dataclass(frozen=True, slots=True)
class PublicationMutationUnit:
    """Receipt-bound progress for one deterministic storage mutation."""

    ordinal: int
    unit: CommitUnit
    state: ProofMutationState
    prepared_at: float
    applied_at: float | None = None
    confirmed_at: float | None = None
    sealed_ordinal: int | None = None

    def __post_init__(self) -> None:
        if (
            isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            or self.ordinal < 0
        ):
            raise ValueError("ordinal must be a non-negative integer")
        if not isinstance(self.unit, CommitUnit):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("unit must be a CommitUnit")
        if not isinstance(self.state, ProofMutationState):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("state must be a ProofMutationState")
        if self.sealed_ordinal is not None and (
            isinstance(self.sealed_ordinal, bool)
            or not isinstance(self.sealed_ordinal, int)  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            or self.sealed_ordinal < 0
        ):
            raise ValueError("sealed_ordinal must be a non-negative integer")
        _require_timestamp(self.prepared_at, name="prepared_at")
        required = {
            ProofMutationState.PREPARED: 0,
            ProofMutationState.APPLIED: 1,
            ProofMutationState.CONFIRMED: 2,
        }[self.state]
        timestamps = (self.applied_at, self.confirmed_at)
        if any(value is None for value in timestamps[:required]) or any(
            value is not None for value in timestamps[required:]
        ):
            raise ValueError("mutation timestamps must match its state")
        present = (
            self.prepared_at,
            *(value for value in timestamps if value is not None),
        )
        for name, value in zip(
            ("prepared_at", "applied_at", "confirmed_at"),
            present,
            strict=False,
        ):
            _require_timestamp(value, name=name)
        if present != tuple(sorted(present)):
            raise ValueError("mutation timestamps must be monotonic")

    @property
    def identity(self) -> str:
        """Return the deterministic idempotency identity of this mutation."""
        return self.unit.identity


@dataclass(frozen=True, slots=True)
class PublicationProof:
    """Committed ledger projection of one exact publication proof revision."""

    revision: int
    reservation_sequence: int
    compatibility_key: ProofCompatibilityKey
    generation_id: str
    aggregate: ProofAggregate
    provenance: ProofProvenance
    committed_at: float
    verified_at: float | None = None

    def __post_init__(self) -> None:
        for name in ("revision", "reservation_sequence"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if not isinstance(self.compatibility_key, ProofCompatibilityKey):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("compatibility_key must be a ProofCompatibilityKey")
        _require_non_empty_text(self.generation_id, name="generation_id")
        if not isinstance(self.aggregate, ProofAggregate):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("aggregate must be a ProofAggregate")
        if not isinstance(self.provenance, ProofProvenance):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("provenance must be a ProofProvenance")
        _require_timestamp(self.committed_at, name="committed_at")
        if self.verified_at is not None:
            _require_timestamp(self.verified_at, name="verified_at")
            if self.verified_at > self.committed_at:
                raise ValueError("verified_at must not follow committed_at")
        if self.provenance is ProofProvenance.VERIFIED:
            if self.verified_at is None:
                raise ValueError("verified proof requires verified_at")
        elif self.verified_at is not None:
            raise ValueError("delta-derived proof must not carry verified_at")


@dataclass(frozen=True, slots=True)
class PublicationReceipt:
    """Durable replay contract spanning external storage and proof commit."""

    receipt_id: str
    reservation_sequence: int
    compatibility_key: ProofCompatibilityKey
    generation_id: str
    parent_revision: int
    target_revision: int
    state: ProofReceiptState
    reserved_at: float
    mutations: tuple[PublicationMutationUnit, ...] = ()
    deltas: tuple[PathDelta, ...] = ()
    sealed_at: float | None = None
    committed_at: float | None = None
    rolled_back_at: float | None = None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.receipt_id, name="receipt_id")
        if not isinstance(self.compatibility_key, ProofCompatibilityKey):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("compatibility_key must be a ProofCompatibilityKey")
        _require_non_empty_text(self.generation_id, name="generation_id")
        for name in ("reservation_sequence", "parent_revision", "target_revision"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
                raise TypeError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} must be non-negative")
        if self.reservation_sequence == 0:
            raise ValueError("reservation_sequence must be positive")
        if self.target_revision != self.parent_revision + 1:
            raise ValueError("target_revision must immediately follow parent_revision")
        if not isinstance(self.state, ProofReceiptState):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("state must be a ProofReceiptState")
        if not isinstance(self.mutations, tuple):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("mutations must be a tuple")
        _validate_receipt_mutations(self.mutations)
        if not isinstance(self.deltas, tuple):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
            raise TypeError("deltas must be a tuple")
        _validate_receipt_deltas(self.deltas, parent_revision=self.parent_revision)
        self._validate_timestamps()
        self._validate_mutation_timestamps()
        self._validate_sealed_mutations()
        if self.state is ProofReceiptState.COMMITTED:
            if not any(delta.changes_proof for delta in self.deltas):
                raise ValueError("a no-op receipt must not commit a proof revision")
            if any(
                mutation.state is not ProofMutationState.CONFIRMED
                for mutation in self.mutations
            ):
                raise ValueError(
                    "committed receipt requires every mutation to be confirmed"
                )

    @property
    def is_open(self) -> bool:
        """Return whether this receipt fences live proof reads."""
        return self.state.is_open

    def _validate_timestamps(self) -> None:
        _require_timestamp(self.reserved_at, name="reserved_at")
        optional_timestamps = {
            "sealed_at": self.sealed_at,
            "committed_at": self.committed_at,
            "rolled_back_at": self.rolled_back_at,
        }
        for name, value in optional_timestamps.items():
            if value is not None:
                _require_timestamp(value, name=name)
        valid_shape = {
            ProofReceiptState.RESERVED: (
                self.sealed_at is None
                and self.committed_at is None
                and self.rolled_back_at is None
            ),
            ProofReceiptState.SEALED: (
                self.sealed_at is not None
                and self.committed_at is None
                and self.rolled_back_at is None
            ),
            ProofReceiptState.COMMITTED: (
                self.sealed_at is not None
                and self.committed_at is not None
                and self.rolled_back_at is None
            ),
            ProofReceiptState.ROLLED_BACK: (
                self.committed_at is None and self.rolled_back_at is not None
            ),
        }[self.state]
        if not valid_shape:
            raise ValueError("receipt timestamps must match its state")
        terminal_at = (
            self.committed_at if self.committed_at is not None else self.rolled_back_at
        )
        present = (
            self.reserved_at,
            *((self.sealed_at,) if self.sealed_at is not None else ()),
            *((terminal_at,) if terminal_at is not None else ()),
        )
        if present != tuple(sorted(present)):
            raise ValueError("receipt timestamps must be monotonic")

    def _validate_mutation_timestamps(self) -> None:
        terminal_at = (
            self.committed_at if self.committed_at is not None else self.rolled_back_at
        )
        for mutation in self.mutations:
            if mutation.prepared_at < self.reserved_at:
                raise ValueError("mutation cannot precede receipt reservation")
            mutation_at = (
                mutation.confirmed_at
                if mutation.confirmed_at is not None
                else mutation.applied_at
                if mutation.applied_at is not None
                else mutation.prepared_at
            )
            if terminal_at is not None and mutation_at > terminal_at:
                raise ValueError("mutation cannot follow receipt closure")

    def _validate_sealed_mutations(self) -> None:
        if self.sealed_at is None:
            if self.deltas:
                raise ValueError("receipt deltas exist only after sealing")
            if any(mutation.sealed_ordinal is not None for mutation in self.mutations):
                raise ValueError("unsealed receipt must not seal mutation identities")
            return
        sealed = sorted(self.mutations, key=lambda mutation: mutation.identity)
        if tuple(mutation.sealed_ordinal for mutation in sealed) != tuple(
            range(len(sealed))
        ):
            raise ValueError(
                "sealed receipt must freeze every mutation in identity order"
            )
        _validate_mutation_coverage(self.deltas, self.mutations)


def _validate_receipt_mutations(
    mutations: tuple[PublicationMutationUnit, ...],
) -> None:
    if any(not isinstance(mutation, PublicationMutationUnit) for mutation in mutations):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
        raise TypeError("mutations must contain only PublicationMutationUnit values")
    if tuple(mutation.ordinal for mutation in mutations) != tuple(
        range(len(mutations))
    ):
        raise ValueError("mutations must use contiguous ordinal ordering")
    identities = tuple(mutation.identity for mutation in mutations)
    if len(frozenset(identities)) != len(identities):
        raise ValueError("mutation identities must be unique within a receipt")


def _validate_mutation_coverage(
    deltas: tuple[PathDelta, ...],
    mutations: tuple[PublicationMutationUnit, ...],
) -> None:
    expected_points, expected_content = _expected_mutation_coverage(deltas)
    actual_units: dict[tuple[CommitUnitKind, str], list[CommitUnit]] = {}
    for mutation in mutations:
        key = (mutation.unit.kind, mutation.unit.rel_path)
        actual_units.setdefault(key, []).append(mutation.unit)
    if actual_units.keys() != expected_points.keys():
        raise ValueError("sealed mutations must exactly cover changed proof paths")

    for key, units in actual_units.items():
        _validate_mutation_group(
            key,
            units,
            expected_points=expected_points[key],
            expected_content=expected_content.get(key[1]),
        )


def _expected_mutation_coverage(
    deltas: tuple[PathDelta, ...],
) -> tuple[
    dict[tuple[CommitUnitKind, str], frozenset[str]],
    dict[str, str],
]:
    expected_points: dict[tuple[CommitUnitKind, str], frozenset[str]] = {}
    expected_content: dict[str, str] = {}
    for delta in deltas:
        if not delta.changes_proof:
            continue
        if delta.new is not None:
            expected_points[(CommitUnitKind.UPSERT, delta.new.rel_path)] = frozenset(
                delta.new.point_ids
            )
            expected_content[delta.new.rel_path] = delta.new.content_identity
        deletion = _expected_deletion(delta)
        if deletion is not None:
            deletion_kind, rel_path, deleted_points = deletion
            expected_points[(deletion_kind, rel_path)] = deleted_points
    return expected_points, expected_content


def _expected_deletion(
    delta: PathDelta,
) -> tuple[CommitUnitKind, str, frozenset[str]] | None:
    if delta.old is None:
        return None
    if delta.outcome in {PathOutcome.DELETE, PathOutcome.RENAME}:
        return (
            CommitUnitKind.DELETE_PATH,
            delta.old.rel_path,
            frozenset(delta.old.point_ids),
        )
    if delta.outcome not in {
        PathOutcome.MODIFY,
        PathOutcome.EMPTY,
        PathOutcome.IGNORED,
        PathOutcome.REJECTED,
    }:
        return None
    new_points: frozenset[str] = (
        frozenset(delta.new.point_ids) if delta.new is not None else frozenset()
    )
    deleted_points = frozenset(delta.old.point_ids).difference(new_points)
    if not deleted_points:
        return None
    return CommitUnitKind.DELETE_STALE, delta.old.rel_path, deleted_points


def _validate_mutation_group(
    key: tuple[CommitUnitKind, str],
    units: list[CommitUnit],
    *,
    expected_points: frozenset[str],
    expected_content: str | None,
) -> None:
    point_ids = tuple(point_id for unit in units for point_id in unit.point_ids)
    if len(frozenset(point_ids)) != len(point_ids):
        raise ValueError("sealed mutation point identities must not overlap")
    if frozenset(point_ids) != expected_points:
        raise ValueError("sealed mutations must match exact proof point membership")
    kind, _rel_path = key
    if kind is CommitUnitKind.UPSERT:
        if any(unit.source_digest != expected_content for unit in units):
            raise ValueError("upsert mutation content must match new proof evidence")
        segments = sorted(units, key=lambda unit: unit.segment_ordinal)
        if tuple(unit.segment_ordinal for unit in segments) != tuple(
            range(len(segments))
        ) or tuple(unit.is_file_end for unit in segments) != (
            *(False for _ in segments[:-1]),
            True,
        ):
            raise ValueError("upsert mutations must form one complete segment stream")
    elif len(units) != 1:
        raise ValueError("one deletion mutation must carry exact removed membership")


def _validate_receipt_deltas(
    deltas: tuple[PathDelta, ...], *, parent_revision: int
) -> None:
    if any(not isinstance(delta, PathDelta) for delta in deltas):  # pyright: ignore[reportUnnecessaryIsInstance] - validate persisted input at runtime
        raise TypeError("deltas must contain only PathDelta values")
    if any(delta.expected_parent_revision != parent_revision for delta in deltas):
        raise ValueError("every delta must name the receipt parent revision")
    ordering = tuple(
        (delta.rel_path, delta.target_rel_path or "", delta.outcome.value)
        for delta in deltas
    )
    if ordering != tuple(sorted(ordering)):
        raise ValueError("deltas must use canonical path ordering")
    reserved_paths: set[str] = set()
    for delta in deltas:
        paths = (delta.rel_path,) + (
            (delta.target_rel_path,) if delta.target_rel_path is not None else ()
        )
        if any(path in reserved_paths for path in paths):
            raise ValueError("a receipt must not affect one path more than once")
        reserved_paths.update(paths)
    _validate_delta_point_ownership(deltas)


def _validate_delta_point_ownership(deltas: tuple[PathDelta, ...]) -> None:
    old_owners: dict[str, str] = {}
    new_owners: dict[str, str] = {}
    for delta in deltas:
        for evidence, owners in (
            (delta.old, old_owners),
            (delta.new, new_owners),
        ):
            if evidence is None:
                continue
            for point_id in evidence.point_ids:
                owner = owners.setdefault(point_id, evidence.rel_path)
                if owner != evidence.rel_path:
                    raise ValueError(
                        "one point identity must not belong to multiple proof paths"
                    )
    transferred = {
        point_id
        for point_id in old_owners.keys() & new_owners.keys()
        if old_owners[point_id] != new_owners[point_id]
    }
    if transferred:
        raise ValueError("a receipt must not transfer point identity between paths")


def _is_digest(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == _DIGEST_REPR_LENGTH
        and all(character in "0123456789abcdef" for character in value)
    )
