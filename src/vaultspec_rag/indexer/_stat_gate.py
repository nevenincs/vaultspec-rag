"""Advisory stat-evidence gate over content rehashing.

Change detection proves a file unchanged by rehashing it, which prices an
unscoped convergence pass at the total byte count of the corpus. This gate
remembers the ``(size, mtime_ns)`` a file had when its content hash was last
computed and answers "may that hash be reused" from a stat call alone, so the
pass costs stat calls plus the bytes that actually changed.

What "hash" means is the owning domain's choice, carried by the gate itself:
each indexer holds its own point-addressable evidence database and digests every
file through the one function it was built with. The vault's fingerprint
splits a document into body and metadata halves rather than digesting raw
bytes, and binding that function to the gate is what keeps the recorded
evidence and the fingerprint it is evidence *for* from ever meaning different
things.

The content hash stays the sole indexing authority. Evidence is held in an
indexed SQLite table and read or updated only for the paths in the current
operation. Missing evidence causes extra hashing, never a skipped one, and a
reused hash is still diffed
against canonical publication proof exactly like a freshly computed one. The one
deliberate acceptance is the standard stat-cache limitation: content replaced
while ``(size, mtime_ns)`` is byte-identically restored is indistinguishable
from no change until any stat-visible difference appears.

Trust requires the recorded mtime to predate the recorded hashing instant by
a safety window, so a file hashed while it was being written - where a
coarse filesystem timestamp can survive a second write unchanged - is never
trusted and is rehashed on the next pass.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Self

from ..job_control import NO_RUN_CONTROL

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Collection, Iterable, Sequence

    from ..job_control import RunControl
    from ..progress import ProgressReporter

__all__ = [
    "BatchHashOutcome",
    "StatEvidenceGate",
    "StatEvidenceStore",
    "file_digest",
    "hash_paths",
    "record_computed_hashes",
]

logger = logging.getLogger(__name__)

#: A recorded mtime must be at least this much older than the instant the
#: hash was computed before the entry may be trusted. Two seconds absorbs the
#: coarsest real filesystem timestamp granularity (FAT's 2s) plus timer
#: batching, so a write landing in the same timestamp tick as the hashed read
#: can never satisfy the gate.
_RACY_WINDOW_NS: Final = 2_000_000_000

_SCHEMA_VERSION: Final = 1

#: Worker count for the read-and-digest pool. File reads release the GIL for
#: the duration of the syscall and blake2b releases it for updates beyond 2047
#: bytes, so a small pool overlaps I/O latency with hashing. The calling
#: thread serializes every stat, gate decision, and result collection, so past
#: eight workers it is the bottleneck and more threads only add contention.
_HASH_POOL_WORKERS: Final = min(8, os.cpu_count() or 1)

#: Mean pending-file size below which the pool is skipped and reads run
#: inline. Submit-and-collect costs tens of microseconds per file, while a
#: small file's whole open-read-digest is ~0.1ms - measured on this corpus
#: shape, pooling 1.5KB files was a 0.74x slowdown and 64KB files a 1.34x
#: win, with the crossover near the point where per-file work is a few
#: multiples of the dispatch overhead. 32KiB sits safely on the winning side.
_POOL_MIN_MEAN_BYTES: Final = 32 * 1024

#: Time budget between progress flushes and control checkpoints in a hashing
#: loop. Each service progress tick persists job state through an
#: fsync-bounded atomic write - milliseconds per call, which dominated
#: small-file hashing when paid per file - and a control checkpoint takes
#: locks. Flushing on this budget amortizes both across hundreds of files
#: while keeping operator-visible progress fresh at five updates a second and
#: holding worst-case cancellation latency far below one second.
_FLUSH_INTERVAL_SECONDS: Final = 0.2


@dataclass(frozen=True, slots=True)
class _StatEvidence:
    """The stat identity one content hash was computed against."""

    size: int
    mtime_ns: int
    content_hash: str
    hashed_at_ns: int


def file_digest(path: pathlib.Path) -> str:
    """Digest a file's raw bytes - the default a domain gets without asking.

    Raises:
        OSError: The file could not be opened or read.
    """
    with open(path, "rb") as stream:
        return hashlib.file_digest(stream, "blake2b").hexdigest()


class StatEvidenceGate:
    """One load-use-persist cycle of stat evidence for a hashing loop.

    Not thread-safe; each indexing run loads its own instance under the
    domain's writer lock, uses it for one hashing loop, and persists it.
    """

    __slots__ = (
        "_connection",
        "_dirty",
        "_entries",
        "_path",
        "_prune_keep",
        "digest",
        "rehashed",
        "reused",
    )

    def __init__(
        self,
        path: pathlib.Path,
        entries: dict[str, _StatEvidence] | None = None,
        *,
        digest: Callable[[pathlib.Path], str] = file_digest,
    ) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(self._path)
        self._entries = entries or {}
        self._dirty = False
        self._prune_keep: frozenset[str] | None = None
        self.digest = digest
        self.reused = 0
        self.rehashed = 0

    @classmethod
    def load(
        cls,
        path: pathlib.Path,
        *,
        digest: Callable[[pathlib.Path], str] = file_digest,
    ) -> Self:
        """Open the current point-addressable evidence store."""
        gate = cls(path, digest=digest)
        gate._ensure_schema()
        return gate

    def _ensure_schema(self) -> None:
        with self._connection as connection:
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version not in {0, _SCHEMA_VERSION}:
                raise RuntimeError("stat evidence schema requires a rebuild")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS stat_evidence (
                    path TEXT PRIMARY KEY,
                    size INTEGER NOT NULL,
                    mtime_ns INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    hashed_at_ns INTEGER NOT NULL
                ) WITHOUT ROWID"""
            )
            if version == 0:
                connection.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")

    def hash_file(self, key: str, path: pathlib.Path) -> str:
        """Return *path*'s content hash, reading it only when evidence demands.

        Raises:
            OSError: The file could not be statted or read, exactly as the
                ungated digest call would have raised.
        """
        stat = os.stat(path)
        reused = self.probe(key, stat)
        if reused is not None:
            return reused
        hashed_at_ns = time.time_ns()
        digest = self.digest(path)
        self.record(key, stat, digest, hashed_at_ns)
        self.rehashed += 1
        return digest

    def probe(self, key: str, stat: os.stat_result) -> str | None:
        """Return the reusable recorded hash for *stat*'s identity, or ``None``.

        The reuse decision from :meth:`hash_file`, split out so a batching
        caller can make it from a stat it already holds without any file I/O.
        """
        entry = self._entries.get(key)
        if entry is None:
            row = self._connection.execute(
                "SELECT size, mtime_ns, content_hash, hashed_at_ns "
                "FROM stat_evidence WHERE path = ?",
                (key,),
            ).fetchone()
            if row is not None:
                entry = _StatEvidence(
                    int(row[0]), int(row[1]), str(row[2]), int(row[3])
                )
                self._entries[key] = entry
        if (
            entry is not None
            and entry.size == stat.st_size
            and entry.mtime_ns == stat.st_mtime_ns
            and entry.mtime_ns + _RACY_WINDOW_NS <= entry.hashed_at_ns
        ):
            self.reused += 1
            return entry.content_hash
        return None

    def record(
        self,
        key: str,
        stat: os.stat_result,
        content_hash: str,
        hashed_at_ns: int,
    ) -> None:
        """Bind *content_hash* to the stat identity it was computed against."""
        self._entries[key] = _StatEvidence(
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            content_hash=content_hash,
            hashed_at_ns=hashed_at_ns,
        )
        self._dirty = True

    def record_known_hash(
        self,
        key: str,
        path: pathlib.Path,
        content_hash: str,
        *,
        computed_not_before_ns: int,
    ) -> bool:
        """Record an externally computed hash only when it binds honestly.

        A hash computed elsewhere - a chunk worker, an earlier phase of the
        same run - may be bound to the file's current stat identity only when
        that identity provably predates the computation: the current mtime
        must clear the racy window before *computed_not_before_ns*. Anything
        else is skipped, because a skipped entry only costs one later rehash
        while a false binding could reuse a hash the content never had.

        Returns whether the evidence is now recorded.
        """
        try:
            stat = os.stat(path)
        except OSError:
            return False
        if stat.st_mtime_ns + _RACY_WINDOW_NS > computed_not_before_ns:
            return False
        entry = self._entries.get(key)
        if (
            entry is not None
            and entry.size == stat.st_size
            and entry.mtime_ns == stat.st_mtime_ns
            and entry.content_hash == content_hash
        ):
            return True
        self.record(key, stat, content_hash, computed_not_before_ns)
        return True

    def prune(self, keep: Collection[str]) -> None:
        """Drop evidence for every key outside *keep*.

        Only a caller that hashed the full current membership may prune; a
        scoped pass sees a subset and must leave the rest alone.
        """
        self._prune_keep = frozenset(keep)
        self._dirty = True

    def persist(self) -> None:
        """Commit changed rows without serializing untouched evidence."""
        if not self._dirty:
            return
        with self._connection as connection:
            connection.executemany(
                """INSERT INTO stat_evidence
                   (path, size, mtime_ns, content_hash, hashed_at_ns)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(path) DO UPDATE SET
                     size=excluded.size, mtime_ns=excluded.mtime_ns,
                     content_hash=excluded.content_hash,
                     hashed_at_ns=excluded.hashed_at_ns""",
                (
                    (
                        key,
                        item.size,
                        item.mtime_ns,
                        item.content_hash,
                        item.hashed_at_ns,
                    )
                    for key, item in self._entries.items()
                ),
            )
            if self._prune_keep is not None:
                connection.execute(
                    "CREATE TEMP TABLE retained_paths (path TEXT PRIMARY KEY)"
                )
                connection.executemany(
                    "INSERT INTO retained_paths(path) VALUES (?)",
                    ((key,) for key in self._prune_keep),
                )
                connection.execute(
                    "DELETE FROM stat_evidence WHERE path NOT IN "
                    "(SELECT path FROM retained_paths)"
                )
        self._dirty = False


