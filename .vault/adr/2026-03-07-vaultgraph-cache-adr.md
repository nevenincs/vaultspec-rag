---
tags:
  - '#adr'
  - '#gpu-rag-stack'
date: '2026-03-07'
modified: '2026-10-12'
body_hash: 'sha256:288f1c8a94dea333a087d874968a6b7654e0ed2c8301f226b2fc134d2203e9e7'
related:
  - '[[2026-03-07-threading-lock-for-singleton-adr]]'
  - '[[2026-03-07-continuous-research]]'
---

# `gpu-rag-stack` adr: `VaultGraph cache with threading.Lock and explicit invalidation` | (**status:** `accepted`)

## Problem Statement

### Context

`get_related()` in `api.py` builds a fresh `VaultGraph` on every call,
re-reading graph data from disk each time. This is wasteful for repeated
queries. A caching pattern is needed that avoids redundant I/O, invalidates
after reindex, and is thread-safe for MCP worker threads.

## Considerations

No separate considerations is recorded in the retained prior ADR body. Source: retained prior ADR body.

## Considered options

No separate considered options is recorded in the retained prior ADR body. Source: retained prior ADR body.

## Constraints

No separate constraints is recorded in the retained prior ADR body. Source: retained prior ADR body.

## Implementation

### Decision

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

## Search latency amendment, 2026-10-12

Authorized by the user's instruction to fix the measured graph-related search stall.
This amendment replaces the synchronous construction and duplicate search fallback
requirements above for semantic search. Explicit relationship queries may still wait
for the canonical graph. Search reads never wait for construction: they use a current
ready graph or retain semantic ranking without the optional structural tie-breakers.
One GraphCache implementation owns construction, TTL, invalidation, and retry for
service and standalone searchers. Construction runs outside the state lock on a
coalesced background worker. Successful indexing invalidates graph data immediately;
an epoch fences late completion so a superseded build cannot restore stale data.
Eviction closes the cache and refuses subsequent publication. Failures have bounded
retry backoff and cannot trigger a second inline construction in the reranker.

Live evidence: the original 87.44-second query spent 85.41 seconds in graph processing;
a reproduction spent 118.47 of 122.20 seconds there. An immediate vault repeat took
1.80 seconds versus 1.99 seconds for code. The graph had 4,477 documents. A read-only
profile found 9,325 configuration calls and 130,189 path resolutions; cached JSON
loading itself took 0.42 seconds. Background execution addresses request blocking,
not graph calculation cost. The latter is separately authorized follow-on work and
must retain canonical graph semantics and filesystem safety validation.
