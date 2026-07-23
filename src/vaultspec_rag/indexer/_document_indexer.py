"""Independent full and incremental indexing for explicitly routed documents."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .._job_errors import JobError, JobErrorKind
from ..index_profiles import get_index_support_profile
from ..job_control import NO_RUN_CONTROL
from . import _chunk_worker, _preprocess_glue
from ._content_policy import ContentKind, RootContentPolicy, SourceProfileVersion
from ._document_checkpoint import DocumentRunCheckpoint, DocumentRunConfiguration
from ._document_meta import (
    DocumentFileMetadata,
    document_meta_compatible,
    document_metadata_path,
    read_document_meta,
)
from ._file_state import FileStateKind
from ._route_migration import reconcile_generation_storage
from ._run_ledger import FinalizationPhase, RunOperation
from ._run_policy import RunPolicy
from ._streaming import (
    encode_and_upsert_document_slice,
    iter_weighted_document_slices,
)
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..embeddings import EmbeddingModel
    from ..index_profiles import SupportProfileLimits
    from ..job_control import RunControl
    from ..memory_probe import MemoryBudget, MemoryBudgetSnapshot
    from ..progress import ProgressReporter
    from ..store import VaultStore
    from ._preprocess_config import PreprocessContext
    from ._resolved_policy import ResolvedIndexPolicy

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
    rss_ceiling_mb: float | None = None
    cuda_ceiling_mb: float | None = None
    enforce_cuda: bool = True
    generated_chunks: int = 0
    weighted_bytes: int = 0
    extracted_bytes: int = 0
    rss_bytes: int = 0
    cuda_bytes: int = 0
    memory_budget: MemoryBudget = field(init=False)

    def __post_init__(self) -> None:
        from ..memory_probe import MemoryBudget

        mib = 1024**2
        rss_ceiling_mb = (
            self.limits.rss_bytes / mib
            if self.rss_ceiling_mb is None
            else self.rss_ceiling_mb
        )
        cuda_ceiling_mb = (
            self.limits.cuda_bytes / mib
            if self.cuda_ceiling_mb is None
            else self.cuda_ceiling_mb
        )
        self.memory_budget = MemoryBudget(
            rss_ceiling_mb=rss_ceiling_mb,
            cuda_ceiling_mb=cuda_ceiling_mb if self.enforce_cuda else None,
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
        """Project a budget snapshot into profile-compatible byte counters.

        The CUDA dimension projects the allocated high-water (demand), not
        reserved: the profile limit can equal the enforcement ceiling, and
        reserved ratchets with allocator retention history, so projecting it
        would fail well-sized jobs through the corpus-limit dimension.
        """
        self.rss_bytes = max(self.rss_bytes, int(snapshot.peak_rss_mb * 1024**2))
        self.cuda_bytes = max(
            self.cuda_bytes,
            int(snapshot.peak_cuda_allocated_mb * 1024**2),
        )

    def record_runtime_resources(
        self,
        *,
        rss_bytes: int,
        cuda_bytes: int,
        cuda_allocated_bytes: int | None = None,
        label: str = "document supplied resource observation",
    ) -> None:
        """Record measured peaks and enforce both independent ceilings."""
        allocated_bytes = (
            cuda_bytes if cuda_allocated_bytes is None else cuda_allocated_bytes
        )
        try:
            snapshot = self.memory_budget.observe(
                label=label,
                rss_mb=rss_bytes / 1024**2,
                cuda_allocated_mb=allocated_bytes / 1024**2,
                cuda_reserved_mb=cuda_bytes / 1024**2,
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


class DocumentIndexer:
    """Index only paths explicitly admitted to the document domain."""

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
        self.root_dir = root_dir.resolve()
        self.model = model
        self.store = store
        self._gpu_lock = gpu_lock
        self._extra_excludes = tuple(extra_excludes or ())
        self._content_policy = content_policy or RootContentPolicy(
            SourceProfileVersion.CONVENTIONAL_V1
        )
        self._writer_lock = threading.RLock()
        from ..config import get_config

        self._data_root = self.root_dir / get_config().data_dir
        self._meta_path = document_metadata_path(self.root_dir)
        self._last_checkpoint: DocumentRunCheckpoint | None = None
        self._memory_budget: MemoryBudget | None = None

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
        from ._resolved_policy import resolve_index_policy

        return resolve_index_policy(
            self.root_dir,
            content_policy=self._content_policy,
            extra_excludes=self._extra_excludes,
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
        return tuple(sorted(discovered, key=lambda path: path.as_posix()))

    def preflight_content(
        self,
        *,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> DocumentIndexPreflight:
        """Resolve policy and document discovery before any mutable resource."""
        run_control.checkpoint()
        policy = self.resolve_policy_snapshot()
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
    def _hash_path(path: pathlib.Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "blake2b").hexdigest()

    @staticmethod
    def _support_limits() -> SupportProfileLimits:
        from ..config import get_config

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
        from ..config import get_config
        from ..memory_probe import reset_cuda_peak_memory_stats

        config = get_config()
        mib = 1024**2
        uses_cuda = getattr(self.model, "device", None) == "cuda"
        if uses_cuda:
            reset_cuda_peak_memory_stats()
        budget = _DocumentResourceBudget(
            limits,
            rss_ceiling_mb=min(config.index_rss_ceiling_mb, limits.rss_bytes / mib),
            cuda_ceiling_mb=min(
                config.index_cuda_ceiling_mb,
                limits.cuda_bytes / mib,
            ),
            enforce_cuda=uses_cuda,
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
        policy: ResolvedIndexPolicy,
        prep: PreprocessContext | None,
        budget: _DocumentResourceBudget,
        checkpoint: DocumentRunCheckpoint,
        reporter: ProgressReporter,
        run_control: RunControl,
    ) -> tuple[DocumentFileMetadata | None, int, str | None]:
        """Chunk and publish one document, returning durable file evidence."""
        from ._run_policy import RunPolicy

        run_control.checkpoint()
        budget.checkpoint_runtime_resources(f"{path.name} before extraction")
        extractor_policy = RunPolicy.from_config(run_control=run_control)
        result = _chunk_worker.stream_document_and_hash_file(
            path,
            self.root_dir,
            prep,
            self._execution_policy(policy),
            run_control,
            lambda: extractor_policy.checkpoint("document extractor polling"),
        )
        if result.preprocess_status == "skipped":
            reason = result.preprocess_reason or "document extraction skipped"
            checkpoint.record_processing_failure(
                result.rel_path,
                FileStateKind.EXTRACT_RETRYABLE,
                reason,
                content_hash=result.content_hash,
            )
            return None, 0, f"{result.rel_path}: {reason}"
        from ..config import get_config

        cfg = get_config()
        slice_size = max(1, int(cfg.embedding_batch_size))
        weighted_slices = iter_weighted_document_slices(
            result.chunks,
            max_chunks=slice_size,
            run_control=run_control,
        )
        point_ids: list[str] = []
        reporter.phase_start("embed + upsert document chunks", None)
        try:
            iterator = iter(weighted_slices)
            weighted = next(iterator, None)
            ordinal = 0
            while weighted is not None:
                run_control.checkpoint()
                following = next(iterator, None)
                selected = list(weighted.chunks)
                budget.reserve(
                    len(selected),
                    weighted.estimated_bytes,
                    sum(
                        len(chunk.payload.content.encode("utf-8")) for chunk in selected
                    ),
                )
                budget.checkpoint_runtime_resources(
                    f"{result.rel_path} slice-{ordinal} before encode"
                )
                unit = checkpoint.unit_for(
                    result.rel_path,
                    result.content_hash,
                    ordinal,
                    is_file_end=following is None,
                    point_ids=tuple(chunk.id for chunk in selected),
                )
                if not checkpoint.slice_committed(unit):
                    self.store.disk_headroom_preflight(len(selected))

                    def _after_forward(
                        kind: str,
                        slice_ordinal: int = ordinal,
                    ) -> None:
                        run_control.checkpoint()
                        budget.checkpoint_runtime_resources(
                            f"{result.rel_path} slice-{slice_ordinal} "
                            f"after-{kind}-forward"
                        )
                        run_control.checkpoint()

                    def _on_cuda_oom(
                        exc: BaseException,
                        slice_ordinal: int = ordinal,
                    ) -> None:
                        budget.fail_cuda_oom(
                            f"{result.rel_path} slice-{slice_ordinal} allocator-oom",
                            exc,
                        )

                    encode_and_upsert_document_slice(
                        selected,
                        model=self.model,
                        store=self.store,
                        gpu_lock=self._gpu_lock,
                        encode_batch_size=int(cfg.embedding_encode_batch_size),
                        write_policy=checkpoint.run_policy.store_write_policy,
                        after_forward=_after_forward,
                        on_cuda_oom=_on_cuda_oom,
                        run_control=run_control,
                    )
                    checkpoint.record_confirmed_slice(unit)
                    budget.checkpoint_runtime_resources(
                        f"{result.rel_path} slice-{ordinal} after store"
                    )
                point_ids.extend(chunk.id for chunk in selected)
                reporter.advance(len(selected))
                ordinal += 1
                weighted = following
        finally:
            reporter.phase_end()
        if not point_ids:
            checkpoint.record_processing_failure(
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
        from ..config import get_config

        config = get_config()
        sparse_enabled = bool(config.sparse_enabled)
        sparse_dimension_value = getattr(self.model, "sparse_dimension", None)
        if sparse_enabled:
            if type(sparse_dimension_value) is not int or sparse_dimension_value <= 0:
                raise RuntimeError("loaded sparse model has no valid output dimension")
            sparse_dimension = sparse_dimension_value
        else:
            sparse_dimension = 1
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
                encode_batch_size=int(config.embedding_encode_batch_size),
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
            started=started,
            added=0,
            updated=0,
            removed=0,
            files=0,
            preprocess_ok=0,
            failures=[],
        )

    def _finish_result(
        self,
        *,
        started: float,
        added: int,
        updated: int,
        removed: int,
        files: int,
        preprocess_ok: int,
        failures: list[str],
    ) -> IndexResult:
        return IndexResult(
            total=self.store.count_document(),
            added=added,
            updated=updated,
            removed=removed,
            duration_ms=int((time.monotonic() - started) * 1000),
            device=str(getattr(self.model, "device", "unknown")),
            files=files,
            preprocess_ok=preprocess_ok,
            preprocess_skipped=len(failures),
            preprocess_failures=failures,
        )

    def _publish_full_paths(
        self,
        paths: tuple[pathlib.Path, ...],
        *,
        policy: ResolvedIndexPolicy,
        prep: PreprocessContext | None,
        budget: _DocumentResourceBudget,
        checkpoint: DocumentRunCheckpoint,
        previous_files: dict[str, DocumentFileMetadata],
        reporter: ProgressReporter,
        run_control: RunControl,
    ) -> tuple[list[DocumentFileMetadata], _DocumentRunCounts, list[str]]:
        """Publish a full discovered set while retaining failed prior points."""
        published: list[DocumentFileMetadata] = []
        counts = _DocumentRunCounts()
        failures: list[str] = []
        for path in paths:
            rel = path.relative_to(self.root_dir).as_posix()
            if policy.execution_mode == "off" and policy.match_preprocess(rel):
                retained = previous_files.get(rel)
                if retained is not None:
                    published.append(retained)
                failures.append(
                    f"{rel}: preprocessing disabled; retained work as stale"
                )
                continue
            metadata, chunk_count, failure = self._publish_file(
                path,
                policy=policy,
                prep=prep,
                budget=budget,
                checkpoint=checkpoint,
                reporter=reporter,
                run_control=run_control,
            )
            if failure is not None:
                failures.append(failure)
                retained = previous_files.get(rel)
                if retained is not None:
                    published.append(retained)
                continue
            assert metadata is not None
            published.append(metadata)
            if rel in previous_files:
                counts.updated += chunk_count
            else:
                counts.added += chunk_count
            if policy.match_preprocess(rel) is not None:
                counts.preprocess_ok += 1
        return published, counts, failures

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
        selected = {
            rel
            for rel, path in discovered.items()
            if rel not in previous_files
            or self._hash_path(path) != previous_files[rel].content_fingerprint
        }
        selected.update(set(previous_files) - set(discovered))
        return selected

    def _reconcile_incremental_paths(
        self,
        selected: set[str],
        *,
        policy: ResolvedIndexPolicy,
        prep: PreprocessContext | None,
        budget: _DocumentResourceBudget,
        checkpoint: DocumentRunCheckpoint,
        previous_files: dict[str, DocumentFileMetadata],
        reporter: ProgressReporter,
        run_control: RunControl,
    ) -> tuple[dict[str, DocumentFileMetadata], _DocumentRunCounts, list[str]]:
        """Apply one selected incremental set under the document writer lock."""
        current = dict(previous_files)
        counts = _DocumentRunCounts()
        failures: list[str] = []
        for rel in sorted(selected):
            path = self.root_dir / pathlib.PurePosixPath(rel)
            disposition = policy.classify(rel).disposition
            admitted = disposition.admitted and disposition.kind is ContentKind.DOCUMENT
            if not path.is_file() or not admitted:
                old = current.pop(rel, None)
                if old is not None:
                    self.store.delete_document_content_chunks(list(old.point_ids))
                    checkpoint.record_confirmed_deletion(rel, old.point_ids)
                    counts.removed += len(old.point_ids)
                continue
            if policy.execution_mode == "off" and policy.match_preprocess(rel):
                failures.append(
                    f"{rel}: preprocessing disabled; retained work as stale"
                )
                continue
            old = current.get(rel)
            metadata, chunk_count, failure = self._publish_file(
                path,
                policy=policy,
                prep=prep,
                budget=budget,
                checkpoint=checkpoint,
                reporter=reporter,
                run_control=run_control,
            )
            if failure is not None:
                failures.append(failure)
                continue
            assert metadata is not None
            current[rel] = metadata
            self._replace_incremental_metadata(
                current,
                rel=rel,
                old=old,
                metadata=metadata,
                chunk_count=chunk_count,
                counts=counts,
                checkpoint=checkpoint,
            )
            if policy.match_preprocess(rel) is not None:
                counts.preprocess_ok += 1
        return current, counts, failures

    def _replace_incremental_metadata(
        self,
        current: dict[str, DocumentFileMetadata],
        *,
        rel: str,
        old: DocumentFileMetadata | None,
        metadata: DocumentFileMetadata,
        chunk_count: int,
        counts: _DocumentRunCounts,
        checkpoint: DocumentRunCheckpoint,
    ) -> None:
        """Replace one file generation and account for obsolete points."""
        current[rel] = metadata
        obsolete = set(old.point_ids if old else ()) - set(metadata.point_ids)
        if obsolete:
            obsolete_ids = tuple(sorted(obsolete))
            self.store.delete_document_content_chunks(list(obsolete_ids))
            checkpoint.record_confirmed_stale_deletion(rel, obsolete_ids)
            counts.removed += len(obsolete)
        if old is None:
            counts.added += chunk_count
        else:
            counts.updated += chunk_count

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
        limits = self._support_limits()
        prep = self._preprocess_context(policy, limits)
        preprocessing_disabled = policy.execution_mode == "off" and any(
            policy.match_preprocess(path.relative_to(self.root_dir).as_posix())
            is not None
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
        resumed = self._resume_pending_finalization(
            checkpoint,
            reporter=reporter,
            started=started,
        )
        if resumed is not None:
            return resumed
        with self._writer_lock:
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
                if effective_clean and not clean_has_confirmed_units:
                    self.store.drop_document_table()
                self.store.ensure_document_table()
                published, counts, failures = self._publish_full_paths(
                    paths,
                    policy=policy,
                    prep=prep,
                    budget=budget,
                    checkpoint=checkpoint,
                    previous_files=previous_files,
                    reporter=reporter,
                    run_control=run_control,
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
                started=started,
                added=counts.added,
                updated=counts.updated,
                removed=removed,
                files=len(paths),
                preprocess_ok=counts.preprocess_ok,
                failures=failures,
            )

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
        policy, authorized_paths = self._accept_preflight(
            preflight,
            changed_paths=changed_paths,
            run_control=run_control,
        )
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
        if previous is None:
            return self.full_index(
                reporter=reporter,
                preflight=DocumentIndexPreflight(
                    self.root_dir,
                    policy,
                    self._discover(policy, run_control=run_control),
                ),
                run_control=run_control,
            )

        operation = (
            RunOperation.SCOPED_INCREMENTAL
            if changed_paths is not None
            else RunOperation.INCREMENTAL
        )
        checkpoint = self._open_checkpoint(
            policy=policy,
            operation=operation,
            clean=False,
            limits=limits,
            run_control=run_control,
        )
        with checkpoint.preserve_incomplete_generation():
            budget = self._begin_resource_budget(limits)
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
            scoped=changed_paths is not None,
        )

        with self._writer_lock, checkpoint.preserve_incomplete_generation():
            _current, counts, failures = self._reconcile_incremental_paths(
                selected,
                policy=policy,
                prep=prep,
                budget=budget,
                checkpoint=checkpoint,
                previous_files=previous_files,
                reporter=reporter,
                run_control=run_control,
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
                started=started,
                added=counts.added,
                updated=counts.updated,
                removed=counts.removed,
                files=len(selected),
                preprocess_ok=counts.preprocess_ok,
                failures=failures,
            )
