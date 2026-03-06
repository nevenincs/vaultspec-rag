# Grounding Report: fastembed + Qwen3-Embedding + qdrant-client

Date: 2026-03-06 (verified pass: 2026-03-06)

## Research Methodology

- **context7 (mcp__context7)**: NOT AVAILABLE in this environment. Searched with 3 ToolSearch queries; no context7 MCP tools found.
- **Primary verification**: GitHub raw source code (exact class/method signatures extracted)
- **Secondary**: WebSearch + WebFetch against official docs, PyPI, HuggingFace

## Pinned Versions (for pyproject.toml)

| Package | Latest Version | Python Requires | Install |
|---|---|---|---|
| fastembed | 0.7.4 (2025-12-05) | >=3.9 | `pip install fastembed` |
| qdrant-client | 1.17.0 (2026-02-19) | >=3.10 | `pip install qdrant-client` |
| qdrant-client[fastembed] | -- | -- | Bundles fastembed as optional extra |

Sources (all verified against source code or official docs):

- <https://github.com/qdrant/fastembed> (source: TextEmbedding, SparseTextEmbedding)
- <https://github.com/qdrant/qdrant-client> (source: models, client methods)
- <https://python-client.qdrant.tech/qdrant_client.qdrant_client> (official readthedocs)
- <https://qdrant.tech/documentation/concepts/hybrid-queries/> (official hybrid search docs)
- <https://qdrant.tech/articles/hybrid-search/> (Query API article)
- <https://qdrant.github.io/fastembed/examples/Supported_Models/> (model registry)
- <https://huggingface.co/nomic-ai/nomic-embed-text-v1.5> (model card)
- <https://huggingface.co/zhiqing/Qwen3-Embedding-0.6B-ONNX> (model card)
- <https://github.com/qdrant/fastembed/issues/528> (Qwen3 support status)
- <https://pypi.org/project/fastembed/> (version info)
- <https://pypi.org/project/qdrant-client/> (version info)

---

## 1. fastembed

### Key Classes & Constructors (VERIFIED from GitHub source)

```python
from fastembed import TextEmbedding, SparseTextEmbedding, SparseEmbedding

# Dense embeddings -- EXACT constructor signature from source:
# TextEmbedding(
#     model_name: str = "BAAI/bge-small-en-v1.5",
#     cache_dir: str | None = None,
#     threads: int | None = None,
#     providers: Sequence[OnnxProvider] | None = None,
#     cuda: bool | Device = Device.AUTO,
#     device_ids: list[int] | None = None,
#     lazy_load: bool = False,
#     **kwargs: Any,
# )
dense_model = TextEmbedding(
    model_name="nomic-ai/nomic-embed-text-v1.5",
    cache_dir=None,      # model cache directory
    threads=None,        # ONNX runtime threads
    providers=None,      # ONNX providers (e.g., ["CUDAExecutionProvider"])
    cuda=False,          # or Device.AUTO for auto-detection
    lazy_load=False,     # load model immediately
)

# Sparse embeddings -- SAME constructor signature as TextEmbedding
sparse_model = SparseTextEmbedding(
    model_name="prithivida/Splade_PP_en_v1",
)
```

**NOTE**: Default model is `BAAI/bge-small-en-v1.5`, NOT nomic. Always pass `model_name` explicitly.

### embed() Method (VERIFIED from GitHub source)

```python
# EXACT signature from source:
# def embed(
#     self,
#     documents: str | Iterable[str],
#     batch_size: int = 256,        # NOTE: default is 256, not 32!
#     parallel: int | None = None,  # number of parallel workers
#     **kwargs: Any,
# ) -> Iterable[NumpyArray]        # for TextEmbedding
# ) -> Iterable[SparseEmbedding]   # for SparseTextEmbedding

# Dense: returns Iterable[NumpyArray] -- MUST wrap in list()
embeddings = list(dense_model.embed(
    documents=["text1", "text2"],
    batch_size=256,      # default is 256 (NOT 32)
    parallel=None,       # data parallelism (int or None)
))
# Each element is np.ndarray of shape (dim,)

# Sparse: returns Iterable[SparseEmbedding]
sparse_embeddings = list(sparse_model.embed(
    documents=["text1", "text2"],
    batch_size=256,
))
# SparseEmbedding dataclass (VERIFIED from source):
# @dataclass
# class SparseEmbedding:
#     values: NumpyArray                              # float array
#     indices: NDArray[np.int64] | NDArray[np.int32]  # integer indices
#     # Methods: as_object(), as_dict(), from_dict()
```

