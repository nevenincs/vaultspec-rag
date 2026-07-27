"""Watcher event classification and immutable policy snapshots."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .indexer._content_policy import ContentKind
from .indexer._preprocess_config import PREPROCESS_CONFIG_FILENAME
from .logging_config import log_event

if TYPE_CHECKING:
    from pathlib import Path

    from .indexer import CodebaseIndexer
    from .indexer._resolved_policy import ResolvedIndexPolicy

logger = logging.getLogger(__name__)
_VAULT_EXTENSIONS = frozenset({".md"})
CONFIG_FILENAMES = frozenset(
    {".gitignore", ".vaultragignore", PREPROCESS_CONFIG_FILENAME}
)


def is_vault_change(path: Path, vault_dir: Path) -> bool:
    """Return True if path is a markdown file inside the vault."""
    try:
        path.relative_to(vault_dir)
    except ValueError as exc:
        logger.debug("watcher: %s not under vault dir %s: %s", path, vault_dir, exc)
        return False
    return path.suffix.lower() in _VAULT_EXTENSIONS


def is_code_change(
    path: Path, root_dir: Path, vault_dir: Path, policy: ResolvedIndexPolicy | None
) -> bool:
    """Return whether one watcher path is code-owned in this snapshot."""
    try:
        path.relative_to(vault_dir)
        return False
    except ValueError as exc:
        logger.debug(
            "watcher code-path: %s not under vault %s: %s", path, vault_dir, exc
        )
    try:
        rel = path.relative_to(root_dir)
    except ValueError as exc:
        logger.debug("watcher code-path: %s not under root %s: %s", path, root_dir, exc)
        return False
    if path.name in CONFIG_FILENAMES:
        return True
    if policy is None:
        return False
    disposition = policy.classify(str(rel).replace("\\", "/")).disposition
    return disposition.admitted and disposition.kind is ContentKind.CODE


def is_document_change(
    path: Path, root_dir: Path, vault_dir: Path, policy: ResolvedIndexPolicy | None
) -> bool:
    """Return whether one watcher path is document-owned in this snapshot."""
    try:
        path.relative_to(vault_dir)
        return False
    except ValueError:
        pass
    try:
        rel = path.relative_to(root_dir)
    except ValueError:
        return False
    if path.name in CONFIG_FILENAMES:
        return True
    if policy is None:
        return False
    disposition = policy.classify(rel.as_posix()).disposition
    return disposition.admitted and disposition.kind is ContentKind.DOCUMENT


def refresh_watcher_policy(
    code_indexer: CodebaseIndexer,
    root_dir: Path,
    previous: ResolvedIndexPolicy | None,
) -> ResolvedIndexPolicy | None:
    """Advance watcher classification authority or retain fail-closed state."""
    try:
        policy = code_indexer.resolve_policy_snapshot()
    except (OSError, ValueError) as exc:
        log_event(
            logger,
            "service.watcher",
            "policy_snapshot_rejected",
            severity=logging.ERROR,
            root=root_dir,
            error=exc,
        )
        return previous
    log_event(
        logger,
        "service.watcher",
        "policy_snapshot_advanced",
        root=root_dir,
        policy_fingerprint=policy.fingerprints.snapshot,
    )
    return policy
