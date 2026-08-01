---
tags:
  - '#exec'
  - '#service-graph'
date: '2026-04-02'
modified: '2026-07-27'
body_hash: 'sha256:d1c366d14bef194f44f70636b4f1aede908038f759a63d4c831c0927895cc34e'
related:
  - '[[2026-04-02-service-graph-phase1-plan]]'
---

# service-graph phase-1 step-1: graph cache unification (D3, R36-C1)

## Description

### Changes

- Renamed `_GraphCache` to `GraphCache` (public) in `api.py`, added TTL
  support (`_built_at`, `_ttl_seconds`, `_is_stale()`), double-check
  locking inside `get()` now also checks TTL expiry. `invalidate()`
  resets `_built_at` to 0.0. Exported from `__init__.py`.

- Added `graph_provider: Callable[[], VaultGraph | None] | None` parameter
  to `VaultSearcher.__init__` in `search.py`. When set, `_get_graph()`
  delegates entirely to it. When `None`, falls back to internal cache
  with `threading.Lock` + double-check + TTL (fixes R36-C1 for the
  fallback path too).

- Wired `GraphCache` into `_Engine` in `api.py`: creates per-engine
  instance, passes `graph_provider` lambda to `VaultSearcher`.
  `index()` and `get_related()` now use `engine.graph_cache`.

- Wired `GraphCache` into `mcp_server.py`: `get_comp()` creates a
  module-level `_graph_cache`, passes provider to `VaultSearcher`.
  `reindex_vault()` calls `_graph_cache.invalidate()` instead of
  `comp.searcher._graph_built_at = 0.0`.

- Updated `watcher.py`: added `graph_cache` parameter to
  `watch_and_reindex()`, prefers `graph_cache.invalidate()` over
  legacy `searcher._graph_built_at` poke. `_ensure_watcher()` in
  `mcp_server.py` passes `_graph_cache`.

- Updated 3 ADR regression tests that referenced `_GraphCache` or
  checked for `_graph_built_at` in source.

### Files modified

- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/search.py`
- `src/vaultspec_rag/mcp_server.py`
- `src/vaultspec_rag/watcher.py`
- `src/vaultspec_rag/__init__.py`
- `src/vaultspec_rag/tests/test_adr_regression.py`

### Files created

- `src/vaultspec_rag/tests/test_graph_cache.py` (10 tests)

## Outcome

### Test results

- 10/10 new `test_graph_cache.py` tests pass
- 230/230 unit tests pass (0 regressions)
- 0 ruff violations across all modified files

### Verification

- `GraphCache.get()` returns cached instance within TTL, rebuilds after expiry
- `GraphCache.invalidate()` forces rebuild on next `get()`
- Concurrent `get()` with 8 threads at TTL boundary: all threads get a result
- `VaultSearcher._get_graph()` delegates to provider when set
- `VaultSearcher._get_graph()` uses internal lock+TTL when provider is None
- Concurrent fallback with 4 threads: lock prevents parallel builds

## Notes

No separate notes is recorded in the retained prior execution record. Source: retained prior execution record body.