### Adding Custom Models (for Qwen3-Embedding)

```python
from fastembed import TextEmbedding
from fastembed.common.model_description import PoolingType, ModelSource

# EXACT add_custom_model signature from source:
# @classmethod
# def add_custom_model(
#     cls,
#     model: str,
#     pooling: PoolingType,
#     normalization: bool,
#     sources: ModelSource,
#     dim: int,
#     model_file: str = "onnx/model.onnx",
#     description: str = "",
#     license: str = "",
#     size_in_gb: float = 0.0,
#     additional_files: list[str] | None = None,
# ) -> None

TextEmbedding.add_custom_model(
    model="electroglyph/Qwen3-Embedding-0.6B-onnx-uint8",
    pooling=PoolingType.DISABLED,    # Qwen3 uses last-token pooling, not mean
    normalization=True,
    sources=ModelSource(hf="electroglyph/Qwen3-Embedding-0.6B-onnx-uint8"),
    dim=1024,
    model_file="onnx/model.onnx",   # path within the HF repo
)

model = TextEmbedding(model_name="electroglyph/Qwen3-Embedding-0.6B-onnx-uint8")
embeddings = list(model.embed(["hello world"]))
```

### Supported Dense Models (key ones)

| Model | Dim |
|---|---|
| BAAI/bge-small-en-v1.5 | 384 |
| BAAI/bge-base-en-v1.5 | 768 |
| BAAI/bge-large-en-v1.5 | 1024 |
| sentence-transformers/all-MiniLM-L6-v2 | 384 |
| nomic-ai/nomic-embed-text-v1.5 | 768 |
| snowflake/snowflake-arctic-embed-l | 1024 |
| mixedbread-ai/mxbai-embed-large-v1 | 1024 |
| intfloat/multilingual-e5-large | 1024 |

### Supported Sparse Models

| Model | Type |
|---|---|
| Qdrant/bm25 | BM25-based, no fixed dim |
| Qdrant/bm42-all-minilm-l6-v2-attentions | BM42, vocab 30522 |
| prithivida/Splade_PP_en_v1 | SPLADE++, vocab 30522 |

### nomic-embed-text-v1.5 (Recommended Dense Model)

Natively supported in fastembed as `nomic-ai/nomic-embed-text-v1.5` (768 dim).

**Key properties:**

- **Full dimension**: 768
- **Matryoshka (MRL)**: supports 768, 512, 256, 128, 64 -- truncate the vector to desired dim
- **REQUIRES task prefixes** on all inputs:
  - `search_query: <query text>` -- for queries
  - `search_document: <document text>` -- for documents being indexed
  - `clustering: <text>` -- for clustering tasks
  - `classification: <text>` -- for classification
- **MTEB**: 62.28 (768d), 61.96 (512d), 61.04 (256d)
- ONNX available, BERT-based architecture (fast on CPU)

```python
from fastembed import TextEmbedding

model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5")

# Indexing documents -- MUST prefix with "search_document: "
doc_embeddings = list(model.embed([
    "search_document: The capital of France is Paris.",
    "search_document: Python is a programming language.",
]))

# Querying -- MUST prefix with "search_query: "
query_embeddings = list(model.embed([
    "search_query: What is the capital of France?",
]))
```

**CRITICAL**: If you forget the prefix, embeddings will be in the wrong space and similarity scores will be degraded. The prefix is NOT optional.

### Gotchas & Deprecations

1. **BM42 performance**: Qdrant's own benchmarks show BM42 underperforms SPLADE on many tasks. Consider `Qdrant/bm25` or `prithivida/Splade_PP_en_v1` as sparse alternatives.
2. **embed() returns a generator**: Always wrap in `list()` or iterate -- cannot index directly.
3. **Model download on first use**: Models are downloaded from HuggingFace on first call. Set `cache_dir` for reproducible environments.
4. **No GPU by default**: Must explicitly pass `providers=["CUDAExecutionProvider"]` for GPU inference. CPU is the default.

---

## 2. Qwen3-Embedding (ONNX)

### Model Variants

| HF Repo | Size | Quantization | Notes |
|---|---|---|---|
| Qwen/Qwen3-Embedding-0.6B | 0.6B | None (PyTorch) | Official, needs transformers |
| zhiqing/Qwen3-Embedding-0.6B-ONNX | 0.6B | FP32 ONNX | Community conversion |
| electroglyph/Qwen3-Embedding-0.6B-onnx-uint8 | 0.6B | uint8 ONNX | Quantized, works with fastembed |
| zhiqing/Qwen3-Embedding-4B-ONNX | 4B | FP32 ONNX | Large, slow on CPU |
| onnx-community/Qwen3-Embedding-0.6B-ONNX | 0.6B | FP32 ONNX | onnx-community conversion |

