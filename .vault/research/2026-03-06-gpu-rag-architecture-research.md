---
tags:
  - '#research'
  - '#gpu-rag-stack'
date: 2026-03-06
related: []
---

# GPU-Only RAG Architecture: Grounding Report

Date: 2026-03-06
Context7: NOT AVAILABLE. All data from WebSearch + WebFetch + GitHub source verification.

Sources:

- <https://huggingface.co/Qwen/Qwen3-Embedding-0.6B> (model card, sentence-transformers usage)
- <https://huggingface.co/BAAI/bge-m3> (model card, hybrid dense+sparse)
- <https://huggingface.co/nvidia/NV-Embed-v2/discussions/28> (VRAM comparison)
- <https://sbert.net/docs/sparse_encoder/SparseEncoder.html> (SparseEncoder API)
- <https://sbert.net/docs/sparse_encoder/usage/efficiency.html> (GPU optimization)
- <https://sbert.net/docs/sentence_transformer/usage/efficiency.html> (GPU optimization)
- <https://docs.vllm.ai/en/stable/serving/openai_compatible_server/> (vLLM embedding mode)
- <https://developer.nvidia.com/blog/enhancing-gpu-accelerated-vector-search-in-faiss-with-nvidia-cuvs/> (FAISS-GPU)
- <https://www.daft.ai/blog/embedding-millions-of-text-documents-with-qwen3> (GPU pipeline architecture)
- <https://github.com/UKPLab/sentence-transformers/releases/tag/v5.0.0> (SparseEncoder v5)

______________________________________________________________________

## 1. GPU-Native Embedding Inference

### Option A: sentence-transformers (RECOMMENDED)

The most mature GPU embedding inference library. Version 5.0+ adds native `SparseEncoder` for SPLADE models on GPU.

**Pros:**

- Direct `.encode()` with `device="cuda"`, fp16/bf16 support
- Built-in batching, progress bars, multi-GPU encode
- flash_attention_2 support for Qwen3/newer models
- SparseEncoder for SPLADE on GPU (same API)
- Benchmarked: fp16 gives ~1.54x speedup, ONNX-O4 gives ~1.83x on RTX 3090

**API:**

```python
from sentence_transformers import SentenceTransformer

model = SentenceTransformer(
    "Qwen/Qwen3-Embedding-0.6B",
    model_kwargs={
        "torch_dtype": "float16",
        "attn_implementation": "flash_attention_2",
        "device_map": "auto",
    },
    tokenizer_kwargs={"padding_side": "left"},
)

# Dense embeddings
doc_embs = model.encode(documents, batch_size=64, show_progress_bar=True)
query_embs = model.encode(queries, prompt_name="query")
```

### Option B: vLLM (for serving at scale)

vLLM supports `--task embed` mode with OpenAI-compatible `/v1/embeddings` endpoint. Best for high-concurrency serving, NOT for local indexing pipelines.

**Pros:** Continuous batching, PagedAttention, high throughput under concurrent load
**Cons:** Server-based (overkill for local indexing), more ops complexity

```bash
vllm serve Qwen/Qwen3-Embedding-0.6B --task embed --dtype float16
```

### Option C: Raw transformers + torch (fallback)

Direct model loading for maximum control. Required for BGE-M3's multi-output (dense+sparse+ColBERT).

```python
from transformers import AutoTokenizer, AutoModel
import torch

model = AutoModel.from_pretrained("Qwen/Qwen3-Embedding-0.6B",
    torch_dtype=torch.float16, attn_implementation="flash_attention_2"
).cuda()
```

### Recommendation

**Use sentence-transformers for both dense and sparse GPU inference.** It wraps torch, supports flash_attention_2, fp16/bf16, multi-GPU, and has the cleanest API. Only fall back to raw transformers if you need BGE-M3's multi-output mode.

______________________________________________________________________

## 2. Embedding Model Comparison

### VRAM Footprint & Key Metrics

