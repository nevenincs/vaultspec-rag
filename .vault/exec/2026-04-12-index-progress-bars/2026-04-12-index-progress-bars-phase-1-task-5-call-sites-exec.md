---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-04-12'
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
---

# `index-progress-bars` `phase-1` `task-5-call-sites`

Update every in-tree call site of `full_index` / `incremental_index` to
pass the required `reporter` keyword argument.

- Modified: `src/vaultspec_rag/api.py`
- Modified: `src/vaultspec_rag/mcp_server.py`
- Modified: `src/vaultspec_rag/watcher.py`
- Modified: `src/vaultspec_rag/tests/conftest.py`
- Modified: `src/vaultspec_rag/tests/integration/conftest.py`
- Modified: `src/vaultspec_rag/tests/integration/test_api_integration.py`
- Modified: `src/vaultspec_rag/tests/integration/test_codebase_integration.py`
- Modified: `src/vaultspec_rag/tests/integration/test_indexer_integration.py`
- Modified: `src/vaultspec_rag/tests/integration/test_performance.py`
- Modified: `src/vaultspec_rag/tests/test_service_registry.py`
- Modified: `src/vaultspec_rag/tests/benchmarks/bench_rag.py`

## Description

`api.py` keeps its public ergonomics: `index` and `index_codebase` accept
an optional `reporter` parameter and construct a `NullProgressReporter`
internally when the caller omits it — the one exception sanctioned by
the ADR for the facade layer. Every other call site threads a
`NullProgressReporter` explicitly:

- `mcp_server.py` — MCP tool handlers have no terminal.
- `watcher.py` — background debounced rebuilds; the `anyio.to_thread.run_sync`
  call is wrapped in a `lambda` so the kwarg survives.
- Test fixtures and benchmark call sites all pass `NullProgressReporter`;
  the phase-6 integration test uses a dedicated `CountingProgressReporter`.

`service.py` does not call the indexer entry points directly (verified by
grep); it mediates via `slot.vault_indexer` / `slot.code_indexer` which
are exercised from `mcp_server.py` and tests, both already updated.

## Tests

Full unit suite (329 tests, excluding pre-existing GPU-gated
`test_service_registry.py` / `test_store_codebase.py` fixtures that
require `HF_TOKEN`) green. Ruff check and format pass for the entire
package.