### Key Properties

- **Embedding dimension**: Up to 1024 (supports MRL/Matryoshka from 32 to 1024)
- **Context length**: 32K tokens
- **Multilingual**: 100+ languages
- **Architecture**: Causal LM (Qwen3-0.6B-Base), uses **last-token pooling** (NOT mean pooling)
- **Tokenizer**: Requires `transformers >= 4.51.0`, `padding_side='left'`

### Instruction Prefix Format

```python
# For QUERIES (retrieval): use instruction prefix
def format_query(task: str, query: str) -> str:
    return f"Instruct: {task}\nQuery:{query}"

# For DOCUMENTS: NO instruction prefix needed
# Just pass raw document text

# Example task descriptions:
# "Given a web search query, retrieve relevant passages that answer the query"
# "Retrieve semantically similar text"
```

### fastembed Integration Status

- **NOT natively supported yet** in fastembed's model registry
- **PR #605** is open: "feat: add Qwen3-Embedding-0.6B and Qwen3-Reranker-0.6B support"
- **Workaround**: Use `TextEmbedding.add_custom_model()` with community ONNX conversions
- **Unofficial fork**: `fastembed-qwen3` (v0.7.3.post3) exists but is NOT official Qdrant

### CRITICAL GOTCHA: Pooling

Qwen3-Embedding uses **last-token pooling**, not mean pooling. When registering as a custom fastembed model, you MUST set `pooling=PoolingType.DISABLED` and handle pooling yourself, OR wait for native support in PR #605 which handles this correctly.

### Performance on CPU

~88 strings/second on CPU (0.6B model). This is significantly slower than BERT-based models (e.g., all-MiniLM-L6-v2) due to the causal LM architecture. Consider whether CPU-only deployment is acceptable.

### Recommendation

**For the migration, use `BAAI/bge-large-en-v1.5` (dim=1024) as the primary dense model.** It is:

- Natively supported in fastembed (no custom model hacks)
- Fast on CPU (BERT architecture)
- 1024-dim (same as Qwen3-Embedding, so switching later is dimension-compatible)
- Well-tested with Qdrant

Optionally support Qwen3-Embedding as a configurable alternative once PR #605 lands.

---

## 3. qdrant-client (VERIFIED from GitHub source + readthedocs)

### Source-Verified Model Definitions

```python
# From qdrant_client/http/models/models.py (GitHub source):

class PointStruct(BaseModel, extra="forbid"):
    id: ExtendedPointId          # int | str (UUID)
    vector: VectorStruct         # dict[str, list[float] | SparseVector] for named vectors
    payload: Optional[Payload]   # dict[str, Any] | None

class SparseVector(BaseModel, extra="forbid"):
    indices: List[int]           # MUST be unique
    values: List[float]          # same length as indices

class VectorParams(BaseModel, extra="forbid"):
    size: int                    # vector dimensionality
    distance: Distance           # COSINE | EUCLID | DOT
    # optional: hnsw_config, quantization_config, on_disk, datatype, multivector_config

class SparseVectorParams(BaseModel, extra="forbid"):
    index: Optional[SparseIndexParams] = None
    modifier: Optional[Modifier] = None

class Distance(str, Enum):
    COSINE = "Cosine"
    EUCLID = "Euclid"
    DOT = "Dot"

class Prefetch(BaseModel, extra="forbid"):
    prefetch: Optional[Union[List[Prefetch], Prefetch]] = None  # nested!
    query: Optional[QueryInterface] = None
    using: Optional[str] = None          # named vector to search
    filter: Optional[Filter] = None
    params: Optional[SearchParams] = None
    score_threshold: Optional[float] = None
    limit: Optional[int] = None          # default 10
    lookup_from: Optional[LookupLocation] = None

class FusionQuery(BaseModel, extra="forbid"):
    fusion: Fusion               # Fusion.RRF or Fusion.DBSF

class Fusion(str, Enum):
    RRF = "rrf"
    DBSF = "dbsf"

class RrfQuery(BaseModel, extra="forbid"):
    rrf: Rrf

class Rrf(BaseModel, extra="forbid"):
    k: Optional[int] = None              # default ~2 in server
    weights: Optional[List[float]] = None  # per-prefetch weights

class Filter(BaseModel, extra="forbid"):
    should: Optional[Union[List[Condition], Condition]] = None
    min_should: Optional[MinShould] = None
    must: Optional[Union[List[Condition], Condition]] = None
    must_not: Optional[Union[List[Condition], Condition]] = None

class FieldCondition(BaseModel, extra="forbid"):
    key: str                     # payload field name
    match: Optional[MatchValue | MatchText | ...] = None
    range: Optional[Range] = None
    # ... other filter types

class MatchValue(BaseModel, extra="forbid"):
    value: ValueVariants         # str | int | bool

class MatchText(BaseModel, extra="forbid"):
    text: str                    # full-text match

class FilterSelector(BaseModel, extra="forbid"):
    filter: Filter

class QueryResponse(BaseModel):
    points: List[ScoredPoint]

class ScoredPoint(BaseModel):
    id: ExtendedPointId
    version: int
    score: float                 # distance/relevance score
    payload: Optional[Payload] = None
    vector: Optional[VectorStructOutput] = None
```

