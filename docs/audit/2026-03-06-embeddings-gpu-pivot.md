# Audit: Embeddings GPU Pivot

Feature: embeddings.py GPU rewrite (sentence-transformers + Qwen3 + SPLADE v3)

## 2026-03-06 -- Initial Review (Passes 15-17)

### embeddings.py Rewrite: VERIFIED CORRECT

- Qwen3-Embedding-0.6B (1024d) via SentenceTransformer with fp16 + flash_attention_2 fallback
- SPLADE v3 via SparseEncoder on CUDA
- `_check_rag_deps()` correctly verifies torch CUDA + sentence_transformers
- `SparseResult` dataclass bridges SPLADE COO output to `.indices`/`.values` interface
- `_sparse_tensor_to_results()` handles scipy sparse, torch sparse/dense, and numpy fallback
- `encode_query()` uses `prompt_name="query"` (no manual prefix)
- `encode_documents()` no longer prepends "search_document:" prefix
- `MAX_EMBED_CHARS = 8000` truncation applied before encoding

### SparseResult Interface Mismatch (Task #43 -- RESOLVED)

`SparseResult.indices` and `.values` are `list[int]`/`list[float]`. Six call sites used `.tolist()` which fails on lists. All fixed to use `list()` wrapper.

### SparseVectorParams -- No Modifier (CORRECT for SPLADE v3)

store.py uses `SparseVectorParams()` with no `Modifier.IDF`. This is correct for SPLADE v3 which produces learned sparse weights already encoding term importance. (BM42 in the previous stack DID need Modifier.IDF -- Task #18.)

### Config Defaults Updated

config.py now has correct GPU defaults:

- `embedding_model: "Qwen/Qwen3-Embedding-0.6B"`
- `embedding_dimension: 1024`
- `sparse_model: "naver/splade-v3"`

### Dependencies Updated

pyproject.toml: `sentence-transformers>=5.0`, `torch>=2.4`, `transformers>=4.51`, plain `qdrant-client>=1.12.0`. fastembed removed.

## Pass 28 — Full encode method review

All encode methods verified correct:

- `encode_documents()`: batch encoding with truncation, normalized, returns numpy float32. No `prompt_name` (correct -- documents don't get instruction prefix in Qwen3).
- `encode_query()`: uses `prompt_name="query"` for Qwen3 instruction-based encoding (correct asymmetry with documents).
- `encode_documents_sparse()`: batch SPLADE encoding with truncation via `_sparse_tensor_to_results()`.
- `encode_query_sparse()`: single query SPLADE encoding, returns `results[0]`.

No new issues found.
