---
tags:
  - '#reference'
  - '#job-admission-visibility'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:50d38bf50975c689cf72e0b0cc9445dcc19eb185cd169214d21c4ee9376afc65'
related: []
---

# `job-admission-visibility` reference: `how admission waits are queued, ordered and reported`

Read on branch `nevenincs/rag-backlog-fixes` on 2026-11-20, with anyio 4.16.0 installed.
Sources: the capacity limiters, the job manager's attempt runner, the job projection
and filters, and the CLI jobs adapters.

## Summary

**Slots.** `get_encode_limiter` (`src/vaultspec_rag/concurrency.py:76-90`) is one
in-process token (`_ENCODE_ADMISSION_SLOTS = 1`, `:35-39`). `_attempt_limiter`
(`src/vaultspec_rag/job_manager/_execution.py:686-706`) gives encode-bearing jobs the
encode limiter and every other managed job the index limiter. `limiter_stats`
(`src/vaultspec_rag/concurrency.py:111-121`) reports only token totals and a waiter
count.

**Wait loop.** `_run_attempt` (`src/vaultspec_rag/job_manager/_execution.py:584`) waits
for capacity inside `move_on_after(_ADMISSION_CONTROL_POLL_SECONDS)` (`:622-631`), with
the poll at 0.1 s (`:77`), so it can check control between waits. Each expiry cancels
the limiter acquisition and the loop acquires again.

**Limiter order.** anyio's asyncio `CapacityLimiter` keeps waiters in an `OrderedDict`,
appends on acquire, removes on cancellation, and grants with `popitem(last=False)`
(`anyio/_backends/_asyncio.py`, `CapacityLimiter`). Combined with the poll, every waiter
moves to the back every 0.1 s, so grant order is not arrival order.

**Admission stamp.** `_run_worker_attempt` stamps `admission_acquired_at` when the
worker starts (`src/vaultspec_rag/job_manager/_execution.py:723-733`). The stamp is per
attempt: a transition that rewrites the start clock clears it
(`src/vaultspec_rag/job_manager/_persistence.py:478-484`). Persistence rejects a stamp
without a start (`src/vaultspec_rag/job_persistence.py:332-333`). The job-state file
version is `_VERSION = 2` (`src/vaultspec_rag/job_persistence.py:63`).

**State and phase.** `JobState` (`src/vaultspec_rag/job_models.py:83`) has no waiting
member; a waiter is `running`. `_job_phase`
(`src/vaultspec_rag/server/_routes_jobs.py:105-114`) maps canonical states to
themselves and keeps legacy terminal aliases. `_job_with_liveness` (`:705`) writes
`state` and `phase` into each `/jobs` record.

**Service waiting predicate.** `_job_is_waiting` (`:283-284`) is true only when the
progress step is `queued` (the writer wait). Stall (`:303`), confirmed progress
(`:321`), rates (`:369`), degradation (`:507`) and machine pressure (`:1002`) use it, so
they treat an admission waiter as working.

**Filtering.** `jobs_route` (`src/vaultspec_rag/server/_routes.py:524-600`) filters with
`_job_matches` (`src/vaultspec_rag/server/_routes_jobs.py:810`), then sorts, then
applies `offset` and `limit`. The service-client parameter set is `_JOBS_PARAMS`
(`src/vaultspec_rag/serviceclient/_transport.py:1051`).

**CLI inference.** `job_awaiting_admission`
(`src/vaultspec_rag/cli/_service_jobs_query.py:15-39`) reads a present-and-null
`admission_acquired_at` on a `running` job. `job_is_waiting` (`:42-56`) adds the writer
wait. `jobs_state_filter` (`:124-141`) sends `phase=running` for `--state active` and
`--state waiting`, and `apply_client_state_filter` (`:284-305`) filters the returned,
already-limited page. Callers: `src/vaultspec_rag/cli/_service_jobs_collection.py:117`,
`:158`; `src/vaultspec_rag/cli/_service_jobs_watch.py:60`;
`src/vaultspec_rag/cli/_service_jobs_presentation.py` (imports at `:39-40`);
`src/vaultspec_rag/cli/_jobs_tui_cells.py:37`. Commit `a48e7e660` changed the
`--state failed` mapping in the same file to use the service `failed` flag.

**Existing waits.** `wait_for_attempt`
(`src/vaultspec_rag/job_manager/_execution.py:437-497`) joins an attempt's task with a
bound, for task release only. No route waits for a job state. Job routes are registered
at `src/vaultspec_rag/server/_routes.py:1124-1132`. Job verbs live in
`src/vaultspec_rag/cli/_service_jobs_control.py:321-404` and fail with exit 1, invalid
input 2, service not running 3.
