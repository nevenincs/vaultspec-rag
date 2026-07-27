"""On-disk cache for preprocessor output.

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

Key composition: ``blake2b(source_hash | command | schema_version)``. The
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
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, cast

from pydantic import ValidationError

from .._atomic_write import write_json_atomically
from ._preprocess_schema import (
    SUPPORTED_SCHEMA_VERSION,
    UnsupportedSchemaVersionError,
    validate_max_emitted_bytes,
    validate_preproc_output,
)

if TYPE_CHECKING:
    import pathlib

    from ._preprocess_config import PreprocessRule
    from ._preprocess_schema import PreprocessInvocationMode, PreprocOutput

logger = logging.getLogger(__name__)

__all__ = [
    "PREPROCESS_CACHE_DIRNAME",
    "PreprocessCacheIdentity",
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


@dataclass(frozen=True, slots=True)
class PreprocessCacheIdentity:
    """Complete deterministic identity for one successful extraction."""

    source_path: str
    source_hash: str
    execution_fingerprint: str
    path_independent: bool = False

    def __post_init__(self) -> None:
        normalized = PurePosixPath(self.source_path)
        if (
            not self.source_path
            or normalized.is_absolute()
            or ".." in normalized.parts
            or normalized.as_posix() != self.source_path
        ):
            raise ValueError("source_path must be normalized and project-relative")
        if not self.source_hash or not self.execution_fingerprint:
            raise ValueError("cache hashes and fingerprints must be non-empty")
        if not isinstance(self.path_independent, bool):  # pyright: ignore[reportUnnecessaryIsInstance] - runtime API validation
            raise TypeError("path_independent must be a bool")

    @classmethod
    def from_rule(
        cls,
        *,
        source_path: str,
        source_hash: str,
        rule: PreprocessRule,
        mode: PreprocessInvocationMode,
        max_emitted_bytes: int,
    ) -> PreprocessCacheIdentity:
        """Bind one source to the rule's complete execution semantics."""
        validate_max_emitted_bytes(max_emitted_bytes)
        execution = {
            "command": rule.command,
            "entry_point": rule.entry_point,
            "options": dict(rule.options),
            "extractor_version": rule.extractor_version,
            "target": rule.target.value,
            "mode": mode,
            "max_emitted_bytes": max_emitted_bytes,
            "output_schema": SUPPORTED_SCHEMA_VERSION,
        }
        encoded = json.dumps(
            execution,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return cls(
            source_path=source_path,
            source_hash=source_hash,
            execution_fingerprint=hashlib.blake2b(encoded.encode("utf-8")).hexdigest(),
            path_independent=rule.path_independent,
        )

    @property
    def key(self) -> str:
        """Return the sharded filename key for this identity."""
        payload = asdict(self)
        if self.path_independent:
            payload["source_path"] = ""
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.blake2b(encoded.encode("utf-8"), digest_size=16).hexdigest()


def _cache_path(cache_root: pathlib.Path, key: str) -> pathlib.Path:
    """Return the sharded cache file path for a key."""
    return cache_root / key[:2] / f"{key}.json"


def read_cached_output(
    cache_root: pathlib.Path,
    identity: PreprocessCacheIdentity,
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
    path = _cache_path(cache_root, identity.key)
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
    expected = asdict(identity)
    if identity.path_independent:
        expected["source_path"] = ""
    if entry.get("identity") != expected:
        # Key collision or tampering; treat as a miss rather than trust it.
        return None
    try:
        return validate_preproc_output(entry.get("output"))
    except (ValidationError, UnsupportedSchemaVersionError) as exc:
        logger.debug("preprocess cache %s failed re-validation; miss: %s", path, exc)
        return None


def write_cached_output(
    cache_root: pathlib.Path,
    identity: PreprocessCacheIdentity,
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
    path = _cache_path(cache_root, identity.key)
    stored_identity = asdict(identity)
    if identity.path_independent:
        stored_identity["source_path"] = ""
    entry = {
        "identity": stored_identity,
        "schema_version": output.schema_version,
        "preprocessor_id": output.preprocessor_id,
        "preprocessor_version": output.preprocessor_version,
        "output": output.model_dump(mode="json"),
    }
    try:
        write_json_atomically(path, entry)
    except OSError as exc:
        logger.debug("could not write preprocess cache %s: %s", path, exc)


def clear_preprocess_cache(cache_root: pathlib.Path) -> None:
    """Remove the entire preprocess cache subtree (for a clean rebuild).

    Args:
        cache_root: The preprocess cache root.
    """
    import shutil

    if cache_root.exists():
        shutil.rmtree(cache_root, ignore_errors=True)
