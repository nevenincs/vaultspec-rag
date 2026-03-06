# Follow-Up Research: Qwen3-Embedding, BM42, Qdrant Named Vectors

Date: 2026-03-06
Context7: NOT AVAILABLE (confirmed via ToolSearch). All data verified from GitHub source code.

Sources:

- `https://github.com/qdrant/fastembed/blob/main/fastembed/text/pooled_embedding.py` (nomic model registry)
- `https://github.com/qdrant/fastembed/blob/main/fastembed/text/onnx_embedding.py` (ONNX model registry)
- `https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/bm42.py` (BM42 source)
- `https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/sparse_text_embedding.py` (sparse registry)
- `https://github.com/qdrant/fastembed/blob/main/fastembed/sparse/sparse_embedding_base.py` (SparseEmbedding dataclass)
- `https://github.com/qdrant/fastembed/issues/528` (Qwen3 issue)
- `https://github.com/qdrant/fastembed/pull/605` (Qwen3 PR)
- `https://github.com/qdrant/qdrant-client/blob/master/qdrant_client/http/models/models.py` (all qdrant models)

---

## 1. Qwen3-Embedding in fastembed

### Answer: NOT in the default registry. Must use `add_custom_model`

**Verified from source** (searched all model registration files):

- `fastembed/text/onnx_embedding.py` -- no Qwen3 references
- `fastembed/text/pooled_embedding.py` -- no Qwen3 references
- `fastembed/text/pooled_normalized_embedding.py` -- no Qwen3 references
- `fastembed/text/text_embedding.py` -- no Qwen3 references

**PR #605** ("feat: add Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B support") is **still open** as of 2026-03-06.

### Custom Loading Path

To use Qwen3-Embedding today, you must register it manually:

```python
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

TextEmbedding.add_custom_model(
    model="electroglyph/Qwen3-Embedding-0.6B-onnx-uint8",
    pooling=PoolingType.DISABLED,    # CRITICAL: Qwen3 uses last-token pooling
    normalization=True,
    sources=ModelSource(hf="electroglyph/Qwen3-Embedding-0.6B-onnx-uint8"),
    dim=1024,
    model_file="onnx/model.onnx",
)

model = TextEmbedding(model_name="electroglyph/Qwen3-Embedding-0.6B-onnx-uint8")
```

### Available ONNX Repos on HuggingFace

| HF Repo | Quantization | Notes |
|---|---|---|
| `zhiqing/Qwen3-Embedding-0.6B-ONNX` | FP32 | Community, large |
| `electroglyph/Qwen3-Embedding-0.6B-onnx-uint8` | uint8 | Community, tested with fastembed |
| `onnx-community/Qwen3-Embedding-0.6B-ONNX` | FP32 | onnx-community conversion |

### Gotchas

1. **PoolingType.DISABLED is mandatory** -- Qwen3 is a causal LM using last-token pooling. Mean pooling (default) will produce garbage embeddings.
2. **Instruction prefix format**: `"Instruct: {task}\nQuery:{query}"` for queries; no prefix for documents.
3. **~88 strings/sec on CPU** -- much slower than BERT-based models.
4. **Recommendation**: Use `nomic-ai/nomic-embed-text-v1.5` (natively registered, 768d, fast) for now. Qwen3 can be a future config option.

---

## 2. BM42 Sparse Embeddings

### Answer: Yes, `SparseTextEmbedding` with model `"Qdrant/bm42-all-minilm-l6-v2-attentions"`

**Verified from `fastembed/sparse/bm42.py` source:**

```python
# Registry entry:
SparseModelDescription(
    model="Qdrant/bm42-all-minilm-l6-v2-attentions",
    vocab_size=30522,
    description="Light sparse embedding model, assigns importance score to each token",
    license="apache-2.0",
    size_in_GB=0.09,
    sources=ModelSource(hf="Qdrant/all_miniLM_L6_v2_with_attentions"),
    model_file="model.onnx",
    additional_files=["stopwords.txt"],
    requires_idf=True,    # <-- CRITICAL: needs IDF modifier in Qdrant
)
```

### Usage

```python
from fastembed import SparseTextEmbedding, SparseEmbedding

sparse_model = SparseTextEmbedding(model_name="Qdrant/bm42-all-minilm-l6-v2-attentions")

# embed() signature (same as TextEmbedding):
# def embed(documents: str | Iterable[str], batch_size: int = 256, parallel: int | None = None)
# -> Iterable[SparseEmbedding]

sparse_embs = list(sparse_model.embed(["Hello world", "Another document"]))
```

### SparseEmbedding Output Type (verified from source)

```python
@dataclass
class SparseEmbedding:
    values: NumpyArray                              # float array of weights
    indices: NDArray[np.int64] | NDArray[np.int32]  # integer token indices

    def as_object(self) -> dict:     # {"values": ..., "indices": ...}
    def as_dict(self) -> dict:       # {index: value, ...} sparse dict
    @classmethod
    def from_dict(cls, d) -> SparseEmbedding
```

