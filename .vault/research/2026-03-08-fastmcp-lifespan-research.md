---
tags:
  - "#research"
  - "#gpu-rag-stack"
date: 2026-03-08
related: []
---
# FastMCP Lifespan Context Research for Task #25

**Date**: 2026-03-08
**Task**: #25 (Refactor mcp_server.py to use FastMCP lifespan context)
**Status**: Complete

## Executive Summary

**RECOMMENDATION: Close Task #25 as "not beneficial".**

The current `get_comp()` lazy-initialization pattern with `threading.Lock` is **strictly better** than FastMCP's lifespan context for this use case. The lifespan approach has three critical disadvantages:

1. **Forces eager initialization** at server startup (5-15s GPU delay) vs lazy init on first request
2. **No error recovery mechanism** — if lifespan fails, server startup fails (current approach caches errors)
3. **Thread safety still required** — lifespan context object must be thread-safe for access from worker threads

---

## Verified: FastMCP Lifespan API (SDK-bundled v1.0+)

### What works

- **Parameter exists**: `FastMCP.__init__(lifespan=...)` signature confirmed
- **Type signature**: `Callable[[FastMCP[LifespanResultT]], AbstractAsyncContextManager[LifespanResultT]] | None`
- **Access in tools**: `@mcp.tool()` decorated functions receive `ctx: Context` parameter
  - Lifespan result stored in: `ctx.request_context.lifespan_context`
  - Type: `RequestContext[SessionT, LifespanContextT, RequestT].lifespan_context` attribute
- **Transport support**: Works with `stdio`, `sse`, and `streamable-http` equally

### Basic usage pattern

```python
from contextlib import asynccontextmanager
from mcp.server.fastmcp import FastMCP, Context

@asynccontextmanager
async def app_lifespan(server):
    """Initialize at startup, cleanup at shutdown."""
    print("Starting up...")
    model = EmbeddingModel()
    try:
        yield model
    finally:
        print("Cleaning up...")

mcp = FastMCP("VaultSpec", lifespan=app_lifespan)

@mcp.tool()
async def search_vault(query: str, ctx: Context) -> SearchResponse:
    model = ctx.request_context.lifespan_context
    # Use model
    return SearchResponse(...)
```

---

## Problem: Startup Blocking

### Current approach (lazy init)

```
Time 0.0s: Server process starts and listens for requests
Time 0.1s: Server is ready, client connects
Time 5.0s: Client makes first search request
Time 5.1s: get_comp() initializes GPU (Qwen3 1024d + SPLADE + CrossEncoder)
Time 20.0s: First search completes
```

### Lifespan approach

```
Time 0.0s: Server process starts, runs lifespan startup
Time 5.0s: GPU initialization complete
Time 5.1s: Server listens for requests (was blocking until now!)
Time 5.2s: Client connects and makes request
Time 5.3s: First search completes (no init delay)
```

**Tradeoff analysis**:

- **Lazy init wins** if: Client doesn't always make a request (e.g., server starts for other reasons), or slow startup is acceptable
- **Lifespan wins** if: All clients will immediately search, and you want to fail fast on init errors

For VaultSpec:

- MCP server is a **background service** often started in advance
- First client request may come seconds or minutes later
- Blocking the event loop for 5-15s is **poor UX** — the server appears hung
- **Verdict**: Lazy init is better for this architecture

---

## Problem: Error Recovery

### Current approach

```python
_comp_error: Exception | None = None

def get_comp() -> RagComponents:
    global _comp, _comp_error
    if _comp_error is not None:
        raise RuntimeError(f"RAG init failed: {_comp_error}") from _comp_error
    try:
        # ... init code
    except Exception as exc:
        _comp_error = exc
        raise
```

**Caching strategy**:

- First request with no GPU → exception cached in `_comp_error`
- Subsequent requests → immediately re-raise cached error
- Prevents retry loop on every request (good!)
- But allows **server to stay alive** while reporting init failure

### Lifespan approach

```python
@asynccontextmanager
async def app_lifespan(server):
    try:
        model = EmbeddingModel()  # Raises RuntimeError if no GPU
        yield model
    finally:
        model.shutdown()
```

**Startup failure scenario**:

- Lifespan raises during `yield`
- Server startup fails completely
- MCP server process exits
- Client sees connection reset

**Problem**: No way to distinguish "server is running but init failed" from "server crashed". This is **worse** for debugging — users won't know if it's a GPU issue or a server crash.

---

## Problem: Thread Safety

