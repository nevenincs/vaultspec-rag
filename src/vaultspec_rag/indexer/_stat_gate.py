"""Advisory stat-evidence gate over content rehashing.

Change detection proves a file unchanged by rehashing it, which prices an
unscoped convergence pass at the total byte count of the corpus. This gate
remembers the ``(size, mtime_ns)`` a file had when its content hash was last
computed and answers "may that hash be reused" from a stat call alone, so the
pass costs stat calls plus the bytes that actually changed.

What "hash" means is the owning domain's choice, carried by the gate itself:
each indexer holds its own gate over its own sidecar, and a gate digests every
file through the one function it was built with. The vault's fingerprint
splits a document into body and metadata halves rather than digesting raw
bytes, and binding that function to the gate is what keeps the recorded
evidence and the fingerprint it is evidence *for* from ever meaning different
things.

The content hash stays the sole indexing authority. The gate is advisory in
both directions: a missing, stale, corrupt, or unwritable sidecar only ever
causes extra hashing, never a skipped one, and a reused hash is still diffed
against the published manifest exactly like a freshly computed one. The one
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
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final, Self, cast

from .._atomic_write import JsonWriteOptions, write_json_atomically
from ..job_control import NO_RUN_CONTROL

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable, Collection, Iterable, Sequence

    from ..job_control import RunControl
    from ..progress import ProgressReporter

__all__ = [
    "BatchHashOutcome",
    "ResidentGateCache",
    "StatEvidenceGate",
    "file_digest",
    "hash_paths",
    "record_computed_hashes",
    "sidecar_for",
]

logger = logging.getLogger(__name__)

#: A recorded mtime must be at least this much older than the instant the
#: hash was computed before the entry may be trusted. Two seconds absorbs the
#: coarsest real filesystem timestamp granularity (FAT's 2s) plus timer
#: batching, so a write landing in the same timestamp tick as the hashed read
#: can never satisfy the gate.
_RACY_WINDOW_NS: Final = 2_000_000_000

#: Reserved sidecar key carrying the schema version. Dot-free relative paths
#: never start with ``__``, so it cannot collide with an entry key.
_SCHEMA_KEY: Final = "__stat_gate_schema__"
_SCHEMA_VERSION: Final = "1"

_WRITE_OPTIONS: Final = JsonWriteOptions(sort_keys=True, compact=True)

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


def sidecar_for(meta_path: pathlib.Path) -> pathlib.Path:
    """Return the gate sidecar path derived from a domain's meta sidecar."""
    return meta_path.with_name(f"{meta_path.name}.statgate.json")


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

    __slots__ = ("_dirty", "_entries", "_path", "digest", "rehashed", "reused")

    def __init__(
        self,
        path: pathlib.Path,
        entries: dict[str, _StatEvidence],
        *,
        digest: Callable[[pathlib.Path], str] = file_digest,
    ) -> None:
        self._path = path
        self._entries = entries
        self._dirty = False
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
        """Load the sidecar, treating every defect as an empty gate.

        A corrupt or partially valid sidecar is discarded whole rather than
        salvaged entry by entry: the only cost of discarding is rehashing,
        while trusting a file that failed validation once invites trusting
        whatever corrupted it.
        """
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls(path, {}, digest=digest)
        entries = _validated_entries(raw)
        if entries is None:
            logger.debug("stat gate sidecar %s invalid; rehashing instead", path)
            return cls(path, {}, digest=digest)
        return cls(path, entries, digest=digest)

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

    def share_entries(self) -> dict[str, _StatEvidence]:
        """Expose the live entry mapping for :class:`ResidentGateCache`.

        The returned mapping is the gate's own state, not a copy; only the
        cache may hold it, under the same writer-lock serialization that
        makes the cache safe at all.
        """
        return self._entries

    def prune(self, keep: Collection[str]) -> None:
        """Drop evidence for every key outside *keep*.

        Only a caller that hashed the full current membership may prune; a
        scoped pass sees a subset and must leave the rest alone.
        """
        stale = [key for key in self._entries if key not in keep]
        for key in stale:
            del self._entries[key]
        if stale:
            self._dirty = True

    def persist(self) -> None:
        """Publish accumulated evidence atomically; advisory, so never raise.

        Written even after a run that later fails to publish its index: an
        entry binds a hash to the stat identity it was computed against, which
        holds regardless of what the run did with the hash afterwards.
        """
        if not self._dirty:
            return
        payload: dict[str, object] = {_SCHEMA_KEY: _SCHEMA_VERSION}
        for key, entry in self._entries.items():
            payload[key] = [
                entry.size,
                entry.mtime_ns,
                entry.content_hash,
                entry.hashed_at_ns,
            ]
        try:
            write_json_atomically(self._path, payload, _WRITE_OPTIONS)
        except OSError:
            logger.warning(
                "stat gate sidecar %s could not be written; the next pass "
                "rehashes what this one proved",
                self._path,
                exc_info=True,
            )


