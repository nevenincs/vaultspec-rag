"""Independent full and incremental indexing for explicitly routed documents."""

from __future__ import annotations

import contextlib
import json
import logging
import os
import pathlib
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, TypedDict, Unpack

from .._job_errors import JobError, JobErrorKind
from ..index_profiles import get_index_support_profile
from ..job_control import NO_RUN_CONTROL
from ..store_runtime import StorageGeometryError
from . import _chunk_worker, _preprocess_glue, _stat_gate
from ._content_policy import ContentKind, RootContentPolicy, SourceProfileVersion
from ._document_checkpoint import DocumentRunCheckpoint, DocumentRunConfiguration
from ._document_meta import (
    DocumentFileMetadata,
    DocumentIndexMetadata,
    document_meta_compatible,
    document_metadata_path,
    read_document_meta,
)
from ._file_state import FileStateKind
from ._index_lifecycle import (
    incremental_mode,
    preprocess_completion_fields,
    run_index_lifecycle,
)
from ._resolved_policy import preprocess_stale_note
from ._route_migration import reconcile_generation_storage
from ._run_ledger_models import (
    FinalizationPhase,
    RunLedgerCompatibilityError,
    RunOperation,
)
from ._run_policy import RunPolicy
from ._scan_cache import MembershipScanCache
from ._streaming import (
    DocumentSliceRequest,
    DocumentSliceStreamRequest,
    _SliceWriter,
    encode_and_upsert_document_slice,
    iter_weighted_document_slices,
)
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    from collections.abc import Iterable

    from .._store_models import DocumentChunk
    from ..embeddings import EmbeddingModel
    from ..index_profiles import SupportProfileLimits
    from ..job_control import RunControl
    from ..memory_probe import MemoryBudget, MemoryBudgetSnapshot
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._preprocess_config import PreprocessContext
    from ._resolved_policy import ResolvedIndexPolicy
    from ._reuse import DonorReuseContext, ReuseStats
    from ._run_ledger_models import CommitUnit

logger = logging.getLogger(__name__)

__all__ = ["DocumentIndexPreflight", "DocumentIndexer", "DocumentScopedPreflight"]


@dataclass(frozen=True, slots=True)
class DocumentIndexPreflight:
    """Read-only document discovery authority for one policy snapshot."""

    root_dir: pathlib.Path
    policy: ResolvedIndexPolicy
    files: tuple[pathlib.Path, ...]


@dataclass(frozen=True, slots=True)
class DocumentScopedPreflight:
    """Read-only authority for one exact set of changed document paths."""

    root_dir: pathlib.Path
    policy: ResolvedIndexPolicy
    changed_paths: tuple[pathlib.Path, ...]


type DocumentExecutionPreflight = DocumentIndexPreflight | DocumentScopedPreflight


@dataclass(slots=True)
class _DocumentResourceBudget:
    """Aggregate document ceilings enforced at each measurable runtime edge."""

    limits: SupportProfileLimits
    rss_ceiling_mib: float | None = None
    cuda_ceiling_mib: float | None = None
    cuda_baseline_mib: float | None = None
    enforce_cuda: bool = True
    generated_chunks: int = 0
    weighted_bytes: int = 0
    extracted_bytes: int = 0
    rss_bytes: int = 0
    cuda_bytes: int = 0
    memory_budget: MemoryBudget = field(init=False)

    def __post_init__(self) -> None:
        from .._units import bytes_to_mib
        from ..memory_probe import MemoryBudget

        rss_ceiling_mib = (
            bytes_to_mib(self.limits.rss_bytes)
            if self.rss_ceiling_mib is None
            else self.rss_ceiling_mib
        )
        cuda_ceiling_mib = (
            bytes_to_mib(self.limits.cuda_bytes)
            if self.cuda_ceiling_mib is None
            else self.cuda_ceiling_mib
        )
        self.memory_budget = MemoryBudget(
            rss_ceiling_mib=rss_ceiling_mib,
            cuda_ceiling_mib=cuda_ceiling_mib if self.enforce_cuda else None,
            cuda_baseline_mib=self.cuda_baseline_mib if self.enforce_cuda else None,
        )

    def reserve(
        self,
        chunks: int,
        weighted_bytes: int,
        extracted_bytes: int,
    ) -> None:
        next_chunks = self.generated_chunks + chunks
        next_weight = self.weighted_bytes + weighted_bytes
        next_extracted = self.extracted_bytes + extracted_bytes
        if next_chunks > self.limits.generated_chunks:
            raise JobError(
                JobErrorKind.CORPUS_LIMIT_EXCEEDED,
                f"document generated_chunks is {next_chunks}; support profile permits "
                f"{self.limits.generated_chunks}",
            )
        if next_weight > self.limits.weighted_bytes:
            raise JobError(
                JobErrorKind.CORPUS_LIMIT_EXCEEDED,
                f"document weighted_bytes is {next_weight}; support profile permits "
                f"{self.limits.weighted_bytes}",
            )
        if next_extracted > self.limits.extracted_bytes:
            raise JobError(
                JobErrorKind.CORPUS_LIMIT_EXCEEDED,
                f"document extracted_bytes is {next_extracted}; support profile "
                f"permits {self.limits.extracted_bytes}",
            )
        self.generated_chunks = next_chunks
        self.weighted_bytes = next_weight
        self.extracted_bytes = next_extracted

    @property
    def snapshot(self) -> MemoryBudgetSnapshot | None:
        """Return the latest enforced resource observation."""
        return self.memory_budget.snapshot

    def checkpoint_runtime_resources(
        self,
        label: str = "document runtime resource checkpoint",
    ) -> None:
        """Enforce peak process and CUDA measurements around document work."""
        try:
            snapshot = self.memory_budget.sample(label)
        except JobError:
            snapshot = self.memory_budget.snapshot
            if snapshot is not None:
                self._retain_snapshot(snapshot)
            raise
        self._retain_snapshot(snapshot)

    def _retain_snapshot(self, snapshot: MemoryBudgetSnapshot) -> None:
        """Ratchet this run's profile-compatible byte counters upward."""
        from ..memory_probe import snapshot_resource_bytes

        rss_bytes, cuda_bytes = snapshot_resource_bytes(snapshot)
        self.rss_bytes = max(self.rss_bytes, rss_bytes)
        self.cuda_bytes = max(self.cuda_bytes, cuda_bytes)

    def record_runtime_resources(
        self,
        *,
        rss_bytes: int,
        cuda_bytes: int,
        cuda_allocated_bytes: int | None = None,
        label: str = "document supplied resource observation",
    ) -> None:
        """Record measured peaks and enforce both independent ceilings."""
        from .._units import bytes_to_mib

        allocated_bytes = (
            cuda_bytes if cuda_allocated_bytes is None else cuda_allocated_bytes
        )
        try:
            snapshot = self.memory_budget.observe(
                label=label,
                rss_mib=bytes_to_mib(rss_bytes),
                cuda_allocated_mib=bytes_to_mib(allocated_bytes),
                cuda_reserved_mib=bytes_to_mib(cuda_bytes),
            )
        except JobError:
            snapshot = self.memory_budget.snapshot
            if snapshot is not None:
                self._retain_snapshot(snapshot)
            raise
        self._retain_snapshot(snapshot)

    def fail_cuda_oom(self, label: str, exc: BaseException) -> None:
        """Translate allocator exhaustion into the admitted typed outcome."""
        self.memory_budget.fail_cuda_oom(label=label, detail=str(exc))


