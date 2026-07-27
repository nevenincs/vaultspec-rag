"""Source-code indexing orchestration.

Walks the project tree with gitignore-aware pruning, chunks files via
tree-sitter ASTs (or a text-splitter fallback), embeds, and upserts code
chunks, tracking content hashes for incremental re-indexing.
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import pathlib
import queue
import time
from functools import partial
from typing import TYPE_CHECKING, NamedTuple

from .._atomic_write import write_json_atomically
from .._index_breadth import PUBLISHED_FILES_KEY, PUBLISHED_POINTS_KEY
from .._job_errors import JobError, JobErrorKind
from .._store_models import (
    generation_code_collection,
    publish_generation_as_served,
)
from ..index_profiles import (
    SupportMeasurement,
    SupportProfileLimits,
    get_index_support_profile,
)
from ..job_control import NO_RUN_CONTROL, RunControlSignal
from . import _chunk_worker, _code_meta, _preprocess_glue
from ._chunk_producer import (
    CONTROL_POLL_SECONDS,
    CodeChunkProducer,
    WeightedCodeSegmentQueue,
    drain_code_chunks,
)
from ._code_meta import (
    CODE_EMBED_SCHEMA,
    CONTENT_EPOCH_KEY,
    EMBED_SCHEMA_KEY,
    MEMBERSHIP_EPOCH_KEY,
)
from ._content_discovery import (
    DEFAULT_SCAN_SAMPLE_LIMIT as _DEFAULT_SCAN_SAMPLE_LIMIT,
)
from ._content_discovery import (
    CodeContentDiscovery,
    CodeExecutionPreflight,
    CodeIndexPreflight,
    CodeScopedPreflight,
    ContentScanResult,
)
from ._content_policy import (
    ClassifiedContent,
    ContentKind,
    RootContentPolicy,
    SourceProfileVersion,
)
from ._file_state import FileStateKind
from ._generation_lifecycle import CodeGenerationLifecycle
from ._index_lifecycle import preprocess_completion_fields, run_index_lifecycle
from ._route_migration import reconcile_generation_storage
from ._run_checkpoint import CodeRunCheckpoint, CodeRunConfiguration
from ._run_ledger import (
    CommitUnitKind,
    RunLedgerCompatibilityError,
    RunOperation,
)
from ._streaming import (
    CodeFileSegment,
    WeightedCodeSlice,
    _release_cuda_cache,
    encode_and_upsert_code_slice,
    iter_code_file_segments,
    iter_weighted_code_slices,
)
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    import threading
    from collections.abc import Callable, Iterable, Iterator

    from ..embeddings import EmbeddingModel
    from ..job_control import RunControl
    from ..memory_probe import MemoryBudget, MemoryBudgetSnapshot, MemoryProbe
    from ..progress import ProgressReporter
    from ..store import VaultStore
    from ._chunk_worker import FileChunkResult
    from ._preprocess_config import (
        PreprocessContext,
    )
    from ._resolved_policy import ResolvedIndexPolicy
    from ._reuse import DonorReuseContext, ReuseStats
    from ._run_policy import RunPolicy

logger = logging.getLogger(__name__)

# Upper bound on how long pipeline shutdown waits for the GPU consumer thread
# to drain its final batch and terminate. Generous enough for any healthy
# final encode (a couple of slices) yet finite, so a wedged CUDA/Qdrant call
# escalates to a raised error instead of hanging the producer and holding the
# indexer's writer lock forever (#155).
_CONSUMER_SHUTDOWN_TIMEOUT_S = 300.0

#: Conservative chunks-per-file factor for the pre-pool disk pre-flight;
#: a measured large mixed-language tree averaged ~12 chunks per source file.
_CHUNKS_PER_FILE_ESTIMATE = 12

# The digest a zero-byte source hashes to. Comparing against it identifies an
# empty read exactly, from the hash the chunk worker already returned, without
# re-reading a file that may still be mid-write.
_EMPTY_SOURCE_DIGEST = hashlib.blake2b(b"").hexdigest()


class _UnsettledCodeConsumerError(RuntimeError):
    """The code consumer remained live after its bounded shutdown wait."""


class _CodePipelineLimits(NamedTuple):
    """Frozen weighted limits shared by code-index producers and consumer."""

    segment_max_chunks: int
    segment_max_bytes: int
    queue_max_chunks: int
    queue_max_bytes: int
    slice_max_chunks: int
    slice_max_bytes: int
    dense_dimension: int
    sparse_enabled: bool
    sparse_dimension: int
    encode_batch_size: int
    flush_slices: int

    @property
    def run_configuration(self) -> CodeRunConfiguration:
        """Project the limits a resumed generation must be compatible with."""
        return CodeRunConfiguration(
            segment_max_chunks=self.segment_max_chunks,
            segment_max_bytes=self.segment_max_bytes,
            queue_max_chunks=self.queue_max_chunks,
            queue_max_bytes=self.queue_max_bytes,
            slice_max_chunks=self.slice_max_chunks,
            slice_max_bytes=self.slice_max_bytes,
            sparse_enabled=self.sparse_enabled,
            sparse_dimension=self.sparse_dimension,
            encode_batch_size=self.encode_batch_size,
            flush_slices=self.flush_slices,
        )


class CodebaseIndexer:
    """Orchestrates source code indexing into the vector store.

    Walks the project tree with ``.gitignore``-aware pruning, chunks source
    files using tree-sitter AST analysis when a grammar is available or
    ``TextSplitter`` as a fallback, generates dense and sparse embeddings,
    and upserts the results into Qdrant. Supports 16+ languages via
    tree-sitter grammars and incremental indexing using blake2b content
    hashing to skip unchanged files.
    """

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        *,
        gpu_lock: threading.Lock | None = None,
        extra_excludes: list[str] | None = None,
        content_policy: RootContentPolicy | None = None,
    ) -> None:
        """Initialize the codebase indexer.

        Args:
            root_dir: Path to the project root directory to index.
            model: Embedding model used to encode code chunks.
            store: Vector store where indexed code chunks are
                persisted.
            gpu_lock: Optional ``threading.Lock`` that serializes
                GPU operations (encoding) with concurrent searches.
            extra_excludes: Additional gitignore-syntax exclusion
                patterns (e.g. from CLI ``--exclude``). Merged into
                the ``.vaultragignore`` spec.
            content_policy: Caller-authored content ownership policy. The
                versioned conventional source profile is used when omitted.
        """
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._gpu_lock = gpu_lock
        self._extra_excludes = extra_excludes or []
        self._content_policy = content_policy or RootContentPolicy(
            SourceProfileVersion.CONVENTIONAL_V1
        )
        # Discovery is fully determined by the three inputs above and holds no
        # per-run state, so one instance serves every operation on this root.
        self._discovery = CodeContentDiscovery(
            self.root_dir,
            content_policy=self._content_policy,
            extra_excludes=self._extra_excludes,
        )
        # Indexer-level writer lock that serializes full_index and
        # incremental_index against each other on the same instance,
        # preventing a concurrent reindex race.
        import threading as _threading

        self._writer_lock: _threading.Lock = _threading.Lock()
        from ..config import get_config

        cfg = get_config()
        self._data_root = root_dir / cfg.data_dir
        self._meta_path = self._data_root / cfg.code_index_metadata_file
        # Per-run document-preprocessing state (#185). Both are reset at the
        # start of each full/incremental run; the writer lock serialises runs
        # so instance-scoped state is safe. ``_prep_ctx`` is the context handed
        # to chunk workers; ``_prep_skips`` accumulates "rel_path: reason" for
        # files a preprocess rule skipped and ``_prep_ok`` counts rule-fed
        # files, both surfaced in the run's IndexResult.
        self._prep_ctx: PreprocessContext | None = None
        self._chunk_execution_policy = _chunk_worker.ChunkExecutionPolicy()
        # Production reads the preprocess context through a callable because
        # ``_prep_ctx`` is rebound per run; capturing the value here would pin
        # every run to whatever the first one resolved.
        self._producer = CodeChunkProducer(
            self.root_dir,
            chunk_execution_policy=self._chunk_execution_policy,
            prep_ctx=lambda: self._prep_ctx,
        )
        self._prep_skips: list[str] = []
        self._prep_stale_paths: set[str] = set()
        self._prep_rule_total: int = 0
        self._prep_ok: int = 0
        # Config epochs for the current run. Set at the start of each
        # locked run from the same resolved inputs the scan uses, then stamped
        # by ``_write_meta``; ``None`` means "not yet resolved this run" and the
        # writer recomputes them as a fallback.
        self._membership_epoch: str | None = None
        self._content_epoch: str | None = None
        # Per-run donor reuse state: resolved once when the encode pipeline
        # starts and cleared at the start of every public run so an earlier
        # run's counters can never leak into a later result.
        self._reuse_stats: ReuseStats | None = None
        self._donor_reuse: DonorReuseContext | None = None
        self._resolved_policy: ResolvedIndexPolicy | None = None
        self._support_measurement = SupportMeasurement(0, 0)
        self._support_limits: SupportProfileLimits | None = None
        self._support_profile_name: str | None = None
        self._lifecycle = CodeGenerationLifecycle(
            self.root_dir,
            data_root=self._data_root,
            meta_path=self._meta_path,
            store=self.store,
            load_meta=self._load_meta,
            read_meta_raw=self._read_meta_raw,
        )
        self._memory_budget: MemoryBudget | None = None

    @property
    def support_measurement(self) -> SupportMeasurement:
        """Return the latest immutable code workload measurement snapshot."""
        return self._support_measurement

    @property
    def last_checkpoint(self) -> CodeRunCheckpoint | None:
        """Return the latest run authority for service-domain projection."""
        return self._lifecycle.last_checkpoint

    @property
    def memory_budget_snapshot(self) -> MemoryBudgetSnapshot | None:
        """Return the latest immutable enforced-memory observation."""
        budget = self._memory_budget
        return budget.snapshot if budget is not None else None

    def _begin_memory_budget(self) -> None:
        """Freeze and sample one production memory budget before dispatch."""
        from ..memory_probe import MemoryBudget
        from ._resource_ceilings import admit_index_ceilings

        ceilings = admit_index_ceilings(self.model, self._support_limits)
        self._memory_budget = MemoryBudget(
            rss_ceiling_mb=ceilings.rss_ceiling_mb,
            cuda_ceiling_mb=ceilings.enforced_cuda_ceiling_mb,
            cuda_baseline_mb=ceilings.cuda_baseline_mb,
        )
        self._sample_memory_budget("before code dispatch")

    def _forward_peak_recording(self) -> contextlib.AbstractContextManager[None]:
        """Route this thread's forward-peak captures into the job budget."""
        from ..memory_probe import record_forward_peaks

        budget = self._memory_budget
        if budget is None:
            return contextlib.nullcontext()
        return record_forward_peaks(budget.record_forward_peak_mb)

    def _sample_memory_budget(self, label: str) -> MemoryBudgetSnapshot:
        """Enforce the current budget and retain its resource high-water."""
        from ..memory_probe import snapshot_resource_bytes

        budget = self._memory_budget
        if budget is None:
            raise RuntimeError("code memory budget was not admitted")
        snapshot = budget.sample(label)
        rss_bytes, cuda_bytes = snapshot_resource_bytes(snapshot)
        self._record_resource_measurement(
            rss_bytes=rss_bytes,
            cuda_bytes=cuda_bytes,
        )
        return snapshot

    def _fail_cuda_oom(self, label: str, exc: BaseException) -> None:
        """Translate allocator exhaustion through the admitted budget latch."""
        budget = self._memory_budget
        if budget is None:
            raise RuntimeError("code memory budget was not admitted") from exc
        budget.fail_cuda_oom(label=label, detail=str(exc))

    def _begin_support_measurement(
        self,
        paths: Iterable[pathlib.Path],
    ) -> None:
        """Measure source dimensions by streaming path metadata only."""
        from ..config import get_config

        source_files = 0
        source_bytes = 0
        for path in paths:
            source_files += 1
            source_bytes += path.stat().st_size
        profile = get_index_support_profile(get_config().index_support_profile)
        self._support_limits = profile.code
        self._support_profile_name = profile.name
        self._set_support_measurement(
            SupportMeasurement(
                source_files=source_files,
                source_bytes=source_bytes,
                queue_bytes=int(get_config().index_queue_max_bytes),
            )
        )

    def _record_extracted_bytes(self, extracted_bytes: int) -> None:
        """Add extractor output bytes without retaining output beyond one file."""
        if extracted_bytes <= 0:
            return
        current = self.support_measurement
        self._set_support_measurement(
            SupportMeasurement(
                source_files=current.source_files,
                source_bytes=current.source_bytes,
                generated_chunks=current.generated_chunks,
                weighted_bytes=current.weighted_bytes,
                extracted_bytes=current.extracted_bytes + extracted_bytes,
                queue_bytes=current.queue_bytes,
                rss_bytes=current.rss_bytes,
                cuda_bytes=current.cuda_bytes,
            )
        )

    def _record_resource_measurement(
        self,
        *,
        rss_bytes: int,
        cuda_bytes: int,
    ) -> None:
        """Merge observed process and CUDA high-water dimensions."""
        current = self.support_measurement
        self._set_support_measurement(
            SupportMeasurement(
                source_files=current.source_files,
                source_bytes=current.source_bytes,
                generated_chunks=current.generated_chunks,
                weighted_bytes=current.weighted_bytes,
                extracted_bytes=current.extracted_bytes,
                queue_bytes=current.queue_bytes,
                rss_bytes=max(current.rss_bytes, rss_bytes),
                cuda_bytes=max(current.cuda_bytes, cuda_bytes),
            )
        )

    def _set_support_measurement(self, measured: SupportMeasurement) -> None:
        """Publish one snapshot and reject its first exceeded dimension."""
        self._support_measurement = measured
        limits = self._support_limits
        exceeded = limits.exceeded_by(measured) if limits is not None else None
        if exceeded is None:
            return
        dimension, actual, limit = exceeded
        raise JobError(
            JobErrorKind.CORPUS_LIMIT_EXCEEDED,
            f"code {dimension} is {actual}; profile "
            f"{self._support_profile_name!r} permits {limit}",
        )

    def _measure_code_segments(
        self,
        segments: Iterable[CodeFileSegment],
    ) -> Iterator[CodeFileSegment]:
        """Measure generated workload while retaining one bounded segment."""
        for segment in segments:
            current = self.support_measurement
            self._set_support_measurement(
                SupportMeasurement(
                    source_files=current.source_files,
                    source_bytes=current.source_bytes,
                    generated_chunks=current.generated_chunks + len(segment.chunks),
                    weighted_bytes=current.weighted_bytes + segment.estimated_bytes,
                    extracted_bytes=current.extracted_bytes,
                    queue_bytes=current.queue_bytes,
                    rss_bytes=current.rss_bytes,
                    cuda_bytes=current.cuda_bytes,
                )
            )
            yield segment

    def resolve_policy_snapshot(self) -> ResolvedIndexPolicy:
        """Resolve one immutable policy snapshot before any mutation authority.

        The single way to resolve this indexer's policy. A private twin with an
        identical body existed alongside it, reached only from tests - so the
        path the tests exercised was not the path production ran.
        """
        return self._discovery.resolve_policy()

    def preflight_content(
        self,
        *,
        sample_limit: int = _DEFAULT_SCAN_SAMPLE_LIMIT,
    ) -> CodeIndexPreflight:
        """Resolve and discover once before any mutable index resource."""
        return self._discovery.preflight_content(sample_limit=sample_limit)

    def preflight_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
    ) -> CodeScopedPreflight:
        """Resolve policy and classify one exact normalized changed-path scope."""
        return self._discovery.preflight_changed_paths(changed_paths)

    def _accept_preflight(
        self,
        preflight: CodeExecutionPreflight,
        *,
        changed_paths: Iterable[pathlib.Path] | None,
    ) -> tuple[ResolvedIndexPolicy, tuple[pathlib.Path, ...] | None]:
        """Verify and return one exact caller-owned execution authority."""
        return self._discovery.accept_preflight(
            preflight,
            changed_paths=changed_paths,
        )

    def _compute_code_epochs(
        self,
        policy: ResolvedIndexPolicy,
    ) -> tuple[str, str]:
        """Project code membership and content epochs from one snapshot."""
        fingerprints = policy.fingerprints_for(ContentKind.CODE)
        return fingerprints.membership, fingerprints.content

    def _reset_reuse_state(self) -> None:
        """Clear per-run donor reuse and drift state at the start of a run."""
        self._reuse_stats = None
        self._donor_reuse = None
        self._lifecycle.forget_open_generation()
        # Cleared per run so a generation target can never leak from a
        # finished rebuild into the next job on this indexer.
        self._code_build_target = None

    #: Collection a clean rebuild is populating, or ``None`` outside one. Held
    #: on the indexer rather than the store because the store is shared with
    #: search, while one indexer runs one job at a time behind the writer lock.
    _code_build_target: str | None = None

    def _reuse_snapshot(self) -> dict[str, object] | None:
        """Return this run's reuse telemetry block, or ``None`` when off."""
        stats = self._reuse_stats
        return stats.snapshot() if stats is not None else None

    def _classify_config_drift(self, membership: str, content: str) -> str:
        """Classify config drift against the stored epochs.

        Returns ``"clean"`` (content drift - clean rebuild), ``"unscoped"``
        (membership drift or a legacy sidecar missing the keys - force the
        unscoped incremental), or ``"ok"`` (no drift, or a fresh index with no
        sidecar to compare against). Content drift outranks membership drift
        because the clean rebuild subsumes the membership reconcile.
        """
        return _code_meta.classify_config_drift(
            self._read_meta_raw(), membership, content
        )

    def _config_drift_dispatch(
        self,
        changed_paths: Iterable[pathlib.Path] | None,
        policy: ResolvedIndexPolicy,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[Iterable[pathlib.Path] | None, bool]:
        """Stamp snapshot epochs and classify drift without reloading config.

        Returns the possibly-nulled ``changed_paths`` (a membership mismatch,
        or a legacy sidecar missing the keys, forces the unscoped incremental)
        and whether a content mismatch requires a clean rebuild.
        """
        run_control.checkpoint()
        membership, content = self._compute_code_epochs(policy)
        run_control.checkpoint()
        self._membership_epoch = membership
        self._content_epoch = content
        drift = self._classify_config_drift(membership, content)
        if drift == "clean":
            return changed_paths, True
        if drift == "unscoped" and changed_paths is not None:
            logger.info(
                "Codebase membership config changed; forcing an unscoped "
                "incremental reconcile of the code collection",
            )
            changed_paths = None
        return changed_paths, False

    def _resolve_preprocess_context(
        self,
        policy: ResolvedIndexPolicy,
    ) -> PreprocessContext | None:
        """Build worker context from the operation snapshot without reloading."""
        return _preprocess_glue.resolve_policy_preprocess_context(
            self.root_dir,
            self._data_root,
            policy,
        )

    def _begin_preprocess_run(
        self,
        policy: ResolvedIndexPolicy,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Reset per-run preprocess state at the start of a full/incremental run."""
        run_control.checkpoint()
        self._chunk_execution_policy = _chunk_worker.ChunkExecutionPolicy(
            encoding=policy.decoder.encoding,
            errors=policy.decoder.errors,
            normalize_newlines=policy.decoder.normalize_newlines,
            html_strip=policy.html_strip,
        )
        self._prep_ctx = self._resolve_preprocess_context(policy)
        self._prep_skips = []
        self._prep_stale_paths = set()
        self._prep_rule_total = len(policy.preprocess_rules)
        self._prep_ok = 0
        run_control.checkpoint()

    def _prep_rule_count(self) -> int:
        """Return the number of routed preprocess rules in the run snapshot."""
        return getattr(
            self,
            "_prep_rule_total",
            _preprocess_glue.prep_rule_count(self._prep_ctx),
        )

    @staticmethod
    def _disabled_transform(
        policy: ResolvedIndexPolicy,
        rel_path: str,
    ) -> bool:
        """Return whether routing is retained while its transform is disabled."""
        return (
            policy.execution_mode == "off"
            and policy.match_preprocess(rel_path) is not None
        )

    def _mark_preprocess_stale(self, rel_path: str) -> None:
        """Surface disabled transform work once without changing membership."""
        if rel_path in self._prep_stale_paths:
            return
        self._prep_stale_paths.add(rel_path)
        self._prep_skips.append(
            f"{rel_path}: preprocessing disabled; retained work as stale"
        )

    def _partition_disabled_paths(
        self,
        paths: Iterable[pathlib.Path],
        policy: ResolvedIndexPolicy,
    ) -> list[pathlib.Path]:
        """Remove disabled transforms from execution while retaining ownership."""
        executable: list[pathlib.Path] = []
        for path in paths:
            rel = str(path.relative_to(self.root_dir)).replace("\\", "/")
            if self._disabled_transform(policy, rel):
                self._mark_preprocess_stale(rel)
                continue
            executable.append(path)
        return executable

    def _preserved_disabled_metadata(
        self,
        policy: ResolvedIndexPolicy,
        previous_metadata: dict[str, str],
    ) -> dict[str, str]:
        """Return published transform rows that off mode must retain stale."""
        preserved: dict[str, str] = {}
        for rel, content_hash in previous_metadata.items():
            if not self._disabled_transform(policy, rel):
                continue
            if not (self.root_dir / pathlib.PurePosixPath(rel)).is_file():
                continue
            self._mark_preprocess_stale(rel)
            preserved[rel] = content_hash
        return preserved

    def _prepare_disabled_full_preservation(
        self,
        policy: ResolvedIndexPolicy,
        previous_metadata: dict[str, str],
        *,
        clean: bool,
    ) -> tuple[dict[str, str], set[str] | None, bool]:
        """Resolve stale rows and whether a destructive rebuild remains safe."""
        preserved_metadata = self._preserved_disabled_metadata(
            policy,
            previous_metadata,
        )
        try:
            preserved_ids: set[str] | None = (
                set(self._get_chunk_ids_for_files(set(preserved_metadata)))
                if preserved_metadata
                else set()
            )
        except (OSError, RuntimeError):
            logger.warning(
                "Could not resolve stored IDs for disabled preprocessing paths; "
                "retaining failure-safe rebuild behavior",
                exc_info=True,
            )
            preserved_ids = None
        effective_clean = clean and not preserved_metadata
        if clean and preserved_metadata:
            logger.warning(
                "Preprocessing is disabled for %d published path(s); retaining "
                "their stored content as stale and using a failure-safe rebuild",
                len(preserved_metadata),
            )
        return preserved_metadata, preserved_ids, effective_clean

    def _record_preprocess_result(self, res: FileChunkResult) -> None:
        """Accumulate a worker result's preprocess disposition."""
        self._prep_ok += _preprocess_glue.record_preprocess_result(
            res, self._prep_skips
        )

    def _scan_codebase(
        self,
        policy: ResolvedIndexPolicy | None = None,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[pathlib.Path]:
        """Project structured policy discovery to admitted code paths."""
        return self._discovery.scan_codebase(policy, run_control=run_control)

    def _classify_file(
        self,
        path: pathlib.Path,
        rel_path: str,
        policy: ResolvedIndexPolicy,
    ) -> ClassifiedContent:
        """Apply ownership first, then raw-code size and binary capability."""
        return self._discovery.inspect_file(path, rel_path, policy).classified

    def scan_content(
        self,
        *,
        sample_limit: int = _DEFAULT_SCAN_SAMPLE_LIMIT,
    ) -> ContentScanResult:
        """Return structured admission from one freshly resolved snapshot."""
        return self._discovery.scan_admission(sample_limit=sample_limit)

    def scan_files(self) -> list[pathlib.Path]:
        """Return the list of files that would be indexed.

        Does not require GPU or vector store - safe to call with
        ``model=None`` and ``store=None`` for dry-run usage.

        Returns:
            List of absolute paths to indexable source files.
        """
        return self._discovery.scan_files()

    def _iter_consumer_segments(
        self,
        segment_queue: WeightedCodeSegmentQueue,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> Iterator[CodeFileSegment]:
        """Yield queued segments until the producer supplies its sentinel."""
        while True:
            run_control.checkpoint()
            try:
                segment = segment_queue.get(timeout=CONTROL_POLL_SECONDS)
            except queue.Empty:
                self._sample_memory_budget("code consumer queue wait")
                continue
            run_control.checkpoint()
            if segment is None:
                return
            yield segment

    def _record_confirmed_slice(
        self,
        segments: tuple[CodeFileSegment, ...],
        metadata: dict[str, str],
    ) -> None:
        """Persist the file units covered by one confirmed store mutation.

        Routed through the drift owner rather than straight at the checkpoint:
        the store write has already been confirmed here, so a path that moved
        since its digest was observed must be superseded and re-recorded, not
        allowed to fail a run that has otherwise succeeded.
        """
        self._lifecycle.drift_owner.record_segments(segments, metadata)

    def _consume_weighted_slice(
        self,
        weighted_slice: WeightedCodeSlice,
        *,
        slice_index: int,
        limits: _CodePipelineLimits,
        new_ids: set[str],
        total: list[int],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        probe: MemoryProbe,
        ingest_wait: bool,
        run_control: RunControl,
    ) -> None:
        """Encode, store, and account for one bounded weighted slice."""
        run_control.checkpoint()
        self._sample_memory_budget(f"slice-{slice_index}-before-encode")
        slice_chunks = sorted(
            weighted_slice.chunks,
            key=lambda chunk: -len(chunk.content),
        )
        try:
            probe.checkpoint(f"slice-{slice_index}-before-encode")
            completed_slice_index = slice_index + 1
            on_storage_confirmed = (
                partial(
                    self._record_confirmed_slice,
                    weighted_slice.segments,
                    metadata,
                )
                if checkpoint is not None
                else None
            )

            def _after_forward(kind: str) -> None:
                run_control.checkpoint()
                self._sample_memory_budget(
                    f"slice-{completed_slice_index}-after-{kind}-forward"
                )
                run_control.checkpoint()

            def _on_cuda_oom(exc: BaseException) -> None:
                self._fail_cuda_oom(
                    f"slice-{completed_slice_index}-allocator-oom",
                    exc,
                )

            # Route the lock-bracketed forward captures of this consumer
            # thread into this job's own budget, so checkpoints enforce
            # the job's demand rather than a process-wide high-water.
            with self._forward_peak_recording():
                encode_and_upsert_code_slice(
                    slice_chunks,
                    model=self.model,
                    store=self.store,
                    gpu_lock=self._gpu_lock,
                    release_cache=(completed_slice_index % limits.flush_slices == 0),
                    encode_batch_size=limits.encode_batch_size,
                    write_policy=(
                        checkpoint.run_policy.store_write_policy
                        if checkpoint is not None
                        else None
                    ),
                    ingest_wait=ingest_wait,
                    collection=self._code_build_target,
                    on_storage_confirmed=on_storage_confirmed,
                    after_forward=_after_forward,
                    on_cuda_oom=_on_cuda_oom,
                    run_control=run_control,
                    reuse=self._donor_reuse,
                )
            run_control.checkpoint()
            new_ids.update(chunk.id for chunk in slice_chunks)
            total[0] += len(slice_chunks)
            probe.checkpoint(f"slice-{completed_slice_index}-after-store")
            self._sample_memory_budget(f"slice-{completed_slice_index}-after-store")
        finally:
            del slice_chunks

    def _finish_consumer_probe(
        self,
        probe: MemoryProbe | None,
        consumer_exceptions: list[BaseException],
    ) -> None:
        """Release consumer resources while retaining every cleanup failure."""
        try:
            self._sample_memory_budget("code consumer cleanup")
        except BaseException as exc:
            consumer_exceptions.append(exc)
        try:
            _release_cuda_cache()
            if probe is not None and probe.samples:
                logger.info("%s", probe.report())
        except BaseException as exc:
            consumer_exceptions.append(exc)

    def _run_weighted_consumer(
        self,
        segment_queue: WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        limits: _CodePipelineLimits,
        new_ids: set[str],
        total: list[int],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        ingest_wait: bool,
        run_control: RunControl,
    ) -> None:
        """Run the sole weighted consumer and retain failures for the producer."""
        from ..memory_probe import MemoryProbe

        probe: MemoryProbe | None = None
        try:
            probe = MemoryProbe(name="codebase-index")
            with probe:
                self._sample_memory_budget("code consumer start")
                segments = self._iter_consumer_segments(
                    segment_queue,
                    run_control=run_control,
                )
                for slice_index, weighted_slice in enumerate(
                    iter_weighted_code_slices(
                        segments,
                        max_chunks=limits.slice_max_chunks,
                        max_bytes=limits.slice_max_bytes,
                        run_control=run_control,
                    )
                ):
                    self._consume_weighted_slice(
                        weighted_slice,
                        slice_index=slice_index,
                        limits=limits,
                        new_ids=new_ids,
                        total=total,
                        metadata=metadata,
                        checkpoint=checkpoint,
                        probe=probe,
                        ingest_wait=ingest_wait,
                        run_control=run_control,
                    )
        except BaseException as exc:
            consumer_exceptions.append(exc)
        finally:
            self._finish_consumer_probe(probe, consumer_exceptions)

    def _spawn_weighted_consumer(
        self,
        segment_queue: WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        limits: _CodePipelineLimits,
        new_ids: set[str],
        total: list[int],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        *,
        ingest_wait: bool = True,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> threading.Thread:
        """Start the sole GPU consumer for weighted file segments."""
        import contextvars
        import threading

        # The consumer runs under a copy of the spawning attempt's context
        # so its timed GPU-lock waits accumulate on the owning job record;
        # a bare Thread would silently detach the attribution.
        consumer = threading.Thread(
            target=contextvars.copy_context().run,
            args=(
                self._run_weighted_consumer,
                segment_queue,
                consumer_exceptions,
                limits,
                new_ids,
                total,
                metadata,
                checkpoint,
                ingest_wait,
                run_control,
            ),
            name="codebase-indexer-consumer",
        )
        consumer.start()
        return consumer

    @staticmethod
    def _drain_consumer(
        consumer: threading.Thread,
        segment_queue: WeightedCodeSegmentQueue,
        run_policy: RunPolicy,
        sample_memory: Callable[[str], object] | None = None,
    ) -> None:
        """Finish normal work under the durable no-progress authority."""
        sentinel_delivered = False
        while consumer.is_alive() and not sentinel_delivered:
            run_policy.checkpoint("code consumer drain sentinel")
            timeout = min(
                CONTROL_POLL_SECONDS,
                run_policy.remaining_seconds(),
            )
            try:
                segment_queue.put(None, timeout=timeout)
            except queue.Full:
                if sample_memory is not None:
                    sample_memory("code consumer drain sentinel wait")
                continue
            sentinel_delivered = True
        while consumer.is_alive():
            run_policy.checkpoint("code consumer drain")
            consumer.join(
                timeout=min(
                    CONTROL_POLL_SECONDS,
                    run_policy.remaining_seconds(),
                )
            )
            if consumer.is_alive() and sample_memory is not None:
                sample_memory("code consumer drain wait")

    def _cleanup_consumer(
        self,
        consumer: threading.Thread,
        segment_queue: WeightedCodeSegmentQueue,
    ) -> bool:
        """Bound cleanup after a producer, control, or liveness failure."""
        deadline = time.monotonic() + _CONSUMER_SHUTDOWN_TIMEOUT_S
        while consumer.is_alive():
            try:
                segment_queue.put(None, timeout=CONTROL_POLL_SECONDS)
                break
            except queue.Full:
                if time.monotonic() >= deadline:
                    break
        consumer.join(timeout=max(0.0, deadline - time.monotonic()))
        return consumer.is_alive()

    def _resolve_code_pipeline_limits(self) -> _CodePipelineLimits:
        """Freeze code segment, queue, slice, and model limits."""
        from ..config import get_config
        from ..store_schema import effective_sparse_dim

        config = get_config()
        sparse_enabled = bool(config.sparse_enabled)
        sparse_dimension = effective_sparse_dim(self.model)
        return _CodePipelineLimits(
            segment_max_chunks=int(config.index_segment_max_chunks),
            segment_max_bytes=int(config.index_segment_max_bytes),
            queue_max_chunks=int(config.index_queue_max_chunks),
            queue_max_bytes=int(config.index_queue_max_bytes),
            slice_max_chunks=int(config.index_queue_max_chunks),
            slice_max_bytes=int(config.index_queue_max_bytes),
            dense_dimension=int(config.embedding_dimension),
            sparse_enabled=sparse_enabled,
            sparse_dimension=sparse_dimension,
            encode_batch_size=int(config.embedding_code_encode_batch_size),
            flush_slices=max(1, int(config.index_cache_flush_slices)),
        )

    def _resume_pending_finalization(
        self,
        checkpoint: CodeRunCheckpoint,
        *,
        reporter: ProgressReporter,
        started_at: float,
    ) -> IndexResult | None:
        """Finish an ingestion-complete generation without re-entering writes."""
        if not self._lifecycle.publish_pending_finalization(
            checkpoint, reporter=reporter
        ):
            return None
        return IndexResult(
            total=self.store.count_code(),
            added=0,
            updated=0,
            removed=0,
            duration_ms=int((time.time() - started_at) * 1000),
            device=self.model.device,
            files=0,
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
            reuse=self._reuse_snapshot(),
            drift=self._lifecycle.drift_snapshot(),
        )

    def _unchanged_incremental_result(self, *, started_at: float) -> IndexResult:
        """Return a mutation-free incremental result without publishing metadata."""
        return IndexResult(
            total=self.store.count_code(),
            added=0,
            updated=0,
            removed=0,
            duration_ms=int((time.time() - started_at) * 1000),
            device=self.model.device,
            files=0,
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
            reuse=self._reuse_snapshot(),
            drift=self._lifecycle.drift_snapshot(),
        )

    @staticmethod
    def _code_result_failure(
        result: FileChunkResult,
    ) -> tuple[FileStateKind, JobErrorKind, str] | None:
        """Return the durable state and typed error for a failed file result."""
        if result.preprocess_status == "skipped":
            return (
                FileStateKind.EXTRACT_RETRYABLE,
                JobErrorKind.EXTRACTION_RETRYABLE,
                result.preprocess_reason or "preprocessor skipped the file",
            )
        if result.chunks:
            return None
        if result.preprocess_status == "ok":
            return (
                FileStateKind.EXTRACT_RETRYABLE,
                JobErrorKind.EXTRACTION_RETRYABLE,
                "admitted code source produced no indexable chunks",
            )
        return (
            FileStateKind.CHUNK_FAILED,
            JobErrorKind.CHUNK_FAILED,
            "admitted code source produced no indexable chunks",
        )

    def _record_empty_source(
        self,
        result: FileChunkResult,
        checkpoint: CodeRunCheckpoint | None,
    ) -> bool:
        """Converge an empty source instead of failing the run over it.

        A file that reads as zero bytes yields no chunks, which is not a
        chunking defect - there was nothing to chunk. Treating it as one let a
        single file caught mid-save abort an entire indexing job, which is how
        one editor save became a failed generation and, through resume, a
        sustained outage.

        The rejection is stable only against the hash that evidenced it, so a
        file caught mid-save converges against the empty hash and is classified
        again under its real content once the save lands, while a genuinely
        empty file keeps that hash and stays converged. Neither retries
        forever, and neither needs the run to fail.

        Returns:
            True when the result was an empty source and has been recorded.
        """
        if result.chunks or result.content_hash != _EMPTY_SOURCE_DIGEST:
            return False
        if checkpoint is not None:
            checkpoint.record_empty_source(
                result.rel_path,
                content_hash=self._lifecycle.checkpoint_content_hash(
                    result.content_hash
                ),
            )
        logger.debug(
            "Converged empty source %s with no indexable content",
            result.rel_path,
        )
        return True

    def _raise_code_result_failure(
        self,
        result: FileChunkResult,
        checkpoint: CodeRunCheckpoint | None,
    ) -> None:
        """Record and raise a typed failure for a non-indexable file result."""
        if self._record_empty_source(result, checkpoint):
            return
        failure = self._code_result_failure(result)
        if failure is None:
            return
        failure_state, failure_kind, detail = failure
        if checkpoint is not None:
            checkpoint.record_processing_failure(
                result.rel_path,
                failure_state,
                detail,
                content_hash=self._lifecycle.checkpoint_content_hash(
                    result.content_hash
                ),
            )
        raise JobError(failure_kind, detail)

    def _enqueue_code_result(
        self,
        result: FileChunkResult,
        *,
        limits: _CodePipelineLimits,
        segment_queue: WeightedCodeSegmentQueue,
        consumer: threading.Thread,
        consumer_exceptions: list[BaseException],
        metadata: dict[str, str],
        checkpoint: CodeRunCheckpoint | None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> bool:
        """Drain one file result into bounded weighted segments."""
        run_control.checkpoint()
        self._record_preprocess_result(result)
        self._raise_code_result_failure(result, checkpoint)
        if result.preprocess_status == "ok":
            self._record_extracted_bytes(
                sum(len(chunk.content.encode("utf-8")) for chunk in result.chunks)
            )
        metadata[result.rel_path] = result.content_hash
        segments = iter_code_file_segments(
            drain_code_chunks(result.chunks),
            max_chunks=limits.segment_max_chunks,
            max_bytes=limits.segment_max_bytes,
            dense_dimension=limits.dense_dimension,
            sparse_enabled=limits.sparse_enabled,
            sparse_dimension=limits.sparse_dimension,
            run_control=run_control,
        )
        measured_segments = self._measure_code_segments(segments)
        pending_segments = (
            checkpoint.pending_segments(measured_segments, result.content_hash)
            if checkpoint is not None
            else measured_segments
        )
        return self._producer.submit_segments(
            pending_segments,
            segment_queue=segment_queue,
            consumer=consumer,
            consumer_exceptions=consumer_exceptions,
            on_wait=self._sample_memory_budget,
            run_control=run_control,
        )

    def _finish_weighted_consumer(
        self,
        consumer: threading.Thread,
        segment_queue: WeightedCodeSegmentQueue,
        consumer_exceptions: list[BaseException],
        producer_exception: BaseException | None,
        checkpoint: CodeRunCheckpoint,
    ) -> None:
        """Stop the consumer and preserve cleanup/error precedence."""
        drain_failure: BaseException | None = None
        if producer_exception is None:
            try:
                self._drain_consumer(
                    consumer,
                    segment_queue,
                    checkpoint.run_policy,
                    self._sample_memory_budget,
                )
            except BaseException as exc:
                drain_failure = exc
        cleanup_required = producer_exception is not None or drain_failure is not None
        if cleanup_required and self._cleanup_consumer(consumer, segment_queue):
            logger.error(
                "GPU consumer cleanup did not terminate within %.0fs after "
                "failure; aborting (a CUDA or Qdrant call may be wedged)",
                _CONSUMER_SHUTDOWN_TIMEOUT_S,
            )
            error = _UnsettledCodeConsumerError(
                "codebase index GPU consumer thread did not terminate"
            )
            if drain_failure is not None:
                raise error from drain_failure
            if producer_exception is not None:
                raise error from producer_exception
            raise error
        if drain_failure is not None:
            raise drain_failure
        consumer_failure = next(
            (
                exc
                for exc in consumer_exceptions
                if not isinstance(exc, RunControlSignal)
            ),
            None,
        )
        if consumer_failure is not None:
            raise consumer_failure
        if producer_exception is not None:
            raise producer_exception
        if consumer_exceptions:
            raise consumer_exceptions[0]

    def _pipeline_chunk_and_embed(
        self,
        paths: list[pathlib.Path],
        *,
        reporter: ProgressReporter,
        checkpoint: CodeRunCheckpoint,
        limits: _CodePipelineLimits,
        ingest_wait: bool = True,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[set[str], int, dict[str, str]]:
        """Overlap bounded CPU production with one weighted GPU consumer."""
        from ._donor_candidates import CollectionKind
        from ._reuse import resolve_donor_reuse

        # One donor resolution per run: the consumer thread reads the
        # resolved context per slice, outside the GPU lock.
        self._reuse_stats, self._donor_reuse = resolve_donor_reuse(
            self.root_dir,
            CollectionKind.CODE,
            self.store,
            expected_content_epoch=self._content_epoch or "",
        )
        new_ids: set[str] = set()
        new_ids.update(checkpoint.ledger.iter_point_ids(checkpoint.generation_id))
        if checkpoint.generation.signature.operation is not RunOperation.FULL:
            new_ids.update(
                checkpoint.ledger.iter_retained_point_ids(checkpoint.generation_id)
            )
        metadata: dict[str, str] = {}
        total = [len(new_ids)]
        self._begin_support_measurement(paths)
        # A generation build holds both collections at once, so the served
        # points are part of what has to fit. Charged through the one existing
        # estimator rather than a second sizing rule: a root that cannot afford
        # the duplicate is refused here and keeps serving what it has, which is
        # the whole reason the build never touches the served collection.
        duplicate_points = (
            self.store.count_code() if self._code_build_target is not None else 0
        )
        self.store.disk_headroom_preflight(
            len(paths) * _CHUNKS_PER_FILE_ESTIMATE + duplicate_points
        )
        run_control.checkpoint()
        reporter.phase_start("chunk + embed", len(paths))
        try:
            if not paths:
                return new_ids, total[0], metadata
            self._begin_memory_budget()
            segment_queue = WeightedCodeSegmentQueue(
                max_chunks=limits.queue_max_chunks,
                max_bytes=limits.queue_max_bytes,
            )
            consumer_exceptions: list[BaseException] = []
            consumer = self._spawn_weighted_consumer(
                segment_queue,
                consumer_exceptions,
                limits,
                new_ids,
                total,
                metadata,
                checkpoint,
                ingest_wait=ingest_wait,
                run_control=run_control,
            )

            def _publish_result(result: FileChunkResult) -> bool:
                return self._enqueue_code_result(
                    result,
                    limits=limits,
                    segment_queue=segment_queue,
                    consumer=consumer,
                    consumer_exceptions=consumer_exceptions,
                    metadata=metadata,
                    checkpoint=checkpoint,
                    run_control=run_control,
                )

            producer_exception: BaseException | None = None
            try:
                batch_groups, singles = self._producer.partition_batch_work(
                    paths, run_control=run_control
                )
                if batch_groups:
                    self._producer.produce_batch_groups(
                        batch_groups,
                        _publish_result,
                        reporter,
                        run_control=run_control,
                    )
                if singles:
                    self._producer.produce_singles(
                        singles,
                        publish_result=_publish_result,
                        consumer_failed=lambda: (
                            bool(consumer_exceptions) or not consumer.is_alive()
                        ),
                        reporter=reporter,
                        total=total,
                        run_control=run_control,
                    )
            except BaseException as exc:
                producer_exception = exc
            finally:
                self._finish_weighted_consumer(
                    consumer,
                    segment_queue,
                    consumer_exceptions,
                    producer_exception,
                    checkpoint,
                )
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return new_ids, total[0], metadata

    def _prepare_full_paths(
        self,
        policy: ResolvedIndexPolicy,
        reporter: ProgressReporter,
        *,
        discovered_paths: tuple[pathlib.Path, ...] | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> list[pathlib.Path]:
        """Resolve full-run inputs and scan with bounded control checkpoints."""
        self._begin_preprocess_run(policy, run_control=run_control)
        run_control.checkpoint()
        self._membership_epoch, self._content_epoch = self._compute_code_epochs(policy)
        run_control.checkpoint()

        reporter.phase_start("scan codebase", None)
        try:
            paths = (
                self._scan_codebase(policy, run_control=run_control)
                if discovered_paths is None
                else list(discovered_paths)
            )
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return self._partition_disabled_paths(paths, policy)

    def _publish_incremental_paths(
        self,
        *,
        paths: list[pathlib.Path],
        attempted_paths: set[str],
        existing_ids: set[str],
        reporter: ProgressReporter,
        checkpoint: CodeRunCheckpoint,
        limits: _CodePipelineLimits,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[set[str], dict[str, str]]:
        """Stream changed paths and roll back attempt-introduced IDs."""
        try:
            published_ids, _total, published_hashes = self._pipeline_chunk_and_embed(
                paths,
                reporter=reporter,
                checkpoint=checkpoint,
                limits=limits,
                run_control=run_control,
            )
        except _UnsettledCodeConsumerError:
            raise
        except BaseException:
            self._discard_failed_incremental_additions(
                attempted_paths=attempted_paths,
                existing_ids=existing_ids,
                protected_ids=set(
                    checkpoint.ledger.iter_point_ids(checkpoint.generation_id)
                ),
            )
            raise
        return published_ids, published_hashes

    def _discard_failed_incremental_additions(
        self,
        *,
        attempted_paths: set[str],
        existing_ids: set[str],
        protected_ids: set[str] | None = None,
    ) -> None:
        """Best-effort rollback after every consumer has settled."""
        if not attempted_paths:
            return
        try:
            current_ids = set(self._get_chunk_ids_for_files(attempted_paths))
            introduced_ids = sorted(
                current_ids - existing_ids - (protected_ids or set())
            )
            if introduced_ids:
                self.store.delete_code_chunks(introduced_ids)
        except Exception:
            logger.error(
                "Failed to clean partial incremental code publication",
                exc_info=True,
            )

    def _incremental_prior_ids_by_path(
        self,
        checkpoint: CodeRunCheckpoint,
        rel_paths: set[str],
    ) -> dict[str, set[str]]:
        """Combine carried evidence with real current storage observations."""
        result = self._lifecycle.checkpoint_ids_by_path(
            checkpoint,
            rel_paths,
            retained=True,
        )
        for rel in rel_paths:
            result[rel].update(self._get_chunk_ids_for_files({rel}))
        return result

    def _delete_incremental_obsolete(
        self,
        *,
        existing_ids: set[str],
        published_ids: set[str],
        prior_ids_by_path: dict[str, set[str]] | None,
        deleted_paths: set[str] | None,
        checkpoint: CodeRunCheckpoint | None,
    ) -> None:
        """Delete and checkpoint exact obsolete identities path by path."""
        if checkpoint is None or prior_ids_by_path is None:
            obsolete_ids = sorted(existing_ids - published_ids)
            if obsolete_ids:
                self.store.delete_code_chunks(obsolete_ids)
            return
        current_ids_by_path = self._lifecycle.checkpoint_ids_by_path(
            checkpoint,
            set(prior_ids_by_path),
            retained=False,
        )
        committed_deletions = {
            (unit.rel_path, unit.kind)
            for unit in checkpoint.ledger.iter_units(checkpoint.generation_id)
            if unit.kind in (CommitUnitKind.DELETE_PATH, CommitUnitKind.DELETE_STALE)
        }
        for rel in sorted(prior_ids_by_path):
            deletion_kind = (
                CommitUnitKind.DELETE_PATH
                if rel in (deleted_paths or set())
                else CommitUnitKind.DELETE_STALE
            )
            if (rel, deletion_kind) in committed_deletions:
                continue
            obsolete_ids = tuple(
                sorted(prior_ids_by_path[rel] - current_ids_by_path.get(rel, set()))
            )
            if not obsolete_ids:
                continue
            self.store.delete_code_chunks(list(obsolete_ids))
            if deletion_kind is CommitUnitKind.DELETE_PATH:
                checkpoint.record_confirmed_deletion(rel, obsolete_ids)
            else:
                checkpoint.record_confirmed_stale_deletion(rel, obsolete_ids)

    def _commit_incremental_replacement(
        self,
        *,
        policy: ResolvedIndexPolicy,
        existing_ids: set[str],
        published_ids: set[str],
        prior_ids_by_path: dict[str, set[str]] | None = None,
        deleted_paths: set[str] | None = None,
        checkpoint: CodeRunCheckpoint | None = None,
        metadata: dict[str, str],
        files_count: int,
        protect_replacement: bool,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        """Delete obsolete IDs and publish metadata at one safe control edge."""
        commit_started = False
        try:
            run_control.checkpoint()
            publication_span = (
                (
                    checkpoint.run_policy.protected("incremental code replacement")
                    if checkpoint is not None
                    else run_control.protected()
                )
                if protect_replacement
                else contextlib.nullcontext()
            )
            with publication_span:
                commit_started = True
                reporter.phase_start("delete removed", files_count)
                try:
                    self._delete_incremental_obsolete(
                        existing_ids=existing_ids,
                        published_ids=published_ids,
                        prior_ids_by_path=prior_ids_by_path,
                        deleted_paths=deleted_paths,
                        checkpoint=checkpoint,
                    )
                    reporter.advance(files_count)
                finally:
                    reporter.phase_end()
                reporter.phase_start("write metadata", 1)
                try:
                    if checkpoint is None:
                        self._write_meta(
                            metadata,
                            policy=policy,
                            published_points=self.store.count_code(),
                            published_files=self.store.count_code_files(),
                        )
                    else:
                        reconcile_generation_storage(
                            self.store,
                            checkpoint,
                            policy,
                            ContentKind.CODE,
                        )
                        checkpoint.publish_metadata(
                            self._meta_path,
                            published_points=self.store.count_code(),
                            published_files=self.store.count_code_files(),
                        )
                        checkpoint.publish_generation()
                    reporter.advance(1)
                finally:
                    reporter.phase_end()
        except RunControlSignal:
            if not commit_started and checkpoint is None:
                introduced_ids = sorted(published_ids - existing_ids)
                try:
                    if introduced_ids:
                        self.store.delete_code_chunks(introduced_ids)
                except Exception:
                    logger.error(
                        "Failed to roll back code publication before commit",
                        exc_info=True,
                    )
            raise
        run_control.checkpoint()

    def _scan_and_hash_incremental_inputs(
        self,
        policy: ResolvedIndexPolicy,
        reporter: ProgressReporter,
        *,
        discovered_paths: tuple[pathlib.Path, ...] | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[dict[str, pathlib.Path], dict[str, str]]:
        """Scan and hash one unscoped incremental corpus cooperatively."""
        reporter.phase_start("scan codebase", None)
        try:
            current_paths = (
                self._scan_codebase(policy, run_control=run_control)
                if discovered_paths is None
                else list(discovered_paths)
            )
            current_files: dict[str, pathlib.Path] = {}
            for path in current_paths:
                run_control.checkpoint()
                current_files[
                    str(path.relative_to(self.root_dir)).replace("\\", "/")
                ] = path
                run_control.checkpoint()
        finally:
            reporter.phase_end()

        current_hashes = self._hash_changed_paths(
            current_files,
            reporter,
            run_control=run_control,
        )
        return current_files, current_hashes

    def _reconcile_full_stale_ids(
        self,
        *,
        checkpoint: CodeRunCheckpoint,
        previous_metadata: dict[str, str],
        metadata: dict[str, str],
        existing_ids: set[str],
        retained_ids: set[str],
        reporter: ProgressReporter,
    ) -> list[str]:
        """Delete stale full-run identities and checkpoint removed paths."""
        stale_ids = sorted(existing_ids - retained_ids)
        removed_paths = set(previous_metadata) - set(metadata)
        removed_ids_by_path = self._lifecycle.checkpoint_ids_by_path(
            checkpoint,
            removed_paths,
            retained=True,
        )
        reporter.phase_start("purge stale chunks", len(stale_ids))
        try:
            if not stale_ids:
                return stale_ids
            try:
                path_removed_ids: set[str] = set()
                for rel in sorted(removed_paths):
                    point_ids = tuple(sorted(removed_ids_by_path[rel]))
                    if not point_ids:
                        continue
                    self.store.delete_code_chunks(list(point_ids))
                    checkpoint.record_confirmed_deletion(rel, point_ids)
                    path_removed_ids.update(point_ids)
                remaining_stale_ids = sorted(set(stale_ids) - path_removed_ids)
                if remaining_stale_ids:
                    self.store.delete_code_chunks(remaining_stale_ids)
            except OSError:
                logger.error(
                    "Failed to purge stale code chunks after successful rebuild - "
                    "collection still contains valid new chunks plus %d stale rows",
                    len(stale_ids),
                )
                raise
            reporter.advance(len(stale_ids))
            return stale_ids
        finally:
            reporter.phase_end()

    def full_index(
        self,
        clean: bool = False,
        *,
        reporter: ProgressReporter,
        preflight: CodeIndexPreflight,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Full codebase re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_full_index_locked`. Mirrors the VaultIndexer wrapper
        and serializes against concurrent reindex callers (#68).
        """
        run_control.checkpoint()
        resolved_policy, discovered_paths = self._accept_preflight(
            preflight,
            changed_paths=None,
        )
        run_control.checkpoint()
        with self._writer_lock:
            self._resolved_policy = resolved_policy
            self._reset_reuse_state()
            return run_index_lifecycle(
                lambda: self._full_index_locked(
                    clean=clean,
                    policy=resolved_policy,
                    discovered_paths=discovered_paths,
                    reporter=reporter,
                    run_control=run_control,
                ),
                event_logger=logger,
                store=self.store,
                source="code",
                mode="full",
                clean=clean,
                root=self.root_dir,
                run_control=run_control,
                completion_fields=self._completed_event_fields,
            )

    def _completed_event_fields(self, result: IndexResult) -> dict[str, object]:
        """Code-domain extras carried by this run's ``completed`` event."""
        fields = preprocess_completion_fields(result)
        fields["preprocess_rules"] = self._prep_rule_count()
        return fields

    def _full_index_locked(
        self,
        clean: bool = False,
        *,
        policy: ResolvedIndexPolicy,
        discovered_paths: tuple[pathlib.Path, ...] | None = None,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Locked implementation of :meth:`full_index`.

        Args:
            clean: When ``True``, drop and recreate the codebase
                collection up front so schema-level changes (e.g.
                a new embedding dimension) take effect (#68). The default
                ``clean=False`` path is failure-safe: it streams upserts in place and
                purges only the stale chunk IDs after a successful
                rebuild, so an interrupted run never leaves the
                collection empty.
            reporter: Required progress reporter.
            run_control: Cooperative attempt control checked before the clean
                destructive span and delivered after valid collection and
                metadata publication.

        Returns:
            An ``IndexResult`` where ``added`` equals the total chunk
            count and ``removed`` reports the post-stream stale-chunk
            purge count.

        Raises:
            OSError: If source files cannot be read or hashed.
        """
        start = time.time()
        paths = self._prepare_full_paths(
            policy,
            reporter,
            discovered_paths=discovered_paths,
            run_control=run_control,
        )
        previous_metadata = self._load_meta()
        preserved_metadata, preserved_ids, effective_clean = (
            self._prepare_disabled_full_preservation(
                policy,
                previous_metadata,
                clean=clean,
            )
        )
        limits = self._resolve_code_pipeline_limits()
        checkpoint = self._lifecycle.open_checkpoint(
            policy=policy,
            operation=RunOperation.FULL,
            clean=effective_clean,
            configuration=limits.run_configuration,
            dense_dimensions=limits.dense_dimension,
            sparse_enabled=limits.sparse_enabled,
            run_control=run_control,
        )
        resumed_publication = self._resume_pending_finalization(
            checkpoint,
            reporter=reporter,
            started_at=start,
        )
        if resumed_publication is not None:
            return resumed_publication
        clean_has_confirmed_units = (
            effective_clean
            and next(
                checkpoint.ledger.iter_units(checkpoint.generation_id),
                None,
            )
            is not None
        )

        if effective_clean:
            # Build beside the served collection, never into it. The served one
            # keeps answering searches for the whole build, and an interrupted
            # build leaves this collection unreferenced rather than leaving the
            # served one truncated.
            self._code_build_target = generation_code_collection(
                self.store.CODE_TABLE_NAME, checkpoint.generation_id
            )

        # Failure-safe rebuild (mirrors VaultIndexer.full_index): snapshot the
        # existing chunk ids BEFORE streaming, keep the old chunks live, and
        # purge only the ids absent from the new corpus afterwards. When
        # ``clean=True`` is passed, ALSO drop the collection up front so
        # schema-level changes (e.g. a new embedding dimension) take effect
        # (#68). The snapshot must precede the pipeline because the
        # pipeline upserts as it goes; an empty tree still falls through to the
        # purge below so a rebuild after deleting every source file clears the
        # old collection.
        # A request already pending is delivered by ``protected`` before a
        # clean collection can be dropped. Once the drop begins, defer new
        # requests through recreation, the bounded producer/consumer pipeline,
        # stale cleanup, and atomic metadata publication. Non-clean rebuilding
        # remains failure-safe and interruptible between bounded slices.
        publication_span = (
            checkpoint.run_policy.protected("clean code publication")
            if effective_clean
            else contextlib.nullcontext()
        )
        with checkpoint.preserve_incomplete_generation(), publication_span:
            reporter.phase_start("prepare collection", 1)
            try:
                if effective_clean and not clean_has_confirmed_units:
                    # A fresh generation name cannot collide with a surviving
                    # directory, so this creates rather than recreates and the
                    # served collection is left alone.
                    self.store.ensure_code_table(self._code_build_target)
                    # The generation is new: the snapshot is empty by
                    # construction, and a full id scan of a large local
                    # collection costs minutes of GIL-holding CPU.
                    existing_ids_before: set[str] = set()
                else:
                    self.store.ensure_code_table(self._code_build_target)
                    try:
                        existing_ids_before = set(
                            self.store.get_all_code_ids(self._code_build_target)
                        )
                    except (OSError, RuntimeError):
                        logger.warning(
                            "Could not snapshot existing code-chunk IDs "
                            "before rebuild; stale-chunk purge will be "
                            "skipped",
                            exc_info=True,
                        )
                        existing_ids_before = set()
                reporter.advance(1)
            finally:
                reporter.phase_end()
            run_control.checkpoint()

            # Pipelined chunk -> embed: process-pool workers read, hash, and chunk
            # files while the single in-process GPU consumer encodes and upserts
            # completed slices, so the GPU never idles waiting for the whole tree
            # to be chunked (#155). The workers return the content hash
            # from the same read, so ``meta`` needs no separate hash pass.
            new_ids, total_chunks, meta = self._pipeline_chunk_and_embed(
                paths,
                reporter=reporter,
                checkpoint=checkpoint,
                limits=limits,
                ingest_wait=False,
                run_control=run_control,
            )
            new_ids.update(
                existing_ids_before if preserved_ids is None else preserved_ids
            )
            meta.update(preserved_metadata)

            run_control.checkpoint()
            # The rebuild streamed its upserts without the per-slice apply
            # handshake; nothing terminal may proceed until the store has
            # proven every acknowledged point actually applied. Before the
            # purge the collection must hold exactly the union of the
            # pre-existing snapshot and everything this run published.
            self.store.apply_ingest_barrier(
                self._code_build_target or self.store.CODE_TABLE_NAME,
                expected_points=len(new_ids | existing_ids_before),
                write_policy=checkpoint.run_policy.store_write_policy,
            )
            run_control.checkpoint()
            stale_ids = self._reconcile_full_stale_ids(
                checkpoint=checkpoint,
                previous_metadata=previous_metadata,
                metadata=meta,
                existing_ids=existing_ids_before,
                retained_ids=new_ids,
                reporter=reporter,
            )

            reporter.phase_start("write metadata", 1)
            try:
                reconcile_generation_storage(
                    self.store,
                    checkpoint,
                    policy,
                    ContentKind.CODE,
                )
                build_target = self._code_build_target

                def _record_breadth() -> None:
                    checkpoint.publish_metadata(
                        self._meta_path,
                        published_points=self.store.count_code(build_target),
                        published_files=self.store.count_code_files(build_target),
                    )

                if build_target is None:
                    _record_breadth()
                else:
                    # Breadth first, pointer second - a reader must never
                    # resolve a generation whose published figure is missing.
                    publish_generation_as_served(
                        self.root_dir,
                        collection=build_target,
                        record_breadth=_record_breadth,
                    )
                    # Both collections are complete at this instant: the old one
                    # served throughout and the new one has just reconciled. A
                    # reader mid-flight sees one or the other, never a partial
                    # index, which is what makes this assignment the swap rather
                    # than a race.
                    self.store.CODE_TABLE_NAME = build_target
                checkpoint.publish_generation()
                reporter.advance(1)
            finally:
                reporter.phase_end()
        run_control.checkpoint()

        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=self.store.count_code(),
            added=total_chunks,
            updated=0,
            # Mirror VaultIndexer.full_index - surface the post-stream
            # purge count so MCP / CLI clients can observe how many
            # stale chunks were swept (#68).
            removed=len(stale_ids),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(paths),
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
            reuse=self._reuse_snapshot(),
            drift=self._lifecycle.drift_snapshot(),
        )

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        preflight: CodeExecutionPreflight,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Incremental codebase re-index serialized through the writer lock.

        Thin wrapper that acquires ``self._writer_lock`` and delegates
        to :meth:`_incremental_index_locked`. Mirrors VaultIndexer
        and serializes concurrent reindex callers (#68).

        Args:
            reporter: Required progress reporter.
            changed_paths: When provided, only the given filesystem paths
                are reconciled (scoped reindex, #151). Work becomes
                proportional to the change set rather than the whole tree.
                When ``None`` the full ``.gitignore``-aware scan runs.
        """
        run_control.checkpoint()
        resolved_policy, discovered_paths = self._accept_preflight(
            preflight,
            changed_paths=changed_paths,
        )
        run_control.checkpoint()
        with self._writer_lock:
            self._resolved_policy = resolved_policy
            self._reset_reuse_state()
            return run_index_lifecycle(
                lambda: self._incremental_index_locked(
                    policy=resolved_policy,
                    reporter=reporter,
                    changed_paths=changed_paths,
                    discovered_paths=(
                        discovered_paths if changed_paths is None else None
                    ),
                    run_control=run_control,
                ),
                event_logger=logger,
                store=self.store,
                source="code",
                mode=(
                    "scoped_incremental" if changed_paths is not None else "incremental"
                ),
                clean=False,
                root=self.root_dir,
                run_control=run_control,
                completion_fields=self._completed_event_fields,
            )

    def _incremental_index_locked(
        self,
        *,
        policy: ResolvedIndexPolicy,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        discovered_paths: tuple[pathlib.Path, ...] | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Locked implementation of cooperative incremental indexing."""
        run_control.checkpoint()
        if self._lifecycle.published_evidence_lost():
            # The predicate has already logged which branch fired and, for a
            # shortfall, both counts. Naming only the absent-collection case
            # here would contradict it on the commoner path.
            logger.warning(
                "storage no longer backs the published code index metadata; "
                "running a full failure-safe reconciliation instead of "
                "trusting the carried evidence"
            )
            return self._full_index_locked(
                clean=False,
                policy=policy,
                discovered_paths=discovered_paths,
                reporter=reporter,
                run_control=run_control,
            )
        needs_embed_rebuild = self._needs_embed_rebuild()
        run_control.checkpoint()
        if needs_embed_rebuild:
            logger.info(
                "Codebase embedding input format changed; rebuilding the code index "
                "into a new generation",
            )
            return self._full_index_locked(
                clean=True,
                policy=policy,
                discovered_paths=discovered_paths,
                reporter=reporter,
                run_control=run_control,
            )
        changed_paths, escalate_clean = self._config_drift_dispatch(
            changed_paths,
            policy,
            run_control=run_control,
        )
        if escalate_clean:
            logger.info(
                "Codebase content-shaping config changed; rebuilding the code index "
                "into a new generation",
            )
            return self._full_index_locked(
                clean=True,
                policy=policy,
                discovered_paths=discovered_paths,
                reporter=reporter,
                run_control=run_control,
            )
        if changed_paths is not None:
            return self._scoped_incremental_locked(
                changed_paths=changed_paths,
                policy=policy,
                reporter=reporter,
                run_control=run_control,
            )

        start = time.time()
        self._begin_preprocess_run(policy, run_control=run_control)
        run_control.checkpoint()
        previous_metadata = self._load_meta()
        run_control.checkpoint()
        current_files, current_hashes = self._scan_and_hash_incremental_inputs(
            policy,
            reporter,
            discovered_paths=discovered_paths,
            run_control=run_control,
        )
        disabled_current = {
            rel for rel in current_files if self._disabled_transform(policy, rel)
        }
        for rel in disabled_current:
            self._mark_preprocess_stale(rel)
            current_files.pop(rel, None)
            current_hashes.pop(rel, None)
        current_hashes.update(
            self._preserved_disabled_metadata(policy, previous_metadata)
        )
        previous_files = set(previous_metadata)
        current_names = set(current_hashes)
        new_files = current_names - previous_files
        deleted_files = previous_files - current_names
        modified_files = {
            rel
            for rel in current_names & previous_files
            if current_hashes[rel] != previous_metadata.get(rel)
        }
        to_index = new_files | modified_files
        paths_to_index = [current_files[rel] for rel in sorted(to_index)]
        attempted_paths = to_index | deleted_files
        if not attempted_paths:
            return self._unchanged_incremental_result(started_at=start)
        limits = self._resolve_code_pipeline_limits()
        try:
            checkpoint = self._lifecycle.open_checkpoint(
                policy=policy,
                operation=RunOperation.INCREMENTAL,
                clean=False,
                configuration=limits.run_configuration,
                dense_dimensions=limits.dense_dimension,
                sparse_enabled=limits.sparse_enabled,
                run_control=run_control,
            )
        except RunLedgerCompatibilityError:
            logger.info(
                "No compatible published code manifest; running a full "
                "failure-safe reconciliation"
            )
            return self._full_index_locked(
                clean=False,
                policy=policy,
                discovered_paths=discovered_paths,
                reporter=reporter,
                run_control=run_control,
            )
        resumed_publication = self._resume_pending_finalization(
            checkpoint,
            reporter=reporter,
            started_at=start,
        )
        if resumed_publication is not None:
            return resumed_publication
        run_control.checkpoint()
        # Scoped to the paths this run re-ingests: re-opening anything else
        # would drop its points without republishing them.
        self._lifecycle.drift_owner.supersede_snapshot(
            {rel: current_hashes[rel] for rel in to_index}
        )
        run_control.checkpoint()
        prior_ids_by_path = self._incremental_prior_ids_by_path(
            checkpoint,
            attempted_paths,
        )
        existing_ids: set[str] = (
            set(self._get_chunk_ids_for_files(attempted_paths))
            if attempted_paths
            else set()
        )
        run_control.checkpoint()
        published_ids, published_hashes = self._publish_incremental_paths(
            paths=paths_to_index,
            attempted_paths=attempted_paths,
            existing_ids=existing_ids,
            reporter=reporter,
            checkpoint=checkpoint,
            limits=limits,
            run_control=run_control,
        )
        current_hashes.update(published_hashes)
        self._commit_incremental_replacement(
            policy=policy,
            existing_ids=existing_ids,
            published_ids=published_ids,
            prior_ids_by_path=prior_ids_by_path,
            deleted_paths=deleted_files,
            checkpoint=checkpoint,
            metadata=current_hashes,
            files_count=len(attempted_paths),
            protect_replacement=bool(modified_files or deleted_files),
            reporter=reporter,
            run_control=run_control,
        )
        total = self.store.count_code()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_files),
            updated=len(modified_files),
            removed=len(deleted_files),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(to_index),
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
            reuse=self._reuse_snapshot(),
            drift=self._lifecycle.drift_snapshot(),
        )

    def _scan_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
        reporter: ProgressReporter,
        policy: ResolvedIndexPolicy,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[dict[str, pathlib.Path], set[str]]:
        run_control.checkpoint()
        reporter.phase_start("scan changed", None)
        to_hash: dict[str, pathlib.Path] = {}
        delete_files: set[str] = set()
        try:
            for path in changed_paths:
                run_control.checkpoint()
                self._process_changed_path(
                    path,
                    policy,
                    to_hash,
                    delete_files,
                    run_control=run_control,
                )
                run_control.checkpoint()
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        return to_hash, delete_files

    def _process_changed_path(
        self,
        path: pathlib.Path,
        policy: ResolvedIndexPolicy,
        to_hash: dict[str, pathlib.Path],
        delete_files: set[str],
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> None:
        run_control.checkpoint()
        try:
            rel = str(path.relative_to(self.root_dir)).replace("\\", "/")
        except ValueError:
            return
        if path.is_file():
            classified = self._classify_file(path, rel, policy)
            disposition = classified.disposition
            if self._disabled_transform(policy, rel):
                self._mark_preprocess_stale(rel)
                return
            if disposition.admitted and disposition.kind is ContentKind.CODE:
                to_hash[rel] = path
                return
        delete_files.add(rel)
        run_control.checkpoint()

    def _hash_changed_paths(
        self,
        to_hash: dict[str, pathlib.Path],
        reporter: ProgressReporter,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> dict[str, str]:
        """Hash a path mapping, pruning entries that cannot be read.

        ``to_hash`` is pruned in place so it stays keyed exactly like the
        returned digests; callers index one by the other.
        """
        run_control.checkpoint()
        reporter.phase_start("hash files", len(to_hash))
        changed_hashes: dict[str, str] = {}
        try:
            for rel, path in to_hash.items():
                run_control.checkpoint()
                try:
                    with open(path, "rb") as f:
                        changed_hashes[rel] = hashlib.file_digest(
                            f,
                            "blake2b",
                        ).hexdigest()
                except OSError:
                    logger.warning("Cannot hash file, skipping: %s", rel)
                reporter.advance()
                run_control.checkpoint()
        finally:
            reporter.phase_end()
        run_control.checkpoint()
        for rel in set(to_hash) - set(changed_hashes):
            del to_hash[rel]
        return changed_hashes

    def _scoped_incremental_locked(
        self,
        *,
        changed_paths: Iterable[pathlib.Path],
        policy: ResolvedIndexPolicy,
        reporter: ProgressReporter,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Reconcile only changed paths through the weighted pipeline."""
        start = time.time()
        self._begin_preprocess_run(policy, run_control=run_control)
        run_control.checkpoint()
        previous_metadata = self._load_meta()
        run_control.checkpoint()
        to_hash, delete_files = self._scan_changed_paths(
            changed_paths,
            reporter,
            policy,
            run_control=run_control,
        )
        changed_hashes = self._hash_changed_paths(
            to_hash, reporter, run_control=run_control
        )
        new_files = {rel for rel in changed_hashes if rel not in previous_metadata}
        modified_files = {
            rel
            for rel in changed_hashes
            if (
                rel in previous_metadata
                and changed_hashes[rel] != previous_metadata.get(rel)
            )
        }
        to_index = new_files | modified_files
        paths_to_index = [to_hash[rel] for rel in sorted(to_index)]
        attempted_paths = to_index | delete_files
        if not attempted_paths:
            return self._unchanged_incremental_result(started_at=start)
        limits = self._resolve_code_pipeline_limits()
        try:
            checkpoint = self._lifecycle.open_checkpoint(
                policy=policy,
                operation=RunOperation.SCOPED_INCREMENTAL,
                clean=False,
                configuration=limits.run_configuration,
                dense_dimensions=limits.dense_dimension,
                sparse_enabled=limits.sparse_enabled,
                run_control=run_control,
            )
        except RunLedgerCompatibilityError:
            logger.info(
                "No compatible published code manifest; running a full "
                "failure-safe reconciliation"
            )
            return self._full_index_locked(
                clean=False,
                policy=policy,
                reporter=reporter,
                run_control=run_control,
            )
        resumed_publication = self._resume_pending_finalization(
            checkpoint,
            reporter=reporter,
            started_at=start,
        )
        if resumed_publication is not None:
            return resumed_publication
        run_control.checkpoint()
        # Scoped to the paths this run re-ingests: re-opening anything else
        # would drop its points without republishing them.
        self._lifecycle.drift_owner.supersede_snapshot(
            {rel: changed_hashes[rel] for rel in to_index}
        )
        run_control.checkpoint()
        prior_ids_by_path = self._incremental_prior_ids_by_path(
            checkpoint,
            attempted_paths,
        )
        existing_ids: set[str] = (
            set(self._get_chunk_ids_for_files(attempted_paths))
            if attempted_paths
            else set()
        )
        run_control.checkpoint()
        published_ids, published_hashes = self._publish_incremental_paths(
            paths=paths_to_index,
            attempted_paths=attempted_paths,
            existing_ids=existing_ids,
            reporter=reporter,
            checkpoint=checkpoint,
            limits=limits,
            run_control=run_control,
        )
        new_metadata = dict(previous_metadata)
        new_metadata.update(published_hashes)
        for rel in delete_files:
            new_metadata.pop(rel, None)
        self._commit_incremental_replacement(
            policy=policy,
            existing_ids=existing_ids,
            published_ids=published_ids,
            prior_ids_by_path=prior_ids_by_path,
            deleted_paths=delete_files,
            checkpoint=checkpoint,
            metadata=new_metadata,
            files_count=len(attempted_paths),
            protect_replacement=bool(modified_files or delete_files),
            reporter=reporter,
            run_control=run_control,
        )
        total = self.store.count_code()
        duration_ms = int((time.time() - start) * 1000)
        return IndexResult(
            total=total,
            added=len(new_files),
            updated=len(modified_files),
            removed=len(delete_files.intersection(previous_metadata)),
            duration_ms=duration_ms,
            device=self.model.device,
            files=len(to_index),
            preprocess_ok=self._prep_ok,
            preprocess_skipped=len(self._prep_skips),
            preprocess_failures=list(self._prep_skips),
            reuse=self._reuse_snapshot(),
            drift=self._lifecycle.drift_snapshot(),
        )

    def _get_chunk_ids_for_files(
        self,
        rel_paths: set[str],
    ) -> list[str]:
        """Return chunk IDs from the store that belong to the given files.

        Args:
            rel_paths: Set of file paths (relative to the project
                root) whose chunk IDs should be retrieved.

        Returns:
            List of chunk ID strings stored for the given files.
        """
        return self.store.get_code_ids_by_paths(rel_paths)

    def _needs_embed_rebuild(self) -> bool:
        """Return True when stored vectors predate the embed-input format.

        Chunk vectors embed a locational header alongside the chunk
        text; older stores embedded the bare chunk text. Mixing the two
        regimes (and querying them with the current instruction prompt)
        silently degrades retrieval, so a marker mismatch triggers a
        one-time clean rebuild. A missing sidecar over a non-empty
        collection is treated the same way.
        """
        return _code_meta.needs_embed_rebuild(
            self._read_meta_raw(), self.store.count_code
        )

    def _write_meta(
        self,
        meta: dict[str, str],
        *,
        policy: ResolvedIndexPolicy,
        published_points: int | None = None,
        published_files: int | None = None,
    ) -> None:
        """Atomically write content-hash metadata to the sidecar JSON file.

        Uses write-to-temp + ``os.replace`` so a crash mid-write never
        corrupts the metadata file. The current embedding-input format
        version is stamped under a reserved key so later runs can
        detect format changes.

        Args:
            meta: Mapping of relative file path to blake2b hex digest.
            policy: Exact snapshot whose identity governs publication. Direct
                callers must resolve and supply it explicitly.
            published_points: Collection point count observed after storage
                reconciliation, recording how much breadth this sidecar
                describes. Omitted where the caller has no reconciled count to
                offer, which leaves the sidecar silent on breadth rather than
                stamping a figure nothing verified.

        Raises:
            OSError: If the metadata directory cannot be created or the
                file cannot be written.
        """
        membership, content = self._compute_code_epochs(policy)
        stamped = {**meta, EMBED_SCHEMA_KEY: CODE_EMBED_SCHEMA}
        stamped[MEMBERSHIP_EPOCH_KEY] = membership
        stamped[CONTENT_EPOCH_KEY] = content
        if published_points is not None:
            stamped[PUBLISHED_POINTS_KEY] = str(published_points)
        # Stamped on the incremental path too, so a sidecar this writer
        # produces is comparable rather than reading as "cannot tell".
        if published_files is not None:
            stamped[PUBLISHED_FILES_KEY] = str(published_files)
        write_json_atomically(self._meta_path, stamped, indent=2)

    def _read_meta_raw(self) -> dict[str, str]:
        """Load the sidecar JSON verbatim, reserved keys included."""
        return _code_meta.read_meta_raw(self._meta_path)

    def _load_meta(self) -> dict[str, str]:
        """Load codebase index metadata from the sidecar JSON file.

        Reserved dunder keys (the embed-format marker) are stripped so
        they can never participate in file-path set arithmetic - the
        marker would otherwise be counted as a deleted file on every
        incremental run.

        Returns:
            Mapping of relative file path to blake2b hex digest, or
            an empty dict if the file does not exist or cannot be
            parsed.
        """
        return _code_meta.load_meta(self._meta_path)
