"""Local configuration wrapper for vaultspec-rag.

Provides RAG-specific defaults and bridges the gap when the base vaultspec
VaultSpecConfig is missing RAG-specific attributes.
"""

from __future__ import annotations

from typing import Any

from vaultspec.config import VaultSpecConfig as BaseConfig
from vaultspec.config import get_config as get_base_config


class VaultSpecConfigWrapper:
    """Wraps VaultSpecConfig to provide RAG-specific attributes with defaults."""

    def __init__(self, base: BaseConfig):
        self._base = base

    def __getattr__(self, name: str) -> Any:
        # RAG defaults defined in ADR 2026-02-16
        rag_defaults = {
            "lance_dir": ".lance",
            "qdrant_dir": ".qdrant",
            "index_metadata_file": "index_meta.json",
            "graph_ttl_seconds": 300.0,
            "embedding_batch_size": 64,
            "max_embed_chars": 8000,
            "embedding_model": "Qwen/Qwen3-Embedding-0.6B",
            "embedding_dimension": 1024,
            "sparse_model": "naver/splade-v3",
            "rag_enabled": True,
        }

        if name in rag_defaults:
            try:
                return getattr(self._base, name)
            except AttributeError:
                return rag_defaults[name]

        return getattr(self._base, name)

    @classmethod
    def from_environment(
        cls, overrides: dict[str, Any] | None = None
    ) -> VaultSpecConfigWrapper:
        """Create a wrapped config from environment."""
        base = get_base_config(overrides)
        return cls(base)


def get_config(overrides: dict[str, Any] | None = None) -> VaultSpecConfigWrapper:
    """Return a wrapped config instance with RAG support."""
    base = get_base_config(overrides)
    return VaultSpecConfigWrapper(base)
