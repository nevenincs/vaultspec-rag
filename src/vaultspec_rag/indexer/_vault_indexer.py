"""Vault document indexing orchestration.

Drives full and incremental indexing of ``.vault/`` markdown documents:
scanning, parsing, embedding, upserting, and content-hash metadata
tracking with a per-instance writer lock.
"""

from __future__ import annotations

import contextlib
import functools
import json
import logging
import os
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vaultspec_core.vaultcore import (
    get_doc_type,
    scan_vault,
)

from .._atomic_write import JsonWriteOptions, write_json_atomically
from .._index_breadth import (
    VAULT_PUBLISHED_DOCUMENTS_KEY,
    VAULT_PUBLISHED_POINTS_KEY,
    index_meta_path,
)
from .._source_types import PublicSourceType
from ..job_control import NO_RUN_CONTROL
from ..store_runtime import StorageGeometryError
from . import _config_epoch, _stat_gate, _vault_fingerprint
from ._index_lifecycle import (
    IndexLifecycleRequest,
    incremental_mode,
    run_index_lifecycle,
)
from ._streaming import _stream_encode_and_upsert_vault
from ._streaming_types import VaultStreamRequest
from ._vault_fingerprint import VaultDelta
from ._vault_meta import (
    VAULT_CONTENT_EPOCH_KEY,
    VAULT_FINGERPRINT_SCHEME_KEY,
    VAULT_POINT_SCHEMA,
    VAULT_POINT_SCHEMA_KEY,
)
from ._vault_prep import IndexResult, prepare_document, split_document

if TYPE_CHECKING:
    import pathlib
    import threading
    from collections.abc import Generator, Iterable, Iterator

    from .._store_models import VaultChunk, VaultDocument
    from ..embeddings import EmbeddingModel
    from ..job_control import RunControl
    from ..memory_probe import MemoryBudget, MemoryBudgetSnapshot
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._reuse import DonorReuseContext, ReuseStats

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _DocumentPreparationWindow:
    """Bounded document-preparation work shared by the refill loop."""

    path_iter: Iterator[pathlib.Path]
    pending: set[Future[VaultDocument | None]]
    pool: ThreadPoolExecutor
    root_dir: pathlib.Path
    run_control: RunControl
    max_in_flight: int
    exhausted: bool = False


@dataclass(frozen=True, slots=True)
class _VaultEncodeWork:
    """One incremental document batch and the counts it may replace."""

    docs: list[VaultDocument]
    existing_counts: dict[str, int]
    slice_size: int
    reporter: ProgressReporter
    run_control: RunControl


@dataclass(frozen=True, slots=True)
class _PayloadRefreshPlan:
    """The payload-only work one classification turned out to justify."""

    #: Chunks whose payloads are to be rewritten, vectors untouched.
    chunks: list[VaultChunk]
    #: How many documents those chunks belong to. Counted separately because a
    #: document is not one chunk, and the reported figure names documents.
    documents: int
    #: Documents the plan could not honour, for the re-embed branch instead.
    deferred: set[str]


@dataclass(frozen=True, slots=True)
class _VaultReconcileInputs:
    """What reconciling a classified change set needs, however it was reached."""

    id_to_path: dict[str, pathlib.Path]
    existing_counts: dict[str, int]
    slice_size: int
    reporter: ProgressReporter
    run_control: RunControl


@dataclass(frozen=True, slots=True)
class _VaultReconcileOutcome:
    """What one reconciliation of a classified change set actually did."""

    re_embedded: int
    payload_updated: int
    reuse: ReuseStats | None


@dataclass(frozen=True, slots=True)
class _VaultClassification:
    """One run's split of candidate documents into the work each demands."""

    #: Documents whose body moved: re-chunk and re-embed.
    body: set[str]
    #: Documents whose indexed metadata moved while their body did not:
    #: rebuild payloads, leave vectors alone.
    metadata: set[str]

    def defer_to_body(self, doc_ids: set[str]) -> _VaultClassification:
        """Move *doc_ids* out of the payload branch and into the re-embed one."""
        if not doc_ids:
            return self
        return _VaultClassification(
            body=self.body | doc_ids,
            metadata=self.metadata - doc_ids,
        )


def _group_chunks_by_document(
    chunks: list[VaultChunk],
) -> list[list[VaultChunk]]:
    """Group contiguous chunks by their parent document, preserving order.

    The planner appends each document's chunks together, so grouping is a scan
    rather than a sort, and the output order matches the input's.
    """
    groups: list[list[VaultChunk]] = []
    for chunk in chunks:
        if groups and groups[-1][0].doc_id == chunk.doc_id:
            groups[-1].append(chunk)
        else:
            groups.append([chunk])
    return groups


def _classify_documents(
    candidates: set[str],
    current: dict[str, str],
    previous: dict[str, str],
) -> _VaultClassification:
    """Route each candidate document to the cheapest outcome that is correct."""
    body: set[str] = set()
    metadata: set[str] = set()
    for doc_id in candidates:
        if doc_id not in current:
            # Unhashable this run; the previous publication stands for it.
            continue
        delta = _vault_fingerprint.classify(previous.get(doc_id), current[doc_id])
        if delta is VaultDelta.BODY:
            body.add(doc_id)
        elif delta is VaultDelta.METADATA:
            metadata.add(doc_id)
    return _VaultClassification(body=body, metadata=metadata)


@contextlib.contextmanager
def _controlled_phase(
    reporter: ProgressReporter,
    run_control: RunControl,
    name: str,
    total: int | None,
) -> Generator[None]:
    """Balance one progress phase and checkpoint at both safe edges."""
    run_control.checkpoint()
    reporter.phase_start(name, total)
    try:
        yield
    finally:
        reporter.phase_end()
    run_control.checkpoint()


def _fill_document_window(window: _DocumentPreparationWindow) -> None:
    """Fill one bounded preparation window and return iterator exhaustion."""
    while not window.exhausted and len(window.pending) < window.max_in_flight:
        window.run_control.checkpoint()
        try:
            path = next(window.path_iter)
        except StopIteration:
            window.exhausted = True
        else:
            window.pending.add(
                window.pool.submit(prepare_document, path, window.root_dir)
            )


