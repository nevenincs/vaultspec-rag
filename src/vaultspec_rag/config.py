"""Local configuration wrapper for vaultspec-rag.

Provides RAG-specific defaults and bridges the gap when the base vaultspec
VaultSpecConfig is missing RAG-specific attributes.
"""

from __future__ import annotations

from typing import Any, ClassVar

from vaultspec_core.config import VaultSpecConfig as BaseConfig
from vaultspec_core.config import get_config as get_base_config


class VaultSpecConfigWrapper:
    """Wraps VaultSpecConfig to provide RAG-specific attributes.

    Proxies attribute access to the underlying ``BaseConfig``,
    falling back to ``_RAG_DEFAULTS`` when the base config lacks a
    RAG-specific key.

    Attributes:
        _RAG_DEFAULTS: Default values for RAG-specific configuration
            keys not present on the base ``VaultSpecConfig``.
        _base: The underlying ``VaultSpecConfig`` instance that
            provides project-level settings.
    """

    _RAG_DEFAULTS: ClassVar[dict[str, Any]] = {
        "qdrant_dir": ".qdrant",
        "index_metadata_file": "index_meta.json",
        "graph_ttl_seconds": 300.0,
        "embedding_batch_size": 64,
        "max_embed_chars": 8000,
        "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
        "embedding_dimension": 1024,
        "sparse_model": "naver/splade-v3",
        "reranker_enabled": True,
        "reranker_model": "BAAI/bge-reranker-v2-m3",
        "reranker_batch_size": 32,
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
        """Return a config attribute, falling back to RAG defaults.

        Looks up *name* on the wrapped ``BaseConfig`` first.  If the
        key is a known RAG default and the base config raises
        ``AttributeError``, the default value from
        ``_RAG_DEFAULTS`` is returned instead.

        Args:
            name: The attribute name to look up.

        Returns:
            The attribute value from the base config or the RAG
            default.

        Raises:
            AttributeError: If *name* is not a RAG default and is
                also missing from the base config.
        """
        if name in self._RAG_DEFAULTS:
            try:
                return getattr(self._base, name)
            except AttributeError:
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