### Local Mode Setup

```python
from qdrant_client import QdrantClient, models

# VERIFIED QdrantClient.__init__ key params:
# location: str | None = None,   # ":memory:" for in-memory
# path: str | None = None,       # filesystem path for persistent storage
# force_disable_check_same_thread: bool = False,  # for SQLite threading

# In-memory (testing/CI)
client = QdrantClient(":memory:")

# Persistent local storage (production-like, no server needed)
client = QdrantClient(path="/path/to/qdrant-data")
```

Local mode uses SQLite for persistence. No separate Qdrant server process needed.

### Collection Creation (Dense + Sparse Named Vectors)

```python
client.create_collection(
    collection_name="documents",
    vectors_config={
        "dense": models.VectorParams(
            size=768,                     # nomic-embed-text-v1.5 dim (or lower for MRL)
            distance=models.Distance.COSINE,
        ),
    },
    sparse_vectors_config={
        "sparse": models.SparseVectorParams(
            index=models.SparseIndexParams(
                on_disk=False,            # keep in memory for speed
            ),
        ),
    },
)
```

### Upserting Points

```python
from qdrant_client.models import PointStruct, SparseVector

points = [
    PointStruct(
        id=idx,                           # int or UUID string
        vector={
            "dense": dense_embedding.tolist(),   # list[float]
            "sparse": SparseVector(
                indices=sparse_emb.indices.tolist(),
                values=sparse_emb.values.tolist(),
            ),
        },
        payload={
            "text": "document text",
            "file_path": "/path/to/file",
            "chunk_id": 0,
            # any JSON-serializable metadata
        },
    )
    for idx, (dense_embedding, sparse_emb) in enumerate(
        zip(dense_embeddings, sparse_embeddings)
    )
]

# VERIFIED upsert signature from source:
# def upsert(
#     self,
#     collection_name: str,
#     points: types.Points,     # list[PointStruct] or Batch
#     wait: bool = True,
#     ordering: types.WriteOrdering | None = None,
#     shard_key_selector: types.ShardKeySelector | None = None,
#     update_filter: types.Filter | None = None,
#     update_mode: types.UpdateMode | None = None,
#     timeout: int | None = None,
# ) -> types.UpdateResult
client.upsert(
    collection_name="documents",
    points=points,
)
```

### Hybrid Search with Universal Query API (query_points)

#### Option A: FusionQuery (simple)

```python
results = client.query_points(
    collection_name="documents",
    prefetch=[
        models.Prefetch(
            query=query_dense_vector.tolist(),    # list[float]
            using="dense",
            limit=20,
        ),
        models.Prefetch(
            query=models.SparseVector(
                indices=query_sparse.indices.tolist(),
                values=query_sparse.values.tolist(),
            ),
            using="sparse",
            limit=20,
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=10,
    with_payload=True,
)

# results.points is list of ScoredPoint
for point in results.points:
    print(point.id, point.score, point.payload)
```

#### Option B: RrfQuery (with weights and k parameter)

```python
results = client.query_points(
    collection_name="documents",
    prefetch=[
        models.Prefetch(
            query=query_dense_vector.tolist(),
            using="dense",
            limit=20,
        ),
        models.Prefetch(
            query=models.SparseVector(
                indices=query_sparse.indices.tolist(),
                values=query_sparse.values.tolist(),
            ),
            using="sparse",
            limit=20,
        ),
    ],
    query=models.RrfQuery(
        rrf=models.Rrf(
            k=60,                    # RRF constant (default ~60)
            weights=[1.0, 0.5],      # weight dense higher than sparse
        ),
    ),
    limit=10,
    with_payload=True,
)
```

