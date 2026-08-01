---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:04231ed19a0452d9175d88fb3848d735ce3ba7d490392974cd972a35dcd38b6d'
step_id: 'S11'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# enrich the jobs projection with the encode budget fields and a recent-rate-versus-run-median baseline

## Scope

- `src/vaultspec_rag/server/_routes_jobs.py`

## Description

- enrich the jobs projection in `src/vaultspec_rag/server/_routes_jobs.py` with the encode budget fields and a recent-rate-versus-run-median baseline (recent, median, ratio), bounded and computed from existing progress data

## Outcome

Commit `8d1be9d7`. Gates each exit 0; pytest 117 passed.

## Notes

None.