| Model                     | Params | Dim                 | VRAM (fp16) | MTEB Score        | MRL | Hybrid (dense+sparse)      |
| ------------------------- | ------ | ------------------- | ----------- | ----------------- | --- | -------------------------- |
| **Qwen3-Embedding-0.6B**  | 0.6B   | 1024 (MRL: 32-1024) | ~1.5 GB     | 64.33 (multi)     | YES | NO (dense only)            |
| **Qwen3-Embedding-4B**    | 4B     | 1024 (MRL: 32-1024) | ~8 GB       | --                | YES | NO                         |
| **Qwen3-Embedding-8B**    | 8B     | 1024 (MRL: 32-1024) | ~16 GB      | 70.58 (multi, #1) | YES | NO                         |
| **BGE-M3**                | 568M   | 1024                | ~3.4 GB     | ~62               | NO  | YES (dense+sparse+ColBERT) |
| **NV-Embed-v2**           | 7.8B   | 4096                | ~24 GB      | 72.31 (eng)       | NO  | NO                         |
| **nomic-embed-text-v1.5** | ~137M  | 768 (MRL: 64-768)   | ~0.5 GB     | 62.28             | YES | NO                         |

### VRAM Estimates (approx)

Rule of thumb: fp16 VRAM ~= 2 bytes x params + overhead

- 0.6B model: ~1.5 GB VRAM in fp16
- 568M model: ~1.5 GB VRAM in fp16 (BGE-M3: ~3.4 GB reported, likely due to longer context)
- 4B model: ~8 GB VRAM in fp16
- 8B model: ~16 GB VRAM in fp16
- NV-Embed-v2: ~24 GB (reported, needs RTX 4090+)

### Recommendations by GPU Tier

| GPU                           | VRAM     | Recommended Model                             |
| ----------------------------- | -------- | --------------------------------------------- |
| RTX 3060/4060 (8 GB)          | 8 GB     | Qwen3-Embedding-0.6B or nomic-embed-text-v1.5 |
| RTX 3080/4070 Ti (12 GB)      | 12 GB    | Qwen3-Embedding-0.6B or BGE-M3                |
| RTX 3090/4080/4090 (16-24 GB) | 16-24 GB | Qwen3-Embedding-4B or 8B                      |
| A100/H100 (40-80 GB)          | 40-80 GB | Qwen3-Embedding-8B                            |

### Model Recommendation

**Primary: Qwen3-Embedding-0.6B**

- Best balance of quality (64.33 MTEB multi), VRAM (~1.5 GB), and speed
- MRL support (can reduce to 256d or 512d for storage savings)
- sentence-transformers native support: `SentenceTransformer("Qwen/Qwen3-Embedding-0.6B")`
- Uses instruction prefix format (handled automatically via `prompt_name="query"`)

**Alternative: BGE-M3** (if hybrid dense+sparse from a single model is desired)

- Only model that produces dense, sparse, AND ColBERT vectors simultaneously
- Requires `FlagEmbedding` library (not sentence-transformers for sparse output)
- ~3.4 GB VRAM

______________________________________________________________________

## 3. Sparse/Hybrid Search on GPU (Without BM42/fastembed)

### Option A: SPLADE on GPU via sentence-transformers SparseEncoder (RECOMMENDED)

sentence-transformers v5+ has a `SparseEncoder` class that runs SPLADE models on CUDA.

```python
from sentence_transformers import SparseEncoder

sparse_model = SparseEncoder(
    "naver/splade-v3",
    device="cuda",
    model_kwargs={"torch_dtype": "float16"},
)

# Encode documents (returns sparse COO tensor)
sparse_doc_embs = sparse_model.encode(documents, batch_size=32)
# Shape: (n, vocab_size) -- sparse tensor

# Encode queries
sparse_query_emb = sparse_model.encode(["search query"])
```

**Key models:**

- `naver/splade-v3` -- latest SPLADE, GPU-native
- `naver/splade-cocondenser-ensembledistil` -- older but well-tested
- `opensearch-project/opensearch-neural-sparse-encoding-doc-v3-distill`

**GPU optimizations:** fp16, bf16, ONNX backend available.

### Option B: BGE-M3 Dense + Sparse (single model for both)

BGE-M3 produces dense AND sparse vectors from a single forward pass:

```python
from FlagEmbedding import BGEM3FlagModel

model = BGEM3FlagModel("BAAI/bge-m3", use_fp16=True)

output = model.encode(documents, return_dense=True, return_sparse=True)
dense_vecs = output["dense_vecs"]       # np.ndarray (n, 1024)
lexical_weights = output["lexical_weights"]  # list[dict[token_id, weight]]
```

**Pro:** Single model, single GPU forward pass for both dense and sparse
**Con:** Requires FlagEmbedding library; sparse output format is dict-based (needs conversion for Qdrant)

### Option C: Pure Dense + rank-bm25 (CPU post-process)

Use dense-only GPU embeddings + CPU-based BM25 as a lightweight hybrid:

```python
from rank_bm25 import BM25Okapi

# CPU-side BM25 (no GPU needed)
tokenized_corpus = [doc.split() for doc in documents]
bm25 = BM25Okapi(tokenized_corpus)
bm25_scores = bm25.get_scores(query.split())

# Combine with dense scores via RRF
```

**Pro:** Zero GPU overhead for sparse, simple
**Con:** BM25 index not persistent (must rebuild), no Qdrant server-side fusion

### Recommendation

**Use Option A (SPLADE via SparseEncoder) for hybrid search.** It runs on GPU, integrates cleanly with Qdrant's sparse vector support, and sentence-transformers provides a unified API for both dense (SentenceTransformer) and sparse (SparseEncoder) models on CUDA.

If single-model simplicity is preferred and you accept the FlagEmbedding dependency, **Option B (BGE-M3)** is also viable.

______________________________________________________________________

## 4. Vector Database for GPU-Only Stack

### Qdrant (Local Mode) -- STILL RECOMMENDED

Qdrant remains the best choice even with GPU embeddings:

**Why Qdrant still fits:**

- **Embedding happens on GPU, search happens on CPU** -- this is normal. Vector DB search is I/O-bound, not compute-bound for single-node use.
- Named vectors (dense + sparse) with server-side RRF fusion
- Local mode (`QdrantClient(path=...)`) -- no server process
- Payload filtering, scroll, count -- all needed by VaultStore
- Well-tested with our existing codebase

**Why NOT FAISS-GPU:**

- No persistence layer (must handle save/load yourself)
- No payload filtering (must implement externally)
- No sparse vector support
- No hybrid search / RRF fusion
- Library, not a database -- requires significant integration work

**Why NOT cuVS:**

- NVIDIA-only, bleeding-edge, not production-stable for local use
- Integrated into FAISS (same limitations as FAISS)
- Designed for massive-scale cloud deployments, not local embedded use

**Why NOT Milvus/Weaviate:**

- Require running a server process (Docker)
- Overkill for local/embedded use case
- More ops complexity than Qdrant local mode

### Verdict

**Keep Qdrant with local mode.** The vector DB is not the GPU bottleneck -- embedding inference is. GPU acceleration belongs in the embedding pipeline, not the vector search.

______________________________________________________________________

## 5. GPU Indexing Pipeline Architecture

### Efficient Batch Embedding on GPU

```python
from sentence_transformers import SentenceTransformer, SparseEncoder
import torch

# 1. Load models onto GPU
dense_model = SentenceTransformer(
    "Qwen/Qwen3-Embedding-0.6B",
    model_kwargs={
        "torch_dtype": torch.float16,
        "attn_implementation": "flash_attention_2",
    },
)
sparse_model = SparseEncoder(
    "naver/splade-v3",
    device="cuda",
    model_kwargs={"torch_dtype": "float16"},
)

# 2. Batch encode -- sentence-transformers handles batching internally
documents = [...]  # list of document strings

# Dense: prefixed for Qwen3
dense_embeddings = dense_model.encode(
    documents,
    prompt_name="document",   # auto-applies doc prompt if configured
    batch_size=64,            # tune based on VRAM
    show_progress_bar=True,
    normalize_embeddings=True,
)

# Sparse: SPLADE
sparse_embeddings = sparse_model.encode(
    documents,
    batch_size=32,            # SPLADE may need smaller batch
)
```

### Key Optimization Techniques

1. **fp16 / bf16**: Use `torch_dtype="float16"` or `"bfloat16"` -- ~1.5x speedup, halves VRAM
1. **flash_attention_2**: `attn_implementation="flash_attention_2"` -- significant speedup for long sequences (Qwen3 supports this)
1. **Batch size tuning**: Start with 64, increase until VRAM OOM, then back off. Larger batches = higher throughput.
1. **Pinned memory for data loading**: Use `torch.cuda.Stream` for async data transfer
1. **Sort by length**: Group similar-length documents to minimize padding waste (sentence-transformers does this internally)
1. **Multi-GPU**: `model.encode(docs, device=["cuda:0", "cuda:1"])` for multi-GPU parallel encoding

### Pipeline Architecture (from Daft.ai's Qwen3 case study)

```
[Data Loading]  -->  [CPU: Chunking/Tokenization]  -->  [GPU: Embedding]  -->  [Qdrant: Upsert]
     (async)              (multiprocessing)               (batched fp16)        (sequential)
```

- **Overlap I/O with compute**: Load next batch while GPU processes current batch
- **Multi-level batch sizing**: Pipeline batch (512 records) > GPU batch (16-64 sequences)
- **Near-100% GPU utilization** achievable with proper pipelining

______________________________________________________________________

## 6. Recommended GPU-Only Stack

| Component            | Choice                                                     | Rationale                                                    |
| -------------------- | ---------------------------------------------------------- | ------------------------------------------------------------ |
| **Dense embedding**  | `sentence-transformers` + `Qwen/Qwen3-Embedding-0.6B`      | Best quality/VRAM ratio, MRL, flash_attn2, native ST support |
| **Sparse embedding** | `sentence-transformers.SparseEncoder` + `naver/splade-v3`  | GPU-native SPLADE, same library as dense                     |
| **Vector DB**        | `qdrant-client` (local mode)                               | Named vectors, RRF fusion, persistence, filtering, proven    |
| **Inference dtype**  | `float16` with `flash_attention_2`                         | ~1.5x speedup, halves VRAM                                   |
| **Hybrid search**    | Qdrant `query_points` with `Prefetch` + `FusionQuery(RRF)` | Server-side fusion, no manual RRF                            |

### pyproject.toml Dependencies

```toml
[project.optional-dependencies]
rag = [
    "sentence-transformers>=5.0",
    "torch>=2.4",
    "qdrant-client>=1.17",
    "transformers>=4.51",
    "flash-attn>=2.5",  # optional, for flash_attention_2
]
```

### Key Differences from Previous (fastembed/ONNX/CPU) Stack

| Aspect               | Old (CPU/ONNX)                | New (GPU/torch)                            |
| -------------------- | ----------------------------- | ------------------------------------------ |
| Dense embedding lib  | fastembed (ONNX)              | sentence-transformers (torch+CUDA)         |
| Dense model          | nomic-embed-text-v1.5 (768d)  | Qwen3-Embedding-0.6B (1024d, MRL)          |
| Sparse embedding lib | fastembed SparseTextEmbedding | sentence-transformers SparseEncoder        |
| Sparse model         | BM42 or SPLADE (ONNX)         | SPLADE v3 (torch+CUDA)                     |
| Inference device     | CPU                           | CUDA GPU                                   |
| VRAM required        | 0                             | ~3 GB (dense + sparse models in fp16)      |
| Dependencies         | fastembed, onnxruntime        | torch, sentence-transformers, transformers |
| Vector DB            | Qdrant (local)                | Qdrant (local) -- UNCHANGED                |
| Hybrid search        | Qdrant query_points + RRF     | Qdrant query_points + RRF -- UNCHANGED     |

______________________________________________________________________

## 7. Risks & Open Questions

| Risk                                                          | Severity | Mitigation                                                 |
| ------------------------------------------------------------- | -------- | ---------------------------------------------------------- |
| flash-attn installation complexity (CUDA version sensitivity) | Medium   | Make it optional; bf16 still gives good speedup without it |
| torch CUDA version mismatch                                   | Medium   | Pin torch version to match target CUDA                     |
| SPLADE sparse tensor -> Qdrant SparseVector conversion        | Low      | Convert COO tensor to indices/values lists                 |
| Qwen3 0.6B quality vs nomic 768d tradeoff                     | Low      | Qwen3 scores higher on MTEB multilingual (64.33 vs 62.28)  |
| BGE-M3 alternative needs FlagEmbedding dependency             | Low      | Only if single-model hybrid is desired                     |
| SparseEncoder v5 maturity (released 2025)                     | Low      | Well-documented, backed by Hugging Face/UKP Lab            |
