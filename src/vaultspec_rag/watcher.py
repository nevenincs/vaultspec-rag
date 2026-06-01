"""Filesystem watcher for automatic vault/codebase re-indexing.

Uses watchfiles.awatch() to monitor .vault/ for documentation changes
and the project root for source code changes. Triggers incremental
re-indexing when changes are detected.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from anyio.to_thread import run_sync as _run_in_thread
from watchfiles import Change, awatch

from .mcp_server import _jobs
from .progress import NullProgressReporter

if TYPE_CHECKING:
    import asyncio

    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, VaultIndexer

logger = logging.getLogger(__name__)

# Extensions recognized as vault documentation
_VAULT_EXTENSIONS = frozenset({".md"})

# Extensions recognized as indexable source code (mirrors CodebaseIndexer)
_CODE_EXTENSIONS = frozenset(
    {
        ".py",
        ".rs",
        ".ts",
        ".tsx",
        ".js",
        ".jsx",
        ".go",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".cs",
        ".rb",
        ".swift",
        ".kt",
        ".lua",
        ".zig",
    }
)


def _is_vault_change(path: Path, vault_dir: Path) -> bool:
    """Return True if path is a .md file inside the vault directory.

    Args:
        path: The changed file path.
        vault_dir: The vault directory to check against.

    Returns:
        True if path is a .md file inside vault_dir, False otherwise.
    """
    try:
        path.relative_to(vault_dir)
    except ValueError as exc:
        logger.debug("watcher: %s not under vault dir %s: %s", path, vault_dir, exc)
        return False
    return path.suffix in _VAULT_EXTENSIONS


def _is_code_change(path: Path, root_dir: Path, vault_dir: Path) -> bool:
    """Return True if path is a source file outside the vault directory.

    Args:
        path: The changed file path.
        root_dir: Project root directory.
        vault_dir: Vault directory to exclude.

    Returns:
        True if path is an indexable source file outside vault_dir
        and inside root_dir, False otherwise.
    """
    if path.suffix not in _CODE_EXTENSIONS:
        return False
    try:
        path.relative_to(vault_dir)
        return False  # Inside vault — not a code change
    except ValueError as exc:
        # Expected when path is outside vault — fall through to
        # the root-dir check below.
        logger.debug(
            "watcher code-path: %s not under vault %s: %s",
            path,
            vault_dir,
            exc,
        )
    try:
        path.relative_to(root_dir)
    except ValueError as exc:
        logger.debug(
            "watcher code-path: %s not under root %s: %s",
            path,
            root_dir,
            exc,
        )
        return False
    return True


async def watch_and_reindex(
    root_dir: Path,
    vault_dir: Path,
    vault_indexer: VaultIndexer,
    code_indexer: CodebaseIndexer,
    stop_event: asyncio.Event,
    graph_cache: GraphCache,
    debounce: int = 2000,
    cooldown: float = 30.0,
) -> None:
    """Watch for file changes and trigger incremental re-indexing.

    Runs until stop_event is set. GPU serialization is handled
    internally by the indexers' ``gpu_lock``. Applies an
    application-level cooldown between index runs to prevent
    thrashing. Cooldown is tracked independently per source: vault
    and code each have separate 30-second windows so a vault reindex
    does not suppress a subsequent code reindex (or vice versa).

    Args:
        root_dir: Project root directory to watch.
        vault_dir: Path to the .vault/ documentation directory.
        vault_indexer: Initialized VaultIndexer for doc re-indexing.
        code_indexer: Initialized CodebaseIndexer for source
            re-indexing.
        stop_event: Set this event to stop the watcher gracefully.
        debounce: Milliseconds to wait for additional changes
            before processing.
        cooldown: Seconds to suppress re-index triggers after a
            completed run.
        graph_cache: GraphCache to invalidate after a successful vault
            reindex.

    Raises:
        This coroutine does not propagate exceptions from indexing.
        Indexing errors are caught and logged via ``logger.exception``.
    """
    logger.info(
        "Starting filesystem watcher: root=%s, vault=%s, debounce=%dms, cooldown=%.0fs",
        root_dir,
        vault_dir,
        debounce,
        cooldown,
    )

    # Track last index times per source to enforce the cooldown window.
    _last_vault_index: float = 0.0
    _last_code_index: float = 0.0

    async for changes in awatch(
        root_dir,
        debounce=debounce,
        stop_event=stop_event,
        watch_filter=lambda _change, path: (
            _is_vault_change(Path(path), vault_dir)
            or _is_code_change(Path(path), root_dir, vault_dir)
        ),
    ):
        vault_changed = False
        code_changed = False

        for change_type, path_str in changes:
            path = Path(path_str)
            if change_type in (Change.added, Change.modified, Change.deleted):
                if _is_vault_change(path, vault_dir):
                    vault_changed = True
                elif _is_code_change(path, root_dir, vault_dir):
                    code_changed = True

        now = time.monotonic()

        if vault_changed:
            if now - _last_vault_index < cooldown:
                logger.debug(
                    "Vault re-index suppressed: %.0fs remaining in cooldown",
                    cooldown - (now - _last_vault_index),
                )
            else:
                logger.info(
                    "Vault changes detected, triggering incremental re-index...",
                )
                job_id = _jobs.record_start("vault", "watcher")
                try:
                    result = await _run_in_thread(
                        lambda: vault_indexer.incremental_index(
                            reporter=NullProgressReporter()
                        ),
                    )
                    graph_cache.invalidate()
                    _last_vault_index = time.monotonic()
                    _jobs.record_finish(
                        job_id,
                        result=(
                            f"+{result.added} /{result.updated} "
                            f"-{result.removed} ({result.duration_ms}ms)"
                        ),
                    )
                    logger.info(
                        "Vault re-index complete: +%d /%d -%d (%dms)",
                        result.added,
                        result.updated,
                        result.removed,
                        result.duration_ms,
                    )
                except Exception as exc:
                    _jobs.record_finish(job_id, error=str(exc))
                    logger.exception("Vault re-index failed")

        if code_changed:
            if now - _last_code_index < cooldown:
                logger.debug(
                    "Code re-index suppressed: %.0fs remaining in cooldown",
                    cooldown - (now - _last_code_index),
                )
            else:
                logger.info(
                    "Code changes detected, triggering incremental re-index...",
                )
                job_id = _jobs.record_start("code", "watcher")
                try:
                    result = await _run_in_thread(
                        lambda: code_indexer.incremental_index(
                            reporter=NullProgressReporter()
                        ),
                    )
                    _last_code_index = time.monotonic()
                    _jobs.record_finish(
                        job_id,
                        result=(
                            f"+{result.added} /{result.updated} "
                            f"-{result.removed} ({result.duration_ms}ms)"
                        ),
                    )
                    logger.info(
                        "Code re-index complete: +%d /%d -%d (%dms)",
                        result.added,
                        result.updated,
                        result.removed,
                        result.duration_ms,
                    )
                except Exception as exc:
                    _jobs.record_finish(job_id, error=str(exc))
                    logger.exception("Code re-index failed")

    logger.info("Filesystem watcher stopped.")
