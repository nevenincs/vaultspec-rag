"""Retrieval pipeline for vault semantic search.

Implements query parsing, hybrid search, and graph-aware re-ranking.

This module was split into a package (``search/``) per the
``2026-06-01-module-split-adr``. The verbatim public surface — the
``VaultSearcher`` orchestration class, the ``ParsedQuery`` and
``SearchResult`` dataclasses, the ``parse_query`` and
``rerank_with_graph`` functions, plus the ``_locale_variant_key`` /
``_classify_chunk_type`` / ``_collapse_locale_variants`` helpers that
tests import directly — is re-exported here unchanged.
"""

from __future__ import annotations

from ._models import ParsedQuery, SearchResult
from ._parsing import parse_query
from ._postprocess import (
    _classify_chunk_type,
    _collapse_locale_variants,
    _locale_variant_key,
)
from ._rerank import rerank_with_graph
from ._searcher import VaultSearcher

__all__ = [
    "ParsedQuery",
    "SearchResult",
    "VaultSearcher",
    "_classify_chunk_type",
    "_collapse_locale_variants",
    "_locale_variant_key",
    "parse_query",
    "rerank_with_graph",
]
