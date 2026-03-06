# API Migration Mapping: LanceDB/sentence-transformers -> qdrant-client/fastembed

Date: 2026-03-06

This document maps the current codebase API surface to equivalent qdrant-client/fastembed patterns, preserving the public interface.

---

## embeddings.py

### Current Public API to Preserve

| Symbol | Type | Keep? | Notes |
|---|---|---|---|
| `EmbeddingModel` | class | YES | Core class, change internals only |
| `EmbeddingModel.MODEL_NAME` | str | YES | Keep `"nomic-ai/nomic-embed-text-v1.5"` |
| `EmbeddingModel.DEFAULT_DIMENSION` | int | YES | Keep 768 |
| `EmbeddingModel.DOCUMENT_PREFIX` | str | YES | Keep `"search_document: "` |
| `EmbeddingModel.QUERY_PREFIX` | str | YES | Keep `"search_query: "` |
| `EmbeddingModel.dimension` | int | YES | Set from model |
| `EmbeddingModel.__init__()` | method | CHANGE | No args currently. Replace internals. |
| `EmbeddingModel.encode_documents(texts, batch_size=)` | method | YES | Return np.ndarray (n, dim) |
| `EmbeddingModel.encode_query(query)` | method | YES | Return np.ndarray (dim,) |
| `GPUNotAvailableError` | exception | REMOVE | No GPU needed with fastembed |
| `get_device_info()` | function | REMOVE | No GPU needed |
| `CUDA_INDEX_TAG`, `CUDA_INDEX_URL` | constants | REMOVE | No torch/CUDA |

### Migration Pattern

```python
# OLD (sentence-transformers + torch)
from sentence_transformers import SentenceTransformer
self.model = SentenceTransformer(model_name, device="cuda", trust_remote_code=True)
result = self.model.encode(texts, show_progress_bar=True, normalize_embeddings=True)

# NEW (fastembed)
from fastembed import TextEmbedding
self._dense_model = TextEmbedding(model_name="nomic-ai/nomic-embed-text-v1.5")
result = np.array(list(self._dense_model.embed(prefixed_texts)))
# fastembed already normalizes by default for this model
```

### encode_documents migration

```python
# OLD: self.model.encode(chunk, show_progress_bar=True, normalize_embeddings=True)
# NEW:
def encode_documents(self, texts, *, batch_size=None):
    if batch_size is None:
        batch_size = self._default_batch_size()
    max_chars = self._default_max_embed_chars()
    truncated = [t[:max_chars] for t in texts]
    prefixed = [f"{self.DOCUMENT_PREFIX}{t}" for t in truncated]
    embeddings = list(self._dense_model.embed(prefixed, batch_size=batch_size))
    return np.array(embeddings)
```

### encode_query migration

```python
# OLD: self.model.encode(prefixed, show_progress_bar=False, normalize_embeddings=True)
# NEW:
def encode_query(self, query):
    prefixed = f"{self.QUERY_PREFIX}{query}"
    result = list(self._dense_model.embed([prefixed]))[0]
    return np.asarray(result, dtype=np.float32)
```

### Sparse embedding (NEW -- needed for hybrid search)

Add a new method or separate attribute for sparse embeddings:

```python
from fastembed import SparseTextEmbedding

self._sparse_model = SparseTextEmbedding(model_name="prithivida/Splade_PP_en_v1")

def encode_documents_sparse(self, texts, *, batch_size=None):
    # No prefix needed for SPLADE
    max_chars = self._default_max_embed_chars()
    truncated = [t[:max_chars] for t in texts]
    return list(self._sparse_model.embed(truncated, batch_size=batch_size or 32))

def encode_query_sparse(self, query):
    return list(self._sparse_model.embed([query]))[0]
```

---

## store.py

### Current Public API to Preserve

| Symbol | Type | Keep? | Notes |
|---|---|---|---|
| `EMBEDDING_DIM` | int (768) | YES | |
| `VaultDocument` | dataclass | YES | Drop `to_dict()` if unused outside store |
| `CodeChunk` | dataclass | YES | Same |
| `VaultStore` | class | YES | Change internals |
| `VaultStore.__init__(root_dir, embedding_dim=)` | method | CHANGE | Use QdrantClient(path=...) |
| `VaultStore.close()` | method | YES | Call client.close() |
| `VaultStore.ensure_table()` | method | RENAME? | -> ensure_collection() |
| `VaultStore.upsert_documents(docs)` | method | YES | Convert to PointStruct |
| `VaultStore.upsert_code_chunks(chunks)` | method | YES | Same |
| `VaultStore.delete_documents(ids)` | method | YES | Use client.delete() |
| `VaultStore.get_all_ids()` | method | YES | Use scroll() or payload index |
| `VaultStore.count()` | method | YES | client.count() |
| `VaultStore.get_by_id(doc_id)` | method | YES | Use scroll with filter |
| `VaultStore.hybrid_search(query_vector, query_text, filters, limit)` | method | CHANGE | Use query_points with prefetch+RRF |
| `VaultStore.hybrid_search_codebase(...)` | method | CHANGE | Same pattern |

### Key Mapping: LanceDB -> Qdrant

