# ADR: Filters must go on each Prefetch, not top-level `query_filter`
Date: 2026-03-07
Status: Accepted

## Context
Qdrant's `query_points()` API has two places to specify filters: a top-level
`query_filter` parameter and a `filter` field on each `Prefetch` object. When
using `prefetch` + `FusionQuery(RRF)` for hybrid search, it was unclear
whether a single top-level filter would apply to all prefetch branches.

## Decision
Always place filters on each `Prefetch` individually when using prefetch-based
hybrid search. Do not rely on top-level `query_filter` alone.

For dense-only queries (no prefetch), use top-level `query_filter` normally.

## Rationale
Runtime testing in Qdrant local mode confirmed:

| Scenario | Result |
|----------|--------|
| Top-level `query_filter` only (with prefetch) | **FILTER IGNORED** |
| Per-Prefetch `filter` on each branch | **WORKS** |
| Top-level `query_filter` (no prefetch) | **WORKS** |

The top-level `query_filter` is silently ignored when `prefetch` is used with
`FusionQuery`. This is undocumented behavior specific to local mode. The
correct pattern:

```python
client.query_points(
    collection_name="code_index",
    prefetch=[
        models.Prefetch(query=dense, using="dense", limit=20, filter=f),
        models.Prefetch(query=sparse, using="sparse", limit=20, filter=f),
    ],
    query=models.FusionQuery(fusion=models.Fusion.RRF),
    limit=10,
)
```

Note: the top-level parameter is `query_filter`, but the Prefetch field is
`filter` -- different names.

## Consequences
- `store.py` must add `filter=query_filter` to every `Prefetch` object.
- Current codebase is already correct (verified during research).
- Any new search methods using prefetch must follow this pattern.
- If migrating to Qdrant server mode, re-test whether top-level filtering
  behavior differs.
