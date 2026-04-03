---
tags:
  - '#research'
  - '#gpu-rag-stack'
date: 2026-03-06
related: []
---

# GPU Vector Search Deep Dive

Date: 2026-03-06
Context7: NOT AVAILABLE. All data from WebSearch + WebFetch + official docs.

Sources:

- <https://qdrant.tech/blog/qdrant-1.13.x/> (GPU indexing announcement)
- <https://qdrant.tech/documentation/guides/running-with-gpu/> (GPU configuration)
- <https://engineering.fb.com/2025/05/08/data-infrastructure/accelerating-gpu-indexes-in-faiss-with-nvidia-cuvs/> (Meta FAISS+cuVS benchmarks)
- <https://developer.nvidia.com/blog/enhancing-gpu-accelerated-vector-search-in-faiss-with-nvidia-cuvs/> (NVIDIA cuVS benchmarks)
- <https://zilliz.com/blog/Milvus-introduces-GPU-index-CAGRA> (Milvus GPU CAGRA)
- <https://zilliz.com/blog/milvus-on-gpu-with-nvidia-rapids-cuvs> (Milvus cuVS integration)
- <https://sbert.net/docs/cross_encoder/pretrained_models.html> (CrossEncoder models)
- <https://sbert.net/docs/cross_encoder/usage/usage.html> (CrossEncoder usage)

______________________________________________________________________

## Primary Question: Are we leaving performance on the table?

**Short answer: No.** For our use case (local Obsidian vault, ~10K-100K documents), GPU-accelerated vector search provides negligible benefit. The bottleneck is embedding inference (GPU), not vector search (CPU). Qdrant local mode with CPU HNSW search is already sub-millisecond at this scale.

GPU vector search becomes relevant at 10M+ vectors. GPU reranking is the one area worth considering -- it adds ~5ms per query for meaningful quality improvement.

______________________________________________________________________

## 1. Qdrant GPU Support (v1.13+)

### What's GPU-Accelerated

**Indexing only.** HNSW graph construction is GPU-accelerated. Search remains CPU-based.

### Performance

Benchmarks for 1M vectors at 1536 dimensions:

| GPU                 | Index Build Time | vs CPU (8 cores, 97.5s) |
| ------------------- | ---------------- | ----------------------- |
| AMD Radeon Pro V520 | 33.1s            | 2.9x faster             |
| NVIDIA T4           | 19.1s            | 5.1x faster             |
| NVIDIA L4           | 12.4s            | 7.9x faster             |

Up to **8.7x faster** index builds claimed across configurations. Up to 10x for equivalent hardware cost.

### Configuration

```yaml
# config.yaml
gpu:
  indexing: true                # enable GPU HNSW indexing
  force_half_precision: false   # f16 for indexing (saves VRAM)
  groups_count: 512             # parallel GPU processing units
  device_filter: ""             # filter GPUs by name
  devices: null                 # specific GPU indices (null = auto)
  parallel_indexes: 1           # concurrent indexing processes
  allow_integrated: false       # use integrated GPUs
```

### Docker Images

```bash
# NVIDIA
docker run --rm --gpus=all -p 6333:6333 -p 6334:6334 \
  -e QDRANT__GPU__INDEXING=1 qdrant/qdrant:gpu-nvidia-latest

# AMD
docker run --rm --device /dev/kfd --device /dev/dri \
  -p 6333:6333 -p 6334:6334 -e QDRANT__GPU__INDEXING=1 \
  qdrant/qdrant:gpu-amd-latest
```

### VRAM Limits

- Up to **16 GB vector data per GPU** per indexing iteration
- With scalar quantization (1536d): ~11M vectors per segment
- Without quantization (1536d, fp32): ~2.7M vectors per segment

### Constraints

- **Docker GPU images: Linux x86_64 only** (no Windows, no macOS, no ARM)
- **Requires Qdrant server mode** (Docker container), NOT local embedded mode
- GPU only accelerates index builds, NOT search queries
- Vulkan API required (works on NVIDIA, AMD, Intel, Apple Silicon natively)

### Relevance to Our Stack

**LOW.** We use `QdrantClient(path=...)` local mode (embedded, no Docker). GPU indexing requires Qdrant server mode in a GPU-enabled Docker container. At our scale (~10K-100K docs), CPU HNSW indexing completes in seconds anyway.

