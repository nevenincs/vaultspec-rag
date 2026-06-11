"""On-disk cache for preprocessor output (D7).

Re-running a project extractor (OCR, large PDF, workbook parse) on every full
or restart reindex is wasteful when the source has not changed. This module
caches a *successful* :class:`PreprocOutput` per source file under the data dir,
keyed on the source content hash plus the rule's command and the supported
schema version, so an unchanged file skips the (potentially expensive)
extraction.

Only successful outputs are cached. Skips and passthroughs are re-attempted on
each pass, so a transient extractor failure (e.g. a timeout under load) is never
made sticky. The cache is consulted inside the CPU-only spawn worker, so this
module stays torch-free and dependency-light.

Key composition (D7): ``blake2b(source_hash | command | schema_version)``. The
source hash is the dominant invalidation signal - a changed file produces a new
hash and therefore a new key. The command is the project's explicit lever: a
project that upgrades its extractor without touching the source bumps the
command (or runs a clean rebuild) to force re-extraction. Per-source files under
a two-char shard directory avoid a single-writer manifest bottleneck across the
parallel workers.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import TYPE_CHECKING, cast

from pydantic import ValidationError

from ._preprocess_schema import (
    SUPPORTED_SCHEMA_VERSION,
    UnsupportedSchemaVersionError,
    validate_preproc_output,
)

if TYPE_CHECKING:
    import pathlib

    from ._preprocess_schema import PreprocOutput

logger = logging.getLogger(__name__)

__all__ = [
    "PREPROCESS_CACHE_DIRNAME",
    "clear_preprocess_cache",
    "preprocess_cache_dir",
    "read_cached_output",
    "write_cached_output",
]

#: Subdirectory (under the resolved data dir) holding the preprocess cache.
PREPROCESS_CACHE_DIRNAME = "preprocess-cache"


def preprocess_cache_dir(data_root: pathlib.Path) -> pathlib.Path:
    """Return the preprocess cache root under a resolved data directory.

    Args:
        data_root: The project's resolved data directory
            (``root_dir / cfg.data_dir``).
    """
    return data_root / PREPROCESS_CACHE_DIRNAME


def _cache_key(source_hash: str, command: str) -> str:
    """Compute the content-addressed cache key for a source/command pair."""
    digest = hashlib.blake2b(digest_size=16)
    digest.update(source_hash.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(command.encode("utf-8"))
    digest.update(b"\x00")
    digest.update(str(SUPPORTED_SCHEMA_VERSION).encode("utf-8"))
    return digest.hexdigest()


def _cache_path(cache_root: pathlib.Path, key: str) -> pathlib.Path:
    """Return the sharded cache file path for a key."""
    return cache_root / key[:2] / f"{key}.json"


def read_cached_output(
    cache_root: pathlib.Path,
    source_hash: str,
    command: str,
) -> PreprocOutput | None:
    """Return the cached output for a source/command pair, or ``None`` on miss.

    A corrupt or schema-invalid cache entry is treated as a miss (and logged at
    debug), so a stale cache never crashes indexing - it just re-runs.

    Args:
        cache_root: The preprocess cache root (see :func:`preprocess_cache_dir`).
        source_hash: The source file's content hash.
        command: The matched rule's command template.

    Returns:
        The validated :class:`PreprocOutput`, or ``None`` if absent or unusable.
    """
    path = _cache_path(cache_root, _cache_key(source_hash, command))
    if not path.is_file():
        return None
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.debug("preprocess cache %s unreadable; miss: %s", path, exc)
        return None
    if not isinstance(loaded, dict):
        return None
    entry = cast("dict[str, object]", loaded)
    if entry.get("source_hash") != source_hash or entry.get("command") != command:
        # Key collision or tampering; treat as a miss rather than trust it.
        return None
    try:
        return validate_preproc_output(entry.get("output"))
    except (ValidationError, UnsupportedSchemaVersionError) as exc:
        logger.debug("preprocess cache %s failed re-validation; miss: %s", path, exc)
        return None


def write_cached_output(
    cache_root: pathlib.Path,
    source_hash: str,
    command: str,
    output: PreprocOutput,
) -> None:
    """Atomically cache a successful output for a source/command pair.

    Uses write-to-temp + ``os.replace`` (the same idiom as the index metadata
    sidecar) so a crash mid-write never leaves a torn cache file. Write failures
    are logged at debug and swallowed - the cache is an optimisation, never a
    correctness dependency.

    Args:
        cache_root: The preprocess cache root.
        source_hash: The source file's content hash.
        command: The matched rule's command template.
        output: The validated output to cache.
    """
    path = _cache_path(cache_root, _cache_key(source_hash, command))
    entry = {
        "source_hash": source_hash,
        "command": command,
        "schema_version": output.schema_version,
        "preprocessor_id": output.preprocessor_id,
        "preprocessor_version": output.preprocessor_version,
        "output": output.model_dump(mode="json"),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Per-process temp suffix so two workers writing byte-identical sources
        # (same cache key) never collide on one temp file (review PREPROCESS-006).
        tmp_path = path.with_suffix(f".{os.getpid()}.tmp")
        tmp_path.write_text(json.dumps(entry), encoding="utf-8")
        os.replace(tmp_path, path)
    except OSError as exc:
        logger.debug("could not write preprocess cache %s: %s", path, exc)


def clear_preprocess_cache(cache_root: pathlib.Path) -> None:
    """Remove the entire preprocess cache subtree (for a clean rebuild, D7).

    Args:
        cache_root: The preprocess cache root.
    """
    import shutil

    if cache_root.exists():
        shutil.rmtree(cache_root, ignore_errors=True)
