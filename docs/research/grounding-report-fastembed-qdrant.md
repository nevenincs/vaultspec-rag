# Research Grounding Report: FastEmbed + Qdrant + Qwen3-Embedding Migration

**Date:** 2026-03-06
**Author:** orchestrator (research grounding for coder)
**Status:** VERIFIED against official docs and PyPI

---

## 1. FastEmbed API Reference

### Installation

```
pip install fastembed
# or with qdrant integration:
pip install qdrant-client[fastembed]
```

### Dense Embeddings: `TextEmbedding`

```python
from fastembed import TextEmbedding

# Constructor - model_name is the first positional arg
model = TextEmbedding(model_name="BAAI/bge-small-en-v1.5")

# embed() returns a Generator[numpy.ndarray, None, None]
embeddings = list(model.embed(["doc1", "doc2", "doc3"]))
# Each element is numpy.ndarray of shape (dim,)

# query_embed() for query-time (may apply different pooling)
query_emb = list(model.embed(["search query"]))[0]
```

**Default model:** `BAAI/bge-small-en-v1.5` (384 dims, 0.067 GB)

### Sparse Embeddings: `SparseTextEmbedding`

```python
from fastembed import SparseTextEmbedding

sparse_model = SparseTextEmbedding(model_name="Qdrant/bm42-all-minilm-l6-v2-attentions")

# embed() for documents - returns Generator[SparseEmbedding, None, None]
sparse_embeddings = list(sparse_model.embed(["doc1", "doc2"]))
# SparseEmbedding has .indices (np.ndarray) and .values (np.ndarray)

# query_embed() for queries
sparse_query = list(sparse_model.query_embed("search query"))[0]
```

**Supported sparse models:**

- `Qdrant/bm25` (0.010 GB) - simple term frequency
- `Qdrant/bm42-all-minilm-l6-v2-attentions` (0.090 GB) - transformer attention-based, RECOMMENDED

### Custom Model Registration (for Qwen3-Embedding)

```python
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

TextEmbedding.add_custom_model(
    model="onnx-community/Qwen3-Embedding-0.6B-ONNX",
    pooling=PoolingType.MEAN,  # or PoolingType.DISABLED if model handles pooling
    normalization=True,
    sources=ModelSource(hf="onnx-community/Qwen3-Embedding-0.6B-ONNX"),
    dim=1024,  # Qwen3-Embedding-0.6B native dimension
    model_file="onnx/model.onnx",
)

model = TextEmbedding(model_name="onnx-community/Qwen3-Embedding-0.6B-ONNX")
embeddings = list(model.embed(["test document"]))
```

**IMPORTANT:** Qwen3-Embedding is NOT in fastembed's default model list. Must use `add_custom_model()`.

---

## 2. Qwen3-Embedding-0.6B Specifications

- **Full dimension:** 1024
- **MRL (Matryoshka) support:** Can truncate to 512 or 768 with minimal quality loss
- **Max tokens:** 32,768
- **ONNX variants available on HuggingFace:**
  - `onnx-community/Qwen3-Embedding-0.6B-ONNX` (fp32, fp16, q8)
  - `electroglyph/Qwen3-Embedding-0.6B-onnx-uint8` (uint8 quantized)
- **Instruction format for queries:**

  ```
  Instruct: <task_description>
  Query: <query_text>
  ```

  Documents do NOT need instruction prefix.
- **Pooling:** Last token pooling (must verify fastembed support - may need PoolingType.DISABLED and manual handling, OR use MEAN pooling if the ONNX export supports it)

### DECISION: Use 1024 dimensions (native) for maximum quality. Config should allow override via MRL

---

## 3. Qdrant Client API Reference (Local Mode)

### Initialization

```python
from qdrant_client import QdrantClient, models

# In-memory (tests, ephemeral)
client = QdrantClient(":memory:")

# Persistent local (production, no server needed)
client = QdrantClient(path="/path/to/qdrant_db")
```

**API is 100% identical between local mode and server mode.**

### Collection Creation (Dense + Sparse Named Vectors)

```python
client.create_collection(
    collection_name="vault_docs",
    vectors_config={
        "dense": models.VectorParams(
            size=1024,  # Qwen3-Embedding dim
            distance=models.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        "sparse": models.SparseVectorParams(),
    },
)
```

