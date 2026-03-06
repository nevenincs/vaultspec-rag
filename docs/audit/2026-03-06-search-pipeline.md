# Audit: Search Pipeline

Feature: search.py query parsing, hybrid search, graph re-ranking

## 2026-03-06 -- Review (Passes 18-25)

### Architecture: SOLID

- `parse_query()`: Regex-based filter extraction (type, feature, date, tag, lang, path)
- `VaultSearcher`: Orchestrates hybrid search across vault and codebase
- `search()` -> `search_all()` -> `search_vault()` + `search_codebase()`
- Graph cache with TTL (default from config.graph_ttl_seconds)
- `rerank_with_graph()`: Authority boost `score *= 1 + 0.1 * min(in_links, 10)`, feature neighbor boost `*= 1.15`

### GPU Pivot Compatibility: CLEAN

- No prefix handling in search.py (Qwen3 uses `prompt_name` internally)
- `encode_query_sparse()` returns SparseResult, passed directly to `store.hybrid_search()`
- No old-stack references remaining

### No Issues Found

## Pass 27 — Cross-encoder readiness check

Task #42 (cross-encoder reranker) is `in_progress` but no code has landed. Current pipeline:

```
Qdrant hybrid search (RRF) -> rerank_with_graph() -> return top_k
```

Integration point for cross-encoder: between RRF results (line 196) and graph reranking (line 216), or as a replacement for graph reranking. Will audit when code appears.
