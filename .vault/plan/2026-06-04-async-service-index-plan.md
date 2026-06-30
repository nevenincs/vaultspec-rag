---
tags:
  - '#plan'
  - '#async-service-index'
date: '2026-06-04'
modified: '2026-06-30'
tier: L3
related:
  - '[[2026-06-04-async-service-index-adr]]'
  - '[[2026-06-04-async-service-index-research]]'
---

# `async-service-index` `Asynchronous Reindexing and Search Robustness` plan

## Wave `W01` - Asynchronous Reindexing and Daemon Performance

Implement async background reindexing on the daemon, update the CLI client, and adapt test assertions.

### Phase `W01.P01` - MCP Async Backend

Enable background asyncio tasks on the MCP server reindexing tools

- [x] `W01.P01.S01` - launch indexers as background asyncio tasks returning queue status; `src/vaultspec_rag/mcp_server/_tools.py`.
- [x] `W01.P01.S02` - maintain strong task references to prevent python garbage collection; `src/vaultspec_rag/mcp_server/_tools.py`.

### Phase `W01.P02` - CLI Non-Blocking Exit

Update the CLI client to exit immediately on background job queuing

- [x] `W01.P02.S03` - parse background queue payload and exit CLI client immediately; `src/vaultspec_rag/cli/_index.py`.
- [x] `W01.P02.S04` - adapt test assertions to poll for background job completion in jobs registry; `src/vaultspec_rag/tests/integration/test_jobs_registry.py`.
- [x] `W01.P02.S05` - adapt test assertions to poll for background job completion in service lifecycle; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.
- [x] `W01.P02.S06` - adapt test assertions to poll for background job completion in service metrics; `src/vaultspec_rag/tests/integration/test_service_metrics.py`.

## Wave `W02` - Search Lock Contention and Request Timeout Boundaries

Enforce connection/read request timeouts on service-delegated searches, surface typed diagnostics for local locked-store errors, and add coverage.

### Phase `W02.P03` - Timeout Bounds and Lock Fail-Fast

Implement HTTP request timeouts and surface local Qdrant lock errors

- [x] `W02.P03.S07` - enforce connection and read timeouts on service-delegated client requests; `src/vaultspec_rag/cli/_mcp_search.py`.
- [x] `W02.P03.S08` - catch VaultStoreLockedError and surface actionable diagnostics with port/service remedy; `src/vaultspec_rag/cli/_search.py`.
- [x] `W02.P03.S09` - add regression tests for lock-store direct search failures; `src/vaultspec_rag/tests/test_cli.py`.
- [x] `W02.P03.S10` - add regression tests for service-route timeout behavior; `src/vaultspec_rag/tests/test_cli.py`.

## Wave `W03` - Backend-Agnostic Refactoring

Refactor reindexing background task management and jobs registry into the core backend library, keeping transport/wrapper layers thin.

### Phase `W03.P04` - Backend-Agnostic Task Scheduling

Move the jobs registry and background task execution routines into the core library, converting MCP tool handlers into thin delegates.

- [x] `W03.P04.S11` - Move background task registry and asyncio create_task execution into a new backend module; `src/vaultspec_rag/jobs.py`.
- [x] `W03.P04.S12` - Refactor MCP tool handlers to act as thin transport delegates calling the new backend API; `src/vaultspec_rag/mcp_server/_tools.py`.
- [x] `W03.P04.S13` - Update watcher to import the jobs registry from the backend module; `src/vaultspec_rag/watcher.py`.
- [x] `W03.P04.S14` - Refactor in-process search CLI to use public backend API search functions; `src/vaultspec_rag/cli/_search.py`.
- [x] `W03.P04.S15` - Refactor MCP search tools to consume public backend search API; `src/vaultspec_rag/mcp_server/_tools.py`.
- [x] `W03.P04.S16` - Expose database clean/wipe and engine status as backend API functions; `src/vaultspec_rag/api.py`.
- [x] `W03.P04.S17` - Refactor clean and status commands/tools in CLI and MCP to delegate to backend; `src/vaultspec_rag/cli/_status.py`.

## Description

This plan implements asynchronous background reindexing on the RAG resident service, allowing the client CLI to run the `index` command without blocking or timing out (Issue #160). It also addresses search lock contention and request timeouts during multi-agent concurrent execution on Windows shared-worktrees by enforcing request timeouts on service-delegated calls and fail-fast diagnostics on Qdrant database lock conflicts (Issue #162).

## Steps

## Parallelization

Waves `W01` and `W02` must be executed sequentially, as Wave `W02` builds on the robust service-delegated path and testing infrastructure developed in Wave `W01`. Within Wave `W01`, Phase `W01.P01` (backend) must complete before Phase `W01.P02` (frontend/CLI client integration). Steps within Phase `W01.P02` for updating different integration tests can be run in parallel. Within Wave `W02`, Phase `W02.P03` steps must be executed sequentially.

## Verification

- `just test` (or `pytest`) runs to completion with all integration tests passing.
- Direct local-store search processes do not block or leak during locked store scenarios; they exit with a typed diagnostic.
- Service-routed searches do not hang indefinitely and respect connection/read timeouts.
- Background reindex requests immediately return a queued payload and the client CLI exits successfully.
- No linter errors (checked via `ruff check` and `ruff format --check`).
