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
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._atomic_write import JsonWriteOptions, write_json_atomically
from .._index_breadth import PUBLISHED_FILES_KEY, PUBLISHED_POINTS_KEY
from .._store_models import (
    generation_code_collection,
    publish_generation_as_served,
)
from ..job_control import NO_RUN_CONTROL
from . import _chunk_worker, _code_meta, _preprocess_glue
from ._chunk_producer import CodeChunkProducer
from ._code_meta import (
    CODE_EMBED_SCHEMA,
    CONTENT_EPOCH_KEY,
    EMBED_SCHEMA_KEY,
    MEMBERSHIP_EPOCH_KEY,
)
from ._consumer_pipeline import (
    CodeConsumerPipeline,
    CodePipelineBindings,
    CodePipelineRun,
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
from ._generation_lifecycle import CodeGenerationLifecycle
from ._incremental_commit import (
    CodeIncrementalCommit,
    IncrementalPublicationRequest,
    IncrementalReplacementRequest,
)
from ._index_lifecycle import preprocess_completion_fields, run_index_lifecycle
from ._route_migration import reconcile_generation_storage
from ._run_ledger_models import RunLedgerCompatibilityError, RunOperation
from ._support_budget import CodeSupportBudget
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    import threading
    from collections.abc import Iterable

    from ..embeddings import EmbeddingModel
    from ..index_profiles import SupportMeasurement
    from ..job_control import RunControl
    from ..memory_probe import MemoryBudgetSnapshot
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._chunk_worker import FileChunkResult
    from ._preprocess_config import (
        PreprocessContext,
    )
    from ._resolved_policy import ResolvedIndexPolicy
    from ._reuse import ReuseStats
    from ._run_checkpoint import CodeRunCheckpoint

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _FullStaleReconciliation:
    """Inputs used to remove stale code identities after a full rebuild."""

    checkpoint: CodeRunCheckpoint
    previous_metadata: dict[str, str]
    metadata: dict[str, str]
    existing_ids: set[str]
    retained_ids: set[str]
    reporter: ProgressReporter


class CodebaseIndexer:
    """Orchestrates source code indexing into the vector store.

    Walks the project tree with ``.gitignore``-aware pruning, chunks source
    files using tree-sitter AST analysis when a grammar is available or
    ``TextSplitter`` as a fallback, generates dense and sparse embeddings,
    and upserts the results into Qdrant. Supports 16+ languages via
    tree-sitter grammars and incremental indexing using blake2b content
    hashing to skip unchanged files.
    """

    @dataclass(frozen=True, slots=True)
    class Options:
        """Optional root-level collaborators and discovery policy."""

        gpu_lock: threading.Lock | None = None
        extra_excludes: list[str] | None = None
        content_policy: RootContentPolicy | None = None

    def __init__(
        self,
        root_dir: pathlib.Path,
        model: EmbeddingModel,
        store: VaultStore,
        options: Options | None = None,
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
        options = options or self.Options()
        self.root_dir = root_dir
        self.model = model
        self.store = store
        self._gpu_lock = options.gpu_lock
        self._extra_excludes = options.extra_excludes or []
        self._content_policy = options.content_policy or RootContentPolicy(
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
        self._resolved_policy: ResolvedIndexPolicy | None = None
        self._support_budget = CodeSupportBudget(self.model)
        self._lifecycle = CodeGenerationLifecycle(
            self.root_dir,
            data_root=self._data_root,
            meta_path=self._meta_path,
            store=self.store,
            load_meta=self._load_meta,
            read_meta_raw=self._read_meta_raw,
        )
        self._consumer_pipeline = CodeConsumerPipeline(
            CodePipelineBindings(
                root_dir=self.root_dir,
                model=self.model,
                store=self.store,
                producer=self._producer,
                lifecycle=self._lifecycle,
                gpu_lock=self._gpu_lock,
                begin_memory_budget=self._support_budget.begin_memory_budget,
                sample_memory_budget=self._support_budget.sample_memory_budget,
                forward_peak_recording=self._support_budget.forward_peak_recording,
                fail_cuda_oom=self._support_budget.fail_cuda_oom,
                begin_support_measurement=self._support_budget.begin_support_measurement,
                measure_code_segments=self._support_budget.measure_code_segments,
                record_extracted_bytes=self._support_budget.record_extracted_bytes,
                record_preprocess_result=self._record_preprocess_result,
            )
        )
        self._incremental_commit = CodeIncrementalCommit(
            self.store,
            self._lifecycle,
            self._meta_path,
            self._pipeline_chunk_and_embed,
            self._write_meta,
        )

    @property
    def support_measurement(self) -> SupportMeasurement:
        """Return the latest immutable code workload measurement snapshot."""
        return self._support_budget.measurement

    @property
    def last_checkpoint(self) -> CodeRunCheckpoint | None:
        """Return the latest run authority for service-domain projection."""
        return self._lifecycle.last_checkpoint

    @property
    def memory_budget_snapshot(self) -> MemoryBudgetSnapshot | None:
        """Return the latest immutable enforced-memory observation."""
        budget = self._support_budget.memory_budget
        return budget.snapshot if budget is not None else None

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

    def _pipeline_chunk_and_embed(
        self,
        paths: list[pathlib.Path],
        run: CodePipelineRun,
    ) -> tuple[set[str], int, dict[str, str]]:
        """Chunk, embed, and upsert *paths* through the consumer pipeline.

        The pipeline itself is stateless across runs; this adapts it to the
        indexer's per-run state, supplying the content epoch and generation
        build target it needs and republishing the donor-reuse telemetry it
        resolved so later result construction can read it back through
        ``_reuse_snapshot``.
        """
        result = self._consumer_pipeline.run(
            paths,
            run,
        )
        self._reuse_stats = result.reuse_stats
        return result.new_ids, result.total, result.metadata

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
        request: _FullStaleReconciliation,
    ) -> list[str]:
        """Delete stale full-run identities and checkpoint removed paths."""
        stale_ids = sorted(request.existing_ids - request.retained_ids)
        removed_paths = set(request.previous_metadata) - set(request.metadata)
        removed_ids_by_path = self._lifecycle.checkpoint_ids_by_path(
            request.checkpoint,
            removed_paths,
            retained=True,
        )
        request.reporter.phase_start("purge stale chunks", len(stale_ids))
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
                    request.checkpoint.record_confirmed_deletion(rel, point_ids)
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
            request.reporter.advance(len(stale_ids))
            return stale_ids
        finally:
            request.reporter.phase_end()

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

    def _prepare_full_collection(
        self,
        _checkpoint: CodeRunCheckpoint,
        *,
        effective_clean: bool,
        clean_has_confirmed_units: bool,
        reporter: ProgressReporter,
    ) -> set[str]:
        """Create or snapshot the build collection before streaming a full run."""
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
                        "before rebuild; stale-chunk purge will be skipped",
                        exc_info=True,
                    )
                    existing_ids_before = set()
            reporter.advance(1)
            return existing_ids_before
        finally:
            reporter.phase_end()

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
        limits = self._consumer_pipeline.resolve_limits()
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
            existing_ids_before = self._prepare_full_collection(
                checkpoint,
                effective_clean=effective_clean,
                clean_has_confirmed_units=clean_has_confirmed_units,
                reporter=reporter,
            )
            run_control.checkpoint()

            # Pipelined chunk -> embed: process-pool workers read, hash, and chunk
            # files while the single in-process GPU consumer encodes and upserts
            # completed slices, so the GPU never idles waiting for the whole tree
            # to be chunked (#155). The workers return the content hash
            # from the same read, so ``meta`` needs no separate hash pass.
            new_ids, total_chunks, meta = self._pipeline_chunk_and_embed(
                paths,
                CodePipelineRun(
                    reporter=reporter,
                    checkpoint=checkpoint,
                    limits=limits,
                    content_epoch=self._content_epoch,
                    code_build_target=self._code_build_target,
                    ingest_wait=False,
                    run_control=run_control,
                ),
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
                _FullStaleReconciliation(
                    checkpoint=checkpoint,
                    previous_metadata=previous_metadata,
                    metadata=meta,
                    existing_ids=existing_ids_before,
                    retained_ids=new_ids,
                    reporter=reporter,
                )
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
        full_rebuild_clean: bool | None = None
        if self._lifecycle.published_evidence_lost():
            # The predicate has already logged which branch fired and, for a
            # shortfall, both counts. Naming only the absent-collection case
            # here would contradict it on the commoner path.
            logger.warning(
                "storage no longer backs the published code index metadata; "
                "running a full failure-safe reconciliation instead of "
                "trusting the carried evidence"
            )
            full_rebuild_clean = False
        else:
            needs_embed_rebuild = self._needs_embed_rebuild()
            run_control.checkpoint()
            if needs_embed_rebuild:
                logger.info(
                    "Codebase embedding input format changed; rebuilding the code "
                    "index into a new generation",
                )
                full_rebuild_clean = True
        if full_rebuild_clean is not None:
            return self._full_index_locked(
                clean=full_rebuild_clean,
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
        limits = self._consumer_pipeline.resolve_limits()
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
        if resumed_publication is None:
            publication = self._incremental_commit.supersede_and_publish(
                IncrementalPublicationRequest(
                    checkpoint=checkpoint,
                    hashes=current_hashes,
                    to_index=to_index,
                    paths_to_index=paths_to_index,
                    attempted_paths=attempted_paths,
                    reporter=reporter,
                    limits=limits,
                    run_control=run_control,
                )
            )
            current_hashes.update(publication.published_hashes)
            self._incremental_commit.commit_replacement(
                IncrementalReplacementRequest(
                    policy=policy,
                    existing_ids=publication.existing_ids,
                    published_ids=publication.published_ids,
                    prior_ids_by_path=publication.prior_ids_by_path,
                    deleted_paths=deleted_files,
                    checkpoint=checkpoint,
                    metadata=current_hashes,
                    files_count=len(attempted_paths),
                    protect_replacement=bool(modified_files or deleted_files),
                    reporter=reporter,
                    run_control=run_control,
                )
            )
            result = IndexResult(
                total=self.store.count_code(),
                added=len(new_files),
                updated=len(modified_files),
                removed=len(deleted_files),
                duration_ms=int((time.time() - start) * 1000),
                device=self.model.device,
                files=len(to_index),
                preprocess_ok=self._prep_ok,
                preprocess_skipped=len(self._prep_skips),
                preprocess_failures=list(self._prep_skips),
                reuse=self._reuse_snapshot(),
                drift=self._lifecycle.drift_snapshot(),
            )
        return resumed_publication if resumed_publication is not None else result

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
        limits = self._consumer_pipeline.resolve_limits()
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
        publication = self._incremental_commit.supersede_and_publish(
            IncrementalPublicationRequest(
                checkpoint=checkpoint,
                hashes=changed_hashes,
                to_index=to_index,
                paths_to_index=paths_to_index,
                attempted_paths=attempted_paths,
                reporter=reporter,
                limits=limits,
                run_control=run_control,
            )
        )
        new_metadata = dict(previous_metadata)
        new_metadata.update(publication.published_hashes)
        for rel in delete_files:
            new_metadata.pop(rel, None)
        self._incremental_commit.commit_replacement(
            IncrementalReplacementRequest(
                policy=policy,
                existing_ids=publication.existing_ids,
                published_ids=publication.published_ids,
                prior_ids_by_path=publication.prior_ids_by_path,
                deleted_paths=delete_files,
                checkpoint=checkpoint,
                metadata=new_metadata,
                files_count=len(attempted_paths),
                protect_replacement=bool(modified_files or delete_files),
                reporter=reporter,
                run_control=run_control,
            )
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
        write_json_atomically(self._meta_path, stamped, JsonWriteOptions(indent=2))

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