**If we ever move to server mode**, GPU indexing would reduce index rebuild time from ~10s to ~1-2s for 100K vectors -- nice but not a bottleneck.

______________________________________________________________________

## 2. FAISS-GPU with cuVS (CAGRA)

### Performance Benchmarks (H100 GPU vs Xeon Platinum CPU)

**Index Build Times (95% recall@10):**

| Index Type    | Dataset    | GPU (cuVS) | CPU     | Speedup   |
| ------------- | ---------- | ---------- | ------- | --------- |
| CAGRA vs HNSW | 5M x 1536d | 89.7s      | 1106.1s | **12.3x** |
| CAGRA vs HNSW | 100M x 96d | 518.5s     | 3322.1s | **6.4x**  |
| IVF-PQ        | 5M x 1536d | 9.0s       | 42.0s   | **4.7x**  |
| IVF-Flat      | 5M x 1536d | 15.2s      | 24.4s   | 1.6x      |

**Search Latency (95% recall@10, single query):**

| Index Type    | Dataset    | GPU (cuVS) | CPU    | Speedup  |
| ------------- | ---------- | ---------- | ------ | -------- |
| CAGRA vs HNSW | 5M x 1536d | 0.15ms     | 0.71ms | **4.7x** |
| IVF-PQ        | 5M x 1536d | 0.22ms     | 1.78ms | **8.1x** |
| IVF-Flat      | 5M x 1536d | 1.14ms     | 1.98ms | 1.7x     |
| CAGRA vs HNSW | 100M x 96d | 0.23ms     | 0.56ms | 2.4x     |

### Why NOT FAISS-GPU for Our Stack

1. **No persistence** -- must save/load index manually, no WAL, no crash recovery
1. **No payload filtering** -- cannot filter by vault, file path, tags
1. **No sparse vector support** -- no hybrid search
1. **No named vectors** -- cannot store dense + sparse side by side
1. **Library, not database** -- requires building all DB features yourself
1. **H100-class GPU required** for meaningful speedups at scale
1. **Our scale is too small** -- at 100K vectors, CPU HNSW search is \<1ms anyway

### Verdict

FAISS-GPU is for billion-scale similarity search in research/production ML pipelines. It is **not a vector database** and would require massive integration work to replace Qdrant's feature set.

______________________________________________________________________

## 3. Milvus with GPU Index

### GPU CAGRA Support

Milvus 2.4+ integrates NVIDIA cuVS for GPU-native CAGRA indexing:

- **50x faster search throughput** vs CPU graph search (batch queries)
- **~10x faster** even for single-query latency (where GPUs are typically underutilized)
- 12.5x better time-to-cost ratio for index builds
- Supports GPU_CAGRA, GPU_IVF_FLAT, GPU_IVF_PQ index types

### Why NOT Milvus for Our Stack

1. **Requires Docker server** -- `milvus-standalone` or `milvus-distributed`
1. **Heavy operational footprint** -- etcd + MinIO + Milvus containers
1. **Designed for 10M+ vectors** -- overkill for our scale
1. **No local embedded mode** -- unlike Qdrant's `path=...` mode
1. **GPU benefits only at scale** -- batch throughput gains irrelevant for single-user queries

### When Milvus GPU Would Matter

- 50M+ vectors
- High-concurrency serving (100+ QPS)
- Batch indexing pipelines running continuously
- Cloud deployment with dedicated GPU instances

### Verdict

Milvus GPU is impressive for large-scale deployments but is **architecturally mismatched** for our local, single-user, embedded use case. The Docker + etcd + MinIO overhead alone disqualifies it.

______________________________________________________________________

## 4. GPU Cross-Encoder Reranking

### What It Does

Cross-encoders score (query, document) pairs jointly, producing much higher quality relevance scores than bi-encoder similarity. Used as a post-retrieval reranking step on the top-k results from vector search.

### Available Models (sentence-transformers)

