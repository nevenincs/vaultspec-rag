---
tags:
  - '#exec'
  - '#service-graph'
date: '2026-04-02'
modified: '2026-07-27'
body_hash: 'sha256:c46ec617e8b7a2a05719bb8d2a856e0f1753f1293903561fee7d0ee6b0ead79a'
related:
  - '[[2026-04-02-service-graph-phase1-plan]]'
---

# service-graph phase-2 step-1: ServiceRegistry module

## Description

### Summary

Created `src/vaultspec_rag/service.py` with `ServiceRegistry` class and
`ProjectSlot` dataclass implementing decision D6 from the ADR.

### Changes

- **Created** `src/vaultspec_rag/service.py`:

  - `ProjectSlot` dataclass: `store`, `searcher`, `vault_indexer`,
    `code_indexer`, `graph_cache`
  - `ServiceRegistry` class with `threading.Lock` guarding `_projects`
  - `load_model(model_name=None)` â€” eager GPU model loading, idempotent
  - `model` property â€” raises `RuntimeError` if not loaded
  - `get_project(root)` â€” lazy per-project init with double-check lock
    pattern; creates `VaultStore`, `GraphCache` (config TTL),
    `VaultSearcher` (with `graph_provider=lambda: gc.get(root)`),
    `VaultIndexer`, `CodebaseIndexer`; reuses shared `_model`
  - `close_project(root)` â€” close store, remove from dict
  - `close_all()` â€” close all stores, set model to None
  - `health()` â€” returns `model_loaded`, `project_count`, `projects`

- **Created** `src/vaultspec_rag/tests/test_service_registry.py`:

  - 13 tests across 7 test classes
  - `TestLoadModel` (2): idempotent load, raises before load
  - `TestGetProject` (3): creates components, returns same slot,
    searcher uses shared model
  - `TestMultiProject` (1): two roots share one EmbeddingModel
    (object identity), different stores and graph caches
  - `TestCloseProject` (3): removes from dict, closes store, safe
    on nonexistent
  - `TestCloseAll` (1): clears all state (uses separate registry
    to avoid corrupting shared fixture)
  - `TestHealth` (2): before load, with project
  - `TestConcurrency` (1): 4 threads concurrent `get_project()` on
    same root â€” all get same `ProjectSlot`

## Outcome

### Test results

- 13/13 tests pass (`HF_HUB_OFFLINE=1` required â€” SPLADE v3 is gated,
  no HF_TOKEN configured in this environment)
- 10/10 existing graph cache tests pass (no regressions)
- `ruff check` and `ruff format --check` clean on both files

## Notes

- `api.py` public API unchanged â€” `_Engine` and `get_engine()` remain
  as-is per the plan (full delegation to `ServiceRegistry` deferred to
  Phase 3 when `mcp_server.py` is refactored)
- `ServiceRegistry` is importable but not yet wired into any entry point
- Environment needs `HF_TOKEN` or `HF_HUB_OFFLINE=1` for SPLADE v3
  gated model access
