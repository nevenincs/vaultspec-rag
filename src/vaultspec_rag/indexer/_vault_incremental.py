"""Incremental vault indexing: what changed, and what that means for the index.

Scanning for documents, hashing them against the last run, parsing only what
moved, encoding those, and reconciling the result - including the payload
refresh that updates metadata without re-encoding a body that did not change.

Separate from the indexer that owns the collection because a full rebuild and
an incremental pass share a store and a model but almost nothing else: this is
the half that has to reason about deltas.
"""

from __future__ import annotations

import contextlib
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

from ..job_control import NO_RUN_CONTROL
from . import _stat_gate, _vault_fingerprint
from ._streaming import _stream_encode_and_upsert_vault
from ._streaming_types import VaultStreamRequest
from ._vault_fingerprint import VaultDelta
from ._vault_meta import (
    VAULT_FINGERPRINT_SCHEME_KEY,
)
from ._vault_prep import IndexResult, prepare_document, split_document

if TYPE_CHECKING:
    import pathlib
    import threading
    from collections.abc import Generator, Iterable, Iterator

    from .._store_models import VaultChunk, VaultDocument
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
class VaultReconcileInputs:
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


def classify_documents(
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
def controlled_phase(
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


class VaultIncrementalMixin:
    """Runs an incremental or scoped pass over a vault."""

    if TYPE_CHECKING:
        model: EmbeddingModel
        root_dir: pathlib.Path
        store: VaultStore
        _gpu_lock: threading.Lock | None
        _stat_gate_cache: _stat_gate.ResidentGateCache

        # Provided by the indexer this mixes into.
        def _resolve_reuse(
            self,
        ) -> tuple[ReuseStats | None, DonorReuseContext | None]: ...

        def _read_meta_raw(self) -> dict[str, str]: ...

        def _load_meta(self) -> dict[str, str]: ...

        def _write_meta(
            self, meta: dict[str, str], *, run_control: RunControl = ...
        ) -> int: ...

        def _purge_shrunk_chunk_tails(
            self,
            existing_counts: dict[str, int],
            new_counts: dict[str, int],
            *,
            run_control: RunControl = ...,
        ) -> None: ...

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
        with controlled_phase(
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
            with controlled_phase(
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
        work: VaultReconcileInputs,
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
        with controlled_phase(
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
        with controlled_phase(
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
        with controlled_phase(reporter, run_control, "scan changed", None):
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

        with controlled_phase(
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
        classification = classify_documents(
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
            VaultReconcileInputs(
                id_to_path=to_hash,
                existing_counts=existing_counts,
                slice_size=slice_size,
                reporter=reporter,
                run_control=run_control,
            ),
        )

        with controlled_phase(
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
        with controlled_phase(reporter, run_control, "write metadata", 1):
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
