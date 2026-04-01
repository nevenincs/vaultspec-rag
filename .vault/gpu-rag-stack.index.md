---
generated: true
tags:
  - '#gpu-rag-stack'
date: '2026-04-01'
related:
  - '[[2026-03-06-cli-api-audit]]'
  - '[[2026-03-06-cli-mcp-audit]]'
  - '[[2026-03-06-codebase-indexer-audit]]'
  - '[[2026-03-06-codebase-indexer-tech-stack-research]]'
  - '[[2026-03-06-config-dependencies-audit]]'
  - '[[2026-03-06-embeddings-gpu-pivot-audit]]'
  - '[[2026-03-06-gpu-only-rag-stack-adr]]'
  - '[[2026-03-06-gpu-rag-architecture-research]]'
  - '[[2026-03-06-gpu-vector-search-deep-dive-research]]'
  - '[[2026-03-06-indexer-pipeline-audit]]'
  - '[[2026-03-06-mcp-security-audit]]'
  - '[[2026-03-06-search-pipeline-audit]]'
  - '[[2026-03-06-test-infrastructure-audit]]'
  - '[[2026-03-07-adr-compliance-audit]]'
  - '[[2026-03-07-adr-test-coverage-audit]]'
  - '[[2026-03-07-api-adr-tests-audit]]'
  - '[[2026-03-07-api-config-audit]]'
  - '[[2026-03-07-api-verification-research]]'
  - '[[2026-03-07-blake2b-file-hashing-adr]]'
  - '[[2026-03-07-cli-round14-audit]]'
  - '[[2026-03-07-config-init-round12-audit]]'
  - '[[2026-03-07-continuous-research]]'
  - '[[2026-03-07-embeddings-round10-audit]]'
  - '[[2026-03-07-final-sweep-round27-audit]]'
  - '[[2026-03-07-indexer-round23-audit]]'
  - '[[2026-03-07-indexer-round8-audit]]'
  - '[[2026-03-07-indexer-store-api-audit]]'
  - '[[2026-03-07-integration-tests-round13-audit]]'
  - '[[2026-03-07-integration-tests-round26-audit]]'
  - '[[2026-03-07-libdoc-verification-research]]'
  - '[[2026-03-07-manual-node-walking-adr]]'
  - '[[2026-03-07-mcp-round11-audit]]'
  - '[[2026-03-07-mcp-sync-tools-adr]]'
  - '[[2026-03-07-orchestrator-log-audit]]'
  - '[[2026-03-07-path-resolve-engine-cache-adr]]'
  - '[[2026-03-07-pending-task-verification-audit]]'
  - '[[2026-03-07-qdrant-filter-on-prefetch-adr]]'
  - '[[2026-03-07-qdrant-payload-indexes-local-adr]]'
  - '[[2026-03-07-qwen3-no-document-prompt-adr]]'
  - '[[2026-03-07-score-normalization-adr]]'
  - '[[2026-03-07-search-cli-mcp-audit]]'
  - '[[2026-03-07-search-round7-audit]]'
  - '[[2026-03-07-store-embeddings-audit]]'
  - '[[2026-03-07-store-round9-audit]]'
  - '[[2026-03-07-test-compliance-round2-audit]]'
  - '[[2026-03-07-test-live-audit]]'
  - '[[2026-03-07-test-mandate-audit]]'
  - '[[2026-03-07-tests-round25-audit]]'
  - '[[2026-03-07-threading-lock-for-singleton-adr]]'
  - '[[2026-03-07-vaultgraph-cache-adr]]'
  - '[[2026-03-08-compliance-reaudit-audit]]'
  - '[[2026-03-08-continuous-audit]]'
  - '[[2026-03-08-cross-module-round29-audit]]'
  - '[[2026-03-08-embeddings-round26-audit]]'
  - '[[2026-03-08-fastmcp-lifespan-research]]'
  - '[[2026-03-08-fixture-audit]]'
  - '[[2026-03-08-indexer-correctness-audit]]'
  - '[[2026-03-08-mcp-config-watcher-round28-audit]]'
  - '[[2026-03-08-qdrant-filter-verification-research]]'
  - '[[2026-03-08-qdrant-hybrid-search-patterns-research]]'
  - '[[2026-03-08-search-embeddings-audit]]'
  - '[[2026-03-08-search-round27-audit]]'
  - '[[2026-03-08-store-api-round25-audit]]'
  - '[[2026-03-08-target-flag-propagation-audit]]'
  - '[[2026-03-08-test-mandate-audit]]'
  - '[[2026-03-08-watcher-clipath-audit]]'
  - '[[2026-03-09-coverage-compliance-round33-audit]]'
  - '[[2026-03-09-graph-embedding-round35-audit]]'
  - '[[2026-03-09-graph-embedding-round36-audit]]'
  - '[[2026-03-09-graph-reranker-round34-audit]]'
  - '[[2026-03-09-mcp-server-documentation-audit]]'
  - '[[2026-03-09-performance-round33-audit]]'
  - '[[2026-03-09-qwen3-task-prefix-verification-research]]'
  - '[[2026-03-09-round30-new-code-audit]]'
  - '[[2026-03-09-security-errors-round32-audit]]'
  - '[[2026-03-09-test-infra-round31-audit]]'
