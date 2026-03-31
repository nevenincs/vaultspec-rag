# Persistent Model Daemon Patterns for Sub-Second CLI Latency

**Date**: 2026-03-08
**Task**: #26
**Status**: Complete

## Problem

Each CLI invocation (`vaultspec-rag search "query"`) loads three GPU models (Qwen3 dense + SPLADE sparse + CrossEncoder reranker) taking 5-15 seconds, then runs a 50ms query, then exits. The models are discarded. Next invocation pays the same cold-start cost.

## Architecture Options

### Option A: CLI-as-MCP-Client (RECOMMENDED)

Reuse the existing MCP server as the model daemon. The CLI becomes a thin MCP client.

**How it works**:

1. MCP server runs as a long-lived process (already exists)
2. CLI `search` command connects to running MCP server via streamable-http
3. Calls `search_vault` / `search_codebase` tool via MCP protocol
4. Falls back to in-process mode if server not running

**MCP client code** (from official python-sdk):

```python
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

async def mcp_search(query: str, top_k: int = 5) -> list[dict]:
    async with streamable_http_client("http://localhost:8000/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            result = await session.call_tool("search_vault", {
                "query": query, "top_k": top_k
            })
            return result
```

**CLI integration**:

```python
async def search_command(query, top_k, target):
    try:
        results = await mcp_search(query, top_k)  # ~50ms
    except (ConnectionRefusedError, OSError):
        # Server not running, fall back to cold start
        engine = get_engine(target)  # ~10s
        results = engine.searcher.search_vault(query, top_k)
```

**Pros**:

- Zero new infrastructure — MCP server already exists
- MCP protocol handles serialization, error reporting
- GPU semaphore already protects concurrent access
- Server already has model singleton (`get_comp()`)

**Cons**:

- Requires MCP server to be running (manual start or auto-start)
- HTTP overhead (~5-10ms) vs direct socket (~1ms) — negligible
- Need to configure server to listen on HTTP (currently stdio-only)

**Server-side change needed**: Run MCP server with streamable-http transport:

```python
# mcp_server.py
def main():
    mcp.run(transport="streamable-http", host="127.0.0.1", port=8000)
```

### Option B: Custom TCP Daemon

Dedicated daemon process that loads models and serves inference requests over localhost TCP.

```
vaultspec-rag daemon start    # loads models, listens on localhost:9876
vaultspec-rag search "query"  # connects to daemon, gets response
vaultspec-rag daemon stop     # graceful shutdown
```

**IPC options**:

- **localhost TCP** (recommended): Cross-platform, simple, ~5ms overhead
- **Unix domain socket**: Lower latency (~1ms) but Linux/macOS only
- **Windows named pipe**: Windows-native but requires platform-specific code

**Cross-platform strategy**: Use localhost TCP. It works everywhere and the latency difference (~4ms) is negligible for a CLI tool.

**Lifecycle management**:

- PID file at `~/.vaultspec-rag/daemon.pid`
- Health check endpoint (TCP ping)
- Auto-start on first CLI query if daemon not running
- Graceful shutdown on `daemon stop` or SIGTERM

**Pros**:

- Full control over protocol and lifecycle
- No MCP overhead

**Cons**:

- Duplicates what MCP server already does
- New code to write and maintain (daemon lifecycle, IPC protocol, error handling)
- PID file management, orphan process cleanup

### Option C: NVIDIA Persistence Daemon

`nvidia-persistenced` keeps GPU driver state initialized between applications. Reduces CUDA context creation from ~2s to ~100ms.

**Verdict**: Helpful supplement but doesn't solve the model loading problem (3-10s for weight transfer to GPU). Models still need to be loaded per-process. Only eliminates the CUDA driver init portion (~1-2s of the 5-15s total).

### Option D: vLLM Sleep Mode

vLLM's sleep mode keeps model weights in GPU memory but releases compute resources. Wake-up is 18-200x faster than cold start.

**Verdict**: vLLM is for LLM serving (autoregressive generation). Wrong model type — this project uses SentenceTransformer (encoder) and CrossEncoder (classifier), not generative LLMs.

## Recommendation

**Option A (CLI-as-MCP-Client)** is the clear winner:

1. **Already built**: MCP server exists, model singleton exists, GPU semaphore exists
2. **One change needed**: Add streamable-http transport option to server
3. **CLI change**: Add `mcp_search()` fast path with cold-start fallback
4. **Zero new dependencies**: `mcp` package already provides client SDK

**Implementation order**:

1. Add `--transport http` flag to `server mcp start` CLI command
2. Implement `mcp_search()` client function in CLI
3. Add connection retry + fallback logic
4. Optional: auto-start server if not running

## NVIDIA Persistence Daemon Note

Even with Option A, consider enabling `nvidia-persistenced` on development machines. It keeps the CUDA driver initialized between GPU applications, shaving ~1-2s off the first model load after GPU idle. This is orthogonal to the daemon pattern and helps all GPU workloads.

```bash
sudo systemctl enable nvidia-persistenced
sudo systemctl start nvidia-persistenced
```

On Windows, NVIDIA persistence mode is enabled by default via the NVIDIA driver service.
