---
tags:
  - '#reference'
  - '#job-failure-health'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:f079c81310b8bff20f47b7e8ec96a512042d009ecaf03f30d7fdd19dea672f32'
related: []
---

# `job-failure-health` reference: `how service health selects and clears job failures`

Read on branch `nevenincs/rag-backlog-fixes` on 2026-11-20. Sources: the health route's
job rollup, the job projection helpers, and the CLI status renderers. The live
observation below came from the coordinating session and was not re-measured here.

## Summary

**Selection.** `_jobs_health` (`src/vaultspec_rag/server/_lifespan.py:1260`) picks one
record: the newest `failed` record across every project that is not a
`full_reindex_required` refusal (`:1278-1285`). `_latest_job_record` (`:1098`) orders
by `job_updated_timestamp` (`src/vaultspec_rag/server/_routes_jobs.py:209`), which takes
the newest of progress, state change, finish, start and create stamps.

**Degrading.** The selected failure degrades health with `JOB_FAILED` only when two
checks pass (`:1347-1358`):

- `_failure_belongs_to_this_generation` (`:1177`): the failure finished at or after the
  daemon's generation start. A missing stamp counts as current.
- `not _failure_was_superseded` (`:1204`): no `succeeded` record with the same source
  and normalized project root (`:1230-1232`) is newer. The check is quadratic in the
  record count.

Nothing else clears it. A later `cancelled` or `interrupted` run on the same key leaves
it in place. No age limit applies inside a generation. Interrupted runs are excluded from
selection by design, as the comment at `:1268-1277` explains.

**Hidden failures.** Because only the newest failure is examined, an older failure on
another project is never evaluated. If the newest failure is superseded, health reads
clean even when an older one on another project is unresolved.

**Payload.** `jobs.last_failed` (`:1320`) carries `id`, `source`, `project_root`,
`error_kind` and `finished_at` from `_failed_job_health` (`:1112`). `jobs` is an open
mapping on the typed `HealthReport` (`src/vaultspec_rag/operator_state/_models.py:136`).
The `JOB_FAILED` label is "the latest indexing job failed"
(`src/vaultspec_rag/operator_state/_service.py:171`).

**Precedent for a bounded named list.** Stale watcher roots name up to
`_STALE_ROOTS_NAMED = 5` roots and count the rest
(`src/vaultspec_rag/server/_lifespan.py:1363-1380`).

**CLI consumers.** `src/vaultspec_rag/cli/_status_labels.py:409-496` reads
`jobs.last_failed` to name the job, its age, and a rebuild or logs remedy.
`_HISTORICAL_FAMILIES` (`:392`) stops the CLI promoting `job_failed` unless the service
emitted it. `_failure_followup` (`src/vaultspec_rag/cli/_status_render.py:814`) names
the latest failure when the degraded block did not. No MCP tool exposes `/health` job
failures; `get_index_status` returns the service-state report
(`src/vaultspec_rag/mcp/_tools.py:710`).

**Tests touching this path.** `src/vaultspec_rag/tests/test_health_degraded_clears.py`,
`src/vaultspec_rag/tests/test_cli_service_status.py`,
`src/vaultspec_rag/tests/test_job_manager_degradation.py`,
`src/vaultspec_rag/tests/integration/test_service_jobs_resilience.py`.

**Live observation (reported, not re-measured).** One failed job held health at
`degraded` for 16 hours while other jobs succeeded. The registry held 69 failed jobs.
