---
tags:
  - '#exec'
  - '#storage-autoprune-safety'
date: '2026-07-14'
modified: '2026-07-14'
body_hash: 'sha256:89f416ef351bc4e836b36e060186d8bbc25711cdb4697044be045f5c35550873'
step_id: 'S07'
related:
  - "[[2026-07-14-storage-autoprune-safety-plan]]"
---

# Register each cycle in the jobs registry with source maintenance and trigger schedule, and export the rollup gauges (disk free, namespace counts by status, dangling bytes, pending-grace counts) through /metrics and server status

## Scope

- `src/vaultspec_rag/jobs.py`

## Description

- Widen the jobs taxonomy: `Source` gains `maintenance`, `Trigger` gains
  `schedule`, so cycles are first-class records in `server jobs` and the
  `/jobs` route.
- Register each cycle with `record_start("maintenance", "schedule", command="storage_maintenance")` and finish it with a one-line summary
  (`error` phase when any reclaim failed; exception path finishes the
  record before re-raising into the loop's catch).
- Add the rollup metrics to the inline holder rendered by `/metrics`:
  counters `maintenance_cycles_total` / `maintenance_reclaims_total`,
  gauges disk-free, dangling bytes, pending grace, orphaned namespaces,
  last reclaimed bytes - refreshed inline by the tick, never a collector.

## Outcome

134 server + jobs unit tests pass; ruff, ruff format, and basedpyright
clean.

## Notes

`server status` visibility rides the jobs registry (the cycle appears in
the operational jobs block status already renders) rather than a bespoke
status field; the /metrics gauges carry the numeric rollup.
