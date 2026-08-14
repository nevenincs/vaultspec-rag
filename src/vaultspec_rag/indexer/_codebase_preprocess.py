"""Document preprocessing rules, and the paths they take out of the index.

A rule can disable a path that was previously indexed, which means its old
chunks have to be preserved or removed deliberately rather than left behind as
orphans. Partitioning those paths and carrying their metadata across a run is
this module's whole subject.
"""

from __future__ import annotations

import logging
import pathlib
from typing import TYPE_CHECKING

from ..job_control import NO_RUN_CONTROL
from . import _chunk_worker, _preprocess_glue
from ._resolved_policy import preprocess_stale_note

if TYPE_CHECKING:
    from collections.abc import Iterable

    from ..job_control import RunControl
    from ._chunk_worker import FileChunkResult
    from ._preprocess_config import (
        PreprocessContext,
    )
    from ._resolved_policy import ResolvedIndexPolicy

logger = logging.getLogger(__name__)


class CodebasePreprocessMixin:
    """Resolves preprocessing rules and the paths they disable."""

    if TYPE_CHECKING:
        # Owned by the indexer this mixes into.
        root_dir: pathlib.Path
        _data_root: pathlib.Path
        _prep_ctx: PreprocessContext | None
        _prep_ok: int
        _prep_rule_total: int
        _prep_skips: list[str]
        _prep_stale_paths: set[str]
        _chunk_execution_policy: _chunk_worker.ChunkExecutionPolicy

        def _get_chunk_ids_for_files(self, rel_paths: set[str]) -> list[str]: ...

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

    def _mark_preprocess_stale(self, rel_path: str) -> None:
        """Surface disabled transform work once without changing membership."""
        if rel_path in self._prep_stale_paths:
            return
        self._prep_stale_paths.add(rel_path)
        self._prep_skips.append(preprocess_stale_note(rel_path))

    def _partition_disabled_paths(
        self,
        paths: Iterable[pathlib.Path],
        policy: ResolvedIndexPolicy,
    ) -> list[pathlib.Path]:
        """Remove disabled transforms from execution while retaining ownership."""
        executable: list[pathlib.Path] = []
        for path in paths:
            rel = str(path.relative_to(self.root_dir)).replace("\\", "/")
            if policy.transform_disabled(rel):
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
            if not policy.transform_disabled(rel):
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
