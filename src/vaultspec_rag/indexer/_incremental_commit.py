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
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from ..job_control import NO_RUN_CONTROL
from ._consumer_pipeline import UnsettledCodeConsumerError
from ._run_ledger_models import CommitUnitKind, RunOperation

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Callable

    from ..job_control import RunControl
    from ..progress import ProgressReporter
    from ..store_runtime import VaultStore
    from ._consumer_pipeline import CodePipelineRun
    from ._generation_lifecycle import CodeGenerationLifecycle
    from ._run_checkpoint import CodeRunCheckpoint

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


@dataclass(frozen=True, slots=True)
class IncrementalPublicationRequest:
    """Inputs for one supersede-and-stream publication attempt."""

    hashes: dict[str, str]
    to_index: set[str]
    paths_to_index: list[pathlib.Path]
    attempted_paths: set[str]
    pipeline_run: CodePipelineRun


@dataclass(frozen=True, slots=True)
class IncrementalReplacementRequest:
    """Inputs for the delete-and-metadata edge of an incremental publication."""

    existing_ids: set[str]
    published_ids: set[str]
    files_count: int
    protect_replacement: bool
    reporter: ProgressReporter
    checkpoint: CodeRunCheckpoint
    prior_ids_by_path: dict[str, set[str]] | None = None
    deleted_paths: set[str] | None = None
    run_control: RunControl = NO_RUN_CONTROL


@dataclass(frozen=True, slots=True)
class PathPublicationRequest:
    """State needed to stream paths and clean a failed partial publication."""

    paths: list[pathlib.Path]
    attempted_paths: set[str]
    existing_ids: set[str]
    pipeline_run: CodePipelineRun


class CodeIncrementalCommit:
    """Own the supersede/stream/delete/publish sequence for one code root."""

    def __init__(
        self,
        store: VaultStore,
        lifecycle: CodeGenerationLifecycle,
        chunk_and_embed: Callable[
            [list[pathlib.Path], CodePipelineRun], tuple[set[str], int, dict[str, str]]
        ],
    ) -> None:
        """Bind the commit sequence to storage and canonical proof publication.

        Args:
            store: Vector store the confirmed delta is deleted from and
                counted against.
            lifecycle: The root's generation lifecycle, which owns drift,
                checkpointed point-id evidence, and canonical proof publication.
            chunk_and_embed: Streams changed paths through the chunk+embed
                pipeline, returning the published ids, a count, and the
                published content hashes.
        """
        self._store = store
        self._lifecycle = lifecycle
        self._chunk_and_embed = chunk_and_embed

    def supersede_and_publish(
        self,
        request: IncrementalPublicationRequest,
    ) -> IncrementalPublication:
        """Supersede this run's re-ingested snapshot, then stream and publish.

        The supersede is deliberately narrowed to ``to_index``: re-opening any
        other path would drop its points without republishing them, so the
        mapping passed here decides what stays addressable. A second copy of
        that scoping rule is the kind that loses points rather than raising.
        """
        request.pipeline_run.run_control.checkpoint()
        self._lifecycle.drift_owner.supersede_snapshot(
            {rel: request.hashes[rel] for rel in request.to_index}
        )
        request.pipeline_run.run_control.checkpoint()
        prior_ids_by_path = self._prior_ids_by_path(
            request.pipeline_run.checkpoint, request.attempted_paths
        )
        existing_ids: set[str] = (
            set(self._store.get_code_ids_by_paths(request.attempted_paths))
            if request.attempted_paths
            else set()
        )
        request.pipeline_run.run_control.checkpoint()
        published_ids, published_hashes = self._publish_paths(
            PathPublicationRequest(
                paths=request.paths_to_index,
                attempted_paths=request.attempted_paths,
                existing_ids=existing_ids,
                pipeline_run=request.pipeline_run,
            )
        )
        return IncrementalPublication(
            prior_ids_by_path=prior_ids_by_path,
            existing_ids=existing_ids,
            published_ids=published_ids,
            published_hashes=published_hashes,
        )

    def _publish_paths(
        self,
        request: PathPublicationRequest,
    ) -> tuple[set[str], dict[str, str]]:
        """Stream changed paths and roll back attempt-introduced IDs."""
        try:
            published_ids, _total, published_hashes = self._chunk_and_embed(
                request.paths,
                request.pipeline_run,
            )
        except UnsettledCodeConsumerError:
            raise
        except BaseException:
            self._discard_failed_additions(
                attempted_paths=request.attempted_paths,
                existing_ids=request.existing_ids,
                protected_ids=set(
                    request.pipeline_run.checkpoint.ledger.iter_point_ids(
                        request.pipeline_run.checkpoint.generation_id
                    )
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
            from ._streaming import execute_store_mutation

            execute_store_mutation(
                lambda ids=obsolete_ids: self._store.delete_code_chunks(list(ids)),
                checkpoint.deletion_lifecycle(rel, deletion_kind, obsolete_ids),
            )
            if deletion_kind is CommitUnitKind.DELETE_PATH:
                checkpoint.record_confirmed_deletion(rel, obsolete_ids)
            else:
                checkpoint.record_confirmed_stale_deletion(rel, obsolete_ids)

    def commit_replacement(
        self,
        request: IncrementalReplacementRequest,
    ) -> None:
        """Delete obsolete IDs and publish metadata at one safe control edge."""
        request.run_control.checkpoint()
        publication_span = (
            request.checkpoint.run_policy.protected("incremental code replacement")
            if request.protect_replacement
            else contextlib.nullcontext()
        )
        with publication_span:
            request.reporter.phase_start("delete removed", request.files_count)
            try:
                self._delete_obsolete(
                    existing_ids=request.existing_ids,
                    published_ids=request.published_ids,
                    prior_ids_by_path=request.prior_ids_by_path,
                    deleted_paths=request.deleted_paths,
                    checkpoint=request.checkpoint,
                )
                request.reporter.advance(request.files_count)
            finally:
                request.reporter.phase_end()
            self._lifecycle.publish(
                request.checkpoint,
                build_target=None,
                reporter=request.reporter,
                phase_label="write metadata",
                affected_paths=(
                    set(request.prior_ids_by_path or {})
                    if request.checkpoint.generation.signature.operation
                    is RunOperation.SCOPED_INCREMENTAL
                    else None
                ),
            )
        request.run_control.checkpoint()