---

# `gpu-rag-stack` feature index

Auto-generated index of all documents tagged with `#gpu-rag-stack`.

## Documents

### adr

- `2026-03-06-gpu-only-rag-stack-adr` - ADR: GPU-Only RAG Stack — sentence-transformers + Qwen3 + SPLADE v3
- `2026-03-07-blake2b-file-hashing-adr` - ADR: Use blake2b via `file_digest()` for file change detection
- `2026-03-07-manual-node-walking-adr` - ADR: Manual tree-sitter node walking over Query API for metadata extraction
- `2026-03-07-mcp-sync-tools-adr` - ADR: MCP tools use `async def` + `anyio.to_thread.run_sync`
- `2026-03-07-path-resolve-engine-cache-adr` - ADR: Use `Path.resolve()` for engine cache key
- `2026-03-07-qdrant-filter-on-prefetch-adr` - ADR: Filters must go on each Prefetch, not top-level `query_filter`
- `2026-03-07-qdrant-payload-indexes-local-adr` - ADR: Payload indexes are no-ops in local mode; add for forward compatibility
- `2026-03-07-qwen3-no-document-prompt-adr` - ADR: Qwen3-Embedding encodes documents without prompt, queries with `prompt_name="query"`
- `2026-03-07-score-normalization-adr` - ADR: Sigmoid + min-max per-source normalization in `search_all()`
- `2026-03-07-threading-lock-for-singleton-adr` - ADR: Use `threading.Lock` for `get_comp()` singleton
- `2026-03-07-vaultgraph-cache-adr` - ADR: VaultGraph cache with `threading.Lock` and explicit invalidation

### audit

