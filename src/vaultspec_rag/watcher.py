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
from watchfiles import (
    Change,
    awatch,  # pyright: ignore[reportUnknownVariableType]  # watchfiles awatch return type is partially stubbed
)

from . import jobs as _jobs
from .concurrency import get_index_limiter
from .logging_config import log_event

if TYPE_CHECKING:
    import asyncio

    from .graph_cache import GraphCache
    from .indexer import CodebaseIndexer, VaultIndexer
    from .indexer._preprocess_config import PreprocessConfig

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
        # Plain-text/markup tails added to LANGUAGE_MAP (#185 adjacent ask) so a
        # watched edit to one triggers a reindex like any other source file.
        ".txt",
        ".xml",
        ".xsd",
        ".properties",
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


def _is_code_change(
    path: Path,
    root_dir: Path,
    vault_dir: Path,
    preprocess_config: PreprocessConfig | None = None,
) -> bool:
    """Return True if path is a source file outside the vault directory.

    A file whose extension is in ``_CODE_EXTENSIONS`` qualifies, and so does a
    file matched by a preprocess rule even when its extension is unsupported
    (#185, D8) - otherwise a watched ``.pdf`` change would never trigger a
    reindex. Ignore filtering still happens downstream in the indexer scan.

    Args:
        path: The changed file path.
        root_dir: Project root directory.
        vault_dir: Vault directory to exclude.
        preprocess_config: Resolved preprocess rules for the root, if any.

    Returns:
        True if path is an indexable source or preprocessable file outside
        vault_dir and inside root_dir, False otherwise.
    """
    try:
        path.relative_to(vault_dir)
        return False  # Inside vault - not a code change
    except ValueError as exc:
        logger.debug(
            "watcher code-path: %s not under vault %s: %s", path, vault_dir, exc
        )
    try:
        rel = path.relative_to(root_dir)
    except ValueError as exc:
        logger.debug("watcher code-path: %s not under root %s: %s", path, root_dir, exc)
        return False
    if path.suffix in _CODE_EXTENSIONS:
        return True
    if preprocess_config is not None:
        rel_posix = str(rel).replace("\\", "/")
        return preprocess_config.match(rel_posix) is not None
    return False


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
    log_event(
        logger,
        "service.watcher",
        "started",
        root=root_dir,
        vault=vault_dir,
        debounce_ms=debounce,
        cooldown_seconds=f"{cooldown:.0f}",
    )

    # Track last index times per source to enforce the cooldown window.
    _last_vault_index: float = 0.0
    _last_code_index: float = 0.0

    # Paths observed but not yet reindexed (suppressed by cooldown, or
    # dropped by a failed run). A scoped reindex only processes the paths it
    # is handed, so - unlike the former full rescan, which re-discovered
    # everything each run - these must be carried forward and merged into the
    # next run or the edits would be lost (#151).
    active_vault_job: str | None = None
    active_code_job: str | None = None

    pending_vault: set[Path] = set()
    pending_code: set[Path] = set()
    # Resolved once at watcher start so a watched change to a preprocessable
    # file (e.g. a .pdf) routes through the same debounce/cooldown machinery
    # (#185, D8). A rule added mid-session is picked up on the next restart.
    preprocess_config = code_indexer.preprocess_config()

    try:
        async for changes in awatch(
            root_dir,
            debounce=debounce,
            stop_event=stop_event,
            watch_filter=lambda _change, path: (
                _is_vault_change(Path(path), vault_dir)
                or _is_code_change(Path(path), root_dir, vault_dir, preprocess_config)
            ),
        ):
            for change_type, path_str in changes:
                path = Path(path_str)
                if change_type in (Change.added, Change.modified, Change.deleted):
                    if _is_vault_change(path, vault_dir):
                        pending_vault.add(path)
                    elif _is_code_change(path, root_dir, vault_dir, preprocess_config):
                        pending_code.add(path)

            now = time.monotonic()

            if pending_vault:
                (
                    _last_vault_index,
                    pending_vault,
                    active_vault_job,
                ) = await _process_vault_changes(
                    pending_vault,
                    _last_vault_index,
                    cooldown,
                    now,
                    vault_indexer,
                    graph_cache,
                    active_vault_job,
                )

            if pending_code:
                (
                    _last_code_index,
                    pending_code,
                    active_code_job,
                ) = await _process_code_changes(
                    pending_code,
                    _last_code_index,
                    cooldown,
                    now,
                    code_indexer,
                    active_code_job,
                )
    finally:
        if active_vault_job is not None:
            _jobs.record_finish(
                active_vault_job, phase="cancelled", error="watcher task stopped"
            )
        if active_code_job is not None:
            _jobs.record_finish(
                active_code_job, phase="cancelled", error="watcher task stopped"
            )
        log_event(logger, "service.watcher", "stopped", root=root_dir)