class ResidentGateCache:
    """Keeps one sidecar's parsed entries resident between runs.

    A long-lived indexer reloads and re-parses its gate sidecar on every run,
    which prices a no-change pass at a JSON parse of the whole corpus's
    evidence. This cache hands the in-memory entries back when the sidecar's
    stat identity still matches what the cache itself last observed after
    persisting, and reloads from disk otherwise, so an external rewrite or a
    manual delete is always honoured on the next acquire.

    Single-threaded by contract: every user runs under its indexer's writer
    lock, which serializes acquire/retain pairs, so the cache adds no locking
    of its own. A run that mutates the shared entries and then fails before
    persisting leaves honest, freshly computed evidence resident; the sidecar
    merely lags it, which only means another process rehashes what this one
    already proved.
    """

    __slots__ = ("_digest", "_entries", "_path", "_signature")

    def __init__(
        self,
        path: pathlib.Path,
        *,
        digest: Callable[[pathlib.Path], str] = file_digest,
    ) -> None:
        self._path = path
        self._digest = digest
        self._entries: dict[str, _StatEvidence] | None = None
        self._signature: tuple[int, int] | None = None

    def acquire(self) -> StatEvidenceGate:
        """Return a gate over resident entries when the sidecar is unchanged."""
        signature = self._sidecar_signature()
        if (
            self._entries is not None
            and signature is not None
            and signature == self._signature
        ):
            return StatEvidenceGate(self._path, self._entries, digest=self._digest)
        return StatEvidenceGate.load(self._path, digest=self._digest)

    def retain(self, gate: StatEvidenceGate) -> None:
        """Adopt *gate*'s entries after :meth:`StatEvidenceGate.persist`."""
        self._entries = gate.share_entries()
        self._signature = self._sidecar_signature()

    def _sidecar_signature(self) -> tuple[int, int] | None:
        """Stat identity of the sidecar file, or ``None`` when unreadable."""
        try:
            stat = os.stat(self._path)
        except OSError:
            return None
        return (stat.st_size, stat.st_mtime_ns)


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

    Runs on pool workers: file I/O and hashing only, no gate, reporter, or
    control access. The post-read stat lets the calling thread refuse to
    record evidence for a file whose identity moved while it was being read.
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
    cache: ResidentGateCache,
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
    cache.retain(gate)


def _validated_entries(raw: object) -> dict[str, _StatEvidence] | None:
    """Parse a raw sidecar payload, refusing the whole file on any defect."""
    if not isinstance(raw, dict):
        return None
    mapping = cast("dict[object, object]", raw)
    if mapping.get(_SCHEMA_KEY) != _SCHEMA_VERSION:
        return None
    entries: dict[str, _StatEvidence] = {}
    for key, value in mapping.items():
        if key == _SCHEMA_KEY:
            continue
        if not isinstance(key, str) or not key:
            return None
        entry = _validated_entry(value)
        if entry is None:
            return None
        entries[key] = entry
    return entries


def _validated_entry(value: object) -> _StatEvidence | None:
    """Parse one raw sidecar row, rejecting anything but its exact shape.

    ``bool`` is checked explicitly because it satisfies ``isinstance(_, int)``
    while being a shape defect a hand-edited or corrupted row could carry.
    """
    if not isinstance(value, list):
        return None
    row = cast("list[object]", value)
    if len(row) != 4:
        return None
    size, mtime_ns, content_hash, hashed_at_ns = row
    if (
        type(size) is not int
        or type(mtime_ns) is not int
        or type(hashed_at_ns) is not int
        or not isinstance(content_hash, str)
    ):
        return None
    if size < 0 or not content_hash:
        return None
    return _StatEvidence(
        size=size,
        mtime_ns=mtime_ns,
        content_hash=content_hash,
        hashed_at_ns=hashed_at_ns,
    )
