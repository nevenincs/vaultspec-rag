# Model Server Patterns for Resident Models

**Date**: 2026-03-08
**Task**: #9
**Status**: Complete

## Current State

The project already uses singleton patterns correctly:

- `api.py`: `_Engine` singleton + `_engine_lock` — model loaded once per process
- `mcp_server.py`: `RagComponents` singleton + `_comp_lock` — same pattern

**MCP server is already optimal** — long-running process, models load once at first request.

**CLI is the cold-start problem** — each invocation is a new process (5-15s model load for a 50ms query).

## Recommendation by Timeframe

### Short Term: No Change

MCP server (primary use case) already keeps models resident.

### Medium Term: CLI-as-MCP-Client

CLI connects to running MCP server as thin client (fast path), falls back to in-process if server not running:

```python
def search(query, top_k):
    try:
        result = mcp_client_search(query, top_k)  # fast path
    except ConnectionRefusedError:
        engine = get_engine(root_dir)  # cold start fallback
        result = engine.searcher.search_vault(query, top_k)
```

### Long Term: Not Needed

"Local-first single-GPU tool" doesn't need Triton/vLLM/BentoML.

## Alternatives Evaluated

| Option | Verdict |
|---|---|
| MCP server singleton (current) | Already optimal for server mode |
| CLI-as-MCP-client | **RECOMMENDED** for CLI latency |
| BentoML | Overkill — cloud deployment framework |
| LitServe | Overkill — full HTTP server framework |
| Triton | Requires ONNX export (violates mandate) |
| vLLM | Wrong model type (LLM serving) |
| subprocess pipes | Fragile lifecycle management |

## Model Loading Bottleneck

Disk caching (HuggingFace `~/.cache/`) already works. The expensive steps are:

1. Loading weights disk -> CPU (~1-2s)
2. Moving to GPU + compiling (~3-10s)
3. CUDA context allocation (~1-2s)

Only a resident process avoids steps 2-3.
