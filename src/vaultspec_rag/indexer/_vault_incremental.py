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
from ._run_ledger_models import FETCH_BATCH, CommitUnitKind, RunAuthority, RunOperation
from ._streaming import _stream_encode_and_upsert_vault
from ._streaming_types import VaultStreamRequest
from ._vault_checkpoint import VaultRunCheckpoint
from ._vault_fingerprint import VaultDelta
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
    from ._publication_proof import ProofCompatibilityKey, ProofEvidence
    from ._reuse import DonorReuseContext, ReuseStats
    from ._run_ledger_runtime import RunLedger

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
    checkpoint: VaultRunCheckpoint
    content_identities: dict[str, str]


@dataclass(frozen=True, slots=True)
class VaultReconcileInputs:
    """What reconciling a classified change set needs, however it was reached."""

    id_to_path: dict[str, pathlib.Path]
    existing_counts: dict[str, int]
    slice_size: int
    reporter: ProgressReporter
    run_control: RunControl
    checkpoint: VaultRunCheckpoint
    content_identities: dict[str, str]


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
        _stat_gate_cache: _stat_gate.StatEvidenceStore

        # Provided by the indexer this mixes into.
        def _resolve_reuse(
            self,
        ) -> tuple[ReuseStats | None, DonorReuseContext | None]: ...

        def _purge_shrunk_chunk_tails(
            self,
            existing_counts: dict[str, int],
            new_counts: dict[str, int],
            *,
            run_control: RunControl = ...,
            checkpoint: VaultRunCheckpoint | None = ...,
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

    @staticmethod
    def _publication_evidence_for_paths(
        ledger: RunLedger,
        compatibility_key: ProofCompatibilityKey,
        paths: Iterable[str],
    ) -> dict[str, ProofEvidence]:
        """Read only named proof rows, respecting SQLite's bounded batch size."""
        ordered = tuple(sorted(paths))
        evidence: dict[str, ProofEvidence] = {}
        for start_at in range(0, len(ordered), FETCH_BATCH):
            evidence.update(
                ledger.publication_evidence_for_paths(
                    compatibility_key,
                    ordered[start_at : start_at + FETCH_BATCH],
                )
            )
        return evidence

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
                checkpoint=work.checkpoint,
                content_identities=work.content_identities,
            )
        )
        self._purge_shrunk_chunk_tails(
            work.existing_counts,
            new_counts,
            run_control=work.run_control,
            checkpoint=work.checkpoint,
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
        classification = _VaultClassification(
            body=classification.body | classification.metadata,
            metadata=set(),
        )

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
                checkpoint=work.checkpoint,
                content_identities=work.content_identities,
            )
        )
        return _VaultReconcileOutcome(
            re_embedded=len(classification.body),
            payload_updated=0,
            reuse=reuse_stats,
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

    def _classify_scoped_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
        docs_dir: pathlib.Path,
        reporter: ProgressReporter,
        run_control: RunControl,
    ) -> tuple[dict[str, pathlib.Path], set[str]]:
        """Resolve watcher paths into vault upsert and deletion identities."""
        to_hash: dict[str, pathlib.Path] = {}
        deletion_candidates: set[str] = set()
        with controlled_phase(reporter, run_control, "scan changed", None):
            for path in changed_paths:
                run_control.checkpoint()
                doc_id = self._vault_doc_id(path, docs_dir)
                if doc_id is not None:
                    if path.is_file() and get_doc_type(path, self.root_dir) is not None:
                        to_hash[doc_id] = path
                    else:
                        deletion_candidates.add(doc_id)
                run_control.checkpoint()
        return to_hash, deletion_candidates

    def _scoped_incremental_locked(
        self,
        *,
        changed_paths: Iterable[pathlib.Path],
        reporter: ProgressReporter,
        authority: RunAuthority,
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
        from .._publication_state import acquire_publication_snapshot
        from .._source_types import PublicSourceType

        snapshot = acquire_publication_snapshot(
            self.root_dir,
            PublicSourceType.VAULT,
        )

        to_hash, deletion_candidates = self._classify_scoped_paths(
            changed_paths,
            docs_dir,
            reporter,
            run_control,
        )

        affected = tuple(sorted(set(to_hash) | deletion_candidates))
        prior_evidence = self._publication_evidence_for_paths(
            snapshot.ledger,
            snapshot.proof.compatibility_key,
            affected,
        )
        prev_meta = {
            doc_id: item.content_identity for doc_id, item in prior_evidence.items()
        }
        delete_ids = deletion_candidates.intersection(prior_evidence)

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
        snapshot.validate()

        checkpoint = VaultRunCheckpoint.open(
            self.root_dir,
            backend_identity=self.store.backend_identity,
            authority=authority,
            operation=RunOperation.SCOPED_INCREMENTAL,
            run_control=run_control,
        )
        if checkpoint.receipt is None:
            raise RuntimeError("vault incremental opened without a publication receipt")

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
            existing_counts = self.store.get_chunk_counts(doc_ids=candidate_ids)
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
                checkpoint=checkpoint,
                content_identities=changed_hashes,
            ),
        )

        with controlled_phase(
            reporter,
            run_control,
            "delete removed",
            len(delete_ids),
        ):
            if delete_ids:
                from ._streaming import execute_store_mutation

                for doc_id in sorted(delete_ids):
                    old = prior_evidence[doc_id]
                    execute_store_mutation(
                        lambda current=doc_id: self.store.delete_documents([current]),
                        checkpoint.deletion_lifecycle(
                            doc_id,
                            CommitUnitKind.DELETE_PATH,
                            old.point_ids,
                        ),
                    )
                    checkpoint.record_confirmed_deletion(doc_id, old.point_ids)
                    reporter.advance(1)

        # Partial read-modify-write: preserve every unchanged entry, refresh
        # the changed hashes, and drop the deleted ids. Never recompute the
        # whole map (that is what the full scan is for).
        with controlled_phase(reporter, run_control, "write metadata", 1):
            checkpoint.publish_proof_transition()
            checkpoint.publish_generation()
            total = checkpoint.ledger.publication_proof(
                checkpoint.receipt.compatibility_key
            ).aggregate.indexed_identities
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
