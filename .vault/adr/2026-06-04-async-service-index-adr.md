---
tags:
  - '#adr'
  - '#async-service-index'
date: '2026-06-04'
related:
  - "[[2026-06-04-async-service-index-research]]"
---

# `async-service-index` adr: `asynchronous indexing and timeout-bounded searches` | (**status:** `accepted`)

## Problem Statement

During multi-agent shared-worktree execution, `vaultspec-rag` commands can degrade under resource contention:

1. **Asymmetric Blocking Reindexing (Issue #160)**: Service-delegated reindexing tool calls block the client CLI synchronously without providing progress feedback, appearing as a hang.
1. **Search Lock Contention & Timeouts (Issue #162)**: Concurrent local-store searches fail with `local_store_locked`, and service-routed searches can hang or timeout indefinitely due to lack of request boundaries. Stale processes are left orphaned.

## Considerations

- The CLI and MCP tools must remain completely on par; MCP tools are consumers of the backend.
- The resident service must execute long-running operations asynchronously to keep the HTTP transport responsive.
- Local Qdrant store access requires strict lock validation to prevent database corruption.

## Constraints

- Background tasks spawned in ASGI/HTTP server loops must not be garbage collected by Python before completion.
- Timeouts must be enforced on all service-delegated network calls to prevent orphaned processes.

## Implementation

- **Non-Blocking Reindexing**:
  - The `reindex_vault` and `reindex_codebase` MCP tools launch indexing tasks as background `asyncio.Task`s.
  - A global `_background_tasks` set maintains references to active tasks.
  - The tools immediately return a job start status with a `job_id`.
  - The CLI `index` command detects the async response and exits immediately with instructions.
- **Robustness & Timeout Boundaries**:
  - Enforce timeout boundaries on all `httpx` HTTP requests in the CLI MCP search/admin path.
  - Surface `VaultStoreLockedError` in the CLI `search` command as an actionable diagnostic recommending resident service delegation.

## Rationale

Decoupling the client CLI wait state from service execution prevents lock contention from cascading into system hangs. surfacing typed errors rather than silent blockages keeps multi-agent pipelines robust.

## Consequences

- **Gains**:
  - Fast-failing and clear diagnostics during Qdrant lock contention.
  - The CLI does not hang during service-bound reindexing.
  - Automatic cleanup of background tasks and prevention of orphaned processes.
- **Pitfalls**:
  - Test assertions must poll/wait for background jobs to finish rather than assuming inline completion.

## Codification candidates

- **Rule slug:** `mcp-tools-background-tasks`.
  **Rule:** Every MCP tool that launches a background task must retain a strong reference to the Task in a global collection to prevent Python garbage collection.