class StatEvidenceStore:
    """Factory for point-addressable stat evidence gates."""

    __slots__ = ("_digest", "_path")

    def __init__(
        self,
        path: pathlib.Path,
        *,
        digest: Callable[[pathlib.Path], str] = file_digest,
    ) -> None:
        self._path = path
        self._digest = digest

    def acquire(self) -> StatEvidenceGate:
        """Return a point-addressable gate for one indexing pass."""
        return StatEvidenceGate.load(self._path, digest=self._digest)


@dataclass(slots=True)
class _Cadence:
    """Amortizes progress ticks and control checkpoints over a hashing loop.

    Ticks are accumulated and flushed on the :data:`_FLUSH_INTERVAL_SECONDS`
    budget; final totals stay exact because :meth:`close` flushes the
    remainder. The pending count is flushed before the checkpoint so a
    delivered control signal never discards progress already made.
    """

    reporter: ProgressReporter | None
    run_control: RunControl
    _pending: int = 0
    _last_flush: float = field(default_factory=time.perf_counter)

    def tick(self) -> None:
        """Count one processed file and flush when the budget has elapsed."""
        self._pending += 1
        if time.perf_counter() - self._last_flush >= _FLUSH_INTERVAL_SECONDS:
            self.flush()

    def flush(self) -> None:
        """Publish pending ticks, then honour any pending control request."""
        if self._pending and self.reporter is not None:
            self.reporter.advance(self._pending)
        self._pending = 0
        self._last_flush = time.perf_counter()
        self.run_control.checkpoint()

    def close(self) -> None:
        """Flush the remainder so the reported total is exact."""
        self.flush()


