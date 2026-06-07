---
tags:
  - '#research'
  - '#sparse-search-latency'
date: '2026-06-07'
related: []
---

<!-- FRONTMATTER RULES:
     tags: one directory tag (hardcoded #research) and one feature tag.
     Replace sparse-search-latency with a kebab-case feature tag, e.g. #foo-bar.
     Additional tags may be appended below the required pair.

     Related: use wiki-links as '[[YYYY-MM-DD-foo-bar]]'.

     DO NOT add frontmatter fields
     outside the frontmatter. -->

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the related: field above.
     - NEVER use [[wiki-links]] or markdown links in the document body.
     - NEVER reference file paths in the body. If you must name a source file,
       class, or function, use inline backtick code: `src/module.py`. -->

# `sparse-search-latency` research: `Scaling Bottlenecks`

This document details the research into sparse search latency and scaling bottlenecks as outlined in issue #165. The primary focus is investigating slow sparse query performance (approx 18.9s) in local-mode relative to dense search (0.48s), and architectural verification of zero-business-logic CLI/MCP wrappers.

## Findings

### 1. Zero-Business-Logic CLI and MCP Wrappers
The CLI and MCP entry points must act solely as thin transport layers containing no business logic.
- **Current state**: Needs audit of `src/vaultspec_rag/cli/` and `src/vaultspec_rag/mcp_server/`.
- **Goal**: Standardize modules to only parse parameters/payloads, invoke core `vaultspec_rag` APIs, and format output. Ensure full integration test coverage without mock/stub test gaps.

### 2. Local-Mode Search Latency & Scaling Bottlenecks
For full-codebase queries (e.g., 114k chunks), the local Qdrant in-process store forces a linear scan of SPLADE embeddings because it lacks inverted index support for sparse vectors in local mode.
- Dense-only latency: ~0.48s
- Sparse-only latency: ~18.9s
- Hybrid search (RRF) latency: ~20.1s

### 3. Proposed Remediation Paths
- **Dense-Only Fallback**: Add a configuration toggle (e.g., `VAULTSPEC_RAG_SPARSE_ENABLED=0` or `dense_only=True`) to skip sparse matching for large codebases.
- **Dedicated Qdrant Server**: Benchmark and document running a standalone Qdrant server instance, which supports native HNSW and inverted sparse indexes.
- **Pre-Filtering**: Investigate automatic partitioning or query optimizations to reduce the active point space before running RRF queries.
