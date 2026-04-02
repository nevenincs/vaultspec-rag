---
tags:
  - "#adr"
  - "#gpu-rag-stack"
date: 2026-03-07
related:
  - "[[2026-03-07-mcp-sync-tools-adr]]"
  - "[[2026-03-08-fastmcp-lifespan-research]]"
---

# ADR: Use `threading.Lock` for `get_comp()` singleton

## Status

Accepted

## Context

`get_comp()` in `mcp_server.py` lazily initializes GPU models and Qdrant
connections. With sync `def` MCP tools (see ADR: mcp-sync-tools), this
function is called from worker threads spawned by `anyio.to_thread.run_sync()`.
Two concurrent requests could trigger double model loading without
synchronization.

## Decision

Use `threading.Lock` with double-checked locking to protect `get_comp()`.

```python
import threading

_comp_lock = threading.Lock()
_components: RAGComponents | None = None

def get_comp() -> RAGComponents:
    global _components
    if _components is not None:
        return _components
    with _comp_lock:
        if _components is not None:
            return _components
        _components = _build_components()
        return _components
```

## Rationale

Three lock types were evaluated:

| Lock type | Thread-safe | Async-safe | Usable from worker thread |
|-----------|------------|------------|--------------------------|
| `threading.Lock` | Yes | Deadlock risk | **Yes** |
| `asyncio.Lock` | No | Yes | No |
| `anyio.Lock` | No | Yes | No |

- `asyncio.Lock` and `anyio.Lock` are **not thread-safe** and cannot be
  acquired from worker threads.
- `threading.Lock` deadlocks when used **between coroutines on the same event
  loop thread** (single OS thread contention). But worker threads are real OS
  threads that can block independently -- no deadlock risk.
- Double-checked locking avoids lock contention on the hot path after
  initialization (first check is lock-free).

## Consequences

- `get_comp()` is safe for concurrent MCP requests from worker threads.
- Model loading happens at most once, even under concurrent startup load.
- If MCP tools are later changed back to `async def`, this lock type must
  be reconsidered (would need `anyio.Lock` instead).