@dataclass(frozen=True, slots=True)
class BatchHashOutcome:
    """Digests and per-file failures from one batched hashing pass."""

    #: Key to blake2b hex digest, in the caller's input order.
    hashes: dict[str, str]
    #: ``(key, error)`` for files that could not be statted or read, in the
    #: caller's input order.
    failures: tuple[tuple[str, OSError], ...]


def _read_digest(
    digest: Callable[[pathlib.Path], str],
    path: pathlib.Path,
) -> tuple[str, os.stat_result]:
    """Digest *path* and return the stat observed after the read.

    Runs on pool workers, and touches no gate, reporter, or control state -
    those all stay on the calling thread. What the digest itself does is the
    owning domain's business and is not always just I/O and hashing: the vault
    fingerprint parses frontmatter and reads configuration here. It must
    therefore stay thread-safe and must never raise anything the caller does
    not catch.
    """
    return digest(path), os.stat(path)


def hash_paths(
    gate: StatEvidenceGate,
    items: Sequence[tuple[str, pathlib.Path]],
    *,
    reporter: ProgressReporter | None = None,
    run_control: RunControl = NO_RUN_CONTROL,
) -> BatchHashOutcome:
    """Hash *items* behind *gate*, reading only what evidence demands.

    Reuse decisions, evidence recording, progress, and control stay on the
    calling thread; only read-and-digest work is fanned out to a bounded
    thread pool, and results are applied in the caller's input order. A file
    that cannot be statted or read is reported in ``failures`` instead of
    aborting the batch, mirroring the per-file skip of the serial loops.

    Evidence for a rehashed file is recorded only when the post-read stat
    still matches the pre-read stat; a file whose identity moved mid-read
    yields its digest but no evidence, so the next pass rehashes it.
    """
    cadence = _Cadence(reporter, run_control)
    cadence.run_control.checkpoint()
    reused: dict[str, str] = {}
    computed: dict[str, str] = {}
    failures: dict[str, OSError] = {}
    pending: list[tuple[str, pathlib.Path, os.stat_result, int]] = []
    for key, path in items:
        try:
            stat = os.stat(path)
        except OSError as exc:
            failures[key] = exc
            cadence.tick()
            continue
        recorded = gate.probe(key, stat)
        if recorded is not None:
            reused[key] = recorded
            cadence.tick()
        else:
            # Ticked when its digest is collected, so progress counts work
            # actually finished rather than work merely scheduled.
            pending.append((key, path, stat, time.time_ns()))
    if pending:
        _drain_pending_digests(gate, pending, cadence, computed, failures)
    cadence.close()
    ordered_hashes: dict[str, str] = {}
    ordered_failures: list[tuple[str, OSError]] = []
    for key, _ in items:
        if key in reused:
            ordered_hashes[key] = reused[key]
        elif key in computed:
            ordered_hashes[key] = computed[key]
        elif key in failures:
            ordered_failures.append((key, failures[key]))
    return BatchHashOutcome(ordered_hashes, tuple(ordered_failures))