def _collect_prepared_document(
    future: Future[VaultDocument | None],
    docs: list[VaultDocument],
    *,
    skip_errors: bool,
) -> None:
    """Collect one completed preparation result under the caller's error policy."""
    try:
        doc = future.result()
    except Exception:
        if not skip_errors:
            raise
        logger.warning("Worker failed to prepare document", exc_info=True)
        return
    if doc is not None:
        docs.append(doc)


class VaultIndexer:
    """Orchestrates vault document indexing into the vector store.

    Scans the ``.vault/`` directory for markdown documents, parses YAML
    frontmatter to extract metadata (tags, dates, related links), generates
    dense and sparse embeddings via the provided ``EmbeddingModel``, and
    upserts the results into Qdrant. Supports both full and incremental
    indexing using blake2b content hashing to skip unchanged documents.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        gpu_lock: threading.Lock | None = None,
    ) -> None:
        """Initialize the indexer with a workspace root, embedding model, and store.

        Args:
            root_dir: Path to the vault workspace root.
            model: Embedding model used to encode document text.
            store: Vector store where indexed documents are persisted.
            gpu_lock: Optional non-reentrant ``threading.Lock`` that
                serializes GPU operations (encoding) with concurrent
                searches. ``threading.Lock`` (not ``RLock``) is
                expected - same-thread re-entry would deadlock; the
                indexer never nests its own GPU acquisitions.
        """
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._gpu_lock = gpu_lock
        # Indexer-level writer lock that serializes full_index and
        # incremental_index against each other and against themselves.
        # Without this, two concurrent MCP / CLI / watcher reindex
        # calls on the same indexer instance could race their
        # ``existing_ids_before`` snapshots and overwrite each other's
        # contributions (#68).
        import threading as _threading

        self._writer_lock: _threading.Lock = _threading.Lock()
        self._meta_path = index_meta_path(root_dir, PublicSourceType.VAULT)
        self._stat_gate_path = _stat_gate.sidecar_for(self._meta_path)
        # Resident between runs; every acquire/retain pair runs under
        # ``self._writer_lock``, which is the serialization the cache's
        # single-threaded contract relies on. The gate digests through the
        # split fingerprint, so its evidence and the sidecar it gates always
        # describe the same thing.
        self._stat_gate_cache = _stat_gate.ResidentGateCache(
            self._stat_gate_path,
            digest=functools.partial(
                _vault_fingerprint.fingerprint_path,
                root_dir=root_dir,
            ),
        )
        self._memory_budget: MemoryBudget | None = None

    @property
    def memory_budget_snapshot(self) -> MemoryBudgetSnapshot | None:
        """Return the latest immutable observed-memory reading."""
        from ..memory_probe import held_budget_snapshot

        return held_budget_snapshot(self._memory_budget)

    @contextlib.contextmanager
    def _memory_telemetry(self) -> Generator[None]:
        """Observe one run's memory high-water without admitting a ceiling.

        The budget is constructed with no ceilings at all. No observation can
        then classify a failure, so nothing here can terminate a run that
        would otherwise have completed: this is measurement, not admission.
        That is deliberate rather than incidental. The vault domain has no
        support-profile limits to be held to, and inventing one here would
        add a new way for vault indexing to die in exchange for a number an
        operator can already act on. What the peak is for is watching the
        distance to a ceiling, which is not served by imposing one.

        Every vault forward is already bracketed by the shared capture in
        the encoding path; those readings are discarded today only because
        no recorder is registered on the thread. Registering one is what
        turns them into a published peak, and it leaves the encode path,
        its batching, and its allocation untouched.
        """
        from ..memory_probe import MemoryBudget, record_forward_peaks

        budget = MemoryBudget()
        self._memory_budget = budget
        with record_forward_peaks(budget.record_forward_peak_mib):
            self._sample_memory("before vault dispatch")
            try:
                yield
            finally:
                self._sample_memory("after vault dispatch")

    def _sample_memory(self, label: str) -> None:
        """Record one process and device reading against this run's budget."""
        from ..memory_probe import current_cuda_mib, current_rss_mib

        budget = self._memory_budget
        if budget is None:
            return
        on_cuda = getattr(self.model, "device", None) == "cuda"
        budget.sample_readings(
            label=label,
            rss_mib=current_rss_mib(),
            cuda_mib=current_cuda_mib() if on_cuda else None,
        )

    def _resolve_reuse(
        self,
    ) -> tuple[ReuseStats | None, DonorReuseContext | None]:
        """Resolve this run's donor reuse context, once per index run."""
        from ._donor_candidates import CollectionKind
        from ._reuse import resolve_donor_reuse

        return resolve_donor_reuse(
            self.root_dir,
            CollectionKind.VAULT,
            self.store,
            expected_content_epoch=self._current_vault_content_epoch(),
        )

    def full_index(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Full re-index serialized through the indexer writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_full_index_locked`. The lock guarantees that two
        concurrent ``full_index`` (or ``incremental_index``) calls on
        the same indexer instance run sequentially, eliminating the
        ``existing_ids_before`` snapshot race documented in #68.

        ``run_control`` defaults to the inert implementation so direct and
        legacy callers retain their existing behavior.
        """
        run_control.checkpoint()
        with self._writer_lock, self._memory_telemetry():
            return run_index_lifecycle(
                lambda: self._full_index_locked(
                    clean=clean,
                    reporter=reporter,
                    run_control=run_control,
                ),
                IndexLifecycleRequest(
                    event_logger=logger,
                    store=self.store,
                    source="vault",
                    mode="full",
                    clean=clean,
                    root=self.root_dir,
                    run_control=run_control,
                ),
            )

    def _full_index_locked(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Locked implementation of :meth:`full_index`.

        Scans all documents, embeds them, and replaces the entire store.
        Emits phase events through ``reporter`` at every pipeline step.

        Args:
            clean: When ``True``, additionally purge points that only a
                superseded point layout can leave behind, so the rebuild
                delivers a fully replaced collection. Both modes replace in
                place: they stream upserts over the live points and purge
                what the new corpus no longer contains only after the stream
                succeeds, so an interruption at any instant leaves the old
                complete collection still answering searches. The one
                destructive branch left is a stored geometry the new
                configuration cannot write into (e.g. a changed embedding
                dimension), where recreation is the only possible path and
                the old points were unservable for this configuration
                anyway. Both modes deliver the "no stale documents persist"
                contract on successful completion.
            reporter: Required progress reporter. Callers without a UI
                should pass ``NullProgressReporter``.
            run_control: Cooperative attempt control checked between phases
                and batches. Clean rebuild control is deferred across the
                destructive publication span.

        Returns:
            An ``IndexResult`` where ``added`` equals the total number
            of documents written, ``updated`` is ``0``, and ``removed``
            reports the post-stream stale-document purge count
            (#68). If the vault is empty the returned
            counts are ``added=0`` and ``removed`` reflects every
            previously-indexed row that was purged.

        Raises:
            OSError: If the post-stream stale-document purge fails
                against a Qdrant collection that was successfully
                rebuilt (the collection still contains valid new
                data plus the stale rows).
        """
        from ..config._settings import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)

        with _controlled_phase(reporter, run_control, "scan vault", None):
            paths: list[pathlib.Path] = []
            for path in scan_vault(self.root_dir):
                run_control.checkpoint()
                paths.append(path)
                run_control.checkpoint()

        with _controlled_phase(reporter, run_control, "parse documents", len(paths)):
            docs = self._prepare_documents_bounded(
                paths,
                reporter,
                run_control=run_control,
                skip_errors=True,
            )

        # Note: we intentionally do NOT short-circuit when docs is
        # empty. The streaming helper handles a zero-length list
        # correctly, and falling through the main path means
        # ``full_index(clean=True)`` on a now-empty vault still
        # purges every previously-indexed row.

        # Failure-safe rebuild, clean or not: ensure the table exists,
        # snapshot the current ID set, stream upsert (idempotent by doc_id -
        # existing rows are overwritten in place), then purge only the IDs
        # that no longer exist in the new corpus. If any slice raises we
        # have not destroyed the old collection, so a crash at any instant
        # leaves the old complete index answering searches. ``clean=True``
        # keeps its "no stale documents persist" contract through the final
        # purge steps rather than through an up-front drop, because a drop
        # that precedes the build converts every interruption into a served
        # husk. The only recreation left is the geometry-incompatible case
        # inside ``_prepare_collection``, where in-place replacement is
        # physically impossible.
        # A cooperative request already pending is delivered before a clean
        # publication span begins; within it, new requests are deferred
        # through streaming, stale cleanup, and metadata publication so a
        # deliberate pause/cancel never exposes a partial replacement.
        publication_span = (
            run_control.protected() if clean else contextlib.nullcontext()
        )
        with publication_span:
            existing_counts = self._prepare_collection(
                clean=clean,
                reporter=reporter,
                run_control=run_control,
            )
            existing_ids_before: set[str] = set(existing_counts)

            reuse_stats, donor_reuse = self._resolve_reuse()
            new_counts = _stream_encode_and_upsert_vault(
                VaultStreamRequest(
                    docs=docs,
                    slice_size=slice_size,
                    model=self.model,
                    store=self.store,
                    gpu_lock=self._gpu_lock,
                    reporter=reporter,
                    ingest_wait=False,
                    run_control=run_control,
                    reuse=donor_reuse,
                )
            )
            self._purge_shrunk_chunk_tails(
                existing_counts,
                new_counts,
                run_control=run_control,
            )

            stale_counts: dict[str, int] = existing_counts
            if clean:
                # Points from a superseded layout carry no ordinal, so the
                # upserts wrote beside them and neither replacement purge can
                # see them; only the clean rebuild promises their removal.
                # Like the tail purge above, this runs only after the stream
                # proved the replacement whole - an interruption before this
                # point leaves the old collection fully intact. Removing
                # them changes what the barrier below must expect for the
                # stale documents, so the counts are re-taken when any went.
                with _controlled_phase(
                    reporter,
                    run_control,
                    "purge superseded-layout points",
                    1,
                ):
                    run_control.checkpoint()
                    if self.store.delete_prechunk_vault_points():
                        stale_counts = self.store.get_chunk_counts()
                    reporter.advance(1)

            # Streaming completed successfully - now it is safe to delete
            # the rows that were in the collection before but are absent
            # from the freshly-indexed corpus.
            new_ids = {doc.id for doc in docs}
            stale_ids = sorted(existing_ids_before - new_ids)

            # The stream ran without the per-slice apply handshake, so
            # prove every acknowledged chunk applied before anything
            # terminal happens. After the tail purge the collection must
            # hold exactly the new corpus's chunks plus the untouched
            # chunks of documents that will be purged as stale below.
            expected_points = sum(new_counts.values()) + sum(
                stale_counts.get(doc_id, 0) for doc_id in stale_ids
            )
            run_control.checkpoint()
            self.store.apply_ingest_barrier(
                self.store.TABLE_NAME,
                expected_points=expected_points,
            )
            with _controlled_phase(
                reporter,
                run_control,
                "purge stale documents",
                len(stale_ids),
            ):
                if stale_ids:
                    run_control.checkpoint()
                    try:
                        self.store.delete_documents(stale_ids)
                    except OSError:
                        logger.error(
                            "Failed to purge stale vault documents after "
                            "successful rebuild - collection still "
                            "contains valid new data plus %d stale rows",
                            len(stale_ids),
                        )
                        raise
                    run_control.checkpoint()
                    reporter.advance(len(stale_ids))

            with _controlled_phase(reporter, run_control, "write metadata", 1):
                self._save_meta(docs, run_control=run_control)
                reporter.advance(1)
        run_control.checkpoint()

        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=len(docs),
            added=len(docs),
            updated=0,
            # Report the post-stream stale-purge count so MCP / CLI /
            # watcher observability reflects the rows actually deleted
            # by the failure-safe rebuild (#68).
            removed=len(stale_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            reuse=reuse_stats.snapshot() if reuse_stats is not None else None,
        )

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Incremental re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_incremental_index_locked`. Serializes against
        concurrent ``full_index`` / ``incremental_index`` callers on
        the same indexer (#68).

        Args:
            reporter: Required progress reporter.
            changed_paths: When provided, only the given filesystem paths
                are reconciled (scoped reindex). Work then becomes
                proportional to the change set rather than the whole vault
                (#151). When ``None`` the method keeps its full-scan
                semantics, so first-run, explicit, and ``clean`` callers
                are unchanged.
            run_control: Cooperative attempt control checked between phases,
                batches, and storage mutations.
        """
        run_control.checkpoint()
        with self._writer_lock, self._memory_telemetry():
            return run_index_lifecycle(
                lambda: self._incremental_index_locked(
                    reporter=reporter,
                    changed_paths=changed_paths,
                    run_control=run_control,
                ),
                IndexLifecycleRequest(
                    event_logger=logger,
                    store=self.store,
                    source="vault",
                    mode=incremental_mode(scoped=changed_paths is not None),
                    clean=False,
                    root=self.root_dir,
                    run_control=run_control,
                ),
            )

    def _incremental_index_locked(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Locked implementation of :meth:`incremental_index`.

        Compares blake2b content hashes against stored metadata to identify
        changes. Emits phase events through ``reporter``.

        Args:
            reporter: Required progress reporter.
            changed_paths: When provided, delegates to
                :meth:`_scoped_incremental_locked` so only the named paths
                are reconciled. When ``None`` the full-vault scan below runs.
            run_control: Cooperative attempt control inherited from the
                public index operation.

        Returns:
            An ``IndexResult`` with counts for newly added, updated, and
            removed documents since the last index run.

        Raises:
            OSError: If vault files cannot be read or hashed.
        """
        run_control.checkpoint()
        if self._needs_layout_rebuild():
            logger.info(
                "Vault point layout changed; running a one-time clean "
                "rebuild of the vault collection",
            )
            return self._full_index_locked(
                clean=True,
                reporter=reporter,
                run_control=run_control,
            )

        run_control.checkpoint()
        if self._needs_content_rebuild():
            logger.info(
                "Vault chunk boundary changed; running a one-time clean "
                "rebuild of the vault collection",
            )
            return self._full_index_locked(
                clean=True,
                reporter=reporter,
                run_control=run_control,
            )

        run_control.checkpoint()
        if changed_paths is not None:
            return self._scoped_incremental_locked(
                changed_paths=changed_paths,
                reporter=reporter,
                run_control=run_control,
            )

        from ..config._settings import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)

        run_control.checkpoint()
        prev_meta = self._load_meta()
        run_control.checkpoint()

        with _controlled_phase(reporter, run_control, "scan vault", None):
            docs_dir = self.root_dir / get_config().docs_dir
            current_docs: dict[str, pathlib.Path] = self._scan_vault_for_docs(
                docs_dir,
                run_control=run_control,
            )

        run_control.checkpoint()
        stored_counts = self.store.get_chunk_counts()
        run_control.checkpoint()
        stored_ids = set(stored_counts)
        current_ids = set(current_docs.keys())
        new_ids = current_ids - stored_ids
        deleted_ids = stored_ids - current_ids
        potentially_modified = current_ids & stored_ids

        self._announce_fingerprint_migration()

        with _controlled_phase(
            reporter,
            run_control,
            "hash documents",
            len(current_docs),
        ):
            current_hashes: dict[str, str] = self._hash_documents(
                current_docs,
                reporter,
                run_control=run_control,
                full_membership=True,
            )

        classification = _classify_documents(
            potentially_modified,
            current_hashes,
            prev_meta,
        )
        outcome = self._reconcile_classified(
            classification,
            new_ids,
            _VaultReconcileInputs(
                id_to_path=current_docs,
                existing_counts=stored_counts,
                slice_size=slice_size,
                reporter=reporter,
                run_control=run_control,
            ),
        )

        with _controlled_phase(
            reporter,
            run_control,
            "delete removed",
            len(deleted_ids),
        ):
            if deleted_ids:
                run_control.checkpoint()
                self.store.delete_documents(list(deleted_ids))
                run_control.checkpoint()
                reporter.advance(len(deleted_ids))

        with _controlled_phase(reporter, run_control, "write metadata", 1):
            # The publication's own count, so the reported total and the
            # breadth claim beside it describe one instant of the collection.
            total = self._write_meta(current_hashes, run_control=run_control)
            reporter.advance(1)

        run_control.checkpoint()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_ids),
            updated=outcome.re_embedded,
            payload_updated=outcome.payload_updated,
            removed=len(deleted_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(current_docs),
            reuse=outcome.reuse.snapshot() if outcome.reuse is not None else None,
        )

    def _scan_vault_for_docs(
        self,
        docs_dir: pathlib.Path,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> dict[str, pathlib.Path]:
        current_docs: dict[str, pathlib.Path] = {}
        for path in scan_vault(self.root_dir):
            run_control.checkpoint()
            doc_type = get_doc_type(path, self.root_dir)
            if doc_type is not None:
                try:
                    rel = str(path.relative_to(docs_dir)).replace("\\", "/")
                except ValueError as exc:
                    logger.debug(
                        "relative_to(%s) failed for %s: %s; using basename",
                        docs_dir,
                        path,
                        exc,
                    )
                    rel = path.name
                doc_id = rel.rsplit(".", 1)[0] if "." in rel else rel
                current_docs[doc_id] = path
            run_control.checkpoint()
        return current_docs

    def _hash_documents(
        self,
        current_docs: dict[str, pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
        full_membership: bool = False,
    ) -> dict[str, str]:
        """Hash documents behind the stat-evidence gate.

        Only a caller passing the complete current membership sets
        ``full_membership``, which additionally prunes gate evidence for
        documents that no longer exist.
        """
        gate = self._stat_gate_cache.acquire()
        outcome = _stat_gate.hash_paths(
            gate,
            list(current_docs.items()),
            reporter=reporter,
            run_control=run_control,
        )
        for doc_id, _error in outcome.failures:
            logger.warning("Cannot hash file, skipping: %s", doc_id)
        if full_membership:
            gate.prune(current_docs.keys())
        gate.persist()
        self._stat_gate_cache.retain(gate)
        return outcome.hashes

    def _parse_documents(
        self,
        to_index_ids: set[str],
        id_to_path: dict[str, pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[VaultDocument]:
        docs_to_index: list[VaultDocument] = []
        with _controlled_phase(
            reporter,
            run_control,
            "parse documents",
            len(to_index_ids),
        ):
            if not to_index_ids:
                return docs_to_index
            paths_to_index: list[pathlib.Path] = []
            for doc_id in to_index_ids:
                run_control.checkpoint()
                paths_to_index.append(id_to_path[doc_id])
            docs_to_index = self._prepare_documents_bounded(
                paths_to_index,
                reporter,
                run_control=run_control,
                skip_errors=False,
            )
        return docs_to_index

    def _encode_incremental_documents(
        self,
        work: _VaultEncodeWork,
    ) -> ReuseStats | None:
        """Encode changed documents or emit the empty embedding phase."""
        if not work.docs:
            with _controlled_phase(
                work.reporter,
                work.run_control,
                "embed + upsert documents",
                0,
            ):
                pass
            return None
        reuse_stats, donor_reuse = self._resolve_reuse()
        new_counts = _stream_encode_and_upsert_vault(
            VaultStreamRequest(
                docs=work.docs,
                slice_size=work.slice_size,
                model=self.model,
                store=self.store,
                gpu_lock=self._gpu_lock,
                reporter=work.reporter,
                run_control=work.run_control,
                reuse=donor_reuse,
            )
        )
        self._purge_shrunk_chunk_tails(
            work.existing_counts,
            new_counts,
            run_control=work.run_control,
        )
        return reuse_stats

    def _reconcile_classified(
        self,
        classification: _VaultClassification,
        new_ids: set[str],
        work: _VaultReconcileInputs,
    ) -> _VaultReconcileOutcome:
        """Plan, encode, and write one classified change set.

        Shared verbatim by the full-scan and scoped incremental paths, because
        the two differ only in how they arrive at a classification - what a
        classification then costs must not depend on which caller produced it.
        A copy here would be the shape that drifts: a fix applied to the scan
        path and missed on the scoped one is invisible until a watcher-driven
        edit behaves differently from an operator-driven one.
        """
        plan = self._plan_payload_refresh(
            classification.metadata,
            work.id_to_path,
            work.reporter,
            run_control=work.run_control,
        )
        classification = classification.defer_to_body(plan.deferred)

        docs_to_index = self._parse_documents(
            new_ids | classification.body,
            work.id_to_path,
            work.reporter,
            run_control=work.run_control,
        )
        reuse_stats = self._encode_incremental_documents(
            _VaultEncodeWork(
                docs=docs_to_index,
                existing_counts=work.existing_counts,
                slice_size=work.slice_size,
                reporter=work.reporter,
                run_control=work.run_control,
            )
        )
        self._apply_payload_refresh(
            plan.chunks,
            work.reporter,
            run_control=work.run_control,
        )
        return _VaultReconcileOutcome(
            re_embedded=len(classification.body),
            payload_updated=plan.documents,
            reuse=reuse_stats,
        )

    def _plan_payload_refresh(
        self,
        doc_ids: set[str],
        id_to_path: dict[str, pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> _PayloadRefreshPlan:
        """Build the chunks a payload-only refresh would write, and its fallout.

        A payload-only write assumes the store already holds exactly the points
        this document produces - the body did not move, so its chunk partition
        did not either. That assumption is checked against the ordinals the
        store actually has points under, not against how far they reach: the
        two differ exactly when a document's ordinal range has a hole, and a
        hole is the case where writing by assumed ordinal reaches nothing and
        raises nothing. A document whose stored ordinals are not precisely the
        set it now splits into is returned as deferred, for the caller to route
        into the re-embed branch, which rebuilds its points outright.

        Returns:
            The chunks to write, how many documents they cover, and the ids
            that must be re-embedded instead.
        """
        if not doc_ids:
            return _PayloadRefreshPlan(chunks=[], documents=0, deferred=set())

        from ..config._settings import get_config

        chunk_chars = int(get_config().vault_chunk_chars)
        deferred: set[str] = set()
        chunks: list[VaultChunk] = []
        refreshed = 0
        with _controlled_phase(
            reporter,
            run_control,
            "rebuild payloads",
            len(doc_ids),
        ):
            try:
                stored_ordinals = self.store.get_stored_chunk_ordinals(doc_ids)
            except (OSError, RuntimeError):
                # Without knowing what is stored, nothing can be written
                # safely by ordinal; re-embedding rebuilds these outright.
                logger.warning(
                    "Could not read stored chunk ordinals for the payload "
                    "refresh; re-embedding those documents instead",
                    exc_info=True,
                )
                return _PayloadRefreshPlan(
                    chunks=[],
                    documents=0,
                    deferred=set(doc_ids),
                )
            docs = self._prepare_documents_bounded(
                [id_to_path[doc_id] for doc_id in sorted(doc_ids)],
                reporter,
                run_control=run_control,
                skip_errors=False,
            )
            prepared = {doc.id for doc in docs}
            # A document that would not parse cannot have its payloads rebuilt
            # from what it says, so it goes the way of any other unreconciled
            # document rather than being silently dropped.
            deferred |= doc_ids - prepared
            for doc in docs:
                run_control.checkpoint()
                doc_chunks = split_document(doc, chunk_chars)
                if stored_ordinals.get(doc.id, set()) != set(range(len(doc_chunks))):
                    deferred.add(doc.id)
                    continue
                chunks.extend(doc_chunks)
                refreshed += 1
        return _PayloadRefreshPlan(
            chunks=chunks,
            documents=refreshed,
            deferred=deferred,
        )

    def _apply_payload_refresh(
        self,
        chunks: list[VaultChunk],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Write the planned payload-only refresh, leaving vectors untouched.

        Written one document at a time rather than as a single call over every
        chunk. The store writes a payload per point, so a whole-corpus metadata
        refresh is thousands of sequential round trips; handing them over in one
        call would make the whole write uncancellable and report no progress
        until it finished. A document is the right granularity to break on -
        each one's payloads land together, so a cancellation between documents
        never leaves one half-refreshed.
        """
        with _controlled_phase(
            reporter,
            run_control,
            "upsert payloads",
            len(chunks),
        ):
            if not chunks:
                return
            for doc_chunks in _group_chunks_by_document(chunks):
                run_control.checkpoint()
                self.store.overwrite_vault_chunk_payloads(
                    doc_chunks,
                    write_policy=None,
                )
                reporter.advance(len(doc_chunks))
                run_control.checkpoint()

    def _announce_fingerprint_migration(self) -> None:
        """Say once, at the top of a run, that the sidecar predates the split.

        The migration is cheap by design - documents whose bytes have not moved
        re-label rather than re-embed - but it is not nothing, and a run that
        does more work than its successors will for a reason nobody can see is
        the kind of thing that gets diagnosed twice.
        """
        raw = self._read_meta_raw()
        if not raw:
            return
        if raw.get(VAULT_FINGERPRINT_SCHEME_KEY) == _vault_fingerprint.SCHEME:
            return
        logger.info(
            "Vault fingerprints predate the body/metadata split; this run "
            "re-classifies the corpus and re-embeds only documents whose "
            "bytes actually moved",
        )

    def _prepare_documents_bounded(
        self,
        paths: Iterable[pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
        skip_errors: bool,
    ) -> list[VaultDocument]:
        """Prepare documents with bounded queued work and control-aware unwind."""
        max_workers = min(32, (os.cpu_count() or 1) + 4)
        max_in_flight = max_workers * 2
        window = _DocumentPreparationWindow(
            path_iter=iter(paths),
            pending=set(),
            pool=ThreadPoolExecutor(max_workers=max_workers),
            root_dir=self.root_dir,
            run_control=run_control,
            max_in_flight=max_in_flight,
        )
        docs: list[VaultDocument] = []

        try:
            _fill_document_window(window)
            while window.pending:
                run_control.checkpoint()
                done, _not_done = wait(
                    window.pending,
                    timeout=0.1,
                    return_when=FIRST_COMPLETED,
                )
                run_control.checkpoint()
                for future in done:
                    window.pending.remove(future)
                    _collect_prepared_document(
                        future,
                        docs,
                        skip_errors=skip_errors,
                    )
                    reporter.advance()
                    run_control.checkpoint()
                _fill_document_window(window)
        except BaseException:
            for future in window.pending:
                future.cancel()
            window.pool.shutdown(wait=True, cancel_futures=True)
            raise
        else:
            window.pool.shutdown(wait=True)
        run_control.checkpoint()
        return docs

    def _vault_doc_id(
        self,
        path: pathlib.Path,
        docs_dir: pathlib.Path,
    ) -> str | None:
        """Resolve a filesystem path to its vault document id.

        Mirrors the id scheme used by the full incremental scan: the path
        relative to ``docs_dir`` with its extension stripped.

        Args:
            path: A filesystem path (need not exist - pure-path math only).
            docs_dir: The vault documents root (``root_dir / docs_dir``).

        Returns:
            The document id, or ``None`` when ``path`` is not under
            ``docs_dir``.
        """
        try:
            rel = str(path.relative_to(docs_dir)).replace("\\", "/")
        except ValueError:
            return None
        return rel.rsplit(".", 1)[0] if "." in rel else rel

    def _scoped_incremental_locked(
        self,
        *,
        changed_paths: Iterable[pathlib.Path],
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Reconcile only ``changed_paths`` against the index (#151).

        Resolves each changed path to a vault document id, re-embeds the
        added/modified docs, deletes vanished ones, and persists a partial
        read-modify-write of the hash metadata. Work is proportional to the
        change set, not the vault size.

        Args:
            changed_paths: Filesystem paths reported as changed.
            reporter: Required progress reporter.
            run_control: Cooperative attempt control checked between scoped
                reconciliation batches and mutations.

        Returns:
            An ``IndexResult`` with added/updated/removed counts for the
            reconciled subset and the post-reconcile total document count.
        """
        from ..config._settings import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)
        docs_dir = self.root_dir / get_config().docs_dir
        run_control.checkpoint()
        prev_meta = self._load_meta()
        run_control.checkpoint()

        to_hash: dict[str, pathlib.Path] = {}
        delete_ids: set[str] = set()
        with _controlled_phase(reporter, run_control, "scan changed", None):
            for path in changed_paths:
                run_control.checkpoint()
                self._process_changed_vault_path(
                    path,
                    docs_dir,
                    prev_meta,
                    to_hash,
                    delete_ids,
                )
                run_control.checkpoint()

        with _controlled_phase(
            reporter,
            run_control,
            "hash documents",
            len(to_hash),
        ):
            changed_hashes = self._hash_documents(
                to_hash,
                reporter,
                run_control=run_control,
            )

        new_ids = {d for d in changed_hashes if d not in prev_meta}
        classification = _classify_documents(
            {d for d in changed_hashes if d in prev_meta},
            changed_hashes,
            prev_meta,
        )

        # The chunk-count snapshot serves the payload branch's arity check as
        # well as the shrunk-tail purge, so it is taken over every candidate
        # before either branch is decided.
        candidate_ids = new_ids | classification.body | classification.metadata
        existing_counts: dict[str, int] = {}
        if candidate_ids:
            run_control.checkpoint()
            try:
                existing_counts = self.store.get_chunk_counts(
                    doc_ids=candidate_ids,
                )
            except (OSError, RuntimeError):
                logger.warning(
                    "Could not snapshot chunk counts for the scoped "
                    "reindex; shrunk-tail purge will be skipped",
                    exc_info=True,
                )
                existing_counts = {}
            run_control.checkpoint()

        outcome = self._reconcile_classified(
            classification,
            new_ids,
            _VaultReconcileInputs(
                id_to_path=to_hash,
                existing_counts=existing_counts,
                slice_size=slice_size,
                reporter=reporter,
                run_control=run_control,
            ),
        )

        with _controlled_phase(
            reporter,
            run_control,
            "delete removed",
            len(delete_ids),
        ):
            if delete_ids:
                run_control.checkpoint()
                self.store.delete_documents(list(delete_ids))
                run_control.checkpoint()
                reporter.advance(len(delete_ids))

        # Partial read-modify-write: preserve every unchanged entry, refresh
        # the changed hashes, and drop the deleted ids. Never recompute the
        # whole map (that is what the full scan is for).
        new_meta = dict(prev_meta)
        new_meta.update(changed_hashes)
        for doc_id in delete_ids:
            run_control.checkpoint()
            new_meta.pop(doc_id, None)
        with _controlled_phase(reporter, run_control, "write metadata", 1):
            # The publication's own count, so the reported total and the
            # breadth claim beside it describe one instant of the collection.
            total = self._write_meta(new_meta, run_control=run_control)
            reporter.advance(1)

        run_control.checkpoint()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_ids),
            updated=outcome.re_embedded,
            payload_updated=outcome.payload_updated,
            removed=len(delete_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(changed_paths)
            if isinstance(changed_paths, list)
            else 0,  # Approximate
            reuse=outcome.reuse.snapshot() if outcome.reuse is not None else None,
        )

    def _process_changed_vault_path(
        self,
        path: pathlib.Path,
        docs_dir: pathlib.Path,
        prev_meta: dict[str, str],
        to_hash: dict[str, pathlib.Path],
        delete_ids: set[str],
    ) -> None:
        doc_id = self._vault_doc_id(path, docs_dir)
        if doc_id is None:
            return
        if path.is_file() and get_doc_type(path, self.root_dir) is not None:
            to_hash[doc_id] = path
        elif doc_id in prev_meta:
            delete_ids.add(doc_id)

    def _save_meta(
        self,
        docs: list[VaultDocument],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> int:
        """Save index metadata (content hashes) from VaultDocument list.

        Resolves each document's blake2b hash through the stat-evidence gate
        and delegates to ``_write_meta`` for atomic persistence. Routing
        through the gate both answers unchanged documents from a stat instead
        of rereading every file the run just parsed, and records evidence so
        the first incremental after a full rebuild reuses instead of
        rehashing the whole corpus. Individual file read errors drop the
        document from the metadata, as the ungated read did.

        Args:
            docs: List of indexed documents whose paths are used to
                compute hashes.

        Returns:
            The point count the publication claims, as ``_write_meta``
            observed it.

        Raises:
            OSError: If the collection cannot be counted or the metadata file
                cannot be written (propagated from ``_write_meta``).
        """
        from ..config._settings import get_config

        docs_dir = self.root_dir / get_config().docs_dir
        gate = self._stat_gate_cache.acquire()
        outcome = _stat_gate.hash_paths(
            gate,
            [(doc.id, docs_dir / doc.path) for doc in docs],
            run_control=run_control,
        )
        # ``docs`` is the complete corpus this full save publishes, so
        # evidence for departed documents is pruned with it.
        gate.prune({doc.id for doc in docs})
        gate.persist()
        self._stat_gate_cache.retain(gate)
        return self._write_meta(outcome.hashes, run_control=run_control)

    def _prepare_collection(
        self,
        *,
        clean: bool,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> dict[str, int]:
        """Ensure the collection and snapshot stored chunk counts.

        The snapshot drives both the stale-document purge and the
        shrunk-tail purge after streaming. A failed snapshot degrades
        to skipping those purges rather than failing the rebuild.

        The collection is never dropped here for an ordinary clean rebuild -
        the served points must outlive the build that replaces them. The one
        exception is a stored geometry the current configuration cannot
        write into, where recreation is the only path and nothing servable
        is lost.
        """
        with _controlled_phase(reporter, run_control, "prepare collection", 1):
            run_control.checkpoint()
            try:
                self.store.ensure_table()
            except StorageGeometryError:
                if not clean:
                    raise
                # The stored vectors cannot hold this configuration's
                # geometry, so replacing points in place is impossible and
                # recreation is the only path forward. This is the single
                # remaining destructive branch of a clean rebuild: the old
                # points were unusable for this configuration anyway, so
                # nothing servable is being destroyed. Every other clean
                # rebuild replaces in place - upsert over the live points,
                # purge what the new corpus no longer contains after the
                # stream succeeds - so an interrupted run leaves the old
                # complete collection still answering searches.
                logger.warning(
                    "vault collection geometry cannot hold this "
                    "configuration; recreating it for the clean rebuild",
                )
                run_control.checkpoint()
                self.store.drop_table()
                self.store.ensure_table()
                run_control.checkpoint()
                # The collection was just recreated: the snapshot is empty
                # by construction, and scanning would only burn CPU.
                reporter.advance(1)
                return {}
            run_control.checkpoint()
            try:
                existing_counts: dict[str, int] = self.store.get_chunk_counts()
            except (OSError, RuntimeError):
                # OSError covers I/O failures; RuntimeError covers
                # Qdrant client errors and lock contention
                # (VaultStoreLockedError). Either way the safest
                # response is to skip the stale-document purge so
                # the rebuild can still complete (#68).
                logger.warning(
                    "Could not snapshot existing vault IDs before "
                    "rebuild; stale-document purge will be skipped",
                    exc_info=True,
                )
                existing_counts = {}
            run_control.checkpoint()
            reporter.advance(1)
        return existing_counts

    def _purge_shrunk_chunk_tails(
        self,
        existing_counts: dict[str, int],
        new_counts: dict[str, int],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Delete orphaned tail chunks of documents that shrank.

        Upserts overwrite ordinals below the new chunk count; when a
        document now produces fewer chunks than the store holds, the
        ordinals at or beyond the new count are stale and must go.
        """
        for doc_id, new_count in new_counts.items():
            run_control.checkpoint()
            if existing_counts.get(doc_id, 0) > new_count:
                try:
                    self.store.delete_document_chunk_tail(doc_id, new_count)
                except (OSError, RuntimeError):
                    logger.warning(
                        "Could not purge stale tail chunks of %s; the "
                        "document's fresh chunks are intact but ordinals "
                        ">= %d are stale until the next successful run",
                        doc_id,
                        new_count,
                        exc_info=True,
                    )
            run_control.checkpoint()

    def _needs_layout_rebuild(self) -> bool:
        """Return True when the stored point layout predates chunking.

        Detection is two-pronged: a metadata sidecar whose layout marker
        differs from the current version, or a non-empty collection with
        no sidecar at all (an install whose metadata was deleted). Either
        way the stored points may use the one-point-per-document layout
        and must be rebuilt rather than incrementally patched.
        """
        raw = self._read_meta_raw()
        if raw:
            return raw.get(VAULT_POINT_SCHEMA_KEY) != VAULT_POINT_SCHEMA
        try:
            return self.store.count() > 0
        except (OSError, RuntimeError):
            logger.warning(
                "Could not probe the vault collection for a layout "
                "rebuild decision; assuming no rebuild is needed",
                exc_info=True,
            )
            return False

    def _current_vault_content_epoch(self) -> str:
        """Compute the content epoch over the current ``vault_chunk_chars``."""
        from ..config._settings import get_config

        return _config_epoch.vault_content_epoch(
            vault_chunk_chars=int(get_config().vault_chunk_chars),
        )

    def _needs_content_rebuild(self) -> bool:
        """Return True when the stored chunk boundary differs from the current.

        Detection compares the stored content epoch against the current
        ``vault_chunk_chars``; a mismatch means the chunk boundary changed, so
        every document must re-chunk (a clean rebuild) even though its bytes are
        unchanged. A sidecar predating this key (or no sidecar) is not forced to
        rebuild - the epoch is simply stamped on the next successful write, so an
        existing install is not clean-rebuilt merely for upgrading.
        """
        raw = self._read_meta_raw()
        stored = raw.get(VAULT_CONTENT_EPOCH_KEY)
        if stored is None:
            return False
        return stored != self._current_vault_content_epoch()

    def _observe_published_breadth(self) -> tuple[int, int]:
        """Return the collection's point count and distinct-document count.

        Taken at the publication instant, after every upsert and delete this
        run makes has landed, so the pair describes exactly the corpus the
        sidecar published beside it names. Both are recorded because they fail
        independently: a collection can hold a plausible number of points
        spread across a fraction of the documents the same sidecar names, and
        no comparison of point counts alone can see that.

        The writer lock is held across both reads, so nothing this indexer
        does can move the collection between them.

        Raises:
            OSError: The collection could not be counted.
            RuntimeError: The store rejected the count (client error or lock
                contention).
        """
        return self.store.count(), len(self.store.get_all_ids())

    def _write_meta(
        self,
        meta: dict[str, str],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> int:
        """Publish content-hash metadata and this index's breadth claim.

        Uses an atomic write (write-to-temp + durable replace) so a crash
        mid-write never leaves the metadata file in a corrupt state, and so a
        publication that reports success has reached the disk. The current
        point-layout version, the content epoch over ``vault_chunk_chars``,
        and the observed breadth are stamped under reserved keys so later runs
        can detect layout changes, chunk-boundary changes, and a collection
        that has lost points since it was published.

        The breadth figures and the hash entries land in one atomic
        replacement, which is what makes the ordering safe: there is no
        instant at which the new document set is the published one while the
        breadth describing it is not. A caller that cannot obtain the figures
        gets the exception rather than a sidecar, leaving the previous
        publication in place - an index nobody can reconcile is worse than a
        stale one that verifies.

        Args:
            meta: Mapping of document stem to blake2b hex digest.
            run_control: Cooperative attempt control checked at both edges.

        Returns:
            The point count this publication claims, so a caller reporting a
            collection total describes the same instant the claim does rather
            than paying for a second count of its own.

        Raises:
            OSError: The collection could not be counted, or the metadata
                directory could not be created or written.
            RuntimeError: The store rejected the count.
        """
        run_control.checkpoint()
        points, documents = self._observe_published_breadth()
        stamped = {
            **meta,
            VAULT_POINT_SCHEMA_KEY: VAULT_POINT_SCHEMA,
            VAULT_FINGERPRINT_SCHEME_KEY: _vault_fingerprint.SCHEME,
            VAULT_CONTENT_EPOCH_KEY: self._current_vault_content_epoch(),
            VAULT_PUBLISHED_POINTS_KEY: str(points),
            VAULT_PUBLISHED_DOCUMENTS_KEY: str(documents),
        }
        write_json_atomically(
            self._meta_path,
            stamped,
            JsonWriteOptions(indent=2, durable=True),
        )
        run_control.checkpoint()
        return points

    def _read_meta_raw(self) -> dict[str, str]:
        """Load the sidecar JSON verbatim, reserved keys included."""
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text(encoding="utf-8"))
        except (KeyError, ValueError, OSError) as exc:
            logger.debug(
                "vault meta %s unreadable; treating as empty: %s",
                self._meta_path,
                exc,
                exc_info=True,
            )
            return {}

    def _load_meta(self) -> dict[str, str]:
        """Load index metadata from the sidecar JSON file.

        Reserved dunder keys (the layout marker) are stripped so they
        can never participate in document-id set arithmetic.

        Returns:
            Mapping of document stem to blake2b hex digest, or an empty
            dict if the file does not exist or cannot be parsed.
        """
        return {
            key: value
            for key, value in self._read_meta_raw().items()
            if not key.startswith("__")
        }
