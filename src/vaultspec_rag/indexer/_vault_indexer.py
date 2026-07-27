"""Vault document indexing orchestration.

Drives full and incremental indexing of ``.vault/`` markdown documents:
scanning, parsing, embedding, upserting, and content-hash metadata
tracking with a per-instance writer lock.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
import time
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import TYPE_CHECKING

from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # no stubs for vaultspec_core
    get_doc_type,
    scan_vault,
)

from .._atomic_write import JsonWriteOptions, write_json_atomically
from ..job_control import NO_RUN_CONTROL
from . import _config_epoch
from ._index_lifecycle import run_index_lifecycle
from ._streaming import VaultStreamRequest, _stream_encode_and_upsert_vault
from ._vault_meta import (
    VAULT_CONTENT_EPOCH_KEY,
    VAULT_POINT_SCHEMA,
    VAULT_POINT_SCHEMA_KEY,
)
from ._vault_prep import IndexResult, prepare_document

if TYPE_CHECKING:
    import pathlib
    import threading
    from collections.abc import Generator, Iterable, Iterator

    from .._store_models import VaultDocument
    from ..embeddings import EmbeddingModel
    from ..job_control import RunControl
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
        from ..config import get_config

        cfg = get_config()

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
        self._meta_path = root_dir / cfg.data_dir / cfg.index_metadata_file

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
        with self._writer_lock:
            return run_index_lifecycle(
                lambda: self._full_index_locked(
                    clean=clean,
                    reporter=reporter,
                    run_control=run_control,
                ),
                event_logger=logger,
                store=self.store,
                source="vault",
                mode="full",
                clean=clean,
                root=self.root_dir,
                run_control=run_control,
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
            clean: When ``True``, drop and recreate the vault
                collection up front so schema-level changes (e.g.
                a new embedding dimension) take effect (#68). On the
                ``clean=True`` path an
                interrupted run (CUDA OOM, process kill, Qdrant
                I/O failure mid-stream) may leave the collection
                empty until the next successful run - this is
                the explicit user opt-in to destructive semantics.
                The default ``clean=False`` path is failure-safe:
                it streams upserts in place and purges only the
                stale doc IDs after a successful rebuild, so an
                interrupted run never leaves the collection empty.
                Both modes deliver the "no stale documents persist"
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
        from ..config import get_config

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

        # Failure-safe rebuild: ensure the table exists, snapshot the
        # current ID set, stream upsert (idempotent by doc_id - existing
        # rows are overwritten in place), then purge only the IDs that
        # no longer exist in the new corpus. If any slice raises we have
        # not destroyed the old collection. clean=True preserves its
        # documented contract ("no stale documents persist") via the
        # final purge step.
        #
        # When ``clean=True`` is explicitly passed, we ALSO drop the
        # collection up front so that schema-level changes (e.g. a
        # new embedding dimension) take effect (#68).
        # This re-introduces a narrow data-loss window between the
        # drop and the streaming upsert - but only on the explicit
        # opt-in path. ``clean=False`` (the default + watcher path)
        # remains failure-safe.
        # A cooperative request already pending is delivered before a clean
        # collection can be dropped. Once the drop begins, defer new requests
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
                existing_counts[doc_id] for doc_id in stale_ids
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
            # Removed a dead `if clean and not stale_ids and
            # existing_ids_before` debug log: clean=True drops the
            # collection up front, so existing_ids_before is always empty
            # on that path and the condition could never fire. The
            # non-clean path with no stale_ids is the no-op case and
            # doesn't need a log line.

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
        with self._writer_lock:
            return run_index_lifecycle(
                lambda: self._incremental_index_locked(
                    reporter=reporter,
                    changed_paths=changed_paths,
                    run_control=run_control,
                ),
                event_logger=logger,
                store=self.store,
                source="vault",
                mode=(
                    "scoped_incremental" if changed_paths is not None else "incremental"
                ),
                clean=False,
                root=self.root_dir,
                run_control=run_control,
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

        from ..config import get_config

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
            )

        modified_ids = {
            doc_id
            for doc_id in potentially_modified
            if doc_id in current_hashes
            and current_hashes[doc_id] != prev_meta.get(doc_id)
        }

        to_index_ids = new_ids | modified_ids
        docs_to_index = self._parse_documents(
            to_index_ids,
            current_docs,
            reporter,
            run_control=run_control,
        )

        reuse_stats = self._encode_incremental_documents(
            _VaultEncodeWork(
                docs=docs_to_index,
                existing_counts=stored_counts,
                slice_size=slice_size,
                reporter=reporter,
                run_control=run_control,
            )
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
            self._write_meta(current_hashes, run_control=run_control)
            reporter.advance(1)

        run_control.checkpoint()
        total = self.store.count()
        run_control.checkpoint()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_ids),
            updated=len(modified_ids),
            removed=len(deleted_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(current_docs),
            reuse=reuse_stats.snapshot() if reuse_stats is not None else None,
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
    ) -> dict[str, str]:
        current_hashes: dict[str, str] = {}
        for doc_id, path in current_docs.items():
            run_control.checkpoint()
            try:
                with open(path, "rb") as f:
                    current_hashes[doc_id] = hashlib.file_digest(
                        f,
                        "blake2b",
                    ).hexdigest()
            except OSError:
                logger.warning("Cannot hash file, skipping: %s", doc_id)
            reporter.advance()
            run_control.checkpoint()
        return current_hashes

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
        from ..config import get_config

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
        modified_ids = {
            d
            for d in changed_hashes
            if d in prev_meta and changed_hashes[d] != prev_meta.get(d)
        }
        to_index_ids = new_ids | modified_ids

        docs_to_index = self._parse_documents(
            to_index_ids,
            to_hash,
            reporter,
            run_control=run_control,
        )

        existing_counts: dict[str, int] = {}
        if docs_to_index:
            run_control.checkpoint()
            try:
                existing_counts = self.store.get_chunk_counts(
                    doc_ids=to_index_ids,
                )
            except (OSError, RuntimeError):
                logger.warning(
                    "Could not snapshot chunk counts for the scoped "
                    "reindex; shrunk-tail purge will be skipped",
                    exc_info=True,
                )
                existing_counts = {}
            run_control.checkpoint()
        reuse_stats = self._encode_incremental_documents(
            _VaultEncodeWork(
                docs=docs_to_index,
                existing_counts=existing_counts,
                slice_size=slice_size,
                reporter=reporter,
                run_control=run_control,
            )
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
            self._write_meta(new_meta, run_control=run_control)
            reporter.advance(1)

        run_control.checkpoint()
        total = self.store.count()
        run_control.checkpoint()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_ids),
            updated=len(modified_ids),
            removed=len(delete_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(changed_paths)
            if isinstance(changed_paths, list)
            else 0,  # Approximate
            reuse=reuse_stats.snapshot() if reuse_stats is not None else None,
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
    ) -> None:
        """Save index metadata (content hashes) from VaultDocument list.

        Computes blake2b hashes for each document's file and delegates
        to ``_write_meta`` for atomic persistence.  Individual file
        read errors are suppressed.

        Args:
            docs: List of indexed documents whose paths are used to
                compute hashes.

        Raises:
            OSError: If the metadata file cannot be written (propagated
                from ``_write_meta``).
        """
        meta: dict[str, str] = {}
        from ..config import get_config

        docs_dir = self.root_dir / get_config().docs_dir
        for doc in docs:
            run_control.checkpoint()
            path = docs_dir / doc.path
            with contextlib.suppress(OSError), open(path, "rb") as f:
                meta[doc.id] = hashlib.file_digest(
                    f,
                    "blake2b",
                ).hexdigest()
            run_control.checkpoint()
        self._write_meta(meta, run_control=run_control)

    def _prepare_collection(
        self,
        *,
        clean: bool,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> dict[str, int]:
        """Drop/ensure the collection and snapshot stored chunk counts.

        The snapshot drives both the stale-document purge and the
        shrunk-tail purge after streaming. A failed snapshot degrades
        to skipping those purges rather than failing the rebuild.
        """
        with _controlled_phase(reporter, run_control, "prepare collection", 1):
            if clean:
                run_control.checkpoint()
                self.store.drop_table()
                self.store.ensure_table()
                run_control.checkpoint()
                # The collection was just dropped: the snapshot is empty
                # by construction, and scanning would only burn CPU.
                reporter.advance(1)
                return {}
            run_control.checkpoint()
            self.store.ensure_table()
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
        from ..config import get_config

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

    def _write_meta(
        self,
        meta: dict[str, str],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Write content-hash metadata to the sidecar JSON file.

        Uses an atomic write (write-to-temp + os.replace) so a crash mid-write
        never leaves the metadata file in a corrupt state. The current
        point-layout version and the content epoch over ``vault_chunk_chars``
        are stamped under reserved keys so later runs can detect layout and
        chunk-boundary changes.

        Args:
            meta: Mapping of document stem to blake2b hex digest.

        Raises:
            OSError: If the metadata directory cannot be created or the
                file cannot be written.
        """
        run_control.checkpoint()
        stamped = {
            **meta,
            VAULT_POINT_SCHEMA_KEY: VAULT_POINT_SCHEMA,
            VAULT_CONTENT_EPOCH_KEY: self._current_vault_content_epoch(),
        }
        write_json_atomically(self._meta_path, stamped, JsonWriteOptions(indent=2))
        run_control.checkpoint()

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
