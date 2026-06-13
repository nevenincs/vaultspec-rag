---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-04-12'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
  - '[[2026-04-12-store-eviction-log-rotation-adr]]'
---

# store-eviction-log-rotation phase-1 step-5

## goal

Delete the parallel `_Engine` cache in `api.py`, introduce
`registry.py` as the singleton holder for `ServiceRegistry`, and
rewrite every facade function to route through
`ServiceRegistry.lease`.

## files touched

- `src/vaultspec_rag/registry.py` (new)
- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/mcp_server.py`
- `src/vaultspec_rag/tests/test_adr_regression.py`

## what was done

- `registry.py` exposes `get_registry()` (double-checked locked
  singleton) and `reset_registry()` (for tests).
- `api.py` trimmed to the six facade functions (`index`,
  `index_codebase`, `search_vault`, `search_codebase`,
  `list_documents`, `get_related`), each opening a lease via
  `with get_registry().lease(root) as slot: ...`. `_Engine`,
  `_engine`, `_engine_lock`, `get_engine`, `reset_engine` are all
  deleted. `GraphCache` is still re-exported for `__init__.py`.
- `mcp_server.py` now initialises `_registry = get_registry()`
  instead of constructing its own `ServiceRegistry()`.
- `test_adr_regression.py`: `test_api_engine_lock_exists` rewritten
  as `test_registry_singleton_has_lock`; `TestPathResolveCache`
  updated to reference the registry instead of `_engine_lock`.

## test results

- `pytest src/vaultspec_rag/tests/ -m unit` -> 315 passed.
- `pytest src/vaultspec_rag/tests/integration/test_api_integration.py` -> 10 passed.
- `ruff check src/vaultspec_rag/` + `ty check src/vaultspec_rag`
  clean.
- Final sweep: `grep -rn "_engine\|_Engine\|get_engine\|reset_engine\|_engine_lock" src/vaultspec_rag/` -> 0 matches.

## deviations

None.

## commit hash

`027ccc6 refactor(api): collapse Engine cache into ServiceRegistry singleton`

## time spent

~20 minutes.
