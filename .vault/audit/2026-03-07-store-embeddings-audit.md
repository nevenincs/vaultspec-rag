---
tags:
  - "#audit"
  - "#gpu-rag-stack"
date: 2026-03-07
related: []
---
# Round 22b Audit -- store.py, embeddings.py

## store.py

### R22b-M1: `_build_filter` uses `MatchText` for date filter -- tokenized full-text search instead of prefix match (Major)

Line 657-662: The `date` filter uses `models.MatchText(text=value)`. Qdrant's `MatchText` performs full-text search with tokenization. For a partial date like `"2026-02"`, the text is tokenized on hyphens, potentially matching any document containing token `"02"` or `"2026"` independently. The intended behavior is likely prefix matching (all docs from February 2026). Should use `MatchValue` for exact date strings, or switch to a Qdrant range filter if prefix semantics are needed.

**File:** `store.py:657-662`

### R22b-M2: `hybrid_search` and `hybrid_search_codebase` call `self.count()` on every query (Major)

Lines 517 and 581: Both search methods call `self.count()` / `self.count_code()` as an emptiness guard before running the actual query. Each `count()` call triggers `ensure_table()` (another `collection_exists` check) plus a Qdrant count RPC -- two round-trips per search just to check if the collection is empty. The query itself would return zero results on an empty collection, making this guard redundant overhead on the hot path.

**File:** `store.py:517, 581`

### R22b-M3: `get_engine` in api.py leaks old Qdrant client when root_dir changes (Major)

(Cross-reference from api.py, relevant to store lifecycle.) When `get_engine` detects a different `root_dir` (api.py:53), it creates a new `_Engine` without calling `close()` on the old store. The old `QdrantClient` is leaked with its file handles and lock files. This can cause `PermissionError` on Windows when a new store tries to access the same `.qdrant/` directory.

**File:** `api.py:50-55` (impacts `store.py` resource management)

### R22b-m1: `ensure_table` / `ensure_code_table` call `collection_exists` on every operation (Minor)

Lines 187 and 203: Every store method that calls `ensure_table()` or `ensure_code_table()` makes a `collection_exists` RPC to Qdrant. After the first successful creation, the collection is guaranteed to exist for the lifetime of the `VaultStore` instance. A boolean cache (`self._vault_table_ensured = True`) would eliminate repeated checks.

**File:** `store.py:183-197, 199-213`

### R22b-m2: `_stable_id` imports `hashlib` on every call (Minor)

Line 711: `import hashlib` is inside the static method body. While Python caches module imports after the first load, the import machinery still has overhead per call (dict lookup in `sys.modules`). For bulk operations like `upsert_documents` with hundreds of docs, this is called once per document. Moving the import to module level would be cleaner and marginally faster.

**File:** `store.py:711`

### R22b-m3: `upsert_documents` and `upsert_code_chunks` do not batch large upserts (Minor)

Lines 256-259 and 303-306: All points are sent in a single `self._client.upsert()` call regardless of count. For very large batches (thousands of documents with full content payloads), this can exceed memory limits or Qdrant's internal batch size preferences. Batching in groups of ~500 would be safer.

**File:** `store.py:256-259, 303-306`

### R22b-m4: `_build_filter` and `_build_code_filter` silently drop unknown filter keys (Minor)

Lines 656-677 and 692-699: If a filter dict contains an unexpected key (e.g., `{"title": "foo"}`), it is silently ignored -- no condition is added and no warning logged. The caller believes the filter is active but it has no effect.

**File:** `store.py:656-677, 692-699`

### R22b-m5: `_build_filter` does not handle empty string values (Minor)

Lines 671-676: If `filters={"doc_type": ""}` is passed, a `MatchValue(value="")` condition is created, which will match documents with an empty `doc_type` field. This is likely unintended -- empty values should probably be skipped like `None` values.

**File:** `store.py:671-676`

### R22b-m6: `hybrid_search` fallback swallows all exceptions (Minor)

Lines 555-564: The `except Exception` catch on the hybrid search path falls back to dense-only search. This hides bugs like malformed queries, authentication errors, or corrupted collection state. The fallback should only catch specific Qdrant fusion-related errors, not all exceptions.

**File:** `store.py:555-564`
**Also:** `store.py:619-631` (same pattern in `hybrid_search_codebase`)

