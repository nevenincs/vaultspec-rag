---
tags:
  - '#adr'
  - '#sparse-search-latency'
date: '2026-06-07'
related:
  - "[[2026-06-07-sparse-search-latency-research]]"
---

# `sparse-search-latency` adr: `Scaling Bottlenecks` | (**status:** `approved`)

> **Approval Granted**: The blocked status of this ADR was lifted following the successful implementation of the MCP vs. Server terminological deconflation (Issues #167, #168, #169). The CLI and MCP layers are now fully decoupled, satisfying the prerequisite for proceeding with latency optimizations.

## Problem Statement

During full-codebase queries, local-mode search experiences severe latency (up to ~20 seconds for sparse queries across ~114k chunks), primarily because the local Qdrant in-process store forces a linear scan of SPLADE embeddings. Additionally, an architectural audit surfaced a business logic leak in the MCP layer (`src/vaultspec_rag/mcp_server/_tools.py`) where job scheduling logic bypasses the core APIs.

## Considerations

- The Qdrant in-process engine does not currently support inverted index structures for sparse vectors, forcing a full scan.
- Remote/Dedicated Qdrant servers DO support HNSW and inverted sparse indexes.
- Pre-filtering (reducing the candidate space before RRF computation) is heavily supported by Qdrant's payload indexes.
- Our primary mandate is that all UI layers (CLI and MCP) must be thin wrappers containing strictly zero business logic.

## Constraints

- We cannot modify Qdrant's upstream local mode behavior.
- The `sparse_model` parameter is required for the application configuration.
- We must maintain parity between CLI and MCP behaviors; refactoring MCP cannot break existing API stability.

## Implementation

1. **Zero-Business Logic Enforcement:**

   - **Completed**: Refactored `src/vaultspec_rag/mcp/_tools.py` to route the `reindex_vault` and `reindex_codebase` jobs through the unified `vaultspec_rag` top-level API via the `/reindex` REST endpoint, successfully removing direct dependencies on the internal `jobs` module.

1. **Search Latency Optimizations:**

   - **Dense-Only Fallback:** Introduce a `sparse_enabled: bool` toggle to `_RAG_DEFAULTS` inside the configuration module. When `False`, skip SPLADE computation and sparse matching entirely, relying purely on fast dense searches.
   - **Payload Pre-Filtering (ABORTED):** Originally planned to translate glob parameters into regex-backed Qdrant `MatchPattern` filters to narrow the vector space natively. However, `qdrant-client` `1.18.0` strictly forbids regex `MatchPattern` structures on payload fields. Qdrant does not natively support payload filtering via regular expressions. Therefore, the legacy Python-level post-query `fnmatch` iteration will be retained as it is structurally necessary.
   - **Server Mode Support:** Formalize and document the use of `VAULTSPEC_RAG_QDRANT_URL` to enable connecting to high-performance remote Qdrant instances.

## Rationale

Pushing metadata filters to Qdrant allows the local engine to dramatically reduce the linear scan footprint of SPLADE embeddings. Adding a `sparse_enabled` toggle guarantees a fast path for operators who prioritize speed over exact keyword retrieval. Finally, removing the job-scheduling leak from the MCP wrapper adheres to the core principle of keeping all business logic unified and encapsulated within the backend library.

## Consequences

- **Gains:** Major latency reductions in local codebase searches (from ~20s down to sub-second or single-digit seconds depending on pre-filters and fallback toggles). Guaranteed zero business logic in the wrapper layers.
- **Difficulties:** Users managing large codebases locally must actively choose between the slow hybrid search, configuring payload filters, or toggling off the sparse model entirely.
- **Pitfalls:** Heavy payload filtering might occasionally over-constrain the search space if users supply overly strict glob patterns.

## Codification candidates

- **Rule slug:** `zero-business-logic-wrappers`.
  **Rule:** All entry points in CLI and MCP layers must act purely as data mappers and delegates; they must never import internal orchestration or business logic modules directly, but strictly route through the top-level public API.