| LanceDB Concept | Qdrant Equivalent |
|---|---|
| `lancedb.connect(path)` | `QdrantClient(path=str(path))` |
| `db.create_table(name, data)` | `client.create_collection(name, vectors_config=..., sparse_vectors_config=...)` |
| `table.add(records)` | `client.upsert(name, points=[PointStruct(...)])` |
| `table.delete(predicate)` | `client.delete(name, points_selector=FilterSelector(filter=...))` |
| `table.count_rows()` | `client.count(name).count` |
| `table.search(query_type="hybrid").vector().text().rerank(RRFReranker())` | `client.query_points(name, prefetch=[dense, sparse], query=FusionQuery(RRF))` |
| `table.create_fts_index("content")` | Not needed -- SPLADE sparse vectors replace BM25/FTS |
| `table.to_arrow()` | `client.scroll(name, limit=...)` |
| SQL WHERE clause `"doc_type = 'adr'"` | `Filter(must=[FieldCondition(key="doc_type", match=MatchValue(value="adr"))])` |

### Collection Structure

Two collections (replacing two LanceDB tables):

1. `vault_docs` -- dense (768d) + sparse named vectors, payload = all VaultDocument fields
2. `codebase_docs` -- dense (768d) + sparse named vectors, payload = all CodeChunk fields

### hybrid_search migration

```python
# OLD (LanceDB):
results = table.search(query_type="hybrid") \
    .vector(query_vector.tolist()) \
    .text(query_text) \
    .rerank(RRFReranker()) \
    .limit(limit).to_list()

# NEW (Qdrant):
results = client.query_points(
    collection_name="vault_docs",
    prefetch=[
        models.Prefetch(query=query_vector.tolist(), using="dense", limit=limit * 4),
        models.Prefetch(
            query=models.SparseVector(
                indices=query_sparse.indices.tolist(),
                values=query_sparse.values.tolist(),
            ),
            using="sparse",
            limit=limit * 4,
        ),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    query_filter=qdrant_filter,  # converted from dict filters
    limit=limit,
    with_payload=True,
).points
```

### Filter conversion

```python
# OLD: f"doc_type = 'adr'" (SQL string)
# NEW:
def _build_qdrant_filter(filters: dict[str, str] | None) -> models.Filter | None:
    if not filters:
        return None
    conditions = []
    for key, value in filters.items():
        if key == "date":
            # Date prefix match -- use MatchText or starts_with
            conditions.append(models.FieldCondition(
                key="date", match=models.MatchText(text=value)
            ))
        else:
            conditions.append(models.FieldCondition(
                key=key, match=models.MatchValue(value=value)
            ))
    return models.Filter(must=conditions)
```

---

## search.py

### Current Public API to Preserve (no changes needed)

| Symbol | Keep? | Notes |
|---|---|---|
| `ParsedQuery` | YES | Unchanged |
| `SearchResult` | YES | Unchanged |
| `VaultSearcher` | YES | Internal calls change |
| `parse_query()` | YES | Unchanged |
| `rerank_with_graph()` | YES | Unchanged |
| `VaultSearcher.search_vault()` | YES | Calls store.hybrid_search() |
| `VaultSearcher.search_codebase()` | YES | Calls store.hybrid_search_codebase() |
| `VaultSearcher.search_all()` | YES | Combines above |

### Key Change

`VaultSearcher.__init__` currently takes `(root_dir, model, store)`. The `model` must now also provide sparse encoding. Two approaches:

1. **EmbeddingModel grows sparse methods** -- `encode_query_sparse()`, `encode_documents_sparse()`
2. **Separate SparseEmbeddingModel** -- passed as additional arg

Option 1 is simpler and preserves the interface.

### hybrid_search signature change

The `VaultStore.hybrid_search()` currently takes `(query_vector, query_text, filters, limit)`.

With Qdrant, the sparse query replaces `query_text` for BM25. New signature:

```python
def hybrid_search(
    self,
    query_vector: np.ndarray,          # dense embedding
    query_sparse: SparseEmbedding,     # NEW: sparse embedding (replaces query_text)
    filters: dict[str, str] | None = None,
    limit: int = 5,
) -> list[dict]:
```

The `query_text` parameter is no longer needed because SPLADE sparse vectors encode the text information that BM25/FTS previously provided. The caller (VaultSearcher) will need to generate both dense and sparse query embeddings.

### Score field

- LanceDB returns `_relevance_score` in results
- Qdrant returns `point.score` on each ScoredPoint
- search.py reads `r.get("_relevance_score", 0.0)` -- this must change to read from `.score`

---

## Summary of Breaking Changes (internal only)

1. `EmbeddingModel.__init__` no longer requires CUDA/GPU
2. `EmbeddingModel` gains sparse embedding methods
3. `VaultStore.__init__` uses QdrantClient instead of lancedb.connect
4. `VaultStore.hybrid_search` takes sparse vector instead of query_text
5. No more FTS index management (_ensure_fts_index removed)
6. Filter syntax changes from SQL strings to Qdrant Filter objects
7. Score field changes from `_relevance_score` to `.score`

All public-facing APIs (VaultSearcher, SearchResult, ParsedQuery) remain unchanged.
