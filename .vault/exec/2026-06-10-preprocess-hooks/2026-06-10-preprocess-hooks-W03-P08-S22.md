---
tags:
  - '#exec'
  - '#preprocess-hooks'
date: '2026-06-11'
modified: '2026-06-30'
step_id: 'S22'
related:
  - "[[2026-06-10-preprocess-hooks-plan]]"
---

# Carry preprocess status on FileChunkResult and accumulate counts in the orchestrator (D11)

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

`FileChunkResult` carries `preprocess_status`/`preprocess_reason` from the worker. The
orchestrator accumulates skips via `_record_preprocess_result()` at both result-inspection
sites - `_process_future` (pool) and `_run_serial_chunk_and_embed` (serial) - into
`self._prep_skips`. Every skip is also `logger.warning`-logged in the runner/worker, so no
gap is silent (D11, no-swallow mandate).

## Outcome

Full-index runs surface accurate skip counts + reasons. Incremental/scoped runs log skips
(visible in the service log) but do not yet populate the count field - a documented v1
limitation, since `chunk_file` returns only chunks.

## Notes

Incremental count surfacing is a follow-up; logging already prevents silent coverage loss.
