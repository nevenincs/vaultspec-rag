"""Retrieval pipeline for vault semantic search.

Implements query parsing, hybrid search, and graph-aware re-ranking.

This module was split into a package (``search/``) from a former
monolith. The verbatim public surface - the
``VaultSearcher`` orchestration class, the ``ParsedQuery`` and
``SearchResult`` dataclasses, and the ``parse_query`` and
``rerank_with_graph`` functions - is re-exported here unchanged.
"""

from __future__ import annotations

from ._models import DocumentSearchResult, ParsedQuery, SearchResult
from ._outcomes import CombinedSearchOutcome, SearchDomainOutcome
from ._parsing import parse_query
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
    "parse_query",
    "rerank_with_graph",
    "validate_search_filters",
]
