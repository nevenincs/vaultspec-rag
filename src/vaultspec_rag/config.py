"""Local configuration wrapper for vaultspec-rag.

Provides RAG-specific defaults and bridges the gap when the base vaultspec
VaultSpecConfig is missing RAG-specific attributes.
"""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Any, ClassVar

from vaultspec_core.config import VaultSpecConfig as BaseConfig
from vaultspec_core.config import get_config as get_base_config


class EnvVar(StrEnum):
    """Recognized environment variables for vaultspec-rag.

    Each member's value is the full env var name.  This enum is the
    single source of truth — no other module should use bare string
    literals when reading or writing env vars for RAG configuration.
    """

    RAG_ROOT = "VAULTSPEC_RAG_ROOT"
    DATA_DIR = "VAULTSPEC_RAG_DATA_DIR"
    QDRANT_DIR = "VAULTSPEC_RAG_QDRANT_DIR"
    INDEX_META = "VAULTSPEC_RAG_INDEX_META"
    CODE_INDEX_META = "VAULTSPEC_RAG_CODE_INDEX_META"
    STATUS_DIR = "VAULTSPEC_RAG_STATUS_DIR"
    LOG_FILE = "VAULTSPEC_RAG_LOG_FILE"
    PORT = "VAULTSPEC_RAG_PORT"
    LOG_LEVEL = "VAULTSPEC_RAG_LOG_LEVEL"
    SERVICE_IDLE_TTL_SECONDS = "VAULTSPEC_RAG_SERVICE_IDLE_TTL_SECONDS"
    SERVICE_MAX_PROJECTS = "VAULTSPEC_RAG_SERVICE_MAX_PROJECTS"
    SERVICE_LOG_MAX_BYTES = "VAULTSPEC_RAG_SERVICE_LOG_MAX_BYTES"
    SERVICE_LOG_BACKUP_COUNT = "VAULTSPEC_RAG_SERVICE_LOG_BACKUP_COUNT"
    # Wall-clock + memory tuning knobs introduced in #68 Track B.
    EMBEDDING_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_BATCH_SIZE"
    EMBEDDING_ENCODE_BATCH_SIZE = "VAULTSPEC_RAG_EMBEDDING_ENCODE_BATCH_SIZE"
    EMBEDDING_MAX_SEQ_LENGTH = "VAULTSPEC_RAG_EMBEDDING_MAX_SEQ_LENGTH"
    MAX_EMBED_CHARS = "VAULTSPEC_RAG_MAX_EMBED_CHARS"

    # Third-party env vars referenced in the codebase — defined here so
    # the string literal lives in exactly one place.
    HF_HOME = "HF_HOME"
    HF_HUB_DOWNLOAD_TIMEOUT = "HF_HUB_DOWNLOAD_TIMEOUT"


# Mapping from _RAG_DEFAULTS key → EnvVar member for env override lookup.
_ENV_OVERRIDE_MAP: dict[str, EnvVar] = {
    "data_dir": EnvVar.DATA_DIR,
    "qdrant_dir": EnvVar.QDRANT_DIR,
    "index_metadata_file": EnvVar.INDEX_META,
    "code_index_metadata_file": EnvVar.CODE_INDEX_META,
    "status_dir": EnvVar.STATUS_DIR,
    "log_file": EnvVar.LOG_FILE,
    "mcp_port": EnvVar.PORT,
    "log_level": EnvVar.LOG_LEVEL,
    "service_idle_ttl_seconds": EnvVar.SERVICE_IDLE_TTL_SECONDS,
    "service_max_projects": EnvVar.SERVICE_MAX_PROJECTS,
    "service_log_max_bytes": EnvVar.SERVICE_LOG_MAX_BYTES,
    "service_log_backup_count": EnvVar.SERVICE_LOG_BACKUP_COUNT,
    # Performance tuning knobs (#68 audit F9.1) — surface them via
    # env vars too so deploy-time tuning does not require CLI flags
    # or config file edits.
    "embedding_batch_size": EnvVar.EMBEDDING_BATCH_SIZE,
    "embedding_encode_batch_size": EnvVar.EMBEDDING_ENCODE_BATCH_SIZE,
    "embedding_max_seq_length": EnvVar.EMBEDDING_MAX_SEQ_LENGTH,
    "max_embed_chars": EnvVar.MAX_EMBED_CHARS,
}