### Upserting Points

```python
client.upsert(
    collection_name="vault_docs",
    points=[
        models.PointStruct(
            id="doc-stem-id",  # string IDs supported
            vector={
                "dense": [0.1, 0.2, ...],  # list[float] of size 1024
                "sparse": models.SparseVector(
                    indices=[1, 42, 100],
                    values=[0.22, 0.8, 0.15],
                ),
            },
            payload={
                "path": "plan/2026-02-12-rag-plan.md",
                "doc_type": "plan",
                "feature": "rag",
                "date": "2026-02-12",
                "tags": ["#plan", "#rag"],
                "related": ["[[other-doc]]"],
                "title": "RAG Plan",
                "content": "full markdown body...",
            },
        ),
    ],
)
```

**Key:** Qdrant stores payload as native JSON - no need for JSON-serialized strings. Tags and related can be actual lists.

### Hybrid Search with RRF Fusion (Universal Query API)

```python
results = client.query_points(
    collection_name="vault_docs",
    prefetch=[
        models.Prefetch(
            query=dense_vector,  # list[float]
            using="dense",
            limit=20,
        ),
        models.Prefetch(
            query=models.SparseVector(
                indices=sparse_query.indices.tolist(),
                values=sparse_query.values.tolist(),
            ),
            using="sparse",
            limit=20,
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=10,
)

# results.points is list[ScoredPoint]
# Each point has: .id, .score, .payload, .vector (optional)
```

### Filtering with Payloads

```python
results = client.query_points(
    collection_name="vault_docs",
    prefetch=[...],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="doc_type",
                match=models.MatchValue(value="adr"),
            ),
            models.FieldCondition(
                key="date",
                match=models.MatchText(text="2026-02"),
            ),
        ]
    ),
    limit=10,
)
```

**Key:** Payload filtering replaces SQL WHERE clauses. No SQL injection risk. Native typed filters.

### Delete by ID

```python
client.delete(
    collection_name="vault_docs",
    points_selector=models.PointIdsList(points=["doc-id-1", "doc-id-2"]),
)
```

### Count / Scroll

```python
count = client.count(collection_name="vault_docs").count

# Get all IDs
all_points, _ = client.scroll(
    collection_name="vault_docs",
    limit=10000,
    with_payload=False,
    with_vectors=False,
)
all_ids = {str(p.id) for p in all_points}
```

### Collection Exists Check

```python
if client.collection_exists("vault_docs"):
    ...
```

---

## 4. Migration Mapping (Old -> New)

| Current (LanceDB) | New (Qdrant) |
|---|---|
| `lancedb.connect(path)` | `QdrantClient(path=str)` |
| `db.create_table(name, schema)` | `client.create_collection(name, vectors_config, sparse_vectors_config)` |
| `table.add(records)` | `client.upsert(collection_name, points)` |
| `table.delete(filter)` | `client.delete(collection_name, points_selector)` |
| `table.count_rows()` | `client.count(collection_name).count` |
| `table.search(query_type="hybrid")` | `client.query_points(prefetch=[dense, sparse], query=FusionQuery(RRF))` |
| `RRFReranker()` (Python) | `models.Fusion.RRF` (Rust engine) |
| `table.create_fts_index("content")` | Not needed - BM42 sparse vectors replace Tantivy FTS |
| SQL WHERE `doc_type = 'adr'` | `models.Filter(must=[FieldCondition(...)])` |
| `_sanitize_filter_value()` | Not needed - Qdrant uses typed filters, no SQL |
| `tags` as JSON string | `tags` as native list in payload |
| `related` as JSON string | `related` as native list in payload |
| `pyarrow` schema | Not needed - Qdrant infers from data |

| Current (sentence-transformers) | New (fastembed) |
|---|---|
| `SentenceTransformer(model, device="cuda")` | `TextEmbedding(model_name=...)` (CPU, ONNX) |
| `model.encode(texts, normalize_embeddings=True)` | `list(model.embed(texts))` |
| `torch.cuda.is_available()` check | Not needed - CPU-only |
| `nomic-embed-text-v1.5` (768d) | `Qwen3-Embedding-0.6B` (1024d, MRL to 768/512) |
| N/A | `SparseTextEmbedding("Qdrant/bm42-all-minilm-l6-v2-attentions")` |

