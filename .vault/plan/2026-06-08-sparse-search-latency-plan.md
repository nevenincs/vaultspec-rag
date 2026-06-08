---
tags:
  - '#plan'
  - '#sparse-search-latency'
date: '2026-06-08'
tier: L2
related:
  - '[[2026-06-07-sparse-search-latency-adr]]'
  - '[[2026-06-07-sparse-search-latency-research]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

<!-- RETIRED: S09 -->

# `sparse-search-latency` `Scaling Bottlenecks` plan

## Description

This plan implements latency optimizations for the VaultSpec RAG service to address issue #165. Based on the findings in `[[2026-06-07-sparse-search-latency-research]]` and authorized by `[[2026-06-07-sparse-search-latency-adr]]`, we are introducing a fast-path dense-only fallback by adding a `sparse_enabled` toggle. Additionally, we are pushing the python `fnmatch` filtering down into Qdrant using native `MatchPattern` regex filters to heavily narrow the candidate space prior to costly RRF evaluation during sparse codebase searches.

## Steps

### Phase `P01` - Dense-Only Fallback

Introduce sparse_enabled toggle in configuration to bypass SPLADE and accelerate dense-only queries.

- [x] `P01.S01` - Add sparse_enabled to \_RAG_DEFAULTS; `src/vaultspec_rag/config.py`.
- [x] `P01.S02` - Skip SPLADE computation and index fetching when sparse_enabled is False; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P01.S03` - Update tests to assert dense-only fallback works; `src/vaultspec_rag/tests/`.

### Phase `P02` - Glob Pre-Filtering via Qdrant MatchPattern

Map glob filters to Qdrant native filters before search to skip post-query Python filtering.

- [x] `P02.S04` - Translate include_paths and exclude_paths globs to Regex strings; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P02.S05` - Update VaultStore.hybrid_search_codebase to accept regex filters and construct MatchPattern; `src/vaultspec_rag/store.py`.
- [x] `P02.S06` - Remove post-query \_filter_raw_codebase_results logic; `src/vaultspec_rag/search/_searcher.py`.
- [x] `P02.S07` - Update tests to assert Qdrant glob filtering works correctly; `src/vaultspec_rag/tests/`.

### Phase `P03` - Comprehensive Code Review

Run extensive code reviews to identify and mitigate any hidden exceptions, edge cases, or performance cliffs introduced during the latency optimizations.

- [x] `P03.S08` - Run Vaultspec Code Reviewer subagent for full scope audit; `src/vaultspec_rag/`.
- [x] `P03.S10` - Resolve MCP Deconflation Gap (CRITICAL); `src/vaultspec_rag/mcp/`.
- [x] `P03.S11` - Resolve Execution Paths & Latency Bottlenecks (HIGH); `src/vaultspec_rag/store.py`.
- [x] `P03.S12` - Resolve Sparse Fallback Boundaries Leak (HIGH); `src/vaultspec_rag/indexer/_streaming.py`.

## Parallelization

- Phases `P01` and `P02` modify different orthogonal paths within the search implementation. They can be implemented sequentially or in parallel without conflict.

## Verification

- Running codebase search with `--no-sparse` (or `sparse_enabled=False`) skips the SPLADE encoding and executes in ~0.5s instead of ~20s.
- `include_paths` and `exclude_paths` glob parameters continue to correctly filter results, but the filtering executes natively inside Qdrant.
- Integration tests and search unit tests fully pass.
