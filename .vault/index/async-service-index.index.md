---
generated: true
tags:
  - '#index'
  - '#async-service-index'
date: '2026-06-08'
modified: '2026-06-30'
related:
  - '[[2026-06-04-async-service-index-W01-P01-S01]]'
  - '[[2026-06-04-async-service-index-W01-P01-S02]]'
  - '[[2026-06-04-async-service-index-W01-P02-S03]]'
  - '[[2026-06-04-async-service-index-W01-P02-S04]]'
  - '[[2026-06-04-async-service-index-W01-P02-S05]]'
  - '[[2026-06-04-async-service-index-W01-P02-S06]]'
  - '[[2026-06-04-async-service-index-W02-P03-S07]]'
  - '[[2026-06-04-async-service-index-W02-P03-S08]]'
  - '[[2026-06-04-async-service-index-W02-P03-S09]]'
  - '[[2026-06-04-async-service-index-W02-P03-S10]]'
  - '[[2026-06-04-async-service-index-W03-P04-S11]]'
  - '[[2026-06-04-async-service-index-W03-P04-S12]]'
  - '[[2026-06-04-async-service-index-W03-P04-S13]]'
  - '[[2026-06-04-async-service-index-W03-P04-S14]]'
  - '[[2026-06-04-async-service-index-W03-P04-S15]]'
  - '[[2026-06-04-async-service-index-W03-P04-S16]]'
  - '[[2026-06-04-async-service-index-W03-P04-S17]]'
  - '[[2026-06-04-async-service-index-adr]]'
  - '[[2026-06-04-async-service-index-plan]]'
  - '[[2026-06-04-async-service-index-research]]'
---

# `async-service-index` feature index

Auto-generated index of all documents tagged with `#async-service-index`.

## Documents

### adr

- `2026-06-04-async-service-index-adr` - `async-service-index` adr: `asynchronous indexing and timeout-bounded searches` | (**status:** `accepted`)

### exec

- `2026-06-04-async-service-index-W01-P01-S01` - launch indexers as background asyncio tasks returning queue status
- `2026-06-04-async-service-index-W01-P01-S02` - maintain strong task references to prevent python garbage collection
- `2026-06-04-async-service-index-W01-P02-S03` - parse background queue payload and exit CLI client immediately
- `2026-06-04-async-service-index-W01-P02-S04` - adapt test assertions to poll for background job completion in jobs registry
- `2026-06-04-async-service-index-W01-P02-S05` - adapt test assertions to poll for background job completion in service lifecycle
- `2026-06-04-async-service-index-W01-P02-S06` - adapt test assertions to poll for background job completion in service metrics
- `2026-06-04-async-service-index-W02-P03-S07` - enforce connection and read timeouts on service-delegated client requests
- `2026-06-04-async-service-index-W02-P03-S08` - catch VaultStoreLockedError and surface actionable diagnostics with port/service remedy
- `2026-06-04-async-service-index-W02-P03-S09` - add regression tests for lock-store direct search failures
- `2026-06-04-async-service-index-W02-P03-S10` - add regression tests for service-route timeout behavior
- `2026-06-04-async-service-index-W03-P04-S11` - Move background task registry and asyncio create_task execution into a new backend module
- `2026-06-04-async-service-index-W03-P04-S12` - Refactor MCP tool handlers to act as thin transport delegates calling the new backend API
- `2026-06-04-async-service-index-W03-P04-S13` - Update watcher to import the jobs registry from the backend module
- `2026-06-04-async-service-index-W03-P04-S14` - Refactor in-process search CLI to use public backend API search functions
- `2026-06-04-async-service-index-W03-P04-S15` - Refactor MCP search tools to consume public backend search API
- `2026-06-04-async-service-index-W03-P04-S16` - Expose database clean/wipe and engine status as backend API functions
- `2026-06-04-async-service-index-W03-P04-S17` - Refactor clean and status commands/tools in CLI and MCP to delegate to backend

### plan

- `2026-06-04-async-service-index-plan` - `async-service-index` `Asynchronous Reindexing and Search Robustness` plan

### research

- `2026-06-04-async-service-index-research` - `async-service-index` research: `asynchronous service indexing`