### Payload Filtering

```python
results = client.query_points(
    collection_name="documents",
    prefetch=[...],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    query_filter=models.Filter(
        must=[
            models.FieldCondition(
                key="file_path",
                match=models.MatchValue(value="/vault/notes/topic.md"),
            ),
        ],
    ),
    limit=10,
)
```

### Key Model Imports

```python
from qdrant_client import QdrantClient, models
from qdrant_client.models import (
    Distance,
    VectorParams,
    SparseVectorParams,
    SparseIndexParams,
    PointStruct,
    SparseVector,
    Filter,
    FieldCondition,
    MatchValue,
    # Query types
    FusionQuery,    # or access via models.FusionQuery
    Fusion,         # RRF, DBSF
    RrfQuery,       # weighted RRF
    Rrf,
    Prefetch,
)
```

### Gotchas & Deprecations

1. **FusionQuery vs RrfQuery**: `FusionQuery(fusion=Fusion.RRF)` is the simple form. `RrfQuery(rrf=Rrf(k=60, weights=[...]))` gives fine-grained control. Both work in `query_points()`.
2. **Local mode limitations**: No gRPC, no distributed mode. Fine for single-node / embedded use.
3. **Prefetch limit**: The `limit` in each `Prefetch` must be >= the outer `limit`. Set prefetch limits higher (e.g., 2x-4x) for better fusion results.
4. **SparseVector conversion**: fastembed returns numpy arrays for indices/values; qdrant-client needs Python lists. Always call `.tolist()`.
5. **collection_exists()**: Use `client.collection_exists("name")` to check before creating (avoids error on re-creation).
6. **query_points returns QueryResponse**: Access results via `.points` attribute, not directly.

---

## 4. End-to-End Hybrid Search Pattern

```python
from fastembed import TextEmbedding, SparseTextEmbedding
from qdrant_client import QdrantClient, models

# 1. Initialize models
dense_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5")
sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

# 2. Initialize qdrant
client = QdrantClient(path="./qdrant-data")

if not client.collection_exists("documents"):
    client.create_collection(
        collection_name="documents",
        vectors_config={
            "dense": models.VectorParams(size=768, distance=models.Distance.COSINE),
        },
        sparse_vectors_config={
            "sparse": models.SparseVectorParams(),
        },
    )

# 3. Index documents -- NOTE: prefix with "search_document: "
documents = ["doc1 text", "doc2 text", "doc3 text"]
prefixed_docs = [f"search_document: {d}" for d in documents]
dense_embs = list(dense_model.embed(prefixed_docs))
sparse_embs = list(sparse_model.embed(documents))  # sparse model needs no prefix

points = [
    models.PointStruct(
        id=i,
        vector={
            "dense": dense_embs[i].tolist(),
            "sparse": models.SparseVector(
                indices=sparse_embs[i].indices.tolist(),
                values=sparse_embs[i].values.tolist(),
            ),
        },
        payload={"text": doc},
    )
    for i, doc in enumerate(documents)
]
client.upsert("documents", points)

# 4. Hybrid search -- NOTE: prefix query with "search_query: "
query = "search query"
q_dense = list(dense_model.embed([f"search_query: {query}"]))[0]
q_sparse = list(sparse_model.embed([query]))[0]

results = client.query_points(
    collection_name="documents",
    prefetch=[
        models.Prefetch(query=q_dense.tolist(), using="dense", limit=20),
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

for r in results:
    print(f"Score: {r.score:.4f} | {r.payload['text'][:80]}")
```

---

## 5. Migration Risks & Recommendations

| Risk | Severity | Mitigation |
|---|---|---|
| Qwen3-Embedding not natively in fastembed | Medium | Use BGE-large-en-v1.5 now; switch when PR #605 merges |
| Qwen3 last-token pooling mismatch | High | If using custom model, set PoolingType.DISABLED |
| BM42 underperforms SPLADE | Low | Use SPLADE (Splade_PP_en_v1) for sparse |
| qdrant local mode no gRPC | Low | Fine for embedded/local use case |
| fastembed embed() returns generator | Low | Always wrap in list() |
| SparseVector numpy-to-list conversion | Low | Always .tolist() before passing to qdrant |
