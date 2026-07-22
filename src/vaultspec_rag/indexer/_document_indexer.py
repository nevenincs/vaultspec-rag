"""Independent full and incremental indexing for explicitly routed documents."""

from __future__ import annotations

import hashlib
import os
import pathlib
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .._job_errors import JobError, JobErrorKind
from ..index_profiles import get_index_support_profile
from ..job_control import NO_RUN_CONTROL
from . import _chunk_worker, _preprocess_glue
from ._content_policy import ContentKind, RootContentPolicy, SourceProfileVersion
from ._document_meta import (
    DocumentFileMetadata,
    DocumentIndexMetadata,
    document_meta_compatible,
    document_metadata_path,
    read_document_meta,
    write_document_meta,
)
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
    """Aggregate generated-chunk and weighted-byte ceiling for one operation."""

    limits: SupportProfileLimits
    generated_chunks: int = 0
    weighted_bytes: int = 0

    def reserve(self, chunks: int, weighted_bytes: int) -> None:
        next_chunks = self.generated_chunks + chunks
        next_weight = self.weighted_bytes + weighted_bytes
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
        self.generated_chunks = next_chunks
        self.weighted_bytes = next_weight


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

    def _discover(self, policy: ResolvedIndexPolicy) -> tuple[pathlib.Path, ...]:
        """Return only file paths owned by the document domain."""
        discovered: list[pathlib.Path] = []
        root_text = str(self.root_dir)
        for directory, dirs, files in os.walk(self.root_dir, topdown=True):
            rel_dir = os.path.relpath(directory, root_text).replace("\\", "/")
            prefix = "" if rel_dir == "." else f"{rel_dir}/"
            dirs[:] = [
                name
                for name in dirs
                if not self._ignored_directory(policy, f"{prefix}{name}/")
            ]
            for name in files:
                rel = f"{prefix}{name}"
                disposition = policy.classify(rel).disposition
                if disposition.admitted and disposition.kind is ContentKind.DOCUMENT:
                    discovered.append(pathlib.Path(directory) / name)
        return tuple(sorted(discovered, key=lambda path: path.as_posix()))

    def preflight_content(self) -> DocumentIndexPreflight:
        """Resolve policy and document discovery before any mutable resource."""
        policy = self.resolve_policy_snapshot()
        return DocumentIndexPreflight(self.root_dir, policy, self._discover(policy))

    def _normalize_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
    ) -> tuple[pathlib.Path, ...]:
        normalized = {path.resolve() for path in changed_paths}
        if any(not path.is_relative_to(self.root_dir) for path in normalized):
            raise ValueError("document index scope contains a path outside its root")
        return tuple(sorted(normalized, key=lambda path: path.as_posix()))

    def preflight_changed_paths(
        self,
        changed_paths: Iterable[pathlib.Path],
    ) -> DocumentScopedPreflight:
        """Resolve policy and classify only the exact caller-selected scope."""
        policy = self.resolve_policy_snapshot()
        normalized = self._normalize_changed_paths(changed_paths)
        for path in normalized:
            policy.classify(path.relative_to(self.root_dir).as_posix())
        return DocumentScopedPreflight(self.root_dir, policy, normalized)

    def _accept_preflight(
        self,
        preflight: DocumentExecutionPreflight | None,
        *,
        changed_paths: Iterable[pathlib.Path] | None,
    ) -> tuple[ResolvedIndexPolicy, tuple[pathlib.Path, ...]]:
        authority = preflight or (
            self.preflight_content()
            if changed_paths is None
            else self.preflight_changed_paths(changed_paths)
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
                rel = path.relative_to(self.root_dir).as_posix()
                disposition = authority.policy.classify(rel).disposition
                if not (
                    disposition.admitted and disposition.kind is ContentKind.DOCUMENT
                ):
                    raise ValueError("document preflight contains a non-document path")
            return authority.policy, authority.files
        if changed_paths is None:
            raise ValueError("scoped document preflight requires changed paths")
        normalized = self._normalize_changed_paths(changed_paths)
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

    @staticmethod
    def _execution_policy(
        policy: ResolvedIndexPolicy,
    ) -> _chunk_worker.ChunkExecutionPolicy:
        return _chunk_worker.ChunkExecutionPolicy(
            encoding=policy.decoder.encoding,
            errors=policy.decoder.errors,
            normalize_newlines=policy.decoder.normalize_newlines,
            html_strip=policy.html_strip,
        )

    def _publish_file(
        self,
        path: pathlib.Path,
        *,
        policy: ResolvedIndexPolicy,
        prep: PreprocessContext | None,
        budget: _DocumentResourceBudget,
        reporter: ProgressReporter,
        run_control: RunControl,
    ) -> tuple[DocumentFileMetadata | None, int, str | None]:
        """Chunk and publish one document, returning durable file evidence."""
        run_control.checkpoint()
        result = _chunk_worker.chunk_document_and_hash_file(
            path,
            self.root_dir,
            prep,
            self._execution_policy(policy),
            run_control,
        )
        if result.preprocess_status == "skipped":
            reason = result.preprocess_reason or "document extraction skipped"
            return None, 0, f"{result.rel_path}: {reason}"
        chunks = result.chunks
        if not chunks:
            return None, 0, f"{result.rel_path}: document produced no decodable content"

        from ..config import get_config

        cfg = get_config()
        slice_size = max(1, int(cfg.embedding_batch_size))
        weighted_slices = tuple(
            iter_weighted_document_slices(
                chunks,
                max_chunks=slice_size,
                run_control=run_control,
            )
        )
        budget.reserve(
            len(chunks),
            sum(weighted.estimated_bytes for weighted in weighted_slices),
        )
        self.store.disk_headroom_preflight(len(chunks))
        reporter.phase_start("embed + upsert document chunks", len(chunks))
        try:
            for weighted in weighted_slices:
                run_control.checkpoint()
                selected = list(weighted.chunks)
                encode_and_upsert_document_slice(
                    selected,
                    model=self.model,
                    store=self.store,
                    gpu_lock=self._gpu_lock,
                    encode_batch_size=int(cfg.embedding_encode_batch_size),
                    run_control=run_control,
                )
                reporter.advance(len(selected))
        finally:
            reporter.phase_end()
        return (
            DocumentFileMetadata(
                result.rel_path,
                result.content_hash,
                tuple(chunk.id for chunk in chunks),
            ),
            len(chunks),
            None,
        )

    @staticmethod
    def _metadata(
        policy: ResolvedIndexPolicy,
        files: Iterable[DocumentFileMetadata],
        *,
        complete: bool,
    ) -> DocumentIndexMetadata:
        fingerprints = policy.fingerprints_for(ContentKind.DOCUMENT)
        return DocumentIndexMetadata(
            fingerprints.membership,
            fingerprints.content,
            policy.fingerprints.snapshot,
            tuple(sorted(files, key=lambda item: item.source_path)),
            complete=complete,
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

    @staticmethod
    def _stale_point_ids(
        previous_files: dict[str, DocumentFileMetadata],
        published: Iterable[DocumentFileMetadata],
    ) -> list[str]:
        """Return prior point IDs absent from the new per-path publication."""
        published_by_path = {item.source_path: item for item in published}
        stale_ids: list[str] = []
        for rel, old in previous_files.items():
            current = published_by_path.get(rel)
            if current is None:
                stale_ids.extend(old.point_ids)
            else:
                stale_ids.extend(set(old.point_ids) - set(current.point_ids))
        return stale_ids

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
    ) -> None:
        """Replace one file generation and account for obsolete points."""
        current[rel] = metadata
        obsolete = set(old.point_ids if old else ()) - set(metadata.point_ids)
        if obsolete:
            self.store.delete_document_content_chunks(sorted(obsolete))
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
        policy, paths = self._accept_preflight(preflight, changed_paths=None)
        limits = self._support_limits()
        prep = self._preprocess_context(policy, limits)
        budget = _DocumentResourceBudget(limits)
        with self._writer_lock:
            previous = read_document_meta(self._meta_path)
            previous_files = (
                {item.source_path: item for item in previous.files} if previous else {}
            )
            preprocessing_disabled = policy.execution_mode == "off" and any(
                policy.match_preprocess(path.relative_to(self.root_dir).as_posix())
                is not None
                for path in paths
            )
            if clean and not preprocessing_disabled:
                self.store.drop_document_table()
                previous_files = {}
            self.store.ensure_document_table()
            published, counts, failures = self._publish_full_paths(
                paths,
                policy=policy,
                prep=prep,
                budget=budget,
                previous_files=previous_files,
                reporter=reporter,
                run_control=run_control,
            )
            stale_ids = self._stale_point_ids(previous_files, published)
            if stale_ids:
                self.store.delete_document_content_chunks(sorted(stale_ids))
            write_document_meta(
                self._meta_path,
                self._metadata(policy, published, complete=not failures),
            )
            return self._finish_result(
                started=started,
                added=counts.added,
                updated=counts.updated,
                removed=len(stale_ids),
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
        )
        limits = self._support_limits()
        prep = self._preprocess_context(policy, limits)
        budget = _DocumentResourceBudget(limits)
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
                    self._discover(policy),
                ),
                run_control=run_control,
            )

        previous_files = {item.source_path: item for item in previous.files}
        selected = self._select_incremental_paths(
            authorized_paths,
            previous_files,
            scoped=changed_paths is not None,
        )

        with self._writer_lock:
            current, counts, failures = self._reconcile_incremental_paths(
                selected,
                policy=policy,
                prep=prep,
                budget=budget,
                previous_files=previous_files,
                reporter=reporter,
                run_control=run_control,
            )
            write_document_meta(
                self._meta_path,
                self._metadata(policy, current.values(), complete=not failures),
            )
            return self._finish_result(
                started=started,
                added=counts.added,
                updated=counts.updated,
                removed=counts.removed,
                files=len(selected),
                preprocess_ok=counts.preprocess_ok,
                failures=failures,
            )
