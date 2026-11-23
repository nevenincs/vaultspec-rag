"""Independent full and incremental indexing for explicitly routed documents."""

from __future__ import annotations

import functools
import json
import logging
import os
import pathlib
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict, Unpack, cast

from .. import store_schema
from .._job_errors import JobError, JobErrorKind
from .._source_types import PublicSourceType
from ..index_profiles import get_index_support_profile
from ..job_control import NO_RUN_CONTROL
from . import _chunk_worker, _preprocess_glue, _stat_gate
from ._checkpoint_common import PublicationExecution, publish_checkpoint
from ._content_discovery import (
    CodeContentDiscovery,
    normalize_changed_paths,
    validate_admitted_sources,
)
from ._content_policy import ContentKind, RootContentPolicy
from ._document_checkpoint import (
    DocumentRunCheckpoint,
    DocumentRunConfiguration,
    DocumentRunOpenRequest,
)
from ._document_file import DocumentFileMetadata
from ._file_state import FileStateKind
from ._generation_lifecycle import CodeGenerationLifecycle
from ._index_lifecycle import (
    IndexLifecycleRequest,
    incremental_mode,
    preprocess_completion_fields,
    run_index_lifecycle,
)
from ._preprocess_config import load_filterable_metadata
from ._preprocess_document_batch import DocumentBatchPreprocessor
from ._route_migration import reconcile_generation_storage, reconcile_scoped_routes
from ._run_ledger_models import (
    FETCH_BATCH,
    CommitUnitKind,
    FinalizationPhase,
    RunAuthority,
    RunLedgerCompatibilityError,
    RunOperation,
)
from ._run_policy import RunPolicy
from ._scan_cache import MembershipScanCache
from ._slicing import iter_weighted_document_slices
from ._source_file import source_file_stat
from ._streaming import (
    _SliceWriter,
    encode_and_upsert_document_slice,
    execute_store_mutation,
)
from ._streaming_types import DocumentSliceRequest, DocumentSliceStreamRequest
from ._vault_prep import (
    IndexResult,
    IndexRunCounts,
    IndexRunTelemetry,
    finished_index_result,
    index_run_started,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping, Sequence

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
    metadata_keys: tuple[store_schema.DeclaredMetadataKey, ...] = ()
    #: Per declared key, the units this run published whose value of that key
    #: no keyword index can match. Filled as files publish.
    non_string_metadata: dict[str, int] = field(default_factory=dict)


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
    publish_readiness: Callable[[pathlib.Path, str], object] | None


@dataclass(frozen=True, slots=True)
class _DocumentIndexerConfig:
    gpu_lock: threading.Lock | None = None
    extra_excludes: list[str] | None = None
    content_policy: RootContentPolicy | None = None
    publish_readiness: Callable[[pathlib.Path, str], object] | None = None


def _note_unmatchable_metadata(
    chunks: list[DocumentChunk],
    declared: tuple[store_schema.DeclaredMetadataKey, ...],
    unmatchable: dict[str, set[int]],
) -> None:
    """Note, per declared key, the units whose value no keyword index matches.

    Units, not chunks: one unit split into several chunks carries one value.
    """
    if not declared:
        return
    for chunk in chunks:
        for key in store_schema.non_string_metadata_keys(
            declared,
            unit_metadata=chunk.payload.unit_metadata.materialize(),
            document_metadata=chunk.payload.document_metadata.materialize(),
        ):
            unmatchable.setdefault(key, set()).add(chunk.payload.unit_ordinal)


def _record_unmatchable_metadata(
    rel_path: str,
    unmatchable: dict[str, set[int]],
    totals: dict[str, int],
) -> None:
    """Warn about one published file's unmatchable values and add to *totals*.

    The value is stored unchanged and the file stays indexed; those units just
    never match a filter on that key, so the count shows the extractor defect.
    """
    for key, units in sorted(unmatchable.items()):
        logger.warning(
            "%s: %d unit(s) hold a non-string value for declared metadata key "
            "%r; they are indexed but never match a filter on that key",
            rel_path,
            len(units),
            key,
        )
        totals[key] = totals.get(key, 0) + len(units)


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
        self._discovery = CodeContentDiscovery(
            self.root_dir,
            content_policy=config.content_policy,
            extra_excludes=config.extra_excludes or (),
        )
        self._publish_readiness = config.publish_readiness
        self._writer_lock = threading.RLock()
        from .._store_writes import workspace_volume_path

        self._data_root = workspace_volume_path(self.root_dir)
        self._stat_gate_path = self._data_root / "document_index.statgate.sqlite3"
        # Resident between runs; every acquire/retain pair runs under
        # ``self._writer_lock``, which is the serialization the cache's
        # single-threaded contract relies on.
        self._stat_gate_cache = _stat_gate.StatEvidenceStore(
            self._stat_gate_path,
            digest=functools.partial(_stat_gate.file_digest, root_dir=self.root_dir),
        )
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

    @classmethod
    def for_preflight(
        cls,
        root_dir: pathlib.Path,
        *,
        extra_excludes: list[str] | None = None,
        content_policy: RootContentPolicy | None = None,
    ) -> DocumentIndexer:
        """Build one indexer for read-only preflight, with no model and no store.

        The only construction path that omits both. ``__init__`` stores
        ``model`` and ``store`` without reading either, and the preflight
        methods resolve policy and walk the tree without reaching them: both
        are read only inside an index run, by donor reuse and the encode
        pipeline. An instance built here must therefore never enter a run -
        it answers ``resolve_policy_snapshot``, ``preflight_content`` and
        ``preflight_changed_paths``, and nothing else.

        The two casts are the whole cost of expressing that. They live here,
        beside the ``__init__`` whose behaviour makes them safe, instead of
        being restated at every caller that wants a model-free preflight.
        """
        return cls(
            root_dir,
            cast("Any", None),
            cast("Any", None),
            extra_excludes=extra_excludes,
            content_policy=content_policy,
        )

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
        from ..memory_probe import held_budget_snapshot

        return held_budget_snapshot(self._memory_budget)

    def reset_memory_telemetry(self) -> None:
        """Clear prior attempt observations under managed worker ownership."""
        self._memory_budget = None

    def resolve_policy_snapshot(self) -> ResolvedIndexPolicy:
        """Resolve the immutable admission and extraction policy for one run."""
        return self._discovery.resolve_policy()

    @staticmethod
    def _ignored_directory(policy: ResolvedIndexPolicy, rel_path: str) -> bool:
        return policy.classify(rel_path).disposition.reason.value == "ignored"

    def _is_canonical_source(self, path: pathlib.Path) -> bool:
        """Return whether *path* is a regular file reached through no link.

        Admission is decided on the name; a link smuggles in an unclassified object.
        """
        try:
            source_file_stat(path, self.root_dir)
        except OSError:
            return False
        return True

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
                if not (
                    disposition.admitted and disposition.kind is ContentKind.DOCUMENT
                ):
                    continue
                path = pathlib.Path(directory) / name
                if self._is_canonical_source(path):
                    discovered.append(path)
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

    def preflight_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> DocumentScopedPreflight:
        """Resolve policy and classify only the exact caller-selected scope."""
        policy = self.resolve_policy_snapshot()
        run_control.checkpoint()
        normalized = normalize_changed_paths(
            self.root_dir, changed_paths, ContentKind.DOCUMENT
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
            validate_admitted_sources(
                self.root_dir,
                authority.policy,
                authority.files,
                ContentKind.DOCUMENT,
                run_control=run_control,
            )
            return authority.policy, authority.files
        if changed_paths is None:
            raise ValueError("scoped document preflight requires changed paths")
        run_control.checkpoint()
        normalized = normalize_changed_paths(
            self.root_dir, changed_paths, ContentKind.DOCUMENT
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

    @staticmethod
    def _extractor_checkpoint(run_control: RunControl) -> Callable[[], None]:
        """Build the no-progress check one extractor invocation polls."""
        from ._run_policy import RunPolicy

        extractor_policy = RunPolicy.from_config(run_control=run_control)
        return lambda: extractor_policy.checkpoint("document extractor polling")

    def _batch_preprocessor(
        self,
        paths: Iterable[pathlib.Path],
        request: _DocumentPublishRequest,
    ) -> DocumentBatchPreprocessor:
        """Group this loop's batch-rule documents into one spawn per group."""
        return DocumentBatchPreprocessor(
            paths,
            self.root_dir,
            request.prep,
            extractor_checkpoint=lambda: self._extractor_checkpoint(
                request.run_control
            ),
            run_control=request.run_control,
        )

    def _publish_file(
        self,
        path: pathlib.Path,
        *,
        request: _DocumentPublishRequest,
        batches: DocumentBatchPreprocessor,
    ) -> tuple[DocumentFileMetadata | None, int, str | None]:
        """Chunk and publish one document, returning durable file evidence."""
        request.run_control.checkpoint()
        request.budget.checkpoint_runtime_resources(f"{path.name} before extraction")
        result = _chunk_worker.stream_document_and_hash_file(
            path,
            self.root_dir,
            _chunk_worker.DocumentChunkingOptions(
                prep=request.prep,
                execution_policy=self._execution_policy(request.policy),
                run_control=request.run_control,
                preprocess_checkpoint=self._extractor_checkpoint(request.run_control),
                batch_result=batches.take(path),
            ),
        )
        if result.preprocess_status == "skipped":
            reason = result.preprocess_reason or "document extraction skipped"
            request.checkpoint.record_processing_failure(
                result.rel_path,
                FileStateKind.EXTRACT_RETRYABLE,
                reason,
                # A source refused before it was read carries no digest.
                content_hash=CodeGenerationLifecycle.checkpoint_content_hash(
                    result.content_hash
                ),
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
        unmatchable: dict[str, set[int]] = {}
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
                    _note_unmatchable_metadata(
                        selected, request.metadata_keys, unmatchable
                    )
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
        _record_unmatchable_metadata(
            result.rel_path, unmatchable, request.non_string_metadata
        )
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
                    mutation_lifecycle=request.checkpoint.mutation_lifecycle(
                        request.unit
                    ),
                )
            )

    def _open_checkpoint(
        self,
        *,
        policy: ResolvedIndexPolicy,
        operation: RunOperation,
        clean: bool,
        limits: SupportProfileLimits,
        execution: PublicationExecution,
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
        checkpoint = DocumentRunCheckpoint.open_generation(
            DocumentRunOpenRequest(
                data_root=self._data_root,
                root_dir=self.root_dir,
                policy=policy,
                run_policy=RunPolicy.from_config(run_control=execution.run_control),
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
                backend_identity=self.store.backend_identity,
                authority=execution.authority,
            )
        )
        self._last_checkpoint = checkpoint
        return checkpoint

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
        policy = checkpoint.policy
        if policy is None:
            raise RuntimeError("document checkpoint has no resolved policy")
        reporter.phase_start("resume document publication", 1)
        try:
            if not checkpoint.ledger.publication_already_committed(
                checkpoint.generation_id
            ):
                reconcile_generation_storage(
                    self.store,
                    checkpoint,
                    policy,
                    ContentKind.DOCUMENT,
                )
            publish_checkpoint(checkpoint, self.root_dir, self._publish_readiness)
            reporter.advance(1)
        finally:
            reporter.phase_end()
        return self._finish_result(started, IndexRunCounts())

    def _finish_result(
        self,
        started: float,
        counts: IndexRunCounts,
        *,
        preprocess_ok: int = 0,
        failures: Sequence[str] = (),
        non_string_metadata: Mapping[str, int] | None = None,
    ) -> IndexResult:
        return finished_index_result(
            started,
            counts,
            IndexRunTelemetry(
                preprocess_ok=preprocess_ok,
                preprocess_failures=failures,
                metadata_non_string=dict(non_string_metadata or {}),
                reuse=self._reuse_snapshot(),
            ),
            model=self.model,
            total=self.store.count_document(),
        )

    def _publish_full_paths(
        self,
        paths: tuple[pathlib.Path, ...],
        request: _DocumentPublishRequest,
    ) -> tuple[_DocumentRunCounts, list[str], dict[str, str]]:
        """Publish a full discovered set into the empty rebuilt collection.

        A path that fails, or whose transform is disabled, publishes nothing:
        the reset discarded its old points, and nothing from before the reset
        may stand in for it. The final mapping carries only the hashes this
        run computed itself.
        """
        counts = _DocumentRunCounts()
        failures: list[str] = []
        fresh_hashes: dict[str, str] = {}
        batches = self._batch_preprocessor(paths, request)
        for path in paths:
            rel = path.relative_to(self.root_dir).as_posix()
            if request.policy.transform_disabled(rel):
                failures.append(request.policy.stale_note(rel))
                continue
            metadata, chunk_count, failure = self._publish_file(
                path,
                request=request,
                batches=batches,
            )
            if failure is not None:
                failures.append(failure)
                continue
            assert metadata is not None
            fresh_hashes[rel] = metadata.content_fingerprint
            counts.added += chunk_count
            if request.policy.match_preprocess(rel) is not None:
                counts.preprocess_ok += 1
        return counts, failures, fresh_hashes

    def _select_incremental_paths(
        self,
        authorized_paths: tuple[pathlib.Path, ...],
        previous_files: dict[str, DocumentFileMetadata],
        *,
        scoped: bool,
    ) -> set[str]:
        """Select the authorized paths whose content differs from committed proof.

        A file event does not imply new bytes: an editor save or a touch
        reports a path whose content is unchanged, and republishing it leaves
        the publication with mutations but no proof change. Every run therefore
        compares content against the committed fingerprint; creates and
        pending replays are always selected.

        An unscoped run sees the full membership, so it prunes gate evidence,
        raises on an unreadable file and selects committed paths that vanished.
        A scoped run sees partial membership: it never prunes, and leaves
        deleted or unreadable event paths selected for the reconcile loop.
        """
        from ._checkpoint_common import publication_replay_paths

        discovered = {
            path.relative_to(self.root_dir).as_posix(): path
            for path in authorized_paths
        }
        known = [
            (rel, path)
            for rel, path in discovered.items()
            if rel in previous_files and (not scoped or path.is_file())
        ]
        with self._stat_gate_cache.acquire() as gate:
            outcome = _stat_gate.hash_paths(gate, known)
            if outcome.failures and not scoped:
                raise outcome.failures[0][1]
            if not scoped:
                gate.prune(discovered.keys())
            gate.persist()
            if gate.reused:
                logger.debug(
                    "stat gate reused %d document hashes, rehashed %d",
                    gate.reused,
                    gate.rehashed,
                )
        replay = publication_replay_paths()
        selected = {
            rel
            for rel in discovered
            if rel not in outcome.hashes
            or outcome.hashes[rel] != previous_files[rel].content_fingerprint
            or rel in replay
        }
        if not scoped:
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
        ordered = [
            (rel, self.root_dir / pathlib.PurePosixPath(rel))
            for rel in sorted(selected)
        ]
        batches = self._batch_preprocessor(
            (
                path
                for rel, path in ordered
                if self._publishable_document(rel, path, request.policy)
            ),
            request,
        )
        for rel, path in ordered:
            # Re-checked at publication: the grouping pass above is advisory,
            # and a path replaced since then must still be refused here.
            if not self._publishable_document(rel, path, request.policy):
                old = current.pop(rel, None)
                if old is not None:
                    execute_store_mutation(
                        lambda ids=old.point_ids: self.store.delete_publication_points(
                            PublicSourceType.DOCUMENT, list(ids)
                        ),
                        request.checkpoint.deletion_lifecycle(
                            rel,
                            CommitUnitKind.DELETE_PATH,
                            old.point_ids,
                        ),
                    )
                    request.checkpoint.record_confirmed_deletion(rel, old.point_ids)
                    counts.removed += len(old.point_ids)
                continue
            if request.policy.transform_disabled(rel):
                failures.append(request.policy.stale_note(rel))
                continue
            old = current.get(rel)
            metadata, chunk_count, failure = self._publish_file(
                path,
                request=request,
                batches=batches,
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

    def _publishable_document(
        self,
        rel: str,
        path: pathlib.Path,
        policy: ResolvedIndexPolicy,
    ) -> bool:
        """Return whether an incremental path is still an admitted document."""
        disposition = policy.classify(rel).disposition
        admitted = disposition.admitted and disposition.kind is ContentKind.DOCUMENT
        return admitted and self._is_canonical_source(path)

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
            execute_store_mutation(
                lambda ids=obsolete_ids: self.store.delete_publication_points(
                    PublicSourceType.DOCUMENT, list(ids)
                ),
                replacement.checkpoint.deletion_lifecycle(
                    replacement.rel,
                    CommitUnitKind.DELETE_STALE,
                    obsolete_ids,
                ),
            )
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
        authority: RunAuthority = RunAuthority.REBUILD,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Rebuild the complete explicitly routed document set from empty.

        Every full run is an explicit rebuild: the old document index is
        discarded before the first replacement write and the rebuild writes
        the one canonical document collection. ``clean`` only labels the
        run's events.
        """
        if authority is not RunAuthority.REBUILD:
            raise PermissionError("a full document index requires rebuild authority")
        started = index_run_started()
        run_control.checkpoint()
        from ._rebuild_lifecycle import capture_reset_epoch
        from ._run_ledger_models import index_run_ledger_path
        from ._run_ledger_runtime import set_aside_unsupported_ledger

        set_aside_unsupported_ledger(index_run_ledger_path(self._data_root))
        began_under = capture_reset_epoch(
            self.store.root_dir,
            PublicSourceType.DOCUMENT,
            self.store.backend_identity,
        )
        policy, paths = self._accept_preflight(
            preflight,
            changed_paths=None,
            run_control=run_control,
        )
        self._resolve_reuse(policy)
        limits = self._support_limits()
        prep = self._preprocess_context(policy, limits)
        with self._writer_lock:
            # Declared before the reset recreates the collection, so its
            # ensure creates the index of each declared key.
            metadata_keys = load_filterable_metadata(self.root_dir)
            self.store.declare_document_metadata_keys(metadata_keys)

            def rebuild() -> IndexResult:
                # Opening and resetting run inside the lifecycle, as for code
                # and vault, so a refused open or a failed reset emits the
                # same started and failed events.
                checkpoint = self._open_checkpoint(
                    policy=policy,
                    operation=RunOperation.FULL,
                    clean=True,
                    limits=limits,
                    execution=PublicationExecution(RunAuthority.REBUILD, run_control),
                )
                checkpoint.reset_for_rebuild(self.store, began_under=began_under)
                with checkpoint.preserve_incomplete_generation():
                    budget = self._begin_resource_budget(limits)
                return self._full_index_locked(
                    paths,
                    started=started,
                    request=_DocumentPublishRequest(
                        policy=policy,
                        prep=prep,
                        budget=budget,
                        checkpoint=checkpoint,
                        reporter=reporter,
                        run_control=run_control,
                        metadata_keys=metadata_keys,
                    ),
                )

            return run_index_lifecycle(
                rebuild,
                IndexLifecycleRequest(
                    event_logger=logger,
                    store=self.store,
                    source="document",
                    mode="full",
                    clean=clean,
                    root=self.root_dir,
                    run_control=run_control,
                    completion_fields=preprocess_completion_fields,
                ),
            )

    def _full_index_locked(
        self,
        paths: tuple[pathlib.Path, ...],
        *,
        started: float,
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
        # Durable per-file writes protect their own mutation boundaries;
        # retain confirmed work when control interrupts the remaining rebuild.
        with checkpoint.preserve_incomplete_generation():
            self.store.ensure_document_table()
            publish_started_ns = time.time_ns()
            counts, failures, fresh_hashes = self._publish_full_paths(
                paths,
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
            if failures:
                checkpoint.mark_failed("; ".join(failures))
            else:
                reconcile_generation_storage(
                    self.store,
                    checkpoint,
                    policy,
                    ContentKind.DOCUMENT,
                )
                publish_checkpoint(checkpoint, self.root_dir, self._publish_readiness)
        return self._finish_result(
            started,
            IndexRunCounts(
                added=counts.added,
                updated=counts.updated,
                files=len(paths),
            ),
            preprocess_ok=counts.preprocess_ok,
            failures=failures,
            non_string_metadata=request.non_string_metadata,
        )

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        preflight: DocumentExecutionPreflight | None = None,
        authority: RunAuthority = RunAuthority.PUBLICATION,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Reconcile changed documents, or discover changes when scope is omitted."""
        started = index_run_started()
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
        previous_files: dict[str, DocumentFileMetadata]
        with self._writer_lock:
            DocumentRunCheckpoint.recover_pending_publication(
                self.root_dir,
                PublicSourceType.DOCUMENT,
                store=self.store,
                run_control=run_control,
                replay_source=lambda: self.incremental_index(
                    reporter=reporter,
                    changed_paths=None,
                    authority=authority,
                    run_control=run_control,
                ),
            )
            from .._publication_state import (
                acquire_publication_snapshot,
                read_all_publication_evidence,
            )

            snapshot = acquire_publication_snapshot(
                self.root_dir,
                PublicSourceType.DOCUMENT,
            )
            if changed_paths is not None:
                rel_paths = tuple(
                    sorted(
                        path.relative_to(self.root_dir).as_posix()
                        for path in authorized_paths
                    )
                )
                previous_files = {}
                for start_at in range(0, len(rel_paths), FETCH_BATCH):
                    evidence = snapshot.ledger.publication_evidence_for_paths(
                        snapshot.proof.compatibility_key,
                        rel_paths[start_at : start_at + FETCH_BATCH],
                    )
                    previous_files.update(
                        {
                            rel: DocumentFileMetadata(
                                rel,
                                item.content_identity,
                                item.point_ids,
                            )
                            for rel, item in evidence.items()
                        }
                    )
            else:
                previous_files = {
                    rel: DocumentFileMetadata(
                        rel,
                        item.content_identity,
                        item.point_ids,
                    )
                    for rel, item in read_all_publication_evidence(snapshot).items()
                }
            live = self.store.count_document()
            snapshot.validate()
            from ._checkpoint_common import publication_replay_paths

            if (
                not publication_replay_paths()
                and live < snapshot.proof.aggregate.retained_points
            ):
                raise JobError(
                    JobErrorKind.FULL_REINDEX_REQUIRED,
                    "document storage is shorter than its canonical proof; request "
                    "an explicit full document reindex",
                )
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
                    execution=PublicationExecution(authority, run_control),
                )
            except RunLedgerCompatibilityError as exc:
                logger.warning("document incremental ledger is incompatible: %s", exc)
                raise JobError(
                    JobErrorKind.FULL_REINDEX_REQUIRED,
                    f"no compatible committed document proof ({exc}); request "
                    "an explicit full document reindex",
                ) from exc

            with checkpoint.preserve_incomplete_generation():
                run_control.checkpoint()
                budget = self._begin_resource_budget(limits)
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
                        metadata_keys=load_filterable_metadata(self.root_dir),
                    ),
                    previous_files=previous_files,
                ),
                IndexLifecycleRequest(
                    event_logger=logger,
                    store=self.store,
                    source="document",
                    mode=incremental_mode(scoped=changed_paths is not None),
                    clean=False,
                    root=self.root_dir,
                    run_control=run_control,
                    completion_fields=preprocess_completion_fields,
                ),
            )

    def _incremental_index_locked(
        self,
        authorized_paths: tuple[pathlib.Path, ...],
        *,
        started: float,
        scoped: bool,
        request: _DocumentPublishRequest,
        previous_files: dict[str, DocumentFileMetadata],
    ) -> IndexResult:
        """Locked implementation of :meth:`incremental_index`."""
        self.store.declare_document_metadata_keys(request.metadata_keys)
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
                if scoped:
                    reconcile_scoped_routes(
                        self.store,
                        checkpoint,
                        ContentKind.DOCUMENT,
                        selected,
                    )
                elif selected:
                    reconcile_generation_storage(
                        self.store,
                        checkpoint,
                        policy,
                        ContentKind.DOCUMENT,
                    )
                publish_checkpoint(checkpoint, self.root_dir, self._publish_readiness)
            return self._finish_result(
                started,
                IndexRunCounts(
                    added=counts.added,
                    updated=counts.updated,
                    removed=counts.removed,
                    files=len(selected),
                ),
                preprocess_ok=counts.preprocess_ok,
                failures=failures,
                non_string_metadata=request.non_string_metadata,
            )
