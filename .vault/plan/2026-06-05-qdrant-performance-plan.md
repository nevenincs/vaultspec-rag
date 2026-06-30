---
tags:
  - '#plan'
  - '#qdrant-performance'
date: '2026-06-05'
modified: '2026-06-30'
tier: L3
related:
  - '[[2026-06-05-qdrant-performance-adr]]'
  - '[[2026-06-05-qdrant-performance-research]]'
---

# `qdrant-performance` `qdrant-performance-plan` plan

## Wave `W01` - Config extension and client routing

Implement QDRANT_URL configuration and support Server Mode in VaultStore to bypass SQLite file locks.

### Phase `W01.P01` - Implement configuration parsing

Expose QDRANT_URL and QDRANT_API_KEY environment variables.

- [x] `W01.P01.S01` - Expose QDRANT_URL and QDRANT_API_KEY environment variables in config class; `src/vaultspec_rag/config.py`.

### Phase `W01.P02` - Refactor client instantiation

Bypass file lock checks when Server Mode is configured.

- [x] `W01.P02.S02` - Refactor VaultStore client initialization to bypass FileLock and connect to url; `src/vaultspec_rag/store.py`.

## Wave `W02` - Quantization and search options

Support SQ int8 and Relevance Feedback APIs.

### Phase `W02.P03` - Quantization config support

Allow configuring scalar/product quantization during collection creation.

- [x] `W02.P03.S03` - Add QDRANT_QUANTIZATION environment variable to config wrapper; `src/vaultspec_rag/config.py`.
- [x] `W02.P03.S04` - Configure scalar/product/turbo quantization in Qdrant collection creation; `src/vaultspec_rag/store.py`.

### Phase `W02.P04` - Relevance Feedback support

Add support for relevance feedback recommendations in search.

- [x] `W02.P04.S05` - Add support for positive/negative recommendations in hybrid search calls; `src/vaultspec_rag/store.py`.
- [x] `W02.P04.S06` - Expose like_ids and unlike_ids parameters in api.py search facade functions; `src/vaultspec_rag/api.py`.

## Description

This plan implements performance optimizations and concurrent scaling for vaultspec-rag. It exposes QDRANT_URL and QDRANT_API_KEY environment variables to transition from the locked SQLite local-file mode to Qdrant Server Mode. Additionally, it implements configurable vector quantization (TurboQuant and Scalar Quantization SQ int8) and Relevance Feedback search support, in accordance with the decision ADR.

## Parallelization

Waves W01 and W02 must be executed sequentially, as quantization and recommendation settings depend on having the configuration and server routing backend layer constructed first. Phases within Wave W01 and Wave W02 can be parallelized once their initial database setup steps are completed.

## Verification

- All unit and integration tests compile and run successfully using pytest.
- CLI and MCP commands operate cleanly when a QDRANT_URL is provided, executing search and indexing concurrently without VaultStoreLockedError.
- Collection configurations confirm that quantization (e.g., SQ or TurboQuant) is applied on the Qdrant server side when indexing.
