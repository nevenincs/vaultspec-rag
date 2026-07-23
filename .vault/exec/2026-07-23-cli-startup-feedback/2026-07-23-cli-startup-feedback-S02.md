---
tags:
  - '#exec'
  - '#cli-startup-feedback'
date: '2026-07-23'
modified: '2026-07-23'
step_id: 'S02'
related:
  - "[[2026-07-23-cli-startup-feedback-plan]]"
---

# Publish the structured descriptor at each cold-start stage boundary, filling done/total for the model-load count

## Scope

- `src/vaultspec_rag/server/_lifespan.py`

## Description

- In `_start_components`, computed the model total (three with the reranker enabled, otherwise two) and published `done=0`/`total` before `load_model`, then `done=2`/`total` before the reranker load.

## Outcome

The model-load stage now carries a determinate `N of M` count the start spinner renders.

## Notes

The count is milestone-granular: `load_model` brings up the dense and sparse encoders in one call, so `done` steps 0 -> 2 -> (3), not per-model. Finer per-model or per-byte progress depends on the downloader-callback question investigated in `S04`.
