"""Document-preprocessing glue for the codebase indexer (#185).

Pure functions that resolve ``.vaultragpreprocess.toml`` into compiled rules,
build the per-run preprocess context, and score worker results into the
run's ok/skip tallies. Split out of ``_codebase_indexer`` so the preprocess
plumbing lives apart from the GPU chunk/embed pipeline; the
``CodebaseIndexer`` methods delegate here and own the per-run state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ._preprocess_cache import clear_preprocess_cache, preprocess_cache_dir
from ._preprocess_config import (
    PreprocessConfig,
    PreprocessContext,
    load_preprocess_rules,
)

if TYPE_CHECKING:
    import pathlib

    from . import _chunk_worker
    from ._chunk_worker import FileChunkResult
    from ._resolved_policy import ResolvedIndexPolicy


def build_preprocess_rules(root_dir: pathlib.Path) -> PreprocessConfig:
    """Resolve ``.vaultragpreprocess.toml`` into compiled preprocess rules.

    Root-only resolution, mirroring ``build_vaultragignore_spec``: read
    fresh from the project root on each call so an edited config is picked
    up on the next scan. Degrades to an empty config on any defect (D1, D3).

    Returns:
        The resolved :class:`PreprocessConfig` (empty when no rules apply).
    """
    return load_preprocess_rules(root_dir)


def clear_preprocess_cache_for(data_root: pathlib.Path) -> None:
    """Remove the preprocess output cache subtree for a clean rebuild (D7)."""
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
    from ..config import get_config

    cfg = get_config()
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
    )


def prep_rule_count(prep_ctx: PreprocessContext | None) -> int:
    """Return the number of preprocess rules active for the current run."""
    return len(prep_ctx.config.rules) if prep_ctx is not None else 0


def matches_preprocess_rule(prep_ctx: PreprocessContext | None, rel: str) -> bool:
    """Return whether a preprocess rule matches this project-relative path.

    Ignore always wins (this is only consulted after the ignore gate), but a
    match expands the indexable set: a matched file is admitted even when its
    extension is unsupported, it exceeds ``_MAX_FILE_SIZE``, or it is binary,
    because the preprocessor extracts indexable text from it (D2, D10).
    """
    if prep_ctx is None:
        return False
    return prep_ctx.config.match(rel) is not None


def record_preprocess_result(
    res: FileChunkResult,
    prep_skips: list[str],
) -> int:
    """Score a worker result's preprocess disposition (D11).

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
    """Score a scoped-path preprocess disposition (D11).

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
