---
title: Qdrant Performance Optimization ADR
source: 2026-06-05-qdrant-performance-research
relevance: 10
tags:
  - '#adr'
  - '#qdrant-performance'
date: '2026-06-05'
modified: '2026-06-30'
related:
  - "[[2026-06-05-qdrant-performance-research]]"
---

# `qdrant-performance` adr: Qdrant Performance and Optimization | (**status:** `accepted`)

## Problem Statement

The RAG vector store layer in `vaultspec-rag` currently relies exclusively on Qdrant local-file mode (`QdrantClient(path=...)` inside `src/vaultspec_rag/store.py`). This causes database lock contention (resulting in `VaultStoreLockedError`) during concurrent searches or parallel CLI/MCP command execution. Additionally, indexing large codebases leads to high RAM consumption due to uncompressed float32 dense vectors, and graph construction is slow when constrained to CPU execution.

## Considerations

- **Concurrency**: Parallel processes (such as concurrent agent search tools or background file watchers) must be able to query and index simultaneously without incurring SQLite lock blockages.
- **Memory Footprint**: Embedding dimensions (1024 floats per chunk) must be compressed to reduce RAM overhead in the vector database.
- **Search Recall & Tuning**: Advanced filtering queries must not degrade in recall accuracy when using complex multi-field filters.
- **Agent Integration**: Search APIs should support native vector recommendation (relevance feedback) to allow agents to refine results dynamically.

## Constraints

- **Backward Compatibility**: The zero-config offline local-file mode fallback must be fully retained to support single-developer local use.
- **Idempotency & Robustness**: Creating indices and collections must remain idempotent across both local and server connection modes.

## Implementation

1. **Configuration Extension**: Expose `VAULTSPEC_RAG_QDRANT_URL` and `VAULTSPEC_RAG_QDRANT_API_KEY` environment variables in `src/vaultspec_rag/config.py` to target external Qdrant Server Mode instances.
1. **Dynamic Client Routing**: Refactor the client instantiation in `src/vaultspec_rag/store.py`. If a URL is configured, bypass the `FileLock` acquisition and open a network-based client connection.
1. **Quantization Configuration**: Implement an optional configuration parameter in `src/vaultspec_rag/config.py` to enable TurboQuant (v1.18) or Scalar Quantization (SQ int8) during collection setup in `src/vaultspec_rag/store.py`.
1. **Relevance Feedback**: Add optional `like_ids` and `unlike_ids` parameters to search APIs in `src/vaultspec_rag/store.py` and `src/vaultspec_rag/api.py`, translating them into Qdrant `RecommendQuery` calls.

## Rationale

Grounded in findings from `2026-06-05-qdrant-performance-research`, transitioning to Qdrant Server Mode removes the process-exclusive lock limitations of SQLite. Enabling TurboQuant or Scalar Quantization compresses dense vectors on the database side, saving up to 75% in memory and accelerating search throughput.

## Consequences

- **Gains**:
  - Unlocks concurrent indexing and search operations without file-locking errors.
  - Significant reduction in database RAM consumption.
  - Enables agentic loops to natively guide retrieval relevance.
- **Pitfalls**:
  - Utilizing the server features requires running a separate Qdrant Docker container or connecting to a managed Qdrant Cloud instance.

## Codification candidates

- **Rule slug:** `qdrant-server-mode-fallback`.
  **Rule:** Always maintain local-file mode compatibility when implementing network-based Qdrant client interfaces.
