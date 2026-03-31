# FastMCP Server Configuration and Workspace Root Patterns

**Date**: 2026-03-08
**Task**: #22
**Status**: Complete

## Problem

The MCP server (`mcp_server.py`) determines workspace root via:
```python
root_env = os.environ.get("VAULTSPEC_ROOT")
root_dir = Path(root_env) if root_env else Path.cwd()
```

This has two issues:
1. Falls back to `Path.cwd()` which depends on how the MCP server process is launched
2. Does not use the MCP roots protocol, which is the proper way for clients to communicate workspace paths

## MCP Roots Protocol

The MCP specification defines a `roots` capability where:
- **Clients** declare `roots` capability during initialization
- **Servers** call `list_roots()` to discover workspace paths
- Roots are URIs (typically `file:///path/to/workspace`)
- Clients can notify servers when roots change via `roots/list_changed`

### How to use in FastMCP

The `Context` object (injected via type hints) provides `list_roots()`:

```python
from mcp.server.fastmcp import FastMCP, Context

mcp = FastMCP("VaultSpec Search")

@mcp.tool()
async def search_vault(query: str, ctx: Context) -> SearchResponse:
    roots = await ctx.list_roots()
    # roots is a list of Root objects with .uri and .name
    if roots:
        root_dir = Path(urlparse(roots[0].uri).path)
    else:
        root_dir = Path(os.environ.get("VAULTSPEC_ROOT", "."))
```

**Caveat**: Not all MCP clients support roots. Claude Desktop does, but other clients may not. The server must handle the case where `list_roots()` returns empty or raises.

## FastMCP Lifespan Pattern

For one-time initialization (like loading GPU models), FastMCP provides a lifespan decorator:

```python
from fastmcp import FastMCP
from fastmcp.server.lifespan import lifespan

@lifespan
async def app_lifespan(server):
    # Startup: load models once
    model = EmbeddingModel()
    store = VaultStore(root_dir)
    try:
        yield {"model": model, "store": store}
    finally:
        # Shutdown: cleanup
        store.close()

mcp = FastMCP("VaultSpec Search", lifespan=app_lifespan)

@mcp.tool()
async def search_vault(query: str, ctx: Context):
    model = ctx.lifespan_context["model"]
    # ... use model
```

**Key details**:
- `lifespan` runs once at server start, not per-request
- Yielded dict becomes `ctx.lifespan_context` in tools
- Always use try/finally for cleanup
- Type-safe: can use a dataclass instead of dict

## FastMCP vs mcp.server.fastmcp

**Important version distinction**:
- `from mcp.server.fastmcp import FastMCP` — official MCP SDK's built-in FastMCP (v1.0-based)
- `from fastmcp import FastMCP` — standalone FastMCP package (v2.0+/v3.0+, more features)

The project currently uses `from mcp.server.fastmcp import FastMCP` (the SDK-bundled version). This version:
- Has `Context` injection for tools
- Supports `list_roots()` via context
- Does NOT have the `@lifespan` decorator (that's FastMCP v2+)
- Uses `mcp.run()` for server startup

If the project upgrades to standalone FastMCP, it gains lifespan, dependency injection, and more configuration options. But the SDK-bundled version is sufficient for current needs.

## Recommendation

### Short term (current architecture)
Keep `VAULTSPEC_ROOT` env var as primary configuration. This is the simplest and most portable approach — works with all MCP clients and non-MCP CLI usage.

### Medium term (if workspace flexibility needed)
Add roots protocol support as a fallback chain:
1. Check `VAULTSPEC_ROOT` env var (explicit override)
2. Try `ctx.list_roots()` for MCP-protocol workspace discovery
3. Fall back to `Path.cwd()`

### Long term (if component lifecycle matters)
Consider upgrading to standalone FastMCP for lifespan support, which would cleanly separate model initialization from request handling and provide proper startup/shutdown lifecycle.

## Current Architecture Assessment

The current `get_comp()` pattern with `_comp_lock` is functionally equivalent to a lifespan — it initializes once and caches. The main difference is:
- Lifespan: initialized at server start, before any requests
- get_comp(): initialized lazily on first request

Lazy initialization is actually better for the current use case — it avoids blocking server startup on GPU model loading (5-15s). The server starts instantly and the first request triggers initialization.
