---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S06'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# surface error_kind and stalled through the /jobs route, the server status summary, and /health

## Scope

- `src/vaultspec_rag/server/`

## Description

`/jobs` shaping gains `_job_stalled` (running, non-waiting, progress age past
the shared threshold) exposed as a `stalled` field per record and a `stalled`
count plus `error_kinds` histogram in the summary; `/health` gains a bounded
`jobs` rollup: running count, stalled count, and the most recent failure's
id/error_kind/finished_at.

## Outcome

Committed as `feat(server): service-domain stalled flag on /jobs and bounded jobs rollup on /health (#242)`; covered by `TestJobStallShaping` and
`TestHealthJobsRollup`.

## Notes
