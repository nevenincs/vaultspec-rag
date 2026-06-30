---
tags:
  - '#exec'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-30'
step_id: 'S03'
related:
  - "[[2026-06-02-index-perf-hardening-plan]]"
---

# Apply the same process-pool chunking to the incremental and scoped-incremental paths

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Apply the same process-pool chunking helper to the incremental and scoped-incremental paths.

## Outcome

All three index paths share one parallel chunk primitive.

## Notes

None.
