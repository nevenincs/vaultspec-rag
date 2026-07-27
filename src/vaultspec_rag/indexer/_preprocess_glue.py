"""Document-preprocessing glue for the codebase indexer (#185).

Pure functions that build the per-run preprocess context from an already
resolved config or policy snapshot, clear the output cache, and score worker
results into the run's ok/skip tallies. Split out of ``_codebase_indexer`` so
the preprocess plumbing lives apart from the GPU chunk/embed pipeline; the
``CodebaseIndexer`` methods delegate here and own the per-run state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._preprocess_cache import clear_preprocess_cache, preprocess_cache_dir
from ._preprocess_config import (
    PreprocessConfig,
    PreprocessContext,
)

if TYPE_CHECKING:
    import pathlib

    from . import _chunk_worker
    from ._chunk_worker import FileChunkResult
    from ._resolved_policy import ResolvedIndexPolicy


def clear_preprocess_cache_for(data_root: pathlib.Path) -> None:
    """Remove the preprocess output cache subtree for a clean rebuild."""
    clear_preprocess_cache(preprocess_cache_dir(data_root))


def resolve_preprocess_context(
    root_dir: pathlib.Path,
    data_root: pathlib.Path,
    config: PreprocessConfig,
) -> PreprocessContext | None:
    """Build the per-run preprocess context, or ``None`` when no rules apply.

    Returning ``None`` for a project with no ``.vaultragpreprocess.toml``
    rules keeps the worker path byte-identical to the pre-feature behaviour
    (the workers receive ``prep=None``), so there is zero overhead when the
    hook is unused.
    """
    if not config:
        return None
    from ..config._settings import get_config

    cfg = get_config()
    if cfg.preprocess_mode == "off":
        return None
    return PreprocessContext(
        config=config,
        cache_root=preprocess_cache_dir(data_root),
        max_emitted_bytes=int(cfg.preprocess_max_emitted_bytes),
        project_root=root_dir,
    )


def resolve_policy_preprocess_context(
    root_dir: pathlib.Path,
    data_root: pathlib.Path,
    policy: ResolvedIndexPolicy,
    *,
    max_source_bytes: int | None = None,
) -> PreprocessContext | None:
    """Materialize worker execution state from one immutable policy snapshot."""
    if policy.execution_mode == "off" or not policy.preprocess_rules:
        return None
    config = PreprocessConfig(
        [rule.materialize() for rule in policy.preprocess_rules],
        schema_version=policy.preprocess_schema_version,
    )
    return PreprocessContext(
        config=config,
        cache_root=preprocess_cache_dir(data_root),
        max_emitted_bytes=policy.max_emitted_bytes,
        project_root=root_dir,
        max_source_bytes=max_source_bytes,
    )


def prep_rule_count(prep_ctx: PreprocessContext | None) -> int:
    """Return the number of preprocess rules active for the current run."""
    return len(prep_ctx.config.rules) if prep_ctx is not None else 0


def record_preprocess_result(
    res: FileChunkResult,
    prep_skips: list[str],
) -> int:
    """Score a worker result's preprocess disposition.

    Returns ``1`` for a rule-fed success (so the caller can bump its ok
    tally) and ``0`` otherwise, appending a ``"rel_path: reason"`` line to
    ``prep_skips`` for a skip. Workers run in spawn subprocesses whose
    logging never reaches the owning process, so both outcomes are tallied
    here: skips for failure visibility, successes so a working pipeline is
    positively observable.
    """
    if res.preprocess_status == "ok":
        return 1
    if res.preprocess_status == "skipped":
        reason = res.preprocess_reason or "preprocessor skipped the file"
        prep_skips.append(f"{res.rel_path}: {reason}")
    return 0


def record_scoped_preprocess(
    root_dir: pathlib.Path,
    path: pathlib.Path,
    result: _chunk_worker.ScopedChunkResult,
    prep_skips: list[str],
) -> int:
    """Score a scoped-path preprocess disposition.

    Mirrors :func:`record_preprocess_result` for the scoped/incremental path
    (used by the watcher) so coverage gaps and rule-fed successes are
    surfaced on every path, not just the full index (review VIS-001).
    """
    if result.preprocess_status == "ok":
        return 1
    if result.preprocess_status == "skipped":
        try:
            rel = str(path.relative_to(root_dir)).replace("\\", "/")
        except ValueError:
            rel = str(path)
        reason = result.preprocess_reason or "preprocessor skipped the file"
        prep_skips.append(f"{rel}: {reason}")
    return 0
