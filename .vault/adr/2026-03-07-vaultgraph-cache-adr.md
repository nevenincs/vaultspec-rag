---
tags:
  - '#adr'
  - '#gpu-rag-stack'
date: 2026-03-07
related:
  - '[[2026-03-07-threading-lock-for-singleton-adr]]'
  - '[[2026-03-07-continuous-research]]'
---

# ADR: VaultGraph cache with `threading.Lock` and explicit invalidation

## Status

Accepted

## Context

`get_related()` in `api.py` builds a fresh `VaultGraph` on every call,
re-reading graph data from disk each time. This is wasteful for repeated
queries. A caching pattern is needed that avoids redundant I/O, invalidates
after reindex, and is thread-safe for MCP worker threads.

## Decision

Use a module-level singleton cache with `threading.Lock` for construction/
invalidation, and explicit invalidation after reindex.

```python
class _GraphCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._graph: VaultGraph | None = None

    def get(self, graph_path: Path) -> VaultGraph:
        if self._graph is not None:
            return self._graph
        with self._lock:
            if self._graph is not None:
                return self._graph
            self._graph = VaultGraph.from_path(graph_path)
            return self._graph

    def invalidate(self) -> None:
        with self._lock:
            self._graph = None

_graph_cache = _GraphCache()
```

Call `_graph_cache.invalidate()` after reindex completes.

## Rationale

1. **`threading.Lock` is correct** because `get_related()` runs in MCP worker
   threads (see ADR: threading-lock-for-singleton). Double-checked locking
   avoids contention on the hot path.

1. **Explicit invalidation after reindex** is reliable because reindex and
   search happen in the same process. The indexer (or API facade) calls
   `invalidate()` when done.

1. **Alternatives rejected:**

   - `weakref`: wrong semantic -- we want the graph to stay alive between
     calls, not be GC'd when no references remain
   - `functools.lru_cache`: not invalidatable, stale forever
   - File mtime checking: adds stat() per access, mtime has 1-2s resolution
     on some platforms, unnecessary when reindex is in-process

1. **Concurrent reads are lock-free**: `VaultGraph` is read-only after
   construction. Multiple threads can read simultaneously without locking.
   Only construction and invalidation acquire the lock.

## Consequences

- `api.py` uses `_graph_cache.get(path)` instead of rebuilding on every call.
- Reindex code must call `_graph_cache.invalidate()` after completion.
- If cross-process invalidation is ever needed (CLI reindex while MCP runs),
  switch to mtime-based checking.