| Model                                   | Params | NDCG@10 | Speed (docs/sec) | Use Case                      |
| --------------------------------------- | ------ | ------- | ---------------- | ----------------------------- |
| `cross-encoder/ms-marco-MiniLM-L6-v2`   | ~22M   | 74.30   | 1,800            | **Best balance**              |
| `cross-encoder/ms-marco-MiniLM-L12-v2`  | ~33M   | 74.31   | 960              | Slightly better accuracy      |
| `cross-encoder/ms-marco-MiniLM-L4-v2`   | ~19M   | 73.04   | 2,500            | Fastest accurate              |
| `cross-encoder/ms-marco-TinyBERT-L2-v2` | ~4.4M  | 69.84   | 9,000            | Ultra-fast                    |
| `BAAI/bge-reranker-v2-m3`               | ~568M  | --      | ~200             | Multilingual, highest quality |

### GPU Usage

```python
from sentence_transformers import CrossEncoder

reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L6-v2", device="cuda")

# Rerank top-k results
pairs = [(query, doc.text) for doc in top_k_results]
scores = reranker.predict(pairs, batch_size=32)

# Sort by reranker score
reranked = sorted(zip(top_k_results, scores), key=lambda x: x[1], reverse=True)
```

### Performance Impact

- **Latency**: ~5-10ms for reranking 20 documents on GPU (MiniLM-L6)
- **Quality**: Significant improvement in relevance ordering, especially for ambiguous queries
- **VRAM**: ~0.1-0.5 GB additional (MiniLM models are tiny)
- **Total VRAM with our stack**: ~1.5 GB (Qwen3-0.6B) + ~0.5 GB (SPLADE) + ~0.1 GB (reranker) = ~2.1 GB

### Recommendation

**Worth adding as an optional pipeline stage.** The MiniLM-L6-v2 reranker adds negligible latency (~5ms) and VRAM (~100MB) while meaningfully improving result quality. It fits naturally after Qdrant's RRF fusion step:

```
Query -> [Dense + Sparse Encoding] -> [Qdrant RRF Fusion] -> top-20 -> [CrossEncoder Rerank] -> top-5
```

______________________________________________________________________

## 5. Summary: Are We Leaving Performance on the Table?

| Component                    | GPU Option                   | Benefit at Our Scale        | Recommendation               |
| ---------------------------- | ---------------------------- | --------------------------- | ---------------------------- |
| **Embedding inference**      | sentence-transformers + CUDA | **HIGH** -- 10-50x vs CPU   | Already in our stack         |
| **Vector search**            | Qdrant CPU HNSW              | Sufficient (\<1ms)          | **Keep CPU**                 |
| **Index builds**             | Qdrant GPU (Docker)          | Low (saves seconds)         | Skip -- requires server mode |
| **Index builds**             | FAISS-GPU / cuVS             | Low (wrong tool)            | Skip -- not a database       |
| **Post-retrieval reranking** | CrossEncoder on GPU          | **MEDIUM** -- quality boost | **Consider adding**          |
| **Vector DB alternative**    | Milvus GPU                   | None (overkill)             | Skip -- wrong scale          |

### Final Architecture Recommendation

```
[GPU: Qwen3-0.6B dense] + [GPU: SPLADE v3 sparse]
        |                           |
        v                           v
[Qdrant local mode: named vectors, CPU HNSW search, RRF fusion]
        |
        v (top-20)
[GPU: CrossEncoder reranker (optional)]
        |
        v (top-5)
[Results returned to caller]
```

**The only GPU acceleration gap worth filling is cross-encoder reranking.** Everything else is either already GPU-accelerated (embeddings) or doesn't benefit from GPU at our scale (vector search, index builds).

______________________________________________________________________

## 6. Risks & Caveats

| Item                                         | Detail                                                                |
| -------------------------------------------- | --------------------------------------------------------------------- |
| Qdrant GPU requires Docker (Linux x86_64)    | Cannot use with `QdrantClient(path=...)` local mode                   |
| FAISS-GPU benchmarks use H100                | Consumer GPUs (RTX 3060-4090) will see smaller speedups               |
| CrossEncoder adds latency                    | ~5-10ms per query for 20 docs; acceptable but not free                |
| SPLADE + dense + reranker = 3 models in VRAM | ~2.1 GB total in fp16; fits on any modern GPU                         |
| Reranker model selection                     | MiniLM-L6-v2 is English-only; use BGE-reranker-v2-m3 for multilingual |
