---
tags:
  - '#exec'
  - '#storage-namespace-hygiene'
date: '2026-07-14'
modified: '2026-07-19'
step_id: 'S03'
related:
  - "[[2026-07-14-storage-namespace-hygiene-plan]]"
---

# Wire the warmer task into lifespan startup and shutdown alongside the maintenance task

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- Create the `_survey_warmup_task` in `_start_components` (`src/vaultspec_rag/server/_lifespan.py`), gated on `effective_server_mode` only - deliberately NOT on the autoprune knob, since the survey route serves from the snapshot regardless of scheduled reclamation
- Append it to the periodic-task list so `_shutdown_components` cancels it uniformly

## Outcome

The warmer runs once per daemon lifetime and is torn down through the existing cancel-and-await path. Commit 7ae79ca.

## Notes

Cancelling an already-completed one-shot task is a no-op, so no special-casing was needed.
