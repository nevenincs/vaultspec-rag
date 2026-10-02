---
tags:
  - '#exec'
  - '#service-graph'
date: '2026-04-02'
modified: '2026-09-30'
body_hash: 'sha256:389a914ab6fcaf83d7783e7e14f993eddd1a19a9d422646f93d5615eb374a98d'
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

- 13/13 tests pass (offline cached artifacts were used in this historical run)
- 10/10 existing graph cache tests pass (no regressions)
- `ruff check` and `ruff format --check` clean on both files

## Notes

- `api.py` public API unchanged â€” `_Engine` and `get_engine()` remain
  as-is per the plan (full delegation to `ServiceRegistry` deferred to
  Phase 3 when `mcp_server.py` is refactored)
- `ServiceRegistry` is importable but not yet wired into any entry point
- The historical run depended on available cached model artifacts.
