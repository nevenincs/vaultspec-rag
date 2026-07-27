"""Supersede-then-publish commit sequence shared by incremental code runs.

The whole-run and scoped incremental paths perform the identical
supersede/stream/delete/publish sequence, differing only in which hash
mapping seeds the supersede - every current hash for a full incremental
pass, only the changed ones for a scoped one. Holding the sequence here
instead of duplicating it on each caller is what keeps the two runs from
drifting apart on rollback or obsolete-id deletion.
"""

from __future__ import annotations

import contextlib
import logging
from typing import TYPE_CHECKING, NamedTuple

from ..job_control import NO_RUN_CONTROL, RunControlSignal
from ._consumer_pipeline import UnsettledCodeConsumerError
from ._route_migration import reconcile_generation_storage
from ._run_ledger import CommitUnitKind

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from ..job_control import RunControl
    from ..progress import ProgressReporter
    from ..store import VaultStore
    from ._consumer_pipeline import CodePipelineLimits
    from ._generation_lifecycle import CodeGenerationLifecycle
    from ._resolved_policy import ResolvedIndexPolicy
    from ._run_checkpoint import CodeRunCheckpoint

from ._content_policy import ContentKind

logger = logging.getLogger(__name__)


class IncrementalPublication(NamedTuple):
    """What one incremental ingest phase produced, for the caller to commit.

    Named rather than a bare 4-tuple because both callers use every field and
    two of them are ``set[str]`` - positionally interchangeable, and silently
    so if the order were ever transposed.
    """

    prior_ids_by_path: dict[str, set[str]]
    existing_ids: set[str]
    published_ids: set[str]
    published_hashes: dict[str, str]


class CodeIncrementalCommit:
    """Own the supersede/stream/delete/publish sequence for one code root."""

    def __init__(
        self,
        store: VaultStore,
        lifecycle: CodeGenerationLifecycle,
        meta_path: pathlib.Path,
        chunk_and_embed: Callable[..., tuple[set[str], int, dict[str, str]]],
        write_meta: Callable[..., None],
    ) -> None:
        """Bind the commit sequence to the storage and metadata it publishes.

        Args:
            store: Vector store the confirmed delta is deleted from and
                counted against.
            lifecycle: The root's generation lifecycle, for drift ownership
                and checkpointed point-id evidence.
            meta_path: Carried code-index metadata sidecar, stamped by a
                checkpointed publication.
            chunk_and_embed: Streams changed paths through the chunk+embed
                pipeline, returning the published ids, a count, and the
                published content hashes.
            write_meta: Publishes the un-checkpointed sidecar metadata.
        """
        self._store = store
        self._lifecycle = lifecycle
        self._meta_path = meta_path
        self._chunk_and_embed = chunk_and_embed
        self._write_meta = write_meta

    def supersede_and_publish(
        self,
        *,
        checkpoint: CodeRunCheckpoint,
        hashes: dict[str, str],
        to_index: set[str],
        paths_to_index: list[pathlib.Path],
        attempted_paths: set[str],
        reporter: ProgressReporter,
        limits: CodePipelineLimits,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> IncrementalPublication:
        """Supersede this run's re-ingested snapshot, then stream and publish.

        The supersede is deliberately narrowed to ``to_index``: re-opening any
        other path would drop its points without republishing them, so the
        mapping passed here decides what stays addressable. A second copy of
        that scoping rule is the kind that loses points rather than raising.
        """
        run_control.checkpoint()
        self._lifecycle.drift_owner.supersede_snapshot(
            {rel: hashes[rel] for rel in to_index}
        )
        run_control.checkpoint()
        prior_ids_by_path = self._prior_ids_by_path(checkpoint, attempted_paths)
        existing_ids: set[str] = (
            set(self._store.get_code_ids_by_paths(attempted_paths))
            if attempted_paths
            else set()
        )
        run_control.checkpoint()
        published_ids, published_hashes = self._publish_paths(
            paths=paths_to_index,
            attempted_paths=attempted_paths,
            existing_ids=existing_ids,
            reporter=reporter,
            checkpoint=checkpoint,
            limits=limits,
            run_control=run_control,
        )
        return IncrementalPublication(
            prior_ids_by_path=prior_ids_by_path,
            existing_ids=existing_ids,
            published_ids=published_ids,
            published_hashes=published_hashes,
        )

    def _publish_paths(
        self,
        *,
        paths: list[pathlib.Path],
        attempted_paths: set[str],
        existing_ids: set[str],
        reporter: ProgressReporter,
        checkpoint: CodeRunCheckpoint,
        limits: CodePipelineLimits,
        run_control: RunControl = NO_RUN_CONTROL,
    ) -> tuple[set[str], dict[str, str]]:
        """Stream changed paths and roll back attempt-introduced IDs."""
        try:
            published_ids, _total, published_hashes = self._chunk_and_embed(
                paths,
                reporter=reporter,
                checkpoint=checkpoint,
                limits=limits,
                run_control=run_control,
            )
        except UnsettledCodeConsumerError:
            raise
        except BaseException:
            self._discard_failed_additions(
                attempted_paths=attempted_paths,
                existing_ids=existing_ids,
                protected_ids=set(
                    checkpoint.ledger.iter_point_ids(checkpoint.generation_id)
                ),
            )
            raise
        return published_ids, published_hashes

    def _discard_failed_additions(
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
            current_ids = set(self._store.get_code_ids_by_paths(attempted_paths))
            introduced_ids = sorted(
                current_ids - existing_ids - (protected_ids or set())
            )
            if introduced_ids:
                self._store.delete_code_chunks(introduced_ids)
        except Exception:
            logger.error(
                "Failed to clean partial incremental code publication",
                exc_info=True,
            )

    def _prior_ids_by_path(
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
            result[rel].update(self._store.get_code_ids_by_paths({rel}))
        return result

    def _delete_obsolete(
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
                self._store.delete_code_chunks(obsolete_ids)
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
            self._store.delete_code_chunks(list(obsolete_ids))
            if deletion_kind is CommitUnitKind.DELETE_PATH:
                checkpoint.record_confirmed_deletion(rel, obsolete_ids)
            else:
                checkpoint.record_confirmed_stale_deletion(rel, obsolete_ids)

    def commit_replacement(
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
                    self._delete_obsolete(
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
                            published_points=self._store.count_code(),
                            published_files=self._store.count_code_files(),
                        )
                    else:
                        reconcile_generation_storage(
                            self._store,
                            checkpoint,
                            policy,
                            ContentKind.CODE,
                        )
                        checkpoint.publish_metadata(
                            self._meta_path,
                            published_points=self._store.count_code(),
                            published_files=self._store.count_code_files(),
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
                        self._store.delete_code_chunks(introduced_ids)
                except Exception:
                    logger.error(
                        "Failed to roll back code publication before commit",
                        exc_info=True,
                    )
            raise
        run_control.checkpoint()