class VaultSpecConfigWrapper:
    """Wraps VaultSpecConfig to provide RAG-specific attributes.

    Proxies attribute access to the underlying ``BaseConfig``,
    falling back to ``_RAG_DEFAULTS`` when the base config lacks a
    RAG-specific key.

    Resolution order for RAG keys:
    1. CLI override (stored via ``overrides`` dict at construction)
    2. Environment variable (via ``_ENV_OVERRIDE_MAP``)
    3. ``_RAG_DEFAULTS`` value

    Attributes:
        _RAG_DEFAULTS: Default values for RAG-specific configuration
            keys not present on the base ``VaultSpecConfig``.
        _base: The underlying ``VaultSpecConfig`` instance that
            provides project-level settings.
    """

    _RAG_DEFAULTS: ClassVar[dict[str, Any]] = {
        "data_dir": ".vault/data/search-data",
        "qdrant_dir": "qdrant",
        "index_metadata_file": "index_meta.json",
        "code_index_metadata_file": "code_index_meta.json",
        "status_dir": "~/.vaultspec-rag",
        "log_file": "service.log",
        "graph_ttl_seconds": 300.0,
        "embedding_batch_size": 64,
        # Inner sub-batch size passed to SentenceTransformer.encode().
        # SentenceTransformer sorts each call's input by sequence
        # length, then processes ``encode_batch_size``-item sub-batches
        # of the sorted list. Smaller values produce tighter
        # length-uniform sub-batches and dramatically reduce padding
        # waste on variable-length corpora (e.g. vault docs ranging
        # from 200 to 8000 chars). 8 is the empirical sweet spot for
        # Qwen3-Embedding-0.6B on a 16 GB GPU. #68 wall-clock work.
        "embedding_encode_batch_size": 8,
        "max_embed_chars": 8000,
        # Hard cap on the sequence length the model is allowed to
        # process. ``max_embed_chars=8000`` truncates text to ~2000
        # tokens for typical Qwen3 BPE; capping ``max_seq_length`` at
        # 2048 prevents the model from advertising 32 k context, which
        # otherwise leaks into kernel-selection heuristics and wastes
        # attention memory on padded sequences.
        "embedding_max_seq_length": 2048,
        "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
        "embedding_dimension": 1024,
        "sparse_model": "naver/splade-v3",
        "reranker_enabled": True,
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_batch_size": 32,
        "mcp_port": 8766,
        "log_level": "WARNING",
        "service_idle_ttl_seconds": 1800,
        "service_max_projects": 16,
        "service_log_max_bytes": 10485760,
        "service_log_backup_count": 5,
    }

    def __init__(self, base: BaseConfig) -> None:
        """Initialise the wrapper around an existing config.

        Args:
            base: The base ``VaultSpecConfig`` to wrap.

        Returns:
            None.
        """
        self._base = base

    def __getattr__(self, name: str) -> Any:
        """Return a config attribute, checking env overrides then defaults.

        Resolution order for known RAG keys:
        1. Base config (may contain CLI overrides)
        2. Environment variable (via ``_ENV_OVERRIDE_MAP``)
        3. ``_RAG_DEFAULTS`` fallback

        Args:
            name: The attribute name to look up.

        Returns:
            The resolved attribute value.

        Raises:
            AttributeError: If *name* is not a RAG default and is
                also missing from the base config.
        """
        if name in self._RAG_DEFAULTS:
            # 1. CLI override via base config
            try:
                return getattr(self._base, name)
            except AttributeError:
                pass

            # 2. Env var override
            env_key = _ENV_OVERRIDE_MAP.get(name)
            if env_key is not None:
                env_val = os.environ.get(env_key.value)
                if env_val is not None:
                    default = self._RAG_DEFAULTS[name]
                    if isinstance(default, bool):
                        return env_val.lower() in ("1", "true", "yes")
                    if isinstance(default, int):
                        return int(env_val)
                    if isinstance(default, float):
                        return float(env_val)
                    return env_val

            # 3. Default
            return self._RAG_DEFAULTS[name]

        return getattr(self._base, name)

    @classmethod
    def from_environment(
        cls,
        overrides: dict[str, Any] | None = None,
    ) -> VaultSpecConfigWrapper:
        """Create a wrapped config from the current environment.

        Args:
            overrides: Optional key/value pairs that override
                environment-derived settings.

        Returns:
            A new ``VaultSpecConfigWrapper`` instance.
        """
        base = get_base_config(overrides)
        return cls(base)


_cached_config: VaultSpecConfigWrapper | None = None


def get_config(
    overrides: dict[str, Any] | None = None,
) -> VaultSpecConfigWrapper:
    """Return a cached ``VaultSpecConfigWrapper`` singleton.

    When called without *overrides*, returns the existing cached
    instance (creating one if necessary).  When called with
    *overrides*, replaces the cached instance with a freshly
    built config that incorporates the given overrides.

    Args:
        overrides: Optional key/value pairs forwarded to
            ``get_base_config()`` to override environment defaults.

    Returns:
        The cached ``VaultSpecConfigWrapper`` instance.
    """
    global _cached_config
    if overrides is not None:
        base = get_base_config(overrides)
        _cached_config = VaultSpecConfigWrapper(base)
        return _cached_config
    if _cached_config is None:
        base = get_base_config()
        _cached_config = VaultSpecConfigWrapper(base)
    return _cached_config


def reset_config() -> None:
    """Clear the cached config singleton (for testing).

    Args:
        None.

    Returns:
        None.
    """
    global _cached_config
    _cached_config = None
