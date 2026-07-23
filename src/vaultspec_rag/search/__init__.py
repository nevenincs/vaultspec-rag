"""Retrieval pipeline for vault semantic search.

Implements query parsing, hybrid search, and graph-aware re-ranking.

This module was split into a package (``search/``) from a former
monolith. The verbatim public surface - the
``VaultSearcher`` orchestration class, the ``ParsedQuery`` and
``SearchResult`` dataclasses, the ``parse_query`` and
``rerank_with_graph`` functions, plus the ``_locale_variant_key`` /
``_classify_chunk_type`` / ``_collapse_locale_variants`` helpers that
tests import directly - is re-exported here unchanged.
"""

from __future__ import annotations

from ._models import DocumentSearchResult, ParsedQuery, SearchResult
from ._outcomes import CombinedSearchOutcome, SearchDomainOutcome
from ._parsing import parse_query
from ._postprocess import (
    _classify_chunk_type,  # pyright: ignore[reportPrivateUsage]  # deliberately re-exported as public API; tests import by this name
    _collapse_locale_variants,  # pyright: ignore[reportPrivateUsage]  # deliberately re-exported as public API; tests import by this name
    _locale_variant_key,  # pyright: ignore[reportPrivateUsage]  # deliberately re-exported as public API; tests import by this name
)
from ._rerank import rerank_with_graph
from ._searcher import VaultSearcher
from ._validation import (
    InvalidFilterForSearchTypeError,
    InvalidPreferValueError,
    validate_search_filters,
)

__all__ = [
    "CombinedSearchOutcome",
    "DocumentSearchResult",
    "InvalidFilterForSearchTypeError",
    "InvalidPreferValueError",
    "ParsedQuery",
    "SearchDomainOutcome",
    "SearchResult",
    "VaultSearcher",
    "_classify_chunk_type",
    "_collapse_locale_variants",
    "_locale_variant_key",
    "parse_query",
    "rerank_with_graph",
    "validate_search_filters",
]