def _drain_pending_digests(
    gate: StatEvidenceGate,
    pending: Sequence[tuple[str, pathlib.Path, os.stat_result, int]],
    cadence: _Cadence,
    computed: dict[str, str],
    failures: dict[str, OSError],
) -> None:
    """Digest pending reads and apply every result on the calling thread.

    Reads are pooled only when the batch's mean file size clears
    :data:`_POOL_MIN_MEAN_BYTES`; below it, dispatch overhead exceeds the
    per-file work and the inline loop is faster.
    """

    def consume(
        entry: tuple[str, pathlib.Path, os.stat_result, int],
        fetch: Callable[[], tuple[str, os.stat_result]],
    ) -> None:
        key, _path, stat, hashed_at_ns = entry
        try:
            digest, post_stat = fetch()
        except OSError as exc:
            failures[key] = exc
        else:
            computed[key] = digest
            gate.rehashed += 1
            if (
                post_stat.st_size == stat.st_size
                and post_stat.st_mtime_ns == stat.st_mtime_ns
            ):
                gate.record(key, stat, digest, hashed_at_ns)
        cadence.tick()

    mean_bytes = sum(stat.st_size for _, _, stat, _ in pending) // len(pending)
    if mean_bytes < _POOL_MIN_MEAN_BYTES:
        for entry in pending:
            consume(entry, functools.partial(_read_digest, gate.digest, entry[1]))
        return
    executor = ThreadPoolExecutor(
        max_workers=min(_HASH_POOL_WORKERS, len(pending)),
        thread_name_prefix="stat-gate-hash",
    )
    try:
        futures = [
            executor.submit(_read_digest, gate.digest, path)
            for _, path, _, _ in pending
        ]
        for entry, future in zip(pending, futures, strict=True):
            consume(entry, future.result)
    finally:
        # Drop work not yet started so a delivered cancel waits only for
        # the reads already in flight, never the whole remaining batch.
        executor.shutdown(wait=True, cancel_futures=True)


def record_computed_hashes(
    cache: StatEvidenceStore,
    items: Iterable[tuple[str, pathlib.Path, str]],
    *,
    computed_not_before_ns: int,
    keep: Collection[str] | None = None,
) -> None:
    """Bank hashes a run already computed as stat evidence for later passes.

    Full-index paths hash every file - inside chunk workers or during
    publication - and previously recorded nothing, so the first incremental
    after any full rebuild rehashed the world. Each entry is recorded only
    when :meth:`StatEvidenceGate.record_known_hash` can bind it honestly;
    a *keep* collection additionally prunes evidence for departed files and
    must only be passed by a caller that hashed the full current membership.
    """
    gate = cache.acquire()
    for key, path, content_hash in items:
        gate.record_known_hash(
            key,
            path,
            content_hash,
            computed_not_before_ns=computed_not_before_ns,
        )
    if keep is not None:
        gate.prune(keep)
    gate.persist()
