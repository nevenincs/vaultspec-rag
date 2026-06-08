---
tags:
  - '#plan'
  - '#sparse-search-latency'
date: '2026-06-08'
tier: L2
related:
  - "[[2026-06-07-sparse-search-latency-adr]]"
  - "[[2026-06-07-sparse-search-latency-research]]"
---

# `sparse-search-latency` `Scaling Bottlenecks` plan

## Description

This plan implements latency optimizations for the VaultSpec RAG service to address issue #165. Based on the findings in `[[2026-06-07-sparse-search-latency-research]]` and authorized by `[[2026-06-07-sparse-search-latency-adr]]`, we are introducing a fast-path dense-only fallback by adding a `sparse_enabled` toggle. Additionally, we are pushing the python `fnmatch` filtering down into Qdrant using native `MatchPattern` regex filters to heavily narrow the candidate space prior to costly RRF evaluation during sparse codebase searches.

## Steps

### Phase `P01` - Dense-Only Fallback

Introduce sparse_enabled toggle in configuration to bypass SPLADE and accelerate dense-only queries.

- [ ] `P01.S01` - Add sparse_enabled to \_RAG_DEFAULTS; `src/vaultspec_rag/config.py`.
- [ ] `P01.S02` - Skip SPLADE computation and index fetching when sparse_enabled is False; `src/vaultspec_rag/search/_searcher.py`.
- [ ] `P01.S03` - Update tests to assert dense-only fallback works; `src/vaultspec_rag/tests/`.

### Phase `P02` - Glob Pre-Filtering via Qdrant MatchPattern

Map glob filters to Qdrant native filters before search to skip post-query Python filtering.

- [ ] `P02.S04` - Translate include_paths and exclude_paths globs to Regex strings; `src/vaultspec_rag/search/_searcher.py`.
- [ ] `P02.S05` - Update VaultStore.hybrid_search_codebase to accept regex filters and construct MatchPattern; `src/vaultspec_rag/store.py`.
- [ ] `P02.S06` - Remove post-query \_filter_raw_codebase_results logic; `src/vaultspec_rag/search/_searcher.py`.
- [ ] `P02.S07` - Update tests to assert Qdrant glob filtering works correctly; `src/vaultspec_rag/tests/`.

## Parallelization

- Phases `P01` and `P02` modify different orthogonal paths within the search implementation. They can be implemented sequentially or in parallel without conflict.

## Verification

- Running codebase search with `--no-sparse` (or `sparse_enabled=False`) skips the SPLADE encoding and executes in ~0.5s instead of ~20s.
- `include_paths` and `exclude_paths` glob parameters continue to correctly filter results, but the filtering executes natively inside Qdrant.
- Integration tests and search unit tests fully pass.