@dataclass(slots=True)
class _DocumentRunCounts:
    """Mutable counters local to one serialized document reconciliation."""

    added: int = 0
    updated: int = 0
    removed: int = 0
    preprocess_ok: int = 0


@dataclass(frozen=True, slots=True)
class _DocumentPublishRequest:
    """Shared authority for publishing one document file."""

    policy: ResolvedIndexPolicy
    prep: PreprocessContext | None
    budget: _DocumentResourceBudget
    checkpoint: DocumentRunCheckpoint
    reporter: ProgressReporter
    run_control: RunControl


@dataclass(frozen=True, slots=True)
class _DocumentSliceWriteRequest:
    """One ordered document-slice publication request."""

    selected: list[DocumentChunk]
    unit: CommitUnit
    ordinal: int
    rel_path: str
    budget: _DocumentResourceBudget
    checkpoint: DocumentRunCheckpoint
    writer: _SliceWriter
    run_control: RunControl
    reuse: DonorReuseContext | None = None
    release_cache: bool = True


@dataclass(frozen=True, slots=True)
class _DocumentResultDetails:
    """Measured output for one document indexing attempt."""

    started: float
    added: int
    updated: int
    removed: int
    files: int
    preprocess_ok: int
    failures: list[str]


@dataclass(frozen=True, slots=True)
class _DocumentMetadataReplacement:
    """One in-memory document manifest replacement after slice publication."""

    current: dict[str, DocumentFileMetadata]
    rel: str
    old: DocumentFileMetadata | None
    metadata: DocumentFileMetadata
    chunk_count: int
    counts: _DocumentRunCounts
    checkpoint: DocumentRunCheckpoint


class _DocumentIndexerOptions(TypedDict, total=False):
    gpu_lock: threading.Lock | None
    extra_excludes: list[str] | None
    content_policy: RootContentPolicy | None


@dataclass(frozen=True, slots=True)
class _DocumentIndexerConfig:
    gpu_lock: threading.Lock | None = None
    extra_excludes: list[str] | None = None
    content_policy: RootContentPolicy | None = None


