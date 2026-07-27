---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-27'
step_id: 'S07'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---
# render the shared error_kind and stalled fields in server jobs and server status output via one shared remediation mapping, removing the CLI-local disk-full string match

## Description

### Scope

- `src/vaultspec_rag/cli/_service_jobs.py`

The CLI now renders from the shared taxonomy: `_stale_progress_label` prefers
the service-computed `stalled` flag (age fallback only for older services),
the local threshold aliases `STALL_THRESHOLD_SECONDS`, and the disk-full
string match is replaced by `remediation(classify_error_text(...))` so the
CLI never grows its own error matching again. `server status` inherits both
via the shared helpers.

## Outcome

Committed as `refactor(cli): render jobs errors and stall from the shared service taxonomy (#242)`; existing CLI rendering suites stay green.

## Notes

Evidence gap: the original record contains no Notes section with authored incident, deferred-work, or follow-up evidence.
