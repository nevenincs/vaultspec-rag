---
tags:
  - '#exec'
  - '#search-noise-filtering'
date: '2026-06-30'
modified: '2026-06-30'
step_id: 'S03'
related:
  - "[[2026-06-30-search-noise-filtering-plan]]"
---

# Extend the code filter builder for domain must/must_not pushdown driving exclude-domain and only-domain

## Scope

- `src/vaultspec_rag/store.py`

## Description

- Extend `_build_code_filter` with keyword-only `exclude_domains` /
  `only_domains`: exclude becomes a `must_not` `MatchAny` on the `domain`
  payload field, only becomes a `must` `MatchAny` - both Qdrant pushdown.
- Return `Filter(must=..., must_not=...)` and yield `None` only when no
  conditions of any kind were produced.
- Thread `exclude_domains` / `only_domains` through `hybrid_search_codebase`.
- Tests: exclude->must_not, only->must, empty->None.

## Outcome

`pytest` over the filter-builder tests -> 4 passed. Domain filtering is a
collection-side pushdown (unbounded, not overfetch-limited) on the indexed
`domain` field, available the moment a chunk carries the payload.

## Notes

Pushdown applies only to chunks already carrying the `domain` payload; the
searcher (S04) adds a post-query fallback so un-backfilled chunks are still
classified and filtered.
