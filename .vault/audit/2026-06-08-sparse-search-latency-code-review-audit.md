---
tags:
  - '#audit'
  - '#sparse-search-latency'
date: '2026-06-08'
modified: '2026-07-27'
body_hash: 'sha256:446e411d0ab5033e01315376bb46c920a74a28714fbf2aaac5ce29df2d0286bd'
related:
  - '[[2026-06-08-sparse-search-latency-plan]]'
---

# `sparse-search-latency` Code Review

## Exception Swallowing & Missing Fast-Path in store.py | CRITICAL | Qdrant RRF failure on single prefetch

The newly added `sparse_enabled` toggle correctly sets the sparse vector to `None` in `src/vaultspec_rag/search/_searcher.py`. However, in `src/vaultspec_rag/store.py` (`hybrid_search` and `hybrid_search_codebase`), the code still attempts to run a `models.RrfQuery` even when `prefetch` contains only a single item (the dense query).

Qdrant's `RrfQuery` requires at least two input queries. Submitting a single prefetch causes `query_points` to raise an exception. The `UnexpectedResponse` block catches this exception and executes a fallback dense-only query. While this returns the correct results, it entirely defeats the performance intent of the feature by introducing a failed network roundtrip, an exception, and a logger warning on **every single request** when `sparse_enabled=False`.

**Recommendation**: Modify `VaultStore` to bypass `RrfQuery` and execute a simple dense-only `query_points` (without RRF) when `sparse_vector is None`.

## Missing Integration Tests for Full Search Path | HIGH | `search_vault` and `search_codebase` untested with sparse off

The implemented test `test_encode_query_respects_sparse_enabled` in `src/vaultspec_rag/tests/integration/test_search_integration.py` only asserts that the internal method `_encode_query` returns `None` for the sparse vector. It does not invoke the public `search_vault` or `search_codebase` methods.

Because the integration tests do not execute the entire search pipeline with `sparse_enabled=False`, the exception-loop failure mode in `VaultStore` went undetected.

**Recommendation**: Add tests that instantiate `VaultSearcher` with `sparse_enabled=False` and execute `search_vault` and `search_codebase` end-to-end to ensure the full pipeline correctly handles the missing sparse vector.

## Scope

Retained audit evidence: 2026-06-08-sparse-search-latency-plan are listed in frontmatter; the audit title and retained sections define the reviewed subject.

## Findings

Retained audit evidence: the detailed review entries in this document constitute the findings inventory.

## Recommendations

Evidence gap: the retained audit body and complete git log --follow history state no separate recommendations. No recommendation is asserted.
