---
tags:
  - '#research'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-06-04'
related: []
---

# `async-service-index` research: `asynchronous service indexing`

This research covers the implementation of asynchronous index/reindex tool execution (Issue #160) and mitigates search lock contention/timeouts during multi-agent concurrent execution (Issue #162).

## Findings

### 1. Asynchronous Reindexing (Issue #160)

- **Problem**: Delegating reindexing to a running service via the MCP tools (`reindex_vault` / `reindex_codebase`) blocks the HTTP connection and client CLI until completion. There is no progress feedback on the CLI client, leading it to appear hung.
- **Analysis**:
  - The CLI client calls the MCP server reindex tools synchronously using `asyncio.run()`.
  - The server MCP tools execute the indexers synchronously inside a leased slot.
- **Design Decision**:
  - Convert `reindex_vault` and `reindex_codebase` to return a job start acknowledgment dict (`{"ok": true, "job_id": "...", "status": "queued"}`) immediately.
  - Spawn the indexing operation in a background asyncio Task on the server.
  - Retain Task references globally to prevent garbage collection.
  - Update the client CLI (`_index.py`) to detect the background job ID, print the status, and exit immediately without blocking.

### 2. Search Lock Contention and Timeouts (Issue #162)

- **Problem**: When multiple concurrent processes/agents perform semantic search, direct local-store searches fail with `local_store_locked` (the Qdrant lock). Under network timeouts or slow model processing, service-routed searches can block/timeout indefinitely or leave hanging processes.
- **Analysis**:
  - `_try_mcp_search` uses `streamable_http_client` and `ClientSession` to perform MCP searches over HTTP, but has no timeout limits.
  - When direct local-store search encounters a locked Qdrant file, it raises `VaultStoreLockedError`.
- **Design Decision**:
  - Enforce a strict connection and read timeout on HTTP client requests in `_try_mcp_search` (e.g., using `httpx` timeouts or a custom async timeout).
  - Surface `local_store_locked` errors in the CLI search command with a clear, typed diagnostic advising the user to check/start the resident service on the designated port.
  - Ensure background job progress and service lifecycle checks return cleanly rather than hanging.
