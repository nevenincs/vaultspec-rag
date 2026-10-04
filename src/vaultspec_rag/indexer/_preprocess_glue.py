"""Document-preprocessing glue for the codebase indexer (#185).

Pure functions that build the per-run preprocess context from an already
resolved config or policy snapshot, clear the output cache, and score worker
results into the run's ok/skip tallies. Split out of ``_codebase_indexer`` so
the preprocess plumbing lives apart from the GPU chunk/embed pipeline; the
``CodebaseIndexer`` methods delegate here and own the per-run state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..operator_state._features import PreprocessHookState
from ._preprocess_cache import preprocess_cache_dir
from ._preprocess_config import PreprocessConfig, PreprocessContext

if TYPE_CHECKING:
    import pathlib

    from ._chunk_worker import FileChunkResult
    from ._resolved_policy import ResolvedIndexPolicy


def resolve_policy_preprocess_context(
    root_dir: pathlib.Path,
    data_root: pathlib.Path,
    policy: ResolvedIndexPolicy,
    *,
    max_source_bytes: int | None = None,
) -> PreprocessContext | None:
    """Materialize worker execution state from one immutable policy snapshot."""
    if policy.hook_state is not PreprocessHookState.ACTIVE:
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
