# MCP Streamable-HTTP Client API Verification — 2026-03-08

**Research Topic 17**: Verify the CLI's MCP HTTP client implementation against the actual MCP SDK API.

**Status**: VERIFIED CORRECT ✅ — All 6 implementation points match the SDK.

---

## Verification Results

### 1. Import Path

**Code**: `from mcp.client.streamable_http import streamable_http_client`

**Verification**: ✅ CORRECT

The function is correctly named `streamable_http_client` (with underscores). The SDK also exports a legacy function `streamablehttp_client` (no underscores), but the current code uses the correct modern name.

**MCP SDK version**: Confirmed in installed site-packages at `mcp/client/streamable_http.py`

---

### 2. Context Manager Signature

**Code**:

```python
async with streamable_http_client(url) as (read, write, _):
```

**Verification**: ✅ CORRECT

Signature from MCP SDK:

```python
@asynccontextmanager
async def streamable_http_client(
    url: str,
    *,
    http_client: httpx.AsyncClient | None = None,
    terminate_on_close: bool = True,
) -> AsyncGenerator[
    tuple[
        MemoryObjectReceiveStream[SessionMessage | Exception],
        MemoryObjectSendStream[SessionMessage],
        GetSessionIdCallback,
    ],
    None,
]:
```

Returns exactly `(read_stream, write_stream, get_session_id_callback)` as a tuple. The code correctly unpacks as `(read, write, _)` and ignores the third callback.

---

### 3. ClientSession API

**Code**:

```python
ClientSession(read, write) as session
await session.initialize()
```

**Verification**: ✅ CORRECT

**Signature**:

```python
ClientSession.__init__(
    self,
    read_stream: MemoryObjectReceiveStream[SessionMessage | Exception],
    write_stream: MemoryObjectSendStream[SessionMessage],
    [... optional callbacks and settings ...]
) -> None
```

✅ `ClientSession(read, write)` — positional args in correct order.
✅ `await session.initialize()` — this is the correct async initialization method.

---

### 4. call_tool Return Type

**Code**:

```python
result = await session.call_tool(tool_name, {"query": query, "top_k": top_k})
if result.content:
    data = json.loads(result.content[0].text)
```

**Verification**: ✅ CORRECT

**Return type**: `CallToolResult`

**Structure**:

```python
class CallToolResult(Result):
    """The server's response to a tool call."""
    content: list[ContentBlock]        # ← result.content ✅
    structuredContent: dict[str, Any] | None = None
    isError: bool = False              # ← also available for error checking
```

**ContentBlock type**: Union of `TextContent | ImageContent | AudioContent | ResourceLink | EmbeddedResource`

**TextContent** (the typical case):

```python
class TextContent(BaseModel):
    type: Literal["text"]
    text: str                          # ← result.content[0].text ✅
    annotations: Annotations | None = None
```

✅ `result.content` is a list of `ContentBlock` objects.
✅ `result.content[0].text` is the correct way to get the text from a text-typed content block.
✅ `result.isError` is available to check if the tool call failed.

---

### 5. URL Path — `/mcp` is Correct

**Code**: `url = f"http://127.0.0.1:{port}/mcp"`

**Verification**: ✅ CORRECT

**FastMCP default**: `streamable_http_path: str = '/mcp'` (from `FastMCP.__init__` signature)

This is the default routing path for StreamableHTTP transport. When the MCP server is started with `transport="streamable-http"`, FastMCP creates a Starlette app with a route at this path. The client connects to `http://localhost:8000/mcp` (or whatever port) and receives the StreamableHTTP ASGI handler.

**Note**: The server runs uvicorn on the configured host/port, and the `/mcp` path is where the actual StreamableHTTP protocol endpoint lives.

---

### 6. asyncio.run() Safety in Typer Sync Handler

**Code**:

```python
def _try_mcp_search(query: str, ...) -> list[dict[str, object]] | None:
    import asyncio

    async def _call() -> list[dict[str, object]] | None:
        # ... async work ...

    try:
        return asyncio.run(_call())
    except Exception:
        return None
```

**Verification**: ✅ CORRECT

✅ Calling `asyncio.run()` from a sync Typer command handler is safe.

- `asyncio.run()` creates a new event loop, runs the coroutine to completion, and closes the loop.
- This is the standard pattern for calling async code from sync contexts.
- Typer does NOT automatically create an event loop for sync handlers — you must use `asyncio.run()` or similar.
- No conflict with FastMCP's internal `anyio.run()` in the server — they're in different processes (CLI is client, MCP server is separate process).

**Tested**: Confirmed that `asyncio.run()` works correctly in a sync function context (no RuntimeError).

---

## Summary for Orchestrator

**All 6 verification points PASS.**

The CLI's MCP streamable HTTP client implementation (`src/vaultspec_rag/cli.py` lines ~270–410) correctly uses:

- Import path: `streamable_http_client` ✅
- Context manager unpacking: `(read, write, _)` ✅
- ClientSession positional init: `(read, write)` + `await initialize()` ✅
- Result access: `result.content[0].text` ✅
- Endpoint path: `/mcp` ✅
- asyncio.run() safety: OK ✅

**Recommendation**: No changes needed. The implementation is correct and ready for use.

---

## Research Context

### Files Examined

- `src/vaultspec_rag/cli.py` lines 270–410 (two implementations: `_try_mcp_index`, `_try_mcp_search`)
- MCP SDK source: `mcp.client.streamable_http.streamable_http_client`
- MCP SDK source: `mcp.client.session.ClientSession`
- MCP SDK types: `mcp.types.CallToolResult`, `mcp.types.TextContent`, `mcp.types.ContentBlock`
- FastMCP server: `mcp.server.fastmcp.FastMCP.__init__` (default `streamable_http_path='/mcp'`)

### No Prior Issues Found

- No existing research docs reference MCP client API.
- No alternate implementation in `mcp_client.py` (doesn't exist).
- Stack uses the modern `streamable_http_client` (not legacy `streamablehttp_client`).

---

**Written**: 2026-03-08
**Verified against**: MCP SDK installed in `.venv`