---

## 5. Dependencies to Add/Remove in pyproject.toml

### REMOVE

- `torch>=2.9.0`
- `sentence-transformers>=5.0.0`
- `lancedb>=0.27.0`
- `einops>=0.8.0` (only needed for sentence-transformers)
- `[[tool.uv.index]]` pytorch-cuda section
- `[tool.uv.sources]` torch section

### ADD

- `qdrant-client[fastembed]>=1.12.0`
- `fastembed>=0.4.0`

### KEEP

- `pydantic>=2.12.5`
- `rich>=14.3.2`
- `vaultspec @ file:///vaultspec-worktrees/main`
- `mcp>=1.26.0`
- `typer>=0.12.0`
- `click>=8.1.7`

---

## 6. Public Interface Preservation Notes

### Must preserve (used by cli.py, mcp_server.py, external callers)

- `EmbeddingModel` class with `encode_documents(texts)` and `encode_query(query)` methods
- `EmbeddingModel.dimension` property
- `EmbeddingModel.device` property (change from "cuda" to "cpu")
- `VaultStore` class with all public methods: `upsert_documents`, `delete_documents`, `get_all_ids`, `count`, `hybrid_search`, etc.
- `VaultDocument` and `CodeChunk` dataclasses (may simplify - tags/related become native lists)
- `VaultSearcher` class and `SearchResult` dataclass
- `VaultIndexer` and `CodebaseIndexer` classes
- `IndexResult` dataclass

### Can change

- Internal implementation details
- `_check_rag_deps()` - change to check for fastembed/qdrant
- `GPUNotAvailableError` - remove entirely (no GPU needed)
- `CUDA_INDEX_TAG`, `CUDA_INDEX_URL` - remove
- `_sanitize_filter_value`, `_parse_json_list` - remove (Qdrant uses typed payloads)
- `_ensure_fts_index` - remove (BM42 replaces Tantivy)
- `__init__.py` exports - update to match new public surface

### EmbeddingModel must also provide sparse embeddings now

- Add `encode_documents_sparse(texts) -> list[SparseEmbedding]` or similar
- Add `encode_query_sparse(query) -> SparseEmbedding`
- Or: expose sparse model as separate attribute

---

## 7. CRITICAL FINDING: Qwen3-Embedding Pooling Incompatibility

**Issue:** Qwen3-Embedding-0.6B uses **last token pooling** (extract EOS token hidden state). FastEmbed does NOT natively support last_token pooling (see github.com/qdrant/fastembed/issues/529). Qwen3 also uses left-padding, requiring custom pooling logic.

**Decision:** Use `nomic-ai/nomic-embed-text-v1.5` (768d) as the default embedding model. This model IS in fastembed's default supported model list and works out-of-the-box with no custom registration needed. Qwen3-Embedding becomes a future upgrade path once fastembed adds native last-token pooling.

**Rationale:**

- nomic-embed-text-v1.5 is already our current model -- zero quality regression risk
- fastembed has native support -- no add_custom_model() complexity
- 768 dimensions -- same as current, no schema/dimension changes needed
- Keeps migration focused on infrastructure (lancedb->qdrant, torch->fastembed)

**Updated embedding config defaults:**

- `embedding_model` -> "nomic-ai/nomic-embed-text-v1.5" (unchanged from current)
- `embedding_dimension` -> 768 (unchanged from current)
- `sparse_model` -> "Qdrant/bm42-all-minilm-l6-v2-attentions" (new)

---

## 8. Risk Assessment

1. **nomic-embed-text-v1.5 via fastembed:** Natively supported, zero custom code needed. LOW risk.
2. **Local mode limitations:** Qdrant local mode doesn't support multi-process access. Same as LanceDB. No regression.
3. **BM42 vs Tantivy BM25:** BM42 uses transformer attention weights instead of term frequency. Should be better for short chunks. Low risk.
4. **No dimension change (768 -> 768):** Same model, same dimensions. No schema change needed.
5. **Qwen3 future upgrade:** Deferred until fastembed adds last_token pooling support. No current risk.
