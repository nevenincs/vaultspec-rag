---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-11'
step_id: 'S10'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Wire clean rebuild rmtree of the cache subtree into the codebase indexer clean path (D7)

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

Wired `_clear_preprocess_cache()` into the `clean=True` branch of `_full_index_locked`,
beside `store.drop_code_table()`, so a clean rebuild drops the preprocess cache subtree
along with the collection (D7). Stored `self._data_root = root_dir / cfg.data_dir` in
`__init__` for reuse; the helper calls `clear_preprocess_cache(preprocess_cache_dir(...))`.

## Outcome

Clean rebuild now starts cold; incremental runs leave (harmless, bounded) orphans.
basedpyright zero on the indexer.

## Notes

Incremental orphan sweep is deliberately deferred; clean rebuild is the reset path.