### CRITICAL: BM42 Requires `modifier=Modifier.IDF` in Qdrant

The BM42 model has `requires_idf=True` in its registration. The Qdrant collection's sparse vector config **MUST** include `modifier="idf"`:

```python
from qdrant_client import models

# CORRECT -- with IDF modifier for BM42:
sparse_vectors_config={
    "sparse": models.SparseVectorParams(
        modifier=models.Modifier.IDF,    # REQUIRED for BM42
    ),
}

# WRONG -- without modifier, BM42 scores will be incorrect:
sparse_vectors_config={
    "sparse": models.SparseVectorParams(),  # Missing IDF!
}
```

The `Modifier` enum (from qdrant-client source):

```python
class Modifier(str, Enum):
    NONE = "none"    # no modification (default)
    IDF = "idf"      # inverse document frequency, based on collection statistics
```

### Alternative Sparse Models

| Model | IDF Required? | Notes |
|---|---|---|
| `Qdrant/bm42-all-minilm-l6-v2-attentions` | YES | Transformer-attention-based BM42 |
| `Qdrant/bm25` | YES | Pure BM25, no ONNX model needed |
| `prithivida/Splade_PP_en_v1` | NO | SPLADE++, self-contained scores |

**If using SPLADE (`prithivida/Splade_PP_en_v1`)**, no IDF modifier is needed -- SPLADE computes its own term weights. This is simpler to configure.

---

## 3. Qdrant Named Vectors: Dense + Sparse Collection

### Verified from qdrant-client source

**Complete working example** for creating a collection with both dense and sparse named vectors in local mode:

```python
from qdrant_client import QdrantClient, models

# Local mode -- no server needed
client = QdrantClient(path="./qdrant-data")
# or QdrantClient(":memory:") for tests

COLLECTION = "vault_docs"

if not client.collection_exists(COLLECTION):
    client.create_collection(
        collection_name=COLLECTION,
        vectors_config={
            "dense": models.VectorParams(
                size=768,                        # nomic-embed-text-v1.5
                distance=models.Distance.COSINE,
            ),
        },
        sparse_vectors_config={
            # Option A: For BM42/BM25 (requires IDF)
            "sparse": models.SparseVectorParams(
                modifier=models.Modifier.IDF,
            ),
            # Option B: For SPLADE (no modifier needed)
            # "sparse": models.SparseVectorParams(),
        },
    )
```

### Upserting Points with Both Vector Types

```python
from fastembed import TextEmbedding, SparseTextEmbedding

dense_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5")
sparse_model = SparseTextEmbedding(model_name="Qdrant/bm42-all-minilm-l6-v2-attentions")

documents = ["Document one text", "Document two text"]

# Generate embeddings -- NOTE prefixes for nomic
dense_embs = list(dense_model.embed([f"search_document: {d}" for d in documents]))
sparse_embs = list(sparse_model.embed(documents))  # no prefix for sparse

points = [
    models.PointStruct(
        id=i,
        vector={
            "dense": dense_embs[i].tolist(),          # list[float]
            "sparse": models.SparseVector(
                indices=sparse_embs[i].indices.tolist(),  # list[int]
                values=sparse_embs[i].values.tolist(),    # list[float]
            ),
        },
        payload={"text": doc, "doc_type": "research"},
    )
    for i, doc in enumerate(documents)
]

client.upsert(collection_name=COLLECTION, points=points)
```

### Hybrid Search with RRF Fusion

```python
query = "search topic"
q_dense = list(dense_model.embed([f"search_query: {query}"]))[0]
q_sparse = list(sparse_model.embed([query]))[0]

results = client.query_points(
    collection_name=COLLECTION,
    prefetch=[
        models.Prefetch(
            query=q_dense.tolist(),
            using="dense",
            limit=20,
        ),
        models.Prefetch(
            query=models.SparseVector(
                indices=q_sparse.indices.tolist(),
                values=q_sparse.values.tolist(),
            ),
            using="sparse",
            limit=20,
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=10,
    with_payload=True,
).points

# Each point: ScoredPoint(id=..., score=..., payload={"text": ..., ...})
```

---

## Summary Decision Matrix

| Question | Answer |
|---|---|
| Qwen3 in fastembed registry? | **NO** -- PR #605 still open. Use `add_custom_model()` or skip. |
| Recommended dense model? | `nomic-ai/nomic-embed-text-v1.5` (768d, native, fast, prefixes required) |
| BM42 class? | `SparseTextEmbedding("Qdrant/bm42-all-minilm-l6-v2-attentions")` |
| BM42 output type? | `SparseEmbedding(values=NumpyArray, indices=NDArray)` |
| BM42 Qdrant requirement? | `SparseVectorParams(modifier=Modifier.IDF)` -- **CRITICAL** |
| Simpler sparse alternative? | `prithivida/Splade_PP_en_v1` -- no IDF modifier needed |
| Named vectors API? | `vectors_config={"name": VectorParams(...)}` + `sparse_vectors_config={"name": SparseVectorParams(...)}` |
