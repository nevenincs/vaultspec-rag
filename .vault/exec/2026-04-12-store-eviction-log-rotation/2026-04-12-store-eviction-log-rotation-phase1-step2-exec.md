---
tags:
  - '#exec'
  - '#store-eviction-log-rotation'
date: 2026-04-12
modified: '2026-06-30'
related:
  - '[[2026-04-12-store-eviction-log-rotation-phase1-plan]]'
---

# store-eviction-log-rotation phase-1 step-2

## goal

Relocate `GraphCache` out of `api.py` into a dedicated
`graph_cache.py` module, updating all consumers and leaving a
re-export shim in `api.py` for this commit only.

## files touched

- `src/vaultspec_rag/graph_cache.py` (new)
- `src/vaultspec_rag/api.py`
- `src/vaultspec_rag/service.py`
- `src/vaultspec_rag/watcher.py`
- `src/vaultspec_rag/tests/test_graph_cache.py`
- `src/vaultspec_rag/tests/test_adr_regression.py`

## what was done

- Copied `GraphCache` verbatim into the new module with its docstrings,
  imports, TYPE_CHECKING block, and module logger.
- Deleted the class body from `api.py`, added
  `from .graph_cache import GraphCache` at the top, dropped the
  now-unused `time` import.
- Updated `service.py` and `watcher.py` (TYPE_CHECKING) to import
  from `.graph_cache`.
- Updated the two `test_adr_regression.py` import lines and the
  `test_graph_cache.py` top-level import.
- `__init__.py`'s `from .api import GraphCache` keeps working via
  the re-export, per the plan's step-2 constraint.

## test results

- `ruff check` clean on all six modified files.
- `ty check src/vaultspec_rag` clean.
- `pytest src/vaultspec_rag/tests/test_graph_cache.py src/vaultspec_rag/tests/test_adr_regression.py` -> 38 passed.

## deviations

None.

## commit hash

`1ffe84c refactor: relocate GraphCache to its own module`

## time spent

~10 minutes.
