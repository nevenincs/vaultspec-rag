---
tags:
  - '#adr'
  - '#gpu-rag-stack'
date: 2026-03-07
related:
  - '[[2026-03-07-threading-lock-for-singleton-adr]]'
  - '[[2026-03-07-continuous-research]]'
---

# ADR: MCP tools use `async def` + `anyio.to_thread.run_sync`

## Status

Accepted (corrected same day; original sync-def approach was wrong)

## Context

MCP tool handlers in `mcp_server.py` call synchronous blocking code: GPU
inference (`SentenceTransformer.encode`, `CrossEncoder.predict`) and Qdrant
I/O (`query_points`, `scroll`). These must not block the asyncio event loop.

## Original Decision (WRONG)

Declare all MCP tool functions as plain `def` (synchronous), relying on
MCP Python SDK PR #1909 to auto-wrap sync tools in `anyio.to_thread.run_sync()`.

## Correction

Verified against MCP SDK 1.26.0 installed source: **sync `def` tools are NOT
auto-wrapped** — they execute directly on the event loop, blocking it during
GPU inference and Qdrant I/O. The auto-wrap assumption was incorrect.

## Corrected Decision

Declare all MCP tool functions as `async def` and explicitly wrap blocking
calls with `anyio.to_thread.run_sync()`:

```python
import anyio

@mcp.tool()
async def search_vault(query: str, top_k: int = 5) -> SearchResponse:
    def _run() -> SearchResponse:
        comp = get_comp()
        # ... blocking GPU + Qdrant code ...
        return result
    return await anyio.to_thread.run_sync(_run)
```

## Rationale

1. `anyio.to_thread.run_sync()` offloads the entire blocking call to a
   worker thread, keeping the event loop responsive for heartbeats,
   concurrent requests, and protocol traffic.
1. anyio (not asyncio) is correct because FastMCP uses anyio internally.
   `anyio.to_thread.run_sync()` propagates context via `copy_context()`.
1. PyTorch GPU inference is thread-safe for reads (`model.eval()` +
   `torch.no_grad()`).
1. Qdrant local mode is thread-safe for reads (SQLite WAL mode).

## Consequences

- All `@mcp.tool()` functions are `async def`.
- Each tool wraps its blocking body in a `_run()` closure passed to
  `anyio.to_thread.run_sync()`.
- The event loop remains responsive during GPU inference and Qdrant I/O.