class DocumentIndexer:
    """Index only paths explicitly admitted to the document domain."""

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        **options: Unpack[_DocumentIndexerOptions],
    ) -> None:
        config = _DocumentIndexerConfig(**options)
        self.root_dir = root_dir.resolve()
        self.model = model
        self.store = store
        self._gpu_lock = config.gpu_lock
        self._extra_excludes = tuple(config.extra_excludes or ())
        self._content_policy = config.content_policy or RootContentPolicy(
            SourceProfileVersion.CONVENTIONAL_V1
        )
        self._writer_lock = threading.RLock()
        from .._store_writes import workspace_volume_path

        self._data_root = workspace_volume_path(self.root_dir)
        self._meta_path = document_metadata_path(self.root_dir)
        self._stat_gate_path = _stat_gate.sidecar_for(self._meta_path)
        # Resident between runs; every acquire/retain pair runs under
        # ``self._writer_lock``, which is the serialization the cache's
        # single-threaded contract relies on.
        self._stat_gate_cache = _stat_gate.ResidentGateCache(self._stat_gate_path)
        # Bounded-staleness cache of the document discovery walk, keyed by
        # policy fingerprint. Scoped runs bypass discovery and invalidate it,
        # because the events they carry are membership truth a cached walk
        # cannot see.
        self._discover_cache: MembershipScanCache[tuple[pathlib.Path, ...]] = (
            MembershipScanCache()
        )
        self._last_checkpoint: DocumentRunCheckpoint | None = None
        self._memory_budget: MemoryBudget | None = None
        # Per-run donor reuse state: resolved once per public run entry and
        # reset there, so a prior run's counters never leak into a later
        # result on this long-lived per-root indexer instance.
        self._reuse_stats: ReuseStats | None = None
        self._donor_reuse: DonorReuseContext | None = None

    def _resolve_reuse(self, policy: ResolvedIndexPolicy) -> None:
        """Resolve this run's donor reuse context, once per index run."""
        from ._donor_candidates import CollectionKind
        from ._reuse import resolve_donor_reuse

        self._reuse_stats, self._donor_reuse = resolve_donor_reuse(
            self.root_dir,
            CollectionKind.DOCUMENT,
            self.store,
            expected_content_epoch=policy.fingerprints_for(
                ContentKind.DOCUMENT
            ).content,
        )

    def _reuse_snapshot(self) -> dict[str, object] | None:
        """Return this run's reuse telemetry block, or ``None`` when off."""
        stats = self._reuse_stats
        return stats.snapshot() if stats is not None else None

    @property
    def last_checkpoint(self) -> DocumentRunCheckpoint | None:
        """Return the latest run authority for service-domain projection."""
        return self._last_checkpoint

    @property
    def memory_budget_snapshot(self) -> MemoryBudgetSnapshot | None:
        """Return the latest immutable enforced-memory observation."""
        budget = self._memory_budget
        return budget.snapshot if budget is not None else None

    def resolve_policy_snapshot(self) -> ResolvedIndexPolicy:
        """Resolve the immutable admission and extraction policy for one run."""
        from ._resolved_policy import IndexPolicyResolutionOptions, resolve_index_policy

        return resolve_index_policy(
            self.root_dir,
            IndexPolicyResolutionOptions(
                content_policy=self._content_policy,
                extra_excludes=self._extra_excludes,
            ),
        )

    @staticmethod
    def _ignored_directory(policy: ResolvedIndexPolicy, rel_path: str) -> bool:
        return policy.classify(rel_path).disposition.reason.value == "ignored"

    def _discover(
        self,
        policy: ResolvedIndexPolicy,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[pathlib.Path, ...]:
        """Return only file paths owned by the document domain."""
        fingerprint = policy.fingerprints.snapshot
        cached = self._discover_cache.get(fingerprint)
        if cached is not None:
            return cached
        discovered: list[pathlib.Path] = []
        root_text = str(self.root_dir)
        for directory, dirs, files in os.walk(self.root_dir, topdown=True):
            run_control.checkpoint()
            rel_dir = os.path.relpath(directory, root_text).replace("\\", "/")
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            dirs[:] = [
                name
                for name in dirs
                if not self._ignored_directory(policy, f"{prefix}{name}/")
            ]
            for name in files:
                run_control.checkpoint()
                rel = f"{prefix}{name}"
                disposition = policy.classify(rel).disposition
                if disposition.admitted and disposition.kind is ContentKind.DOCUMENT:
                    discovered.append(pathlib.Path(directory) / name)
            run_control.checkpoint()
        result = tuple(sorted(discovered, key=lambda path: path.as_posix()))
        self._discover_cache.put(fingerprint, result)
        return result

    def preflight_content(
        self,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> DocumentIndexPreflight:
        """Resolve policy and document discovery before any mutable resource."""
        run_control.checkpoint()
        policy = self.resolve_policy_snapshot()
        # An execution preflight is the membership observation the run it
        # authorizes diffs and publishes claims from, so it must see the tree
        # as it stands now: a cached walk would hide any create or delete
        # since the walk was taken. The fresh walk re-primes the cache, so
        # reads inside the authorized run serve this same observation.
        self._discover_cache.invalidate()
        files = self._discover(policy, run_control=run_control)
        run_control.checkpoint()
        return DocumentIndexPreflight(self.root_dir, policy, files)

    def _normalize_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[pathlib.Path, ...]:
        run_control.checkpoint()
        normalized = {path.resolve() for path in changed_paths}
        if any(not path.is_relative_to(self.root_dir) for path in normalized):
            raise ValueError("document index scope contains a path outside its root")
        run_control.checkpoint()
        return tuple(sorted(normalized, key=lambda path: path.as_posix()))

    def preflight_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> DocumentScopedPreflight:
        """Resolve policy and classify only the exact caller-selected scope."""
        policy = self.resolve_policy_snapshot()
        normalized = self._normalize_changed_paths(
            changed_paths,
            run_control=run_control,
        )
        for path in normalized:
            run_control.checkpoint()
            policy.classify(path.relative_to(self.root_dir).as_posix())
        run_control.checkpoint()
        return DocumentScopedPreflight(self.root_dir, policy, normalized)

    def _accept_preflight(
        self,
        preflight: DocumentExecutionPreflight | None,
        *,
        changed_paths: Iterable[pathlib.Path] | None,
        run_control: RunControl,
    ) -> tuple[ResolvedIndexPolicy, tuple[pathlib.Path, ...]]:
        authority = preflight or (
            self.preflight_content(run_control=run_control)
            if changed_paths is None
            else self.preflight_changed_paths(
                changed_paths,
                run_control=run_control,
            )
        )
        if (
            authority.root_dir != self.root_dir
            or authority.policy.root_dir != self.root_dir
        ):
            raise ValueError("document index preflight belongs to another root")
        if isinstance(authority, DocumentIndexPreflight):
            if changed_paths is not None:
                raise ValueError("full document preflight cannot authorize scoped work")
            if any(
                not path.resolve().is_relative_to(self.root_dir)
                for path in authority.files
            ):
                raise ValueError("document preflight contains a path outside its root")
            for path in authority.files:
                run_control.checkpoint()
                rel = path.relative_to(self.root_dir).as_posix()
                disposition = authority.policy.classify(rel).disposition
                if not (
                    disposition.admitted and disposition.kind is ContentKind.DOCUMENT
                ):
                    raise ValueError("document preflight contains a non-document path")
            return authority.policy, authority.files
        if changed_paths is None:
            raise ValueError("scoped document preflight requires changed paths")
        normalized = self._normalize_changed_paths(
            changed_paths,
            run_control=run_control,
        )
        if normalized != authority.changed_paths:
            raise ValueError("document index scope does not match its preflight")
        return authority.policy, authority.changed_paths

    @staticmethod
    def _support_limits() -> SupportProfileLimits:
        from ..config._settings import get_config

        return get_index_support_profile(get_config().index_support_profile).document

    def _preprocess_context(
        self,
        policy: ResolvedIndexPolicy,
        limits: SupportProfileLimits,
    ) -> PreprocessContext | None:
        return _preprocess_glue.resolve_policy_preprocess_context(
            self.root_dir,
            self._data_root,
            policy,
            max_source_bytes=limits.source_bytes,
        )

    def _begin_resource_budget(
        self,
        limits: SupportProfileLimits,
    ) -> _DocumentResourceBudget:
        """Freeze effective document ceilings and sample before dispatch."""
        from ._resource_ceilings import admit_index_ceilings

        ceilings = admit_index_ceilings(self.model, limits)
        budget = _DocumentResourceBudget(
            limits,
            rss_ceiling_mib=ceilings.rss_ceiling_mib,
            cuda_ceiling_mib=ceilings.cuda_ceiling_mib,
            cuda_baseline_mib=ceilings.cuda_baseline_mib,
            enforce_cuda=ceilings.uses_cuda,
        )
        self._memory_budget = budget.memory_budget
        budget.checkpoint_runtime_resources("before document dispatch")
        return budget

    @staticmethod
    def _execution_policy(
        policy: ResolvedIndexPolicy,
    ) -> _chunk_worker.ChunkExecutionPolicy:
        return _chunk_worker.ChunkExecutionPolicy(
            encoding=policy.decoder.encoding,
            errors=policy.decoder.errors,
            normalize_newlines=policy.decoder.normalize_newlines,
            html_strip=policy.html_strip,
            document_chunk_chars=policy.document_chunking.chunk_chars,
            document_chunk_overlap=policy.document_chunking.chunk_overlap_chars,
        )

    def _publish_file(
        self,
        path: pathlib.Path,
        *,
        request: _DocumentPublishRequest,
    ) -> tuple[DocumentFileMetadata | None, int, str | None]:
        """Chunk and publish one document, returning durable file evidence."""
        from ._run_policy import RunPolicy

        request.run_control.checkpoint()
        request.budget.checkpoint_runtime_resources(f"{path.name} before extraction")
        extractor_policy = RunPolicy.from_config(run_control=request.run_control)
        result = _chunk_worker.stream_document_and_hash_file(
            path,
            self.root_dir,
            _chunk_worker.DocumentChunkingOptions(
                prep=request.prep,
                execution_policy=self._execution_policy(request.policy),
                run_control=request.run_control,
                preprocess_checkpoint=lambda: extractor_policy.checkpoint(
                    "document extractor polling"
                ),
            ),
        )
        if result.preprocess_status == "skipped":
            reason = result.preprocess_reason or "document extraction skipped"
            request.checkpoint.record_processing_failure(
                result.rel_path,
                FileStateKind.EXTRACT_RETRYABLE,
                reason,
                content_hash=result.content_hash,
            )
            return None, 0, f"{result.rel_path}: {reason}"
        from ..config._settings import get_config

        cfg = get_config()
        slice_size = max(1, int(cfg.embedding_batch_size))
        flush_slices = max(1, int(cfg.document_cache_flush_slices))
        weighted_slices = iter_weighted_document_slices(
            DocumentSliceStreamRequest(
                chunks=result.chunks,
                max_chunks=slice_size,
                run_control=request.run_control,
            )
        )
        point_ids: list[str] = []
        request.reporter.phase_start("embed + upsert document chunks", None)
        writer = _SliceWriter(name="document-slice-writer")
        try:
            try:
                iterator = iter(weighted_slices)
                weighted = next(iterator, None)
                ordinal = 0
                while weighted is not None:
                    request.run_control.checkpoint()
                    following = next(iterator, None)
                    selected = list(weighted.chunks)
                    request.budget.reserve(
                        len(selected),
                        weighted.estimated_bytes,
                        sum(
                            len(chunk.payload.content.encode("utf-8"))
                            for chunk in selected
                        ),
                    )
                    request.budget.checkpoint_runtime_resources(
                        f"{result.rel_path} slice-{ordinal} before encode"
                    )
                    unit = request.checkpoint.unit_for(
                        result.rel_path,
                        result.content_hash,
                        ordinal,
                        is_file_end=following is None,
                        point_ids=tuple(chunk.id for chunk in selected),
                    )
                    if not request.checkpoint.slice_committed(unit):
                        self._encode_slice_through_writer(
                            _DocumentSliceWriteRequest(
                                selected=selected,
                                unit=unit,
                                ordinal=ordinal,
                                rel_path=result.rel_path,
                                budget=request.budget,
                                checkpoint=request.checkpoint,
                                writer=writer,
                                run_control=request.run_control,
                                reuse=self._donor_reuse,
                                release_cache=(
                                    following is None
                                    or (ordinal + 1) % flush_slices == 0
                                ),
                            )
                        )
                    point_ids.extend(chunk.id for chunk in selected)
                    request.reporter.advance(len(selected))
                    ordinal += 1
                    weighted = following
            except BaseException:
                writer.abandon()
                raise
            writer.close(run_control=request.run_control)
        finally:
            request.reporter.phase_end()
        if not point_ids:
            request.checkpoint.record_processing_failure(
                result.rel_path,
                FileStateKind.CHUNK_FAILED,
                "document produced no decodable content",
                content_hash=result.content_hash,
            )
            return None, 0, f"{result.rel_path}: document produced no decodable content"
        return (
            DocumentFileMetadata(
                result.rel_path,
                result.content_hash,
                tuple(point_ids),
            ),
            len(point_ids),
            None,
        )

    def _encode_slice_through_writer(
        self,
        request: _DocumentSliceWriteRequest,
    ) -> None:
        """Encode one uncommitted slice and hand its publication to the writer.

        Storage confirmation (the ledger checkpoint and the after-store budget
        sample) runs on the writer thread strictly after the slice's upsert
        returns, in slice order, so a write failure surfaces before this
        file's evidence is treated as durable.
        """
        from ..config._settings import get_config
        from ..memory_probe import record_forward_peaks

        self.store.disk_headroom_preflight(len(request.selected))

        def _after_forward(kind: str) -> None:
            request.run_control.checkpoint()
            request.budget.checkpoint_runtime_resources(
                f"{request.rel_path} slice-{request.ordinal} after-{kind}-forward"
            )
            request.run_control.checkpoint()

        def _on_cuda_oom(exc: BaseException) -> None:
            request.budget.fail_cuda_oom(
                f"{request.rel_path} slice-{request.ordinal} allocator-oom", exc
            )

        def _on_storage_confirmed() -> None:
            request.checkpoint.record_confirmed_slice(request.unit)
            request.budget.checkpoint_runtime_resources(
                f"{request.rel_path} slice-{request.ordinal} after store"
            )

        # Route the lock-bracketed forward captures into this job's own
        # budget so checkpoints enforce the job's demand rather than a
        # process-wide high-water.
        with record_forward_peaks(request.budget.memory_budget.record_forward_peak_mib):
            encode_and_upsert_document_slice(
                DocumentSliceRequest(
                    chunks=request.selected,
                    model=self.model,
                    store=self.store,
                    gpu_lock=self._gpu_lock,
                    release_cache=request.release_cache,
                    encode_batch_size=int(
                        get_config().embedding_document_encode_batch_size
                    ),
                    write_policy=request.checkpoint.run_policy.store_write_policy,
                    on_storage_confirmed=_on_storage_confirmed,
                    after_forward=_after_forward,
                    on_cuda_oom=_on_cuda_oom,
                    run_control=request.run_control,
                    reuse=request.reuse,
                    writer=request.writer,
                )
            )

    def _open_checkpoint(
        self,
        *,
        policy: ResolvedIndexPolicy,
        operation: RunOperation,
        clean: bool,
        limits: SupportProfileLimits,
        run_control: RunControl,
    ) -> DocumentRunCheckpoint:
        """Open one compatible storage-confirmed document generation."""
        from ..config._settings import get_config
        from ..store_schema import effective_sparse_dim

        config = get_config()
        sparse_enabled = bool(config.sparse_enabled)
        sparse_dimension = effective_sparse_dim(self.model)
        model_identity = json.dumps(
            {
                "dense": str(config.embedding_model),
                "sparse": str(config.sparse_model) if sparse_enabled else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        checkpoint = DocumentRunCheckpoint.open(
            data_root=self._data_root,
            root_dir=self.root_dir,
            policy=policy,
            run_policy=RunPolicy.from_config(run_control=run_control),
            operation=operation,
            clean=clean,
            model_identity=model_identity,
            dense_dimensions=int(config.embedding_dimension),
            configuration=DocumentRunConfiguration(
                slice_max_chunks=max(1, int(config.embedding_batch_size)),
                source_bytes=limits.source_bytes,
                generated_chunks=limits.generated_chunks,
                weighted_bytes=limits.weighted_bytes,
                sparse_enabled=sparse_enabled,
                sparse_dimension=sparse_dimension,
                encode_batch_size=int(config.embedding_document_encode_batch_size),
            ),
        )
        self._last_checkpoint = checkpoint
        return checkpoint

    @staticmethod
    def _checkpoint_files(
        checkpoint: DocumentRunCheckpoint,
    ) -> dict[str, DocumentFileMetadata]:
        """Project the carried ledger manifest into document metadata rows."""
        return {
            rel: DocumentFileMetadata(rel, content_hash, point_ids)
            for rel, (content_hash, point_ids) in checkpoint.current_files().items()
        }

    def _resume_pending_finalization(
        self,
        checkpoint: DocumentRunCheckpoint,
        *,
        reporter: ProgressReporter,
        started: float,
    ) -> IndexResult | None:
        """Finish a storage-complete document generation without re-ingestion."""
        if checkpoint.generation.finalization_phase is FinalizationPhase.INGESTING:
            return None
        reporter.phase_start("resume document publication", 1)
        try:
            reconcile_generation_storage(
                self.store,
                checkpoint,
                checkpoint.policy,
                ContentKind.DOCUMENT,
            )
            checkpoint.publish_metadata(self._meta_path)
            checkpoint.publish_generation()
            reporter.advance(1)
        finally:
            reporter.phase_end()
        return self._finish_result(
            _DocumentResultDetails(started, 0, 0, 0, 0, 0, []),
        )

    def _finish_result(
        self,
        details: _DocumentResultDetails,
    ) -> IndexResult:
        return IndexResult(
            total=self.store.count_document(),
            added=details.added,
            updated=details.updated,
            removed=details.removed,
            duration_ms=int((time.monotonic() - details.started) * 1000),
            device=str(getattr(self.model, "device", "unknown")),
            files=details.files,
            preprocess_ok=details.preprocess_ok,
            preprocess_skipped=len(details.failures),
            preprocess_failures=details.failures,
            reuse=self._reuse_snapshot(),
        )

    def _publish_full_paths(
        self,
        paths: tuple[pathlib.Path, ...],
        previous_files: dict[str, DocumentFileMetadata],
        request: _DocumentPublishRequest,
    ) -> tuple[
        list[DocumentFileMetadata], _DocumentRunCounts, list[str], dict[str, str]
    ]:
        """Publish a full discovered set while retaining failed prior points.

        The final mapping carries only the hashes this run computed itself -
        retained prior rows are excluded, because a carried hash cannot be
        honestly bound to the file's current stat identity.
        """
        published: list[DocumentFileMetadata] = []
        counts = _DocumentRunCounts()
        failures: list[str] = []
        fresh_hashes: dict[str, str] = {}
        for path in paths:
            rel = path.relative_to(self.root_dir).as_posix()
            if request.policy.transform_disabled(rel):
                retained = previous_files.get(rel)
                if retained is not None:
                    published.append(retained)
                failures.append(preprocess_stale_note(rel))
                continue
            metadata, chunk_count, failure = self._publish_file(
                path,
                request=request,
            )
            if failure is not None:
                failures.append(failure)
                retained = previous_files.get(rel)
                if retained is not None:
                    published.append(retained)
                continue
            assert metadata is not None
            published.append(metadata)
            fresh_hashes[rel] = metadata.content_fingerprint
            if rel in previous_files:
                counts.updated += chunk_count
            else:
                counts.added += chunk_count
            if request.policy.match_preprocess(rel) is not None:
                counts.preprocess_ok += 1
        return published, counts, failures, fresh_hashes

    def _reconcile_full_stale(
        self,
        previous_files: dict[str, DocumentFileMetadata],
        published: Iterable[DocumentFileMetadata],
        checkpoint: DocumentRunCheckpoint,
    ) -> int:
        """Delete and checkpoint points absent from the replacement manifest."""
        published_by_path = {item.source_path: item for item in published}
        removed = 0
        for rel, old in previous_files.items():
            current = published_by_path.get(rel)
            if current is None:
                stale_ids = old.point_ids
            else:
                stale_ids = tuple(sorted(set(old.point_ids) - set(current.point_ids)))
            if not stale_ids:
                continue
            self.store.delete_document_content_chunks(list(stale_ids))
            if current is None:
                checkpoint.record_confirmed_deletion(rel, stale_ids)
            else:
                checkpoint.record_confirmed_stale_deletion(rel, stale_ids)
            removed += len(stale_ids)
        return removed

    def _select_incremental_paths(
        self,
        authorized_paths: tuple[pathlib.Path, ...],
        previous_files: dict[str, DocumentFileMetadata],
        *,
        scoped: bool,
    ) -> set[str]:
        """Select changed/deleted paths without conflating scoped discovery."""
        discovered = {
            path.relative_to(self.root_dir).as_posix(): path
            for path in authorized_paths
        }
        if scoped:
            return set(discovered)
        # The unscoped selection sees the full discovered membership, so it
        # both consults the stat-evidence gate and prunes its evidence for
        # files that no longer exist.
        gate = self._stat_gate_cache.acquire()
        outcome = _stat_gate.hash_paths(
            gate,
            [(rel, path) for rel, path in discovered.items() if rel in previous_files],
        )
        if outcome.failures:
            # The ungated selection raised on the first unreadable file;
            # surface the same failure rather than silently deselecting it.
            raise outcome.failures[0][1]
        selected = {
            rel
            for rel in discovered
            if rel not in previous_files
            or outcome.hashes[rel] != previous_files[rel].content_fingerprint
        }
        gate.prune(discovered.keys())
        gate.persist()
        self._stat_gate_cache.retain(gate)
        if gate.reused:
            logger.debug(
                "stat gate reused %d document hashes, rehashed %d",
                gate.reused,
                gate.rehashed,
            )
        selected.update(set(previous_files) - set(discovered))
        return selected

    def _reconcile_incremental_paths(
        self,
        selected: set[str],
        previous_files: dict[str, DocumentFileMetadata],
        request: _DocumentPublishRequest,
    ) -> tuple[dict[str, DocumentFileMetadata], _DocumentRunCounts, list[str]]:
        """Apply one selected incremental set under the document writer lock."""
        current = dict(previous_files)
        counts = _DocumentRunCounts()
        failures: list[str] = []
        for rel in sorted(selected):
            path = self.root_dir / pathlib.PurePosixPath(rel)
            disposition = request.policy.classify(rel).disposition
            admitted = disposition.admitted and disposition.kind is ContentKind.DOCUMENT
            if not path.is_file() or not admitted:
                old = current.pop(rel, None)
                if old is not None:
                    self.store.delete_document_content_chunks(list(old.point_ids))
                    request.checkpoint.record_confirmed_deletion(rel, old.point_ids)
                    counts.removed += len(old.point_ids)
                continue
            if request.policy.transform_disabled(rel):
                failures.append(preprocess_stale_note(rel))
                continue
            old = current.get(rel)
            metadata, chunk_count, failure = self._publish_file(
                path,
                request=request,
            )
            if failure is not None:
                failures.append(failure)
                continue
            assert metadata is not None
            current[rel] = metadata
            self._replace_incremental_metadata(
                _DocumentMetadataReplacement(
                    current,
                    rel,
                    old,
                    metadata,
                    chunk_count,
                    counts,
                    request.checkpoint,
                )
            )
            if request.policy.match_preprocess(rel) is not None:
                counts.preprocess_ok += 1
        return current, counts, failures

    def _replace_incremental_metadata(
        self,
        replacement: _DocumentMetadataReplacement,
    ) -> None:
        """Replace one file generation and account for obsolete points."""
        replacement.current[replacement.rel] = replacement.metadata
        obsolete = set(replacement.old.point_ids if replacement.old else ()) - set(
            replacement.metadata.point_ids
        )
        if obsolete:
            obsolete_ids = tuple(sorted(obsolete))
            self.store.delete_document_content_chunks(list(obsolete_ids))
            replacement.checkpoint.record_confirmed_stale_deletion(
                replacement.rel, obsolete_ids
            )
            replacement.counts.removed += len(obsolete)
        if replacement.old is None:
            replacement.counts.added += replacement.chunk_count
        else:
            replacement.counts.updated += replacement.chunk_count

    def full_index(
        self,
        *,
        clean: bool = False,
        reporter: ProgressReporter,
        preflight: DocumentIndexPreflight | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Reconcile the complete explicitly routed document set."""
        started = time.monotonic()
        policy, paths = self._accept_preflight(
            preflight,
            changed_paths=None,
            run_control=run_control,
        )
        self._resolve_reuse(policy)
        limits = self._support_limits()
        prep = self._preprocess_context(policy, limits)
        preprocessing_disabled = any(
            policy.transform_disabled(path.relative_to(self.root_dir).as_posix())
            for path in paths
        )
        effective_clean = clean and not preprocessing_disabled
        checkpoint = self._open_checkpoint(
            policy=policy,
            operation=RunOperation.FULL,
            clean=effective_clean,
            limits=limits,
            run_control=run_control,
        )
        with checkpoint.preserve_incomplete_generation():
            budget = self._begin_resource_budget(limits)
        with self._writer_lock:
            return run_index_lifecycle(
                lambda: self._full_index_locked(
                    paths,
                    started=started,
                    effective_clean=effective_clean,
                    request=_DocumentPublishRequest(
                        policy=policy,
                        prep=prep,
                        budget=budget,
                        checkpoint=checkpoint,
                        reporter=reporter,
                        run_control=run_control,
                    ),
                ),
                event_logger=logger,
                store=self.store,
                source="document",
                mode="full",
                clean=clean,
                root=self.root_dir,
                run_control=run_control,
                completion_fields=preprocess_completion_fields,
            )

    def _full_index_locked(
        self,
        paths: tuple[pathlib.Path, ...],
        *,
        started: float,
        effective_clean: bool,
        request: _DocumentPublishRequest,
    ) -> IndexResult:
        """Locked implementation of :meth:`full_index`."""
        policy = request.policy
        checkpoint = request.checkpoint
        reporter = request.reporter
        resumed = self._resume_pending_finalization(
            checkpoint,
            reporter=reporter,
            started=started,
        )
        if resumed is not None:
            return resumed
        previous = read_document_meta(self._meta_path)
        previous_files = self._checkpoint_files(checkpoint)
        if not previous_files and previous is not None:
            previous_files = {item.source_path: item for item in previous.files}
        clean_has_confirmed_units = (
            effective_clean
            and next(
                checkpoint.ledger.iter_units(checkpoint.generation_id),
                None,
            )
            is not None
        )
        publication_span = (
            checkpoint.run_policy.protected("clean document publication")
            if effective_clean
            else contextlib.nullcontext()
        )
        with checkpoint.preserve_incomplete_generation(), publication_span:
            # A clean rebuild replaces in place: every discovered file is
            # republished over its live points and the stale remainder is
            # purged only after the run proves itself, so an interruption at
            # any instant leaves the previous complete collection answering
            # searches under a manifest that still describes it. Dropping
            # first would convert every interruption into a served husk
            # under a full claim. The one recreation left is a stored
            # geometry this configuration cannot write into, where in-place
            # replacement is physically impossible and the old points were
            # unservable for this configuration anyway.
            try:
                self.store.ensure_document_table()
            except StorageGeometryError:
                if not effective_clean or clean_has_confirmed_units:
                    raise
                logger.warning(
                    "document collection geometry cannot hold this "
                    "configuration; recreating it for the clean rebuild",
                )
                self.store.drop_document_table()
                self.store.ensure_document_table()
            publish_started_ns = time.time_ns()
            published, counts, failures, fresh_hashes = self._publish_full_paths(
                paths,
                previous_files=previous_files,
                request=request,
            )
            # Bank the hashes this run computed as stat evidence so the first
            # incremental after a full rebuild answers unchanged files from a
            # stat. Pruned to the full discovered membership, which this run
            # is by construction.
            _stat_gate.record_computed_hashes(
                self._stat_gate_cache,
                (
                    (rel, self.root_dir / pathlib.PurePosixPath(rel), content_hash)
                    for rel, content_hash in fresh_hashes.items()
                ),
                computed_not_before_ns=publish_started_ns,
                keep={path.relative_to(self.root_dir).as_posix() for path in paths},
            )
            removed = self._reconcile_full_stale(
                previous_files,
                published,
                checkpoint,
            )
            if failures:
                checkpoint.mark_failed("; ".join(failures))
            else:
                reconcile_generation_storage(
                    self.store,
                    checkpoint,
                    policy,
                    ContentKind.DOCUMENT,
                )
                checkpoint.publish_metadata(self._meta_path)
                checkpoint.publish_generation()
        return self._finish_result(
            _DocumentResultDetails(
                started,
                counts.added,
                counts.updated,
                removed,
                len(paths),
                counts.preprocess_ok,
                failures,
            ),
        )

    def _published_evidence_lost(self, previous: DocumentIndexMetadata) -> bool:
        """Return whether the store fails to back the carried manifest.

        The manifest outlives the points it describes: destruction drops the
        collection or part of it and leaves the sidecar behind, and an
        incremental diff against that manifest then classifies every
        surviving file as unchanged, skips all encoding, and reports success
        over points that are no longer there. A complete manifest whose
        claimed breadth exceeds the live count is therefore escalated to a
        full failure-safe reconciliation - the same non-destructive rebuild
        the compatibility check chooses - instead of being trusted.

        An incomplete manifest claims nothing to hold the store to, and a
        store that cannot be counted proves nothing about the collection
        either way; both keep the ordinary incremental behaviour rather than
        rebuilding on ignorance.
        """
        if not previous.complete:
            return False
        claimed = previous.claimed_points
        try:
            live = self.store.count_document()
        except (OSError, RuntimeError):
            logger.warning(
                "Could not count the document collection to verify published "
                "breadth; trusting the carried manifest for this run",
                exc_info=True,
            )
            return False
        if live >= claimed:
            return False
        logger.warning(
            "Document collection holds %d of the %d points its published "
            "manifest describes; escalating to a full failure-safe "
            "reconciliation instead of trusting the carried evidence",
            live,
            claimed,
        )
        return True

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        preflight: DocumentExecutionPreflight | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Reconcile changed documents, or discover changes when scope is omitted."""
        started = time.monotonic()
        if changed_paths is not None:
            # A scoped run bypasses discovery, but the creates, deletes, and
            # renames it carries are membership truth a cached walk cannot
            # see; dropping the cache keeps staleness bounded by the events
            # actually observed rather than only by the TTL.
            self._discover_cache.invalidate()
        policy, authorized_paths = self._accept_preflight(
            preflight,
            changed_paths=changed_paths,
            run_control=run_control,
        )
        self._resolve_reuse(policy)
        limits = self._support_limits()
        prep = self._preprocess_context(policy, limits)
        fingerprints = policy.fingerprints_for(ContentKind.DOCUMENT)
        with self._writer_lock:
            previous = read_document_meta(self._meta_path)
            if not document_meta_compatible(
                previous,
                membership_fingerprint=fingerprints.membership,
                content_fingerprint=fingerprints.content,
            ):
                previous = None
            if previous is not None and self._published_evidence_lost(previous):
                previous = None
        checkpoint: DocumentRunCheckpoint | None = None
        if previous is not None:
            operation = (
                RunOperation.SCOPED_INCREMENTAL
                if changed_paths is not None
                else RunOperation.INCREMENTAL
            )
            try:
                checkpoint = self._open_checkpoint(
                    policy=policy,
                    operation=operation,
                    clean=False,
                    limits=limits,
                    run_control=run_control,
                )
            except RunLedgerCompatibilityError:
                # The manifest is trustworthy and the store still backs it,
                # but the ledger holds no generation the run can build on -
                # nothing to resume, nothing to diff against. That is the
                # same "no usable published evidence" the checks above
                # escalate for, so it converges on the same rebuild rather
                # than failing every incremental until someone intervenes.
                logger.info(
                    "No compatible published document manifest; running a "
                    "full failure-safe reconciliation"
                )
        if previous is None or checkpoint is None:
            return self.full_index(
                reporter=reporter,
                preflight=DocumentIndexPreflight(
                    self.root_dir,
                    policy,
                    self._discover(policy, run_control=run_control),
                ),
                run_control=run_control,
            )

        with checkpoint.preserve_incomplete_generation():
            budget = self._begin_resource_budget(limits)
        with self._writer_lock:
            return run_index_lifecycle(
                lambda: self._incremental_index_locked(
                    authorized_paths,
                    started=started,
                    scoped=changed_paths is not None,
                    request=_DocumentPublishRequest(
                        policy=policy,
                        prep=prep,
                        budget=budget,
                        checkpoint=checkpoint,
                        reporter=reporter,
                        run_control=run_control,
                    ),
                    previous=previous,
                ),
                event_logger=logger,
                store=self.store,
                source="document",
                mode=incremental_mode(scoped=changed_paths is not None),
                clean=False,
                root=self.root_dir,
                run_control=run_control,
                completion_fields=preprocess_completion_fields,
            )

    def _incremental_index_locked(
        self,
        authorized_paths: tuple[pathlib.Path, ...],
        *,
        started: float,
        scoped: bool,
        request: _DocumentPublishRequest,
        previous: DocumentIndexMetadata,
    ) -> IndexResult:
        """Locked implementation of :meth:`incremental_index`."""
        policy = request.policy
        checkpoint = request.checkpoint
        reporter = request.reporter
        resumed = self._resume_pending_finalization(
            checkpoint,
            reporter=reporter,
            started=started,
        )
        if resumed is not None:
            return resumed
        previous_files = self._checkpoint_files(checkpoint)
        if not previous_files:
            previous_files = {item.source_path: item for item in previous.files}
        selected = self._select_incremental_paths(
            authorized_paths,
            previous_files,
            scoped=scoped,
        )

        with checkpoint.preserve_incomplete_generation():
            _current, counts, failures = self._reconcile_incremental_paths(
                selected,
                previous_files=previous_files,
                request=request,
            )
            if failures:
                checkpoint.mark_failed("; ".join(failures))
            else:
                reconcile_generation_storage(
                    self.store,
                    checkpoint,
                    policy,
                    ContentKind.DOCUMENT,
                )
                checkpoint.publish_metadata(self._meta_path)
                checkpoint.publish_generation()
            return self._finish_result(
                _DocumentResultDetails(
                    started,
                    counts.added,
                    counts.updated,
                    counts.removed,
                    len(selected),
                    counts.preprocess_ok,
                    failures,
                ),
            )
