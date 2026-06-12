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
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

from vaultspec_core.vaultcore import (  # pyright: ignore[reportMissingTypeStubs]  # no stubs for vaultspec_core
    get_doc_type,
    scan_vault,
)

from ..logging_config import log_event
from ._streaming import _stream_encode_and_upsert_vault
from ._vault_prep import IndexResult, prepare_document

if TYPE_CHECKING:
    import pathlib
    import threading
    from collections.abc import Iterable

    from ..embeddings import EmbeddingModel
    from ..progress import ProgressReporter
    from ..store import VaultDocument, VaultStore

logger = logging.getLogger(__name__)

#: Version of the vault point layout. ``2`` stores one point per
#: heading-aware chunk (``doc_id#c{ordinal}``); ``1`` (or an absent
#: marker over a non-empty collection) stored one point per document.
#: A mismatch triggers a one-time clean rebuild so old-layout points
#: never coexist with chunked ones.
_VAULT_POINT_SCHEMA = "2"

#: Reserved key carrying the layout version inside the hash-metadata
#: sidecar. Never collides with document ids (which are relative paths).
_SCHEMA_KEY = "__vault_point_schema__"


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
        # contributions (#68 audit F6.6).
        import threading as _threading

        self._writer_lock: _threading.Lock = _threading.Lock()
        self._meta_path = root_dir / cfg.data_dir / cfg.index_metadata_file

    def full_index(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
    ) -> IndexResult:
        """Full re-index serialized through the indexer writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_full_index_locked`. The lock guarantees that two
        concurrent ``full_index`` (or ``incremental_index``) calls on
        the same indexer instance run sequentially, eliminating the
        ``existing_ids_before`` snapshot race documented in the #68
        rolling audit (F6.6).
        """
        with self._writer_lock:
            log_event(
                logger,
                "service.index",
                "started",
                source="vault",
                mode="full",
                clean=clean,
                root=self.root_dir,
            )
            try:
                result = self._full_index_locked(clean=clean, reporter=reporter)
            except Exception as exc:
                log_event(
                    logger,
                    "service.index",
                    "failed",
                    severity=logging.ERROR,
                    exc_info=True,
                    source="vault",
                    mode="full",
                    clean=clean,
                    root=self.root_dir,
                    error=exc,
                )
                raise
            log_event(
                logger,
                "service.index",
                "completed",
                source="vault",
                mode="full",
                clean=clean,
                root=self.root_dir,
                total=result.total,
                added=result.added,
                updated=result.updated,
                removed=result.removed,
                duration_ms=result.duration_ms,
            )
            return result

    def _full_index_locked(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
    ) -> IndexResult:
        """Locked implementation of :meth:`full_index`.

        Scans all documents, embeds them, and replaces the entire store.
        Emits phase events through ``reporter`` at every pipeline step.

        Args:
            clean: When ``True``, drop and recreate the vault
                collection up front so schema-level changes (e.g.
                a new embedding dimension) take effect (#68 audit
                F9.6 - codex P2). On the ``clean=True`` path an
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

        Returns:
            An ``IndexResult`` where ``added`` equals the total number
            of documents written, ``updated`` is ``0``, and ``removed``
            reports the post-stream stale-document purge count
            (#68 audit F10.5). If the vault is empty the returned
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

        reporter.phase_start("scan vault", None)
        paths = list(scan_vault(self.root_dir))
        reporter.phase_end()

        reporter.phase_start("parse documents", len(paths))
        docs: list[VaultDocument] = []
        with ThreadPoolExecutor() as pool:
            futures = [pool.submit(prepare_document, p, self.root_dir) for p in paths]
            for future in as_completed(futures):
                try:
                    doc = future.result()
                except Exception:
                    logger.warning("Worker failed to prepare document", exc_info=True)
                    reporter.advance()
                    continue
                if doc is not None:
                    docs.append(doc)
                reporter.advance()
        reporter.phase_end()

        # Note: we intentionally do NOT short-circuit when docs is
        # empty. The streaming helper handles a zero-length list
        # correctly, and falling through the main path means
        # ``full_index(clean=True)`` on a now-empty vault still
        # purges every previously-indexed row (F3.10 regression
        # guard).

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
        # new embedding dimension) take effect (#68 audit F9.6).
        # This re-introduces a narrow data-loss window between the
        # drop and the streaming upsert - but only on the explicit
        # opt-in path. ``clean=False`` (the default + watcher path)
        # remains failure-safe.
        existing_counts = self._prepare_collection(clean=clean, reporter=reporter)
        existing_ids_before: set[str] = set(existing_counts)

        new_counts = _stream_encode_and_upsert_vault(
            docs=docs,
            slice_size=slice_size,
            model=self.model,
            store=self.store,
            gpu_lock=self._gpu_lock,
            reporter=reporter,
        )
        self._purge_shrunk_chunk_tails(existing_counts, new_counts)

        # Streaming completed successfully - now it is safe to delete
        # the rows that were in the collection before but are absent
        # from the freshly-indexed corpus.
        new_ids = {doc.id for doc in docs}
        stale_ids = sorted(existing_ids_before - new_ids)
        reporter.phase_start("purge stale documents", len(stale_ids))
        try:
            if stale_ids:
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
                reporter.advance(len(stale_ids))
        finally:
            reporter.phase_end()
        # F10.1: removed dead `if clean and not stale_ids and
        # existing_ids_before` debug log. After iter 9, clean=True
        # drops the collection up front, so existing_ids_before is
        # always empty on that path and the condition could never
        # fire. The non-clean path with no stale_ids is the no-op
        # case and doesn't need a log line.

        reporter.phase_start("write metadata", 1)
        try:
            self._save_meta(docs)
            reporter.advance(1)
        finally:
            reporter.phase_end()

        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=len(docs),
            added=len(docs),
            updated=0,
            # Report the post-stream stale-purge count so MCP / CLI /
            # watcher observability reflects the rows actually deleted
            # by the failure-safe rebuild (#68 audit F6.3 / F6.10).
            removed=len(stale_ids),
            duration_ms=duration_ms,
            device=self.model.device,
        )

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
    ) -> IndexResult:
        """Incremental re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_incremental_index_locked`. Serializes against
        concurrent ``full_index`` / ``incremental_index`` callers on
        the same indexer (#68 audit F6.6).

        Args:
            reporter: Required progress reporter.
            changed_paths: When provided, only the given filesystem paths
                are reconciled (scoped reindex). Work then becomes
                proportional to the change set rather than the whole vault
                (#151). When ``None`` the method keeps its full-scan
                semantics, so first-run, explicit, and ``clean`` callers
                are unchanged.
        """
        with self._writer_lock:
            mode = "scoped_incremental" if changed_paths is not None else "incremental"
            log_event(
                logger,
                "service.index",
                "started",
                source="vault",
                mode=mode,
                clean=False,
                root=self.root_dir,
            )
            try:
                result = self._incremental_index_locked(
                    reporter=reporter,
                    changed_paths=changed_paths,
                )
            except Exception as exc:
                log_event(
                    logger,
                    "service.index",
                    "failed",
                    severity=logging.ERROR,
                    exc_info=True,
                    source="vault",
                    mode=mode,
                    clean=False,
                    root=self.root_dir,
                    error=exc,
                )
                raise
            log_event(
                logger,
                "service.index",
                "completed",
                source="vault",
                mode=mode,
                clean=False,
                root=self.root_dir,
                total=result.total,
                added=result.added,
                updated=result.updated,
                removed=result.removed,
                duration_ms=result.duration_ms,
            )
            return result

    def _incremental_index_locked(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
    ) -> IndexResult:
        """Locked implementation of :meth:`incremental_index`.

        Compares blake2b content hashes against stored metadata to identify
        changes. Emits phase events through ``reporter``.

        Args:
            reporter: Required progress reporter.
            changed_paths: When provided, delegates to
                :meth:`_scoped_incremental_locked` so only the named paths
                are reconciled. When ``None`` the full-vault scan below runs.

        Returns:
            An ``IndexResult`` with counts for newly added, updated, and
            removed documents since the last index run.

        Raises:
            OSError: If vault files cannot be read or hashed.
        """
        if self._needs_layout_rebuild():
            logger.info(
                "Vault point layout changed; running a one-time clean "
                "rebuild of the vault collection",
            )
            return self._full_index_locked(clean=True, reporter=reporter)

        if changed_paths is not None:
            return self._scoped_incremental_locked(
                changed_paths=changed_paths,
                reporter=reporter,
            )

        from ..config import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)

        prev_meta = self._load_meta()

        reporter.phase_start("scan vault", None)
        docs_dir = self.root_dir / get_config().docs_dir
        current_docs: dict[str, pathlib.Path] = self._scan_vault_for_docs(docs_dir)
        reporter.phase_end()

        stored_counts = self.store.get_chunk_counts()
        stored_ids = set(stored_counts)
        current_ids = set(current_docs.keys())
        new_ids = current_ids - stored_ids
        deleted_ids = stored_ids - current_ids
        potentially_modified = current_ids & stored_ids

        reporter.phase_start("hash documents", len(current_docs))
        current_hashes: dict[str, str] = self._hash_documents(current_docs, reporter)
        reporter.phase_end()

        modified_ids = {
            doc_id
            for doc_id in potentially_modified
            if doc_id in current_hashes
            and current_hashes[doc_id] != prev_meta.get(doc_id)
        }

        to_index_ids = new_ids | modified_ids
        docs_to_index = self._parse_documents(to_index_ids, current_docs, reporter)

        if docs_to_index:
            new_counts = _stream_encode_and_upsert_vault(
                docs=docs_to_index,
                slice_size=slice_size,
                model=self.model,
                store=self.store,
                gpu_lock=self._gpu_lock,
                reporter=reporter,
            )
            self._purge_shrunk_chunk_tails(stored_counts, new_counts)
        else:
            reporter.phase_start("embed + upsert documents", 0)
            reporter.phase_end()

        reporter.phase_start("delete removed", len(deleted_ids))
        if deleted_ids:
            self.store.delete_documents(list(deleted_ids))
            reporter.advance(len(deleted_ids))
        reporter.phase_end()

        reporter.phase_start("write metadata", 1)
        self._write_meta(current_hashes)
        reporter.advance(1)
        reporter.phase_end()

        total = self.store.count()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_ids),
            updated=len(modified_ids),
            removed=len(deleted_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(current_docs),
        )

    def _scan_vault_for_docs(self, docs_dir: pathlib.Path) -> dict[str, pathlib.Path]:
        current_docs: dict[str, pathlib.Path] = {}
        for path in scan_vault(self.root_dir):
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
        return current_docs

    def _hash_documents(
        self, current_docs: dict[str, pathlib.Path], reporter: ProgressReporter
    ) -> dict[str, str]:
        current_hashes: dict[str, str] = {}
        for doc_id, path in current_docs.items():
            try:
                with open(path, "rb") as f:
                    current_hashes[doc_id] = hashlib.file_digest(
                        f,
                        "blake2b",
                    ).hexdigest()
            except OSError:
                logger.warning("Cannot hash file, skipping: %s", doc_id)
            reporter.advance()
        return current_hashes

    def _parse_documents(
        self,
        to_index_ids: set[str],
        id_to_path: dict[str, pathlib.Path],
        reporter: ProgressReporter,
    ) -> list[VaultDocument]:
        docs_to_index: list[VaultDocument] = []
        reporter.phase_start("parse documents", len(to_index_ids))
        if to_index_ids:
            paths_to_index = [id_to_path[d] for d in to_index_ids]

            def _prep(p: pathlib.Path) -> VaultDocument | None:
                return prepare_document(p, self.root_dir)

            with ThreadPoolExecutor() as pool:
                for doc in pool.map(_prep, paths_to_index):
                    if doc is not None:
                        docs_to_index.append(doc)
                    reporter.advance()
        reporter.phase_end()
        return docs_to_index

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
    ) -> IndexResult:
        """Reconcile only ``changed_paths`` against the index (#151).

        Resolves each changed path to a vault document id, re-embeds the
        added/modified docs, deletes vanished ones, and persists a partial
        read-modify-write of the hash metadata. Work is proportional to the
        change set, not the vault size.

        Args:
            changed_paths: Filesystem paths reported as changed.
            reporter: Required progress reporter.

        Returns:
            An ``IndexResult`` with added/updated/removed counts for the
            reconciled subset and the post-reconcile total document count.
        """
        from ..config import get_config

        start = time.time()
        slice_size = max(1, get_config().embedding_batch_size)
        docs_dir = self.root_dir / get_config().docs_dir
        prev_meta = self._load_meta()

        reporter.phase_start("scan changed", None)
        to_hash: dict[str, pathlib.Path] = {}
        delete_ids: set[str] = set()
        for path in changed_paths:
            self._process_changed_vault_path(
                path, docs_dir, prev_meta, to_hash, delete_ids
            )
        reporter.phase_end()

        reporter.phase_start("hash documents", len(to_hash))
        changed_hashes = self._hash_documents(to_hash, reporter)
        reporter.phase_end()

        new_ids = {d for d in changed_hashes if d not in prev_meta}
        modified_ids = {
            d
            for d in changed_hashes
            if d in prev_meta and changed_hashes[d] != prev_meta.get(d)
        }
        to_index_ids = new_ids | modified_ids

        docs_to_index = self._parse_documents(to_index_ids, to_hash, reporter)

        if docs_to_index:
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
            new_counts = _stream_encode_and_upsert_vault(
                docs=docs_to_index,
                slice_size=slice_size,
                model=self.model,
                store=self.store,
                gpu_lock=self._gpu_lock,
                reporter=reporter,
            )
            self._purge_shrunk_chunk_tails(existing_counts, new_counts)
        else:
            reporter.phase_start("embed + upsert documents", 0)
            reporter.phase_end()

        reporter.phase_start("delete removed", len(delete_ids))
        if delete_ids:
            self.store.delete_documents(list(delete_ids))
            reporter.advance(len(delete_ids))
        reporter.phase_end()

        # Partial read-modify-write: preserve every unchanged entry, refresh
        # the changed hashes, and drop the deleted ids. Never recompute the
        # whole map (that is what the full scan is for).
        new_meta = dict(prev_meta)
        new_meta.update(changed_hashes)
        for doc_id in delete_ids:
            new_meta.pop(doc_id, None)
        reporter.phase_start("write metadata", 1)
        self._write_meta(new_meta)
        reporter.advance(1)
        reporter.phase_end()

        total = self.store.count()
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

    def _save_meta(self, docs: list[VaultDocument]) -> None:
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
            path = docs_dir / doc.path
            with contextlib.suppress(OSError), open(path, "rb") as f:
                meta[doc.id] = hashlib.file_digest(
                    f,
                    "blake2b",
                ).hexdigest()
        self._write_meta(meta)

    def _prepare_collection(
        self,
        *,
        clean: bool,
        reporter: ProgressReporter,
    ) -> dict[str, int]:
        """Drop/ensure the collection and snapshot stored chunk counts.

        The snapshot drives both the stale-document purge and the
        shrunk-tail purge after streaming. A failed snapshot degrades
        to skipping those purges rather than failing the rebuild.
        """
        reporter.phase_start("prepare collection", 1)
        try:
            if clean:
                self.store.drop_table()
                self.store.ensure_table()
                # The collection was just dropped: the snapshot is empty
                # by construction, and scanning would only burn CPU.
                reporter.advance(1)
                return {}
            self.store.ensure_table()
            try:
                existing_counts: dict[str, int] = self.store.get_chunk_counts()
            except (OSError, RuntimeError):
                # OSError covers I/O failures; RuntimeError covers
                # Qdrant client errors and lock contention
                # (VaultStoreLockedError). Either way the safest
                # response is to skip the stale-document purge so
                # the rebuild can still complete (#68 audit F9.4).
                logger.warning(
                    "Could not snapshot existing vault IDs before "
                    "rebuild; stale-document purge will be skipped",
                    exc_info=True,
                )
                existing_counts = {}
            reporter.advance(1)
        finally:
            reporter.phase_end()
        return existing_counts

    def _purge_shrunk_chunk_tails(
        self,
        existing_counts: dict[str, int],
        new_counts: dict[str, int],
    ) -> None:
        """Delete orphaned tail chunks of documents that shrank.

        Upserts overwrite ordinals below the new chunk count; when a
        document now produces fewer chunks than the store holds, the
        ordinals at or beyond the new count are stale and must go.
        """
        for doc_id, new_count in new_counts.items():
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

    def _needs_layout_rebuild(self) -> bool:
        """Return True when the stored point layout predates chunking.

        Detection is two-pronged: a metadata sidecar whose layout marker
        differs from the current version, or a non-empty collection with
        no sidecar at all (an install whose metadata was deleted). Either
        way the stored points may use the one-point-per-document layout
        and must be rebuilt rather than incrementally patched.
        """
        prev_meta = self._load_meta()
        if prev_meta:
            return prev_meta.get(_SCHEMA_KEY) != _VAULT_POINT_SCHEMA
        try:
            return self.store.count() > 0
        except (OSError, RuntimeError):
            logger.warning(
                "Could not probe the vault collection for a layout "
                "rebuild decision; assuming no rebuild is needed",
                exc_info=True,
            )
            return False

    def _write_meta(self, meta: dict[str, str]) -> None:
        """Write content-hash metadata to the sidecar JSON file.

        Uses an atomic write (write-to-temp + os.replace) so a crash mid-write
        never leaves the metadata file in a corrupt state. The current
        point-layout version is stamped into the file under a reserved
        key so later runs can detect layout changes.

        Args:
            meta: Mapping of document stem to blake2b hex digest.

        Raises:
            OSError: If the metadata directory cannot be created or the
                file cannot be written.
        """
        self._meta_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._meta_path.with_suffix(".tmp")
        stamped = {**meta, _SCHEMA_KEY: _VAULT_POINT_SCHEMA}
        tmp_path.write_text(json.dumps(stamped, indent=2), encoding="utf-8")
        os.replace(tmp_path, self._meta_path)

    def _load_meta(self) -> dict[str, str]:
        """Load index metadata from the sidecar JSON file.

        Returns:
            Mapping of document stem to blake2b hex digest, or an empty
            dict if the file does not exist or cannot be parsed.
        """
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