### Current approach

```python
_comp_lock = threading.Lock()
_gpu_sem = asyncio.Semaphore(1)

@mcp.tool()
async def search_vault(query: str, ctx: Context) -> SearchResponse:
    def _run():
        comp = get_comp()  # Thread-safe: uses _comp_lock
        # ... search in worker thread

    async with _gpu_sem:
        result = await anyio.to_thread.run_sync(_run)
    return result
```

**Thread safety mechanisms**:

1. `threading.Lock` protects `_comp` initialization (double-checked locking)
2. `asyncio.Semaphore(1)` serializes GPU access across concurrent requests
3. Each tool calls `get_comp()` from worker thread (safe due to lock)

### Lifespan approach

```python
@asynccontextmanager
async def app_lifespan(server):
    model = EmbeddingModel()  # Created in event loop
    try:
        yield model
    finally:
        model.shutdown()

@mcp.tool()
async def search_vault(query: str, ctx: Context) -> SearchResponse:
    def _run():
        model = ctx.request_context.lifespan_context  # Access from worker thread!
        # ... search in worker thread

    async with _gpu_sem:
        result = await anyio.to_thread.run_sync(_run)
    return result
```

**Problem**: `lifespan_context` is created in the event loop but accessed from worker threads. This requires:

- `lifespan_context` object must be **thread-safe** (all models are, CUDA handles this)
- GPU operations still need `asyncio.Semaphore(1)` for serialization
- **You still need the lock and semaphore anyway**

**Conclusion**: Lifespan doesn't eliminate thread safety concerns; it just moves the initialization to a different thread.

---

## Current Architecture Assessment (Verified)

From prior research (docs/research/2026-03-08-fastmcp-workspace-root.md):

> "The current `get_comp()` pattern with `_comp_lock` is functionally equivalent to a lifespan — it initializes once and caches. The main difference is:
>
> - Lifespan: initialized at server start, before any requests
> - get_comp(): initialized lazily on first request
>
> Lazy initialization is actually better for the current use case — it avoids blocking server startup on GPU model loading (5-15s). The server starts instantly and the first request triggers initialization."

This assessment is **correct**. The lazy pattern is optimal here.

---

## Why not lifespan?

| Aspect | Current get_comp() | Lifespan | Winner |
|--------|-------------------|----------|--------|
| **Startup time** | <100ms | 5-15s (GPU load) | Current |
| **Error recovery** | Cached, server stays alive | Hard crash, server exits | Current |
| **Error visibility** | Clear exception on first request | Server fails to start | Current |
| **Thread safety** | `threading.Lock` + `asyncio.Semaphore` | Still needs both | Tie |
| **Code clarity** | Explicit, easy to understand | More idiomatic, less explicit | Lifespan |
| **GPU serialization** | `asyncio.Semaphore(1)` | Still needs `asyncio.Semaphore(1)` | Tie |

---

## When would lifespan be better?

Lifespan becomes beneficial only if:

1. **All clients always perform work on startup** (e.g., warmup pass)
2. **Startup failure should be fatal** (e.g., required credential missing)
3. **VRAM limits prevent keeping components in memory** (e.g., can't fit model + request buffer)
4. **Server has other services that need initialization** (e.g., database connections)

None of these apply to VaultSpec.

---

## Recommendation

**CLOSE TASK #25 as "Not Beneficial".**

The refactor would:

- Make server startup slower (5-15s blocking)
- Remove error recovery (server exits on GPU failure)
- Not simplify code (still need `threading.Lock` and `asyncio.Semaphore`)
- Only benefit: Slightly more idiomatic (uses FastMCP's lifespan feature)

**Cost-benefit ratio is negative.** The current architecture is optimal for this use case.

### If revisiting in future

- Only consider lifespan if VaultSpec needs to support **cold-start scenarios** where all requests are latency-critical
- Or if moving to a **different deployment model** (e.g., serverless, where startup cost is amortized)
- Current pattern is proven, tested, and working well

---

## Supporting Documentation

- **API verification**: Tested `FastMCP.__init__(lifespan=...)` with MCP SDK 1.26.0
- **Context access**: Confirmed `ctx.request_context.lifespan_context` in tools
- **Thread safety**: Both approaches require `asyncio.Semaphore(1)` for GPU serialization
- **Transport modes**: Lifespan works with stdio, SSE, and streamable-http equally
- **Prior research**: docs/research/2026-03-08-fastmcp-workspace-root.md (Task #22)
