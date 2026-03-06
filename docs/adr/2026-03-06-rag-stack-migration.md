---
title: "ADR: RAG Stack Migration"
date: 2026-03-06
status: superseded
superseded-by: [[2026-03-06-gpu-only-rag-stack]]
tags: [#adr, #rag]
related: [[2026-03-06-rag-architecture]]
---

# ADR: RAG Stack Migration — fastembed + qdrant-client

## Date

2026-03-06

## Status

Accepted

## Context

The `vaultspec_rag` module depends on sentence-transformers + torch (CUDA 13.0 strict), lancedb with Tantivy FTS, and a Python-level `RRFReranker`. This creates three problems:

1. **Hardware lock-in.** `_require_cuda()` raises `GPUNotAvailableError` if no CUDA device exists. The tool cannot run on macOS, CPU-only Linux, or CI without a GPU.
2. **Dependency weight.** PyTorch + sentence-transformers + CUDA binaries exceed 3 GB. Fresh installs are slow and Docker images are bloated.
3. **Fragile hybrid search.** Tantivy FTS indices must be rebuilt after every write. The Python `RRFReranker` adds latency. Failures silently fall back to vector-only search.

## Decision

Migrate the entire inference and storage stack. Seven decisions follow.

### 1. Embedding Engine

Replace sentence-transformers + torch with **fastembed** (ONNX Runtime, CPU-first). This eliminates the CUDA/torch dependency (~2 GB) and enables Mac/CPU-only environments.

### 2. Embedding Model

Keep **nomic-ai/nomic-embed-text-v1.5** (768d) as the embedding model, now served via fastembed ONNX instead of sentence-transformers. nomic-embed-text-v1.5 is natively supported in fastembed's model registry. Qwen3-Embedding deferred as a future upgrade pending fastembed last-token pooling support (qdrant/fastembed#529).

### 3. Vector Database

Replace lancedb (embedded, Tantivy FTS) with **qdrant-client local mode** (Rust-backed). Storage path: `QdrantClient(path="{root}/.qdrant/")`. Collections use named vectors: `"dense"` (768d, cosine) and `"sparse"` (BM42). The API is identical between local and server mode — zero code changes if we later deploy Qdrant as a container.

### 4. Hybrid Search

Replace LanceDB hybrid search + Python `RRFReranker` with **Qdrant Universal Query API**. Dense and sparse searches run in parallel via `prefetch`. Results are fused at the Rust engine level using `models.FusionQuery(fusion=models.Fusion.RRF)`. BM42 sparse vectors (transformer attention-based) replace Tantivy BM25 for keyword matching. Payload filtering replaces SQL WHERE clauses — no SQL injection surface.

### 5. Dependencies

**Remove:** torch, sentence-transformers, lancedb, einops. Remove the `[[tool.uv.index]]` pytorch-cuda section and `[tool.uv.sources]` torch entry.

**Add:** `qdrant-client[fastembed]>=1.12.0`, `fastembed>=0.4.0`.

**Keep:** pydantic, rich, vaultspec, mcp, typer, click.

### 6. Public Interface

**Preserved:** `EmbeddingModel` (with `encode_documents`, `encode_query`, `.dimension`, `.device`), `VaultStore` (all public methods), `VaultSearcher`, `VaultIndexer`, `CodebaseIndexer`, `VaultDocument`, `CodeChunk`, `SearchResult`, `ParsedQuery`, `IndexResult`.

**Changed:** `EmbeddingModel` gains sparse embedding methods (`encode_documents_sparse`, `encode_query_sparse`). `VaultStore` uses Qdrant internally. `VaultDocument.tags` and `VaultDocument.related` become native `list[str]` (Qdrant stores JSON payloads natively — no serialization needed).

**Removed:** `GPUNotAvailableError`, `get_device_info()`, `CUDA_INDEX_TAG`, `CUDA_INDEX_URL`, `EMBEDDING_DIM` constant, `_sanitize_filter_value()`, `_parse_json_list()`, `_ensure_fts_index()`.

### 7. Config Changes

| Key | Old Default | New Default |
|---|---|---|
| `lance_dir` | `".lance"` | Renamed to `qdrant_dir`, default `".qdrant"` |
| `embedding_model` | `"nomic-ai/nomic-embed-text-v1.5"` | Unchanged |
| `embedding_dimension` | `768` | Unchanged |
| `sparse_model` | N/A | `"Qdrant/bm42-all-minilm-l6-v2-attentions"` (new) |

## Consequences

### Positive

- Runs on any platform with Python 3.13 — no GPU required.
- Install footprint drops from ~3 GB to ~60 MB.
- Native Rust-level RRF fusion eliminates Python reranker bugs and Tantivy rebuild cycles.
- Qdrant local mode API is identical to server mode — future scale-out requires only a constructor change.
- Payload filtering uses typed `Filter` objects — no SQL injection surface.

### Negative

- Existing `.lance/` indices are incompatible. Full re-index required after migration.
- `GPUNotAvailableError`, `get_device_info()`, `CUDA_INDEX_TAG`, `CUDA_INDEX_URL` are removed from the public API. External code depending on these will break.
- BM42 is less mature than BM25 for exact-match keyword queries. Mitigated by hybrid fusion with dense vectors.
- Embedding model unchanged (nomic-embed-text-v1.5) — Qwen3-Embedding deferred until fastembed adds last-token pooling support (qdrant/fastembed#529).
