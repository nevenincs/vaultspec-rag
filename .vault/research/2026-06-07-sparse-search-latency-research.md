---
tags:
  - '#research'
  - '#sparse-search-latency'
date: '2026-06-07'
modified: '2026-06-30'
related: []
---

# `sparse-search-latency` research: `Scaling Bottlenecks`

This document details the research into sparse search latency and scaling bottlenecks as outlined in issue #165. The primary focus is investigating slow sparse query performance (approx 18.9s) in local-mode relative to dense search (0.48s), and architectural verification of zero-business-logic CLI/MCP wrappers.

## Findings

### 1. Zero-Business-Logic CLI and MCP Wrappers

The CLI and MCP entry points must act solely as thin transport layers containing no business logic.

- **Current state**:
  - `src/vaultspec_rag/cli/`: Codebase discovery confirms that the CLI correctly acts as a transport layer. Commands in `cli/_search.py` and `cli/_index.py` correctly delegate to core `vaultspec_rag.search_codebase` / `search_vault` and `vaultspec_rag.index` APIs.
  - `src/vaultspec_rag/mcp_server/`: While it avoids low-level stores like `QdrantClient` and `VectorParams`, we found a logic leak in `src/vaultspec_rag/mcp_server/_tools.py`. The MCP tools `reindex_vault` and `reindex_codebase` import and invoke internal background job scheduling (`from ..jobs import start_reindex_vault, start_reindex_codebase`) directly, rather than routing through unified `vaultspec_rag` core APIs.
- **Goal**: Standardize modules to only parse parameters/payloads, invoke core `vaultspec_rag` APIs, and format output. Ensure full integration test coverage without mock/stub test gaps.

### 2. Local-Mode Search Latency & Scaling Bottlenecks

For full-codebase queries (e.g., 114k chunks), the local Qdrant in-process store forces a linear scan of SPLADE embeddings because it lacks inverted index support for sparse vectors in local mode.

- Dense-only latency: ~0.48s
- Sparse-only latency: ~18.9s
- Hybrid search (RRF) latency: ~20.1s

### 3. Proposed Remediation Paths Evaluation

Based on codebase investigation within `search.py`, `store.py`, and `config.py`:

- **Dense-Only Fallback**: Highly feasible. `src/vaultspec_rag/config.py` contains settings for `sparse_model: "naver/splade-v3"` but lacks an explicit toggle. We can easily add a `sparse_enabled: True` setting (analogous to the existing `reranker_enabled: True` setting in `_RAG_DEFAULTS`) and wire it up to selectively disable sparse queries. If `sparse_enabled` is False, the fallback skips sparse index fetching and SPLADE computation.
- **Dedicated Qdrant Server**: Already supported by the configuration. `src/vaultspec_rag/config.py` reads `EnvVar.QDRANT_URL` and `qdrant_api_key`. `src/vaultspec_rag/store.py` checks `if cfg.qdrant_url:` and correctly provisions a remote connection (`_QdrantClient(url=cfg.qdrant_url, api_key=cfg.qdrant_api_key)`).
- **Pre-Filtering (ABORTED)**: We initially explored structurally supporting glob filtering natively in Qdrant. While `src/vaultspec_rag/store.py` registers `PayloadSchemaType.KEYWORD` indexes for path attributes, Qdrant (`1.18.0`) natively lacks any `MatchPattern` or regular expression capabilities on payload fields. Trying to filter payload strings using translated glob-to-regex patterns fails Pydantic validation on the `qdrant-client`. Consequently, avoiding post-query Python filtering for globs is impossible with the current backend.
