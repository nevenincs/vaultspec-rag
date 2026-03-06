# Audit: Store / Qdrant Vector Database

Feature: store.py Qdrant local mode with hybrid search

## 2026-03-06 -- Architecture Review (Passes 18-25)

### Architecture: SOLID

- Named vectors: "dense" (1024d, cosine) + "sparse" per collection
- Two collections: `vault_docs` (documents) + `codebase_docs` (code chunks)
- `_stable_id()`: SHA-256 truncation with `& 0x7FFFFFFFFFFFFFFF` for positive int IDs
- Hybrid search: Prefetch (dense + sparse) -> FusionQuery(RRF) -> limit
- Graceful fallback to dense-only on hybrid search failure
- Context manager protocol (`__enter__`/`__exit__`) properly closes client
- `_build_filter()`: MatchText for date prefix, MatchValue for exact matches
- `_build_code_filter()`: language and path filters

### EMBEDDING_DIM Updated

Line 22: `EMBEDDING_DIM = 1024` (updated from 768 for Qwen3).

### Open Issue

- Task #45: store.py:115 docstring still says "(768)" -- [LOW]

### Payload Schema

Vault docs: `doc_id`, `path`, `doc_type`, `feature`, `date`, `tags`, `related`, `title`, `content`
Code chunks: `chunk_id`, `path`, `language`, `content`, `line_start`, `line_end`
`_points_to_dicts()` correctly maps `"doc_id"` for vault and `"chunk_id"` for codebase.

## Pass 27 — Full store.py review

Full line-by-line audit. All confirmed correct:

- All `.tolist()` sites fixed (lines 418-419, 482-483 use `list()` wrappers)
- `SparseVectorParams()` with no Modifier -- correct for SPLADE v3
- `_stable_id()` SHA-256 with `& 0x7FFFFFFFFFFFFFFF` -- positive int IDs
- Hybrid search prefetch + FusionQuery(RRF) -- correct Qdrant pattern
- Dense-only fallback on exception -- reasonable defensive pattern
- Context manager protocol properly closes client

Open: Task #45 [LOW] -- docstring "(768)" at line 114.
