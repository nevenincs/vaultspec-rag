---
tags:
  - '#adr'
  - '#gpu-rag-stack'
date: 2026-03-06
modified: '2026-06-30'
related:
  - '[[2026-03-06-gpu-rag-architecture-research]]'
  - '[[2026-03-06-gpu-vector-search-deep-dive-research]]'
---

# ADR: GPU-Only RAG Stack — sentence-transformers + Qwen3 + SPLADE v3

## Date

2026-03-06

## Status

Accepted (supersedes 2026-03-06-rag-stack-migration)

## Context

The previous ADR migrated from sentence-transformers/torch/lancedb to fastembed/ONNX/qdrant-client with a CPU-first design. This created a new problem: **all embedding inference runs on CPU via ONNX Runtime**, which is significantly slower than GPU inference for batch indexing and leaves available GPU hardware idle.

The user mandates GPU-only inference. No CPU fallback. No fastembed. No ONNX.

## Decision

Rewrite the embedding pipeline for GPU-only inference. Seven decisions follow.

### 1. Embedding Engine

Replace **fastembed (ONNX Runtime, CPU)** with **sentence-transformers >= 5.0 (PyTorch, CUDA)**. sentence-transformers provides a unified API for both dense (`SentenceTransformer`) and sparse (`SparseEncoder`) models on GPU with fp16/bf16 support and flash_attention_2 compatibility.

### 2. Dense Embedding Model

Replace **nomic-ai/nomic-embed-text-v1.5** (768d) with **Qwen/Qwen3-Embedding-0.6B** (1024d).

| Aspect      | Old (nomic)                             | New (Qwen3)               |
| ----------- | --------------------------------------- | ------------------------- |
| Dimension   | 768                                     | 1024 (MRL: 32-1024)       |
| Parameters  | ~137M                                   | 0.6B                      |
| MTEB Score  | 62.28                                   | 64.33 (multilingual)      |
| VRAM (fp16) | ~0.5 GB                                 | ~1.5 GB                   |
| MRL Support | Yes                                     | Yes                       |
| Prefixing   | Manual (search_document:/search_query:) | Automatic via prompt_name |

Inference config:

```python
SentenceTransformer(
    "Qwen/Qwen3-Embedding-0.6B",
    model_kwargs={
        "torch_dtype": "float16",
        "attn_implementation": "flash_attention_2",
    },
    tokenizer_kwargs={"padding_side": "left"},
)
```

flash_attention_2 is optional -- if unavailable, falls back to standard attention with fp16.

### 3. Sparse Embedding Model

Replace **BM42 via fastembed** with **SPLADE v3 via sentence-transformers SparseEncoder**.

```python
SparseEncoder(
    "naver/splade-v3",
    device="cuda",
    model_kwargs={"torch_dtype": "float16"},
)
```

SPLADE v3 runs on GPU natively. BM42 required fastembed (ONNX/CPU). Total VRAM for both models: ~3 GB in fp16.

### 4. Vector Database

**Qdrant local mode -- UNCHANGED.** Vector DB search is I/O-bound, not compute-bound for single-node use. The embedding pipeline is the GPU bottleneck, not the vector search. All Qdrant collection schemas, hybrid search via `query_points` + `Prefetch` + `FusionQuery(RRF)`, payload filtering, and local mode persistence remain identical.

The only schema change: dense vector dimension increases from 768 to 1024.

### 5. Dependencies

**Remove:** `fastembed>=0.4.0`, `qdrant-client[fastembed]>=1.12.0`.

**Add:** `sentence-transformers>=5.0`, `torch>=2.4`, `transformers>=4.51`, `qdrant-client>=1.17`.

**Keep:** pydantic, rich, vaultspec, mcp, typer, click.

**Optional:** `flash-attn>=2.5` (for flash_attention_2 acceleration).

### 6. Public Interface

**Preserved:** `EmbeddingModel` (with `encode_documents`, `encode_query`, `encode_documents_sparse`, `encode_query_sparse`, `.dimension`, `.device`), `VaultStore`, `VaultSearcher`, `VaultIndexer`, `CodebaseIndexer`, `VaultDocument`, `CodeChunk`, `SearchResult`, `ParsedQuery`, `IndexResult`.

**Changed:**

- `EmbeddingModel.device` returns `"cuda"` instead of `"cpu"`.
- `EmbeddingModel.MODEL_NAME` changes to `"Qwen/Qwen3-Embedding-0.6B"`.
- `EmbeddingModel.SPARSE_MODEL_NAME` changes to `"naver/splade-v3"`.
- `EmbeddingModel.DEFAULT_DIMENSION` changes from 768 to 1024.
- `DOCUMENT_PREFIX` and `QUERY_PREFIX` removed (Qwen3 uses `prompt_name` parameter).
- Sparse encode methods return objects compatible with Qdrant's `.indices.tolist()` / `.values.tolist()` interface.

### 7. Config Changes

| Key                   | Old Default                                 | New Default                   |
| --------------------- | ------------------------------------------- | ----------------------------- |
| `embedding_model`     | `"nomic-ai/nomic-embed-text-v1.5"`          | `"Qwen/Qwen3-Embedding-0.6B"` |
| `embedding_dimension` | `768`                                       | `1024`                        |
| `sparse_model`        | `"Qdrant/bm42-all-minilm-l6-v2-attentions"` | `"naver/splade-v3"`           |
| `qdrant_dir`          | `".qdrant"`                                 | Unchanged                     |
| `lance_dir`           | `".lance"`                                  | Removed (LanceDB is gone)     |

## Consequences

### Positive

- GPU inference is ~10-50x faster than CPU/ONNX for batch indexing.
- Qwen3-Embedding-0.6B scores higher on MTEB than nomic-embed-text-v1.5 (64.33 vs 62.28).
- SPLADE v3 on GPU replaces BM42 on CPU -- better sparse representations with GPU acceleration.
- Unified library (sentence-transformers) for both dense and sparse models.
- Qdrant hybrid search pipeline (Prefetch + RRF fusion) is unchanged -- zero risk to search quality.

### Negative

- Requires CUDA-capable GPU with ~3 GB VRAM. Cannot run on CPU-only machines or macOS without CUDA.
- PyTorch + sentence-transformers reinstates the ~3 GB dependency footprint removed by the fastembed migration.
- Existing `.qdrant/` indices are incompatible (768d vs 1024d). Full re-index required.
- flash_attention_2 has CUDA version sensitivity -- may require manual installation on some systems.
- CI/CD must have GPU runners or mock the embedding layer for tests.

### Migration Path

1. Rewrite `embeddings.py`: remove fastembed, use SentenceTransformer + SparseEncoder on CUDA.
1. Update `store.py`: EMBEDDING_DIM 768 -> 1024.
1. Update `config.py`: new model name/dimension/sparse defaults.
1. Update `pyproject.toml`: swap dependencies.
1. Update test files: fix HAS_RAG checks, device assertions, remove obsolete tests.
1. Delete existing `.qdrant/` data and re-index.