### R22b-m7: No payload index on `date` or `tags` fields in vault collection (Minor)

Line 192: `ensure_table` creates keyword indexes on `doc_type` and `feature` only. The `date` and `tags` fields are used in `_build_filter` (lines 657-669) but have no payload index, meaning Qdrant must scan all points for date/tag filters. Adding indexes would improve filter performance.

**File:** `store.py:192-197`

### R22b-m8: `_points_to_dicts` uses `str(point.id)` as fallback ID (Minor)

Line 641: If the `id_field` (`doc_id` or `chunk_id`) is missing from the payload, the fallback is `str(point.id)` which is the integer hash from `_stable_id`. This integer is not reversible back to the original string ID, so downstream code receiving an integer-string ID like `"4582719306421"` instead of a document stem will break lookups.

**File:** `store.py:641`

## embeddings.py

### R22b-M4: `encode_documents` does not use `prompt_name` for documents -- asymmetric encoding (Major)

Line 236: `self._dense_model.encode(truncated, ...)` does not pass `prompt_name`. But `encode_query` (line 268) uses `prompt_name="query"`. Qwen3-Embedding uses instruction-based encoding where queries and documents should use different prompts. The `SentenceTransformer.encode()` method supports prompt templates via `prompt_name`. If Qwen3 expects a document prompt (e.g., `prompt_name="passage"` or similar), omitting it means documents are encoded without the instruction prefix, which may reduce retrieval quality. Should verify whether Qwen3-Embedding-0.6B requires a document-side prompt.

**File:** `embeddings.py:236-241`

### R22b-m9: `encode_documents_sparse` default `batch_size=32` ignores config (Minor)

Line 275: `encode_documents_sparse` hardcodes `batch_size=32` as the default parameter. But `encode_documents` (line 228-229) uses `self._default_batch_size()` which reads from config (default 64). The sparse encoder may have different memory characteristics justifying a smaller default, but this inconsistency is undocumented.

**File:** `embeddings.py:275`

### R22b-m10: `encode_query` has no OOM retry logic (Minor)

Line 267-272: `encode_query` calls `self._dense_model.encode` with a single query and no try/except for `OutOfMemoryError`. While a single query is unlikely to OOM, if the GPU is under memory pressure from a previous batch, this could fail. Both `encode_documents` and `encode_documents_sparse` have OOM retry loops, but `encode_query` and `encode_query_sparse` do not.

**File:** `embeddings.py:267-272, 309-321`

### R22b-m11: `_sparse_tensor_to_results` checks `is_sparse_csr` which may not exist on older torch (Minor)

Line 80: `sparse_tensor.is_sparse_csr` was added in PyTorch 1.10. The project requires CUDA and likely a modern torch version, so this is low risk. But if a user has an older torch version, this raises `AttributeError` with no helpful message.

**File:** `embeddings.py:80`

### R22b-m12: `_check_rag_deps` does not verify CUDA version compatibility (Minor)

Lines 34-48: The function checks `torch.cuda.is_available()` but does not verify the CUDA runtime version matches the torch build. A mismatch (e.g., torch built for CUDA 12.1 but runtime is 11.8) can cause cryptic errors later during model loading or inference rather than a clear message at startup.

**File:** `embeddings.py:34-48`

### R22b-m13: `SparseEncoder` model_kwargs uses string `"float16"` instead of `torch.float16` (Minor)

Line 189: `model_kwargs={"torch_dtype": "float16"}`. The dense model (line 170) correctly uses `torch.float16` (the actual dtype object). The sparse model passes a string. Whether this works depends on `SparseEncoder`'s internal handling -- some HuggingFace model loaders accept string dtype names, but it's inconsistent with the dense model initialization and may silently fall back to fp32.

**File:** `embeddings.py:189`

### R22b-m14: `sparse_model` config access uses `hasattr` check unnecessarily (Minor)

Lines 162-166: The code checks `hasattr(cfg, "sparse_model") and cfg.sparse_model`. Since `VaultSpecConfigWrapper.__getattr__` provides defaults for all RAG keys including `sparse_model` (config.py:31), the `hasattr` check is always True. This is dead defensive code.

**File:** `embeddings.py:162-166`
**Also:** Lines 194-196 same pattern for `embedding_dimension`.
