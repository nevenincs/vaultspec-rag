"""Independent full and incremental indexing for explicitly routed documents."""

from __future__ import annotations

import hashlib
import os
import pathlib
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

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
from ._streaming import encode_and_upsert_document_slice
from ._vault_prep import IndexResult

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..embeddings import EmbeddingModel
    from ..job_control import RunControl
    from ..progress import ProgressReporter
    from ..store import DocumentChunk, VaultStore
    from ._resolved_policy import ResolvedIndexPolicy

__all__ = ["DocumentIndexPreflight", "DocumentIndexer"]


@dataclass(frozen=True, slots=True)
class DocumentIndexPreflight:
    """Read-only document discovery authority for one policy snapshot."""

    root_dir: pathlib.Path
    policy: ResolvedIndexPolicy
    files: tuple[pathlib.Path, ...]


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
        self._writer_lock = threading.Lock()
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

    def _accept_preflight(
        self,
        preflight: DocumentIndexPreflight | None,
    ) -> tuple[ResolvedIndexPolicy, tuple[pathlib.Path, ...]]:
        authority = preflight or self.preflight_content()
        if authority.root_dir != self.root_dir or authority.policy.root_dir != self.root_dir:
            raise ValueError("document index preflight belongs to another root")
        if any(not path.resolve().is_relative_to(self.root_dir) for path in authority.files):
            raise ValueError("document preflight contains a path outside its root")
        for path in authority.files:
            rel = path.relative_to(self.root_dir).as_posix()
            disposition = authority.policy.classify(rel).disposition
            if not (disposition.admitted and disposition.kind is ContentKind.DOCUMENT):
                raise ValueError("document preflight contains a non-document path")
        return authority.policy, authority.files

    @staticmethod
    def _hash_path(path: pathlib.Path) -> str:
        return hashlib.blake2b(path.read_bytes()).hexdigest()

    def _preprocess_context(self, policy: ResolvedIndexPolicy):
        return _preprocess_glue.resolve_policy_preprocess_context(
            self.root_dir,
            self._data_root,
            policy,
        )

    @staticmethod
    def _execution_policy(policy: ResolvedIndexPolicy) -> _chunk_worker.ChunkExecutionPolicy:
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
        reporter: ProgressReporter,
        run_control: RunControl,
    ) -> tuple[DocumentFileMetadata | None, int, str | None]:
        """Chunk and publish one document, returning durable file evidence."""
        run_control.checkpoint()
        result = _chunk_worker.chunk_document_and_hash_file(
            path,
            self.root_dir,
            self._preprocess_context(policy),
            self._execution_policy(policy),
        )
        if result.preprocess_status == "skipped":
            reason = result.preprocess_reason or "document extraction skipped"
            return None, 0, f"{result.rel_path}: {reason}"
        chunks = result.chunks
        if not chunks:
            return None, 0, f"{result.rel_path}: document produced no decodable content"

        from ..config import get_config

        slice_size = max(1, int(get_config().embedding_batch_size))
        self.store.disk_headroom_preflight(len(chunks))
        reporter.phase_start("embed + upsert document chunks", len(chunks))
        try:
            for offset in range(0, len(chunks), slice_size):
                run_control.checkpoint()
                selected = chunks[offset : offset + slice_size]
                encode_and_upsert_document_slice(
                    selected,
                    model=self.model,
                    store=self.store,
                    gpu_lock=self._gpu_lock,
                    encode_batch_size=int(get_config().embedding_encode_batch_size),
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
    ) -> DocumentIndexMetadata:
        fingerprints = policy.fingerprints_for(ContentKind.DOCUMENT)
        return DocumentIndexMetadata(
            fingerprints.membership,
            fingerprints.content,
            policy.fingerprints.snapshot,
            tuple(sorted(files, key=lambda item: item.source_path)),
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
        policy, paths = self._accept_preflight(preflight)
        with self._writer_lock:
            previous = read_document_meta(self._meta_path)
            previous_files = {item.source_path: item for item in previous.files} if previous else {}
            if clean:
                self.store.drop_document_table()
                previous_files = {}
            self.store.ensure_document_table()
            published: list[DocumentFileMetadata] = []
            added = updated = preprocess_ok = 0
            failures: list[str] = []
            for path in paths:
                rel = path.relative_to(self.root_dir).as_posix()
                if policy.execution_mode == "off" and policy.match_preprocess(rel) is not None:
                    retained = previous_files.get(rel)
                    if retained is not None:
                        published.append(retained)
                    failures.append(f"{rel}: preprocessing disabled; retained work as stale")
                    continue
                metadata, chunk_count, failure = self._publish_file(
                    path,
                    policy=policy,
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
                    updated += chunk_count
                else:
                    added += chunk_count
                if policy.match_preprocess(rel) is not None:
                    preprocess_ok += 1

            published_by_path = {item.source_path: item for item in published}
            stale_ids: list[str] = []
            for rel, old in previous_files.items():
                current = published_by_path.get(rel)
                if current is None:
                    stale_ids.extend(old.point_ids)
                else:
                    stale_ids.extend(set(old.point_ids) - set(current.point_ids))
            if stale_ids:
                self.store.delete_document_content_chunks(sorted(stale_ids))
            write_document_meta(self._meta_path, self._metadata(policy, published))
            return self._finish_result(
                started=started,
                added=added,
                updated=updated,
                removed=len(stale_ids),
                files=len(paths),
                preprocess_ok=preprocess_ok,
                failures=failures,
            )

    def incremental_index(
        self,
        *,
        reporter: ProgressReporter,
        changed_paths: Iterable[pathlib.Path] | None = None,
        preflight: DocumentIndexPreflight | None = None,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IndexResult:
        """Reconcile changed documents, or discover changes when scope is omitted."""
        started = time.monotonic()
        policy, discovered = self._accept_preflight(preflight)
        fingerprints = policy.fingerprints_for(ContentKind.DOCUMENT)
        with self._writer_lock:
            previous = read_document_meta(self._meta_path)
            if not document_meta_compatible(
                previous,
                membership_fingerprint=fingerprints.membership,
                content_fingerprint=fingerprints.content,
            ):
                # Release before delegating because full_index owns the same lock.
                previous = None
        if previous is None:
            return self.full_index(
                reporter=reporter,
                preflight=DocumentIndexPreflight(self.root_dir, policy, discovered),
                run_control=run_control,
            )

        previous_files = {item.source_path: item for item in previous.files}
        discovered_by_path = {
            path.relative_to(self.root_dir).as_posix(): path for path in discovered
        }
        if changed_paths is None:
            selected = {
                rel
                for rel, path in discovered_by_path.items()
                if rel not in previous_files
                or self._hash_path(path) != previous_files[rel].content_fingerprint
            }
            selected.update(set(previous_files) - set(discovered_by_path))
        else:
            normalized = {path.resolve() for path in changed_paths}
            if any(not path.is_relative_to(self.root_dir) for path in normalized):
                raise ValueError("document index scope contains a path outside its root")
            selected = {path.relative_to(self.root_dir).as_posix() for path in normalized}

        with self._writer_lock:
            current = dict(previous_files)
            added = updated = removed = preprocess_ok = 0
            failures: list[str] = []
            for rel in sorted(selected):
                path = self.root_dir / pathlib.PurePosixPath(rel)
                disposition = policy.classify(rel).disposition
                if not path.is_file() or not (
                    disposition.admitted and disposition.kind is ContentKind.DOCUMENT
                ):
                    old = current.pop(rel, None)
                    if old is not None:
                        self.store.delete_document_content_chunks(list(old.point_ids))
                        removed += len(old.point_ids)
                    continue
                if policy.execution_mode == "off" and policy.match_preprocess(rel) is not None:
                    failures.append(f"{rel}: preprocessing disabled; retained work as stale")
                    continue
                old = current.get(rel)
                metadata, chunk_count, failure = self._publish_file(
                    path,
                    policy=policy,
                    reporter=reporter,
                    run_control=run_control,
                )
                if failure is not None:
                    failures.append(failure)
                    continue
                assert metadata is not None
                current[rel] = metadata
                obsolete = set(old.point_ids if old else ()) - set(metadata.point_ids)
                if obsolete:
                    self.store.delete_document_content_chunks(sorted(obsolete))
                    removed += len(obsolete)
                if old is None:
                    added += chunk_count
                else:
                    updated += chunk_count
                if policy.match_preprocess(rel) is not None:
                    preprocess_ok += 1
            write_document_meta(self._meta_path, self._metadata(policy, current.values()))
            return self._finish_result(
                started=started,
                added=added,
                updated=updated,
                removed=removed,
                files=len(selected),
                preprocess_ok=preprocess_ok,
                failures=failures,
            )
