"""Run-ledger value objects, schema contract, and durable identity rules."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Final, TypedDict

from ._content_policy import ContentKind
from ._file_state import validate_rel_path

if TYPE_CHECKING:
    from collections.abc import Callable, Generator

__all__ = [
    "INDEX_RUN_LEDGER_FILENAME",
    "LEDGER_BUSY_TIMEOUT_SECONDS",
    "LEDGER_CONTENTION_ATTEMPTS",
    "CommitUnit",
    "CommitUnitKind",
    "FinalizationPhase",
    "RunGeneration",
    "RunLedgerCompatibilityError",
    "RunLedgerConcurrencyError",
    "RunLedgerContentionError",
    "RunLedgerCorruptionError",
    "RunLedgerError",
    "RunLedgerIndexedPathCollisionError",
    "RunLedgerStateError",
    "RunOperation",
    "RunSignature",
    "RunTerminalState",
    "column_int",
    "column_text",
    "fetch_all",
    "fetch_one",
    "index_run_ledger_path",
    "ledger_connection",
    "ledger_transaction",
    "open_ledger_connection",
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
#: repeated as a PRAGMA. It is generous because the thing being waited on is
#: another indexing thread's short commit, and delaying a caller is always
#: cheaper than failing a generation that holds storage-confirmed work.
LEDGER_BUSY_TIMEOUT_SECONDS: Final = 30.0


def open_ledger_connection(path: Path) -> sqlite3.Connection:
    """Open one ledger connection under the durable-state concurrency contract.

    Write-ahead logging is the load-bearing part. Under a rollback journal a
    commit must escalate its reserved lock to an exclusive one, and no reader
    can be holding a shared lock at that moment; a read that outlasts the busy
    budget therefore fails an unrelated writer's commit rather than merely
    delaying it. A root's ledger is shared by every content kind, so that
    starvation crosses content kinds: opening the ledger for a document run can
    fail a code run's commit. Write-ahead logging admits many readers alongside
    one writer and removes the escalation entirely.

    The journal mode is a property of the database file, not of the connection,
    so the first open converts the file and every later open reads the mode
    back. A file that will not hold the conversion cannot honour the contract -
    a network filesystem is the usual reason - and this raises rather than
    returning a connection that would quietly reintroduce the starvation.
    """
    connection = sqlite3.connect(path, timeout=LEDGER_BUSY_TIMEOUT_SECONDS)
    try:
        connection.row_factory = sqlite3.Row
        mode_row: sqlite3.Row | None = fetch_one(
            connection, "PRAGMA journal_mode = WAL"
        )
        mode = column_text(mode_row, 0).lower() if mode_row is not None else "none"
        if mode != "wal":
            raise RunLedgerConcurrencyError(
                f"run ledger {path} reports journal mode {mode!r} after requesting "
                "write-ahead logging; concurrent indexing cannot be made safe on "
                "this filesystem"
            )
        connection.execute("PRAGMA foreign_keys = ON")
    except BaseException:
        connection.close()
        raise
    return connection


@contextmanager
def ledger_connection(path: Path) -> Generator[sqlite3.Connection]:
    """Yield a ledger connection and close it when the block ends.

    ``sqlite3.Connection`` is itself a context manager, but that manager scopes
    a *transaction*, not the handle: its ``__exit__`` commits or rolls back and
    leaves the connection open. A read taken through it strands a live handle
    until the collector happens to reclaim it. This scopes the handle, which is
    what the call sites mean.
    """
    connection = open_ledger_connection(path)
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


SCHEMA_VERSION: Final = 6
FETCH_BATCH: Final = 256
_DIGEST_REPR_LENGTH: Final = 128
INDEX_RUN_LEDGER_FILENAME: Final = "index_runs.sqlite3"
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
    """Return the one shared per-root ledger path."""
    return Path(data_root) / INDEX_RUN_LEDGER_FILENAME


class RunLedgerError(RuntimeError):
    """Base class for durable run-ledger failures."""


class RunLedgerCompatibilityError(RunLedgerError):
    """The ledger schema or requested generation is incompatible."""


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