async def _process_vault_changes(
    pending_vault: set[Path],
    _last_vault_index: float,
    cooldown: float,
    now: float,
    vault_indexer: VaultIndexer,
    graph_cache: GraphCache,
    active_vault_job: str | None,
) -> tuple[float, set[Path], str | None]:
    import asyncio
    import time

    if now - _last_vault_index < cooldown:
        log_event(
            logger,
            "service.watcher",
            "reindex_suppressed",
            severity=logging.DEBUG,
            source="vault",
            cooldown_remaining_seconds=f"{cooldown - (now - _last_vault_index):.0f}",
            pending_paths=len(pending_vault),
        )
        return _last_vault_index, pending_vault, active_vault_job

    batch = frozenset(pending_vault)
    active_vault_job = _jobs.record_start(
        "vault",
        "watcher",
        project_root=vault_indexer.root_dir,
    )
    log_event(
        logger,
        "service.watcher",
        "reindex_started",
        source="vault",
        job_id=active_vault_job,
        pending_paths=len(pending_vault),
    )
    _jobs.record_progress(active_vault_job, "queued")
    try:
        result = await _run_in_thread(
            lambda paths=batch, job_id=active_vault_job: (
                vault_indexer.incremental_index(
                    reporter=_jobs.JobProgressReporter(job_id),
                    changed_paths=paths,
                )
            ),
            limiter=get_index_limiter(),
        )
        graph_cache.invalidate()
        _last_vault_index = time.monotonic()
        pending_vault = set()
        _jobs.record_finish(
            active_vault_job,
            result=(
                f"+{result.added} /{result.updated} "
                f"-{result.removed} ({result.duration_ms}ms)"
            ),
        )
        log_event(
            logger,
            "service.watcher",
            "reindex_completed",
            source="vault",
            job_id=active_vault_job,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
        )
    except Exception as exc:
        _jobs.record_finish(active_vault_job, error=str(exc))
        log_event(
            logger,
            "service.watcher",
            "reindex_failed",
            severity=logging.ERROR,
            exc_info=True,
            source="vault",
            job_id=active_vault_job,
            error=exc,
        )
    except asyncio.CancelledError:
        _jobs.record_finish(
            active_vault_job,
            phase="cancelled",
            error="watcher task cancelled",
        )
        raise
    finally:
        active_vault_job = None
    return _last_vault_index, pending_vault, active_vault_job


async def _process_code_changes(
    pending_code: set[Path],
    _last_code_index: float,
    cooldown: float,
    now: float,
    code_indexer: CodebaseIndexer,
    active_code_job: str | None,
) -> tuple[float, set[Path], str | None]:
    import asyncio
    import time

    if now - _last_code_index < cooldown:
        log_event(
            logger,
            "service.watcher",
            "reindex_suppressed",
            severity=logging.DEBUG,
            source="code",
            cooldown_remaining_seconds=f"{cooldown - (now - _last_code_index):.0f}",
            pending_paths=len(pending_code),
        )
        return _last_code_index, pending_code, active_code_job

    batch = frozenset(pending_code)
    active_code_job = _jobs.record_start(
        "code",
        "watcher",
        project_root=code_indexer.root_dir,
    )
    log_event(
        logger,
        "service.watcher",
        "reindex_started",
        source="code",
        job_id=active_code_job,
        pending_paths=len(pending_code),
    )
    _jobs.record_progress(active_code_job, "queued")
    try:
        result = await _run_in_thread(
            lambda paths=batch, job_id=active_code_job: code_indexer.incremental_index(
                reporter=_jobs.JobProgressReporter(job_id),
                changed_paths=paths,
            ),
            limiter=get_index_limiter(),
        )
        _last_code_index = time.monotonic()
        pending_code = set()
        skipped_suffix = (
            f" ~{result.preprocess_skipped}" if result.preprocess_skipped else ""
        )
        _jobs.record_finish(
            active_code_job,
            result=(
                f"+{result.added} /{result.updated} "
                f"-{result.removed} ({result.duration_ms}ms){skipped_suffix}"
            ),
        )
        log_event(
            logger,
            "service.watcher",
            "reindex_completed",
            source="code",
            job_id=active_code_job,
            added=result.added,
            updated=result.updated,
            removed=result.removed,
            duration_ms=result.duration_ms,
        )
    except Exception as exc:
        _jobs.record_finish(active_code_job, error=str(exc))
        log_event(
            logger,
            "service.watcher",
            "reindex_failed",
            severity=logging.ERROR,
            exc_info=True,
            source="code",
            job_id=active_code_job,
            error=exc,
        )
    except asyncio.CancelledError:
        _jobs.record_finish(
            active_code_job,
            phase="cancelled",
            error="watcher task cancelled",
        )
        raise
    finally:
        active_code_job = None
    return _last_code_index, pending_code, active_code_job
