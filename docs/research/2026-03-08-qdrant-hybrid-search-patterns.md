# Qdrant Hybrid Search Patterns (Verified)

**Date**: 2026-03-08
**Status**: Proactive research — grounding for ongoing coder work

## Universal Query API + FusionQuery(RRF)

The project uses Qdrant's Universal Query API (introduced in v1.10) for hybrid search. Key verified patterns:

### Correct: Filters on each Prefetch individually

```python
prefetches = [
    models.Prefetch(
        query=dense_vector,
        using="dense",
        filter=query_filter,  # CORRECT: filter here
        limit=limit,
    ),
    models.Prefetch(
        query=sparse_vector,
        using="sparse",
        filter=query_filter,  # CORRECT: filter here too
        limit=limit,
    ),
]
results = client.query_points(
    collection_name=collection,
    prefetch=prefetches,
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=limit,
    # NO query_filter here for hybrid search
)
```

**Why**: Top-level `query_filter` on `query_points` applies AFTER prefetch results are fused. Per-prefetch `filter` applies DURING candidate gathering. For correct filtered hybrid search, filters must go on each Prefetch so both dense and sparse candidate pools are filtered before fusion.

**Known issue**: When using multiple prefetches with top-level filter only, some filtered results may be missed because the candidate pool from prefetches is limited before the top-level filter runs.

### RRF Formula

RRF score = `1/(k+r)` where `r` is rank position and `k=2` (Qdrant's constant). This mitigates outlier rankings from individual retrieval methods.

### Fallback Pattern

The codebase correctly implements a fallback to dense-only search when hybrid search returns no results:

```python
fallback = client.query_points(
    collection_name=collection,
    query=dense_vector,
    using="dense",
    query_filter=query_filter,  # OK here: single query, not prefetch
    limit=limit,
)
```

This is correct — `query_filter` on the top level works fine for single-method queries (no prefetch).

### Named Vectors

The project uses two named vectors per collection:
- `dense`: 1024d Qwen3-Embedding-0.6B (Cosine distance)
- `sparse`: SPLADE v3 (sparse vocabulary weights)

### Local Mode

`QdrantClient(path=...)` runs embedded Qdrant — no Docker, no server process. Data persists to disk at the given path. Suitable for single-process access (which this project uses).

**Warning**: Local mode does not support concurrent access from multiple processes. The filesystem watcher service (Task #17) must run in the same process as the MCP server, not as a separate daemon.

## Payload Indexes

The project creates payload indexes for filtered search performance:
- **Vault collection**: `date` (KEYWORD), `tags` (KEYWORD), `doc_type` (KEYWORD), `feature` (KEYWORD)
- **Codebase collection**: `line_start` (INTEGER), `language` (KEYWORD), `node_type` (KEYWORD), `function_name` (KEYWORD), `class_name` (KEYWORD), `doc_type` (KEYWORD), `feature` (KEYWORD)

These are created via `create_payload_index()` at collection creation time.
