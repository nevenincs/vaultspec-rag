# GPU Queuing/Serialization for RAG Systems

**Date**: 2026-03-08
**Task**: #5
**Status**: Complete

## Problem

The MCP server uses `anyio.to_thread.run_sync()` to offload GPU work but has no serialization — concurrent tool calls can trigger simultaneous GPU inference (dense encode + sparse encode + CrossEncoder rerank). The `threading.Lock` instances only protect initialization, not ongoing inference.

## Recommendation

**Use `asyncio.Semaphore(1)` in `mcp_server.py`** to serialize GPU-bound MCP tool calls.

```python
import asyncio
_gpu_sem = asyncio.Semaphore(1)

async def search_vault(query, top_k=5):
    async with _gpu_sem:
        return await anyio.to_thread.run_sync(_run)
```

Apply to: `search_vault`, `search_codebase`, `search_all`, `reindex_vault`, `reindex_codebase`.
Do NOT apply to: `get_index_status`, `get_code_file` (no GPU work).

## Why This Over Alternatives

| Option | Verdict |
|---|---|
| `asyncio.Semaphore(1)` | **RECOMMENDED** — zero deps, 4-5 lines, async backpressure |
| `threading.Lock` | Blocks worker threads (wastes pool slots) |
| Dedicated GPU worker thread + queue | Over-engineered for single-user MCP server |
| Ray Serve | Wrong scale (~100MB dep, requires cluster) |
| Celery + Redis | Wrong paradigm (background jobs, not low-latency search) |
| NVIDIA Triton | Violates no-ONNX mandate, wrong scale |

## Key Details

- `Semaphore(1)` = full serialization; bump to `Semaphore(2)` if GPU has headroom
- Blocks at coroutine level (cheap) not thread level (expensive)
- `anyio.Semaphore` is portable equivalent if trio support ever needed
