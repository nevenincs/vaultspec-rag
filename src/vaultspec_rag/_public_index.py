"""Model-free public discovery facades for document indexing."""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, cast

from .indexer._content_policy import ContentKind

if TYPE_CHECKING:
    from .indexer._content_policy import RootContentPolicy

__all__ = ["DocumentScanResult", "scan_documents"]


@dataclass(frozen=True, slots=True)
class DocumentScanResult:
    """Bounded dry-run projection of explicitly routed document work."""

    total_files: int
    sampled_paths: tuple[str, ...]
    truncated: bool
    membership_fingerprint: str
    content_fingerprint: str
    policy_snapshot: str
    preprocess_rule_count: int
    execution_mode: str


def scan_documents(
    root_dir: pathlib.Path,
    *,
    sample_limit: int = 100,
    extra_excludes: list[str] | None = None,
    content_policy: RootContentPolicy | None = None,
) -> DocumentScanResult:
    """Discover document work without opening storage or loading GPU models."""
    if isinstance(sample_limit, bool) or sample_limit < 0:
        raise ValueError("sample_limit must be a non-negative integer")
    from .indexer import DocumentIndexer

    root = pathlib.Path(root_dir).resolve()
    # ``DocumentIndexer.__init__`` only stores ``model``/``store``; both are
    # read lazily inside a run, never during construction or
    # ``preflight_content``, so ``None`` is safe here.
    indexer = DocumentIndexer(
        root,
        model=cast("Any", None),
        store=cast("Any", None),
        extra_excludes=extra_excludes,
        content_policy=content_policy,
    )
    preflight = indexer.preflight_content()
    paths = tuple(path.relative_to(root).as_posix() for path in preflight.files)
    fingerprints = preflight.policy.fingerprints_for(ContentKind.DOCUMENT)
    return DocumentScanResult(
        total_files=len(paths),
        sampled_paths=paths[:sample_limit],
        truncated=len(paths) > sample_limit,
        membership_fingerprint=fingerprints.membership,
        content_fingerprint=fingerprints.content,
        policy_snapshot=preflight.policy.fingerprints.snapshot,
        preprocess_rule_count=len(preflight.policy.preprocess_rules),
        execution_mode=preflight.policy.execution_mode,
    )
