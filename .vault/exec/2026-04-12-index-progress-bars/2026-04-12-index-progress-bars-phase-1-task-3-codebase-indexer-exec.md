---
tags:
  - '#exec'
  - '#index-progress-bars'
date: '2026-04-12'
modified: '2026-04-12'
related:
  - '[[2026-04-12-index-progress-bars-phase-1-plan]]'
---

# `index-progress-bars` `phase-1` `task-3-codebase-indexer`

Re-implement `CodebaseIndexer.full_index` and
`CodebaseIndexer.incremental_index` with the same required `reporter`
contract as the vault indexer.

- Modified: `src/vaultspec_rag/indexer.py`

## Description

Phase labels are keyed to the unit of work — `scan codebase`, `hash files`,
`chunk files`, `embed chunks (dense)`, `embed chunks (sparse)`,
`upsert chunks`, `delete removed`, `write metadata`. The chunk embed phases
advance against chunk count (not file count). The `ThreadPoolExecutor`
chunk consumer switched from `pool.map` to `pool.submit`/`future.result`
so per-file completion can drive `reporter.advance()` without blocking on
ordered iteration.

Both indexer modules and `embeddings.py` are verified free of `rich`
imports via grep; all Rich usage stays on the CLI side.

## Tests

Compile-verified by the unit suite; real phase invariants asserted in
the phase-6 counting integration test.