- `2026-03-06-cli-api-audit` - Audit: CLI and API Facade
- `2026-03-06-cli-mcp-audit` - CLI and MCP Server Audit Report
- `2026-03-06-codebase-indexer-audit` - CodebaseIndexer Audit — 2026-03-06
- `2026-03-06-config-dependencies-audit` - Audit: Config and Dependencies
- `2026-03-06-embeddings-gpu-pivot-audit` - Audit: Embeddings GPU Pivot
- `2026-03-06-indexer-pipeline-audit` - Audit: Indexer Pipeline
- `2026-03-06-mcp-security-audit` - Audit: MCP Server Security
- `2026-03-06-search-pipeline-audit` - Audit: Search Pipeline
- `2026-03-06-test-infrastructure-audit` - Audit: Test Infrastructure
- `2026-03-07-adr-compliance-audit` - ADR Compliance Audit -- 2026-03-07
- `2026-03-07-adr-test-coverage-audit` - ADR Test Coverage Audit — 2026-03-07
- `2026-03-07-api-adr-tests-audit` - api.py and ADR Regression Tests Audit
- `2026-03-07-api-config-audit` - Round 24 Audit -- api.py, config.py
- `2026-03-07-cli-round14-audit` - Round 14 Audit -- cli.py (full audit)
- `2026-03-07-config-init-round12-audit` - Round 12 Audit -- config.py and __init__.py
- `2026-03-07-embeddings-round10-audit` - Round 10 Audit -- embeddings.py (deep dive)
- `2026-03-07-final-sweep-round27-audit` - Round 27 Audit -- Final Sweep (__init__.py, mcp_server.py second pass, root conftest.py)
- `2026-03-07-indexer-round23-audit` - Round 23 Audit -- indexer.py (deep dive)
- `2026-03-07-indexer-round8-audit` - Round 8 Audit -- indexer.py (deep dive)
- `2026-03-07-indexer-store-api-audit` - Round 22 Audit -- indexer.py, store.py, api.py
- `2026-03-07-integration-tests-round13-audit` - Round 13 Audit -- Integration Tests and Benchmarks
- `2026-03-07-integration-tests-round26-audit` - Round 26 Audit -- Integration Tests Coverage
- `2026-03-07-mcp-round11-audit` - Round 11 Audit -- mcp_server.py (deep dive, post-fix verification)
- `2026-03-07-orchestrator-log-audit` - Orchestrator Log
- `2026-03-07-pending-task-verification-audit` - Pending Task Verification — 2026-03-07
- `2026-03-07-search-cli-mcp-audit` - Round 21 Audit -- search.py, cli.py, mcp_server.py
- `2026-03-07-search-round7-audit` - search.py Deep Audit (Round 7)
- `2026-03-07-store-embeddings-audit` - Round 22b Audit -- store.py, embeddings.py
- `2026-03-07-store-round9-audit` - Round 9 Audit -- store.py (deep dive, post-fix verification)
- `2026-03-07-test-compliance-round2-audit` - Test Compliance Audit Round 2
- `2026-03-07-test-live-audit` - Comprehensive Test Suite Audit
- `2026-03-07-test-mandate-audit` - Test Mandate Compliance Audit — 2026-03-07
- `2026-03-07-tests-round25-audit` - Round 25 Audit -- Full Test Suite
- `2026-03-08-compliance-reaudit-audit` - Test Mandate Compliance Re-audit — 2026-03-08 (Post-Task #19, #41, #42)
- `2026-03-08-continuous-audit` - Continuous Audit Log — 2026-03-08
- `2026-03-08-cross-module-round29-audit` - Round 29: Cross-Module Integration Audit
- `2026-03-08-embeddings-round26-audit` - Round 26 Audit: embeddings.py Deep Dive
- `2026-03-08-fixture-audit` - Audit Report: Integration Test Fixture Scoping & Isolation
- `2026-03-08-indexer-correctness-audit` - Deep Audit: indexer.py Pipeline Correctness
- `2026-03-08-mcp-config-watcher-round28-audit` - Audit: mcp_server.py, config.py, watcher.py — Round 28
- `2026-03-08-search-embeddings-audit` - Audit Round 2: search.py & embeddings.py
- `2026-03-08-search-round27-audit` - Audit: search.py Round 27 — Correctness Deep Dive
- `2026-03-08-store-api-round25-audit` - Round 25 Correctness Audit: store.py & api.py
- `2026-03-08-target-flag-propagation-audit` - Audit: --target Flag Propagation Through CLI Stack
- `2026-03-08-test-mandate-audit` - Test Mandate Compliance Audit — 2026-03-08
- `2026-03-08-watcher-clipath-audit` - Round 24 Audit: Watcher, CLI Fast-Path, MCP Client
- `2026-03-09-coverage-compliance-round33-audit` - Round 33: Integration Test Coverage Gap & Compliance Audit
- `2026-03-09-graph-embedding-round35-audit` - Round 35: api.py Graph Invalidation + search_all() Double Encoding Audit
- `2026-03-09-graph-embedding-round36-audit` - Round 36: Graph/Embedding Domain Audit (2026-03-09)
- `2026-03-09-graph-reranker-round34-audit` - Round 34 Audit: Graph Cache Integrity and CrossEncoder Reranker Safety
- `2026-03-09-mcp-server-documentation-audit` - MCP Server Documentation Audit (2026-03-09)
- `2026-03-09-performance-round33-audit` - Performance Audit — Round 33 (2026-03-09)
- `2026-03-09-round30-new-code-audit` - Round 30: New Code Correctness Audit + ADR Regression Test Coverage
- `2026-03-09-security-errors-round32-audit` - Round 32: Security & Error-Handling Audit
- `2026-03-09-test-infra-round31-audit` - Round 31: Test Infrastructure & Integration Gap Analysis (2026-03-09)

### research

- `2026-03-06-codebase-indexer-tech-stack-research` - Research: CodebaseIndexer Tech Stack — 2026 GPU-First
- `2026-03-06-gpu-rag-architecture-research` - GPU-Only RAG Architecture: Grounding Report
- `2026-03-06-gpu-vector-search-deep-dive-research` - GPU Vector Search Deep Dive
- `2026-03-07-api-verification-research` - API Verification Report — 2026-03-07
- `2026-03-07-continuous-research` - Continuous Research Loop Findings — 2026-03-07
- `2026-03-07-libdoc-verification-research` - Library Documentation Verification Audit
- `2026-03-08-fastmcp-lifespan-research` - FastMCP Lifespan Context Research for Task #25
- `2026-03-08-qdrant-filter-verification-research` - Qdrant Filter API Correctness Audit
- `2026-03-08-qdrant-hybrid-search-patterns-research` - Qdrant Hybrid Search Patterns (Verified)
- `2026-03-09-qwen3-task-prefix-verification-research` - Research Topic 21: Qwen3 Embedding Task Prefixes — Deep Verification
