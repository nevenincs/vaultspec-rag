---
tags:
  - '#adr'
  - '#job-admission-visibility'
date: '2026-11-20'
modified: '2026-11-20'
body_schema: 'body-v2'
body_hash: 'sha256:ce70bb3cb30edbfab32005a92e0607474889a3f56371d49bb49c368b192d2df0'
related:
  - "[[2026-07-24-index-throughput-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-07-29-gpu-admission-gate-adr]]"
  - "[[2026-07-25-service-release-compatibility-adr]]"
  - "[[2026-07-31-job-state-version-suffix-adr]]"
  - '[[2026-11-20-job-admission-visibility-reference]]'
---

# `job-admission-visibility` adr: `service-owned admission wait phase, queue position, and bounded job wait` | (**status:** `proposed`)

## Problem Statement

A job waiting for an admission slot reports phase `running`. Encode-bearing jobs share
one machine-wide slot (`src/vaultspec_rag/concurrency.py:35-39`, `:76-90`), chosen in
`src/vaultspec_rag/job_manager/_execution.py:704-706`. Other index jobs share the wider
index limiter. In both cases the job is `running` from dispatch, before its worker
starts.

Only the CLI tells a waiting job apart. It infers the admission wait from a null
`admission_acquired_at` (`src/vaultspec_rag/cli/_service_jobs_query.py:15-39`), and the
writer wait from a progress step (`:42-56`). It then filters `--state active` and
`--state waiting` on the client (`:276-305`), after the service has already cut the
bounded page, so a page can come back short or empty while matches exist. This is an
entry point owning status logic, which the service-surface rule forbids.

The service has its own narrower predicate. `_job_is_waiting`
(`src/vaultspec_rag/server/_routes_jobs.py:283`) sees only the writer wait, so the
stall, rate, degradation and pressure readers (`:303`, `:321`, `:369`, `:507`, `:1002`)
treat an admission waiter as working.

There is no queue position and no way to wait for a job. A queue position read from the
limiter today would also be false. Each waiter leaves its limiter queue every 100 ms to
poll for control and re-enters at the back (`src/vaultspec_rag/job_manager/_execution.py:77`,
`:622-631`). The limiter grants its oldest waiter first (anyio 4.16.0,
`CapacityLimiter` in `anyio/_backends/_asyncio.py`), so grant order rotates instead of
following arrival.

## Considerations

- The encode slot and its visibility duty are settled: "queued-not-running must be
  visible state, not silence", surfaced identically to `/jobs`, CLI and MCP
  (`2026-07-24-index-throughput-adr`, Part A).
- The observed lifecycle states and the HTTP job resource contract are settled
  (`2026-07-21-service-job-control-adr`). `JobState` is persisted.
- The job-state file is versioned (`src/vaultspec_rag/job_persistence.py:63`) and an
  older build sets a newer file aside (`2026-07-31-job-state-version-suffix-adr`). A new
  persisted state member needs a version bump. The user requires no version bump.
- `phase` is already a projection: canonical states map to themselves and legacy
  terminal aliases survive (`src/vaultspec_rag/server/_routes_jobs.py:105-114`). `state`
  is the canonical field.
- The admission stamp is per attempt and is cleared by a requeued resume
  (`src/vaultspec_rag/job_manager/_persistence.py:478-484`). It measures the wait; it is
  not a live registry of who is waiting.
- Client and daemon are expected to be the same release; a mismatch is detected
  (`2026-07-25-service-release-compatibility-adr`).
- The fail-fast "no path waits or queues" ruling in `2026-07-29-gpu-admission-gate-adr`
  governs model-load admission inside the torch loader. It does not govern the job-level
  encode slot, which queues by design.
- MCP carries no job read or control tools today (`2026-07-21-service-job-control-adr`).

## Considered options

- **Add `awaiting_admission` to `JobState`.** The truest model, but the state is
  persisted, so it needs a job-state file version bump. Every `state=running` reader
  would also stop matching waiters. Rejected.
- **Keep the CLI inference and document it.** Leaves status logic in an entry point and
  the page-truncation defect in place. Rejected.
- **A service projection: `phase` reports `awaiting_admission`, beside `waiting_on`,
  `queue_position` and server-side wait filtering; `state` stays `running` (chosen).** No
  persisted change. One owner for the wait concept. Old `state` readers keep working.
- **Report waiters only through a separate `admission` object and leave `phase`
  alone.** Compatible, but every renderer must still combine two fields to know whether a
  job works, which is the inference this record removes. Rejected.
- **Expose queue position from limiter statistics.** The limiter reports only a waiter
  count, and its order rotates under the control poll. Rejected.
- **Client-side polling of `GET /jobs/{id}` instead of a wait route.** Every client
  writes its own loop and interval. Rejected in favour of one bounded service wait.

## Constraints

- `JobState` gains no member. Persisted job records and the job-state file shape do not
  change. No version or schema bump: the job-state file version, the storage schema, the
  discovery schema and the package version stay as they are.
- The service owns one wait concept. A running job waits on `admission` while its
  attempt is registered as a limiter waiter, or on `writer` while its progress step is
  `queued`. Admission takes precedence. Every service reader that asks "is this job
  working" uses that one predicate.
- Admission waiting is read from a live, in-process waiter registry owned by the job
  manager. It is not inferred from the persisted stamp and it is never persisted.
- Admission order is arrival order per limiter. A waiter never leaves and re-enters its
  limiter queue except when a control signal ends its wait. `queue_position` is the
  waiter's 1-based rank in that order and must equal the grant order.
- `phase` gains exactly one value, `awaiting_admission`. `state` stays `running` for
  every waiter. The writer wait keeps phase `running` and is reported through
  `waiting_on`.
- `waiting` and `working` filtering happen in the service before sorting and
  pagination. No adapter filters a page after the service cut it.
- The wait route is read-only, token-gated and bounded. It waits on an in-process change
  notification, never by polling the persisted file or sleeping in a loop.
- The CLI renders `phase`, `waiting_on` and `queue_position`. It derives nothing. A
  payload without `waiting_on` means not waiting; the CLI never infers a wait from an
  absent or null stamp.
- MCP gains no tool from this record. The MCP scope in
  `2026-07-21-service-job-control-adr` stands.
- None of the new code on service call paths imports torch.
- Affected prior rulings. `2026-07-24-index-throughput-adr` Part A says the admission
  stamp splits admission wait from work. This record keeps the stamp as the wait
  measurement and moves the running-versus-waiting verdict to the service projection.
  `2026-07-21-service-job-control-adr` gains one read route and one `server job` verb;
  its states, desired states and control routes are unchanged. Both records need a
  short amendment once this record is accepted.

## Implementation

We will make admission waiting a service-owned projection of a running job, give it a
truthful queue position, filter on it in the service, and add one bounded wait route.
The CLI inference is deleted.

**Waiter registry and FIFO admission.** In
`src/vaultspec_rag/job_manager/_execution.py`, the job manager records each attempt in an
ordered per-limiter registry (`encode`, `index`) when it starts waiting for capacity,
and removes it when its worker starts or its wait ends. The registry lives with the
manager's runtime state (`src/vaultspec_rag/job_manager/state.py`) under the manager
lock. The 100 ms `move_on_after` re-entry loop (`:622-631`) is replaced so that each
attempt waits once. Implementation hypothesis: the control token's request methods
(`src/vaultspec_rag/job_control.py`) wake the waiting attempt through a callback the
manager registers for the duration of the wait, and the attempt's cancel scope is
cancelled on the event loop. Any mechanism that keeps arrival order and keeps control
latency at or below today's is acceptable. The manager exposes one read,
`admission_queue()`, returning each waiting job id with its slot and position.

**Service projection.** In `src/vaultspec_rag/server/_routes_jobs.py`:

- Replace `_job_is_waiting` (`:283`) with one `job_wait_reason(record)` returning
  `"admission"`, `"writer"` or `None`. Repoint its readers at `:303`, `:321`, `:369`,
  `:507` and `:1002`.
- `_job_phase` (`:105`) returns `awaiting_admission` when the wait reason is admission.
- `_job_with_liveness` (`:705`) adds `waiting_on`, `queue_position` and
  `admission_slot`. All three are null when the job is not waiting.
- `JobFilter` (`:63`) and `_job_matches` (`:810`) gain `waiting: bool | None`. True
  keeps running jobs with a wait reason; false keeps running jobs without one.
- `_job_summary` (`:942`) adds `awaiting_admission`, `waiting` and `working` counts.
  `running` stays the canonical state count and includes waiters.

The admission set comes from `admission_queue()` once per request and is passed to the
projection, so one request sees one consistent queue.

**Routes.** In `src/vaultspec_rag/server/_routes.py`, `jobs_route` (`:524`) parses
`waiting=true|false` with the existing flag parser. A new
`GET /jobs/{job_id}/wait?until=admitted|finished&timeout=<seconds>` route is registered
beside the other job routes (`:1124-1132`):

- `until` defaults to `finished`. `admitted` is reached when the job no longer waits on
  admission, or is terminal. `finished` is reached at any terminal state.
- `timeout` defaults to 30 seconds and is capped at 120 seconds. Both numbers are
  implementation hypotheses.
- The response is 200 with `{job, until, reached, waited_seconds}`. A condition already
  true returns at once with `reached: true`. Expiry returns 200 with `reached: false`.
- An unknown job returns the existing `job_not_found` error. A bad `until` or `timeout`
  returns the existing invalid-request error.
- A record the manager does not own is answered at once from its current snapshot.
- The job manager provides the wait. It notifies waiters on every snapshot replacement
  and every registry change, so the route never polls.

The health job rollup in `src/vaultspec_rag/server/_lifespan.py:1308-1322` adds
`awaiting_admission`, `waiting` and `working` from the summary.

**Service client.** In `src/vaultspec_rag/serviceclient/_transport.py`, add `waiting`
to `_JOBS_PARAMS` (`:1051`) and add one wait call beside `_try_http_get_job` (`:935`).
Its HTTP timeout is the requested wait plus a fixed margin, so the bounded-timeout rule
of `2026-07-22-service-health-client-hardening-adr` holds.

**CLI.**

- `src/vaultspec_rag/cli/_service_jobs_query.py`: delete `job_awaiting_admission`
  (`:15`), `job_is_waiting` (`:42`), `_client_state_matches` (`:276`) and
  `apply_client_state_filter` (`:284`). `jobs_state_filter` (`:124`) maps
  `--state active` to `state=running&waiting=false` and `--state waiting` to
  `state=running&waiting=true`. Keep the `--state failed` mapping that commit
  `a48e7e660` landed in `resolve_jobs_filters` (`:82`).
- `src/vaultspec_rag/cli/_service_jobs_collection.py` and
  `src/vaultspec_rag/cli/_service_jobs_watch.py`: stop applying a client state filter.
- `src/vaultspec_rag/cli/_service_jobs_presentation.py` and
  `src/vaultspec_rag/cli/_jobs_tui_cells.py`: read `phase`, `waiting_on` and
  `queue_position`. A waiter renders as waiting for the GPU slot or the index slot, with
  its position. Its runtime is labelled as wait time.
- `src/vaultspec_rag/cli/_status_labels.py`: render the active and waiting counts from
  the summary's `working` and `waiting` fields.
- `src/vaultspec_rag/cli/_service_jobs_control.py`: add `server job wait JOB_ID
  [--until admitted|finished] [--timeout SECONDS]`. It resolves the id the way
  `server job show` does and emits one JSON envelope on every exit path. Exit 0 when the
  condition is reached, including an already-satisfied one. Exit 1 on expiry with code
  `wait_timeout`. Exit 2 on invalid input. Exit 3 when the service is not running.

**Docs.** `docs/service-mode.md`: list `GET /jobs/{job_id}/wait` and describe
`awaiting_admission`, `waiting_on` and `queue_position`. Regenerate `docs/cli.md` with
`dev/generate_cli_reference.py`.

**Files to change.**

- `src/vaultspec_rag/job_manager/_execution.py`
- `src/vaultspec_rag/job_manager/state.py`
- `src/vaultspec_rag/job_manager/manager.py`, if `admission_queue()` and the wait do not
  sit in `_execution.py`
- `src/vaultspec_rag/job_control.py`, only if the wake-callback hypothesis is used
- `src/vaultspec_rag/server/_routes_jobs.py`
- `src/vaultspec_rag/server/_routes.py`
- `src/vaultspec_rag/server/_lifespan.py` (health job rollup counts only)
- `src/vaultspec_rag/serviceclient/_transport.py`
- `src/vaultspec_rag/cli/_service_jobs_query.py`
- `src/vaultspec_rag/cli/_service_jobs_collection.py`
- `src/vaultspec_rag/cli/_service_jobs_watch.py`
- `src/vaultspec_rag/cli/_service_jobs_presentation.py`
- `src/vaultspec_rag/cli/_jobs_tui_cells.py`
- `src/vaultspec_rag/cli/_status_labels.py`
- `src/vaultspec_rag/cli/_service_jobs_control.py`
- `docs/service-mode.md`, and `docs/cli.md` by regeneration
- Tests: `src/vaultspec_rag/tests/test_jobs_admission_display.py`,
  `src/vaultspec_rag/tests/test_job_manager_encode_admission.py`,
  `src/vaultspec_rag/tests/test_jobs_eta_display.py`,
  `src/vaultspec_rag/tests/test_service_jobs_cli_state_filter.py`, plus new route and
  CLI tests for the wait.

**Guard tests.** Each must be shown to fail on its named assertion when the guard is
broken:

- Three encode jobs queued in order A, B, C are admitted in that order and report
  positions 1, 2, 3. Restoring the re-entry poll must fail this.
- `GET /jobs?waiting=false&limit=1` returns the working job when newer waiters exist.
  Moving the filter after pagination must fail this.
- A pause on a waiting job is acknowledged within today's control latency.

## Rationale

A projection is the only option that removes the entry-point logic without a version
bump. Persisting a new state would be the cleanest model, but it crosses the job-state
file version, which the user ruled out, and it breaks every `state=running` reader.
Leaving `phase` alone and adding only a side object keeps the inference alive in every
renderer. Changing `phase` puts the truth in the field renderers already print, and
`state` keeps the canonical lifecycle stable.

Queue position is only worth reporting if it is true. The control poll makes grant order
rotate, so the position must come from an ordered registry and the poll must stop
re-entering the queue. Ordering is the binding part; the wake mechanism is not.

One wait concept in the service also fixes service-side readers that count an admission
waiter as working. Server-side filtering fixes the short-page defect as a side effect of
moving the logic to its owner.

The wait route gives every client the same bounded answer to "tell me when it starts or
ends", instead of each one writing a polling loop.

## Consequences

- Operators and agents see which jobs wait, for which slot, and in what order, from one
  service answer in `server jobs`, the TUI, status and `/jobs`.
- `--state active` and `--state waiting` return full pages.
- Admission becomes strictly first come, first served. A job that is paused while
  waiting and then resumed rejoins at the back.
- Clients matching `phase == "running"` no longer see admission waiters as running.
  Clients reading `state` see no change. `/jobs?phase=running` now excludes admission
  waiters. Mixed releases are flagged by the release-compatibility check.
- A held wait route keeps one loopback connection open for up to the cap. The cap
  bounds it.
- A job waiting for admission when the daemon dies is still recovered as `interrupted`,
  as today. Revisit that if waiters should be requeued instead.
- Reconsider the projection if a later change versions the job-state file for other
  reasons. `awaiting_admission` could then become a persisted state.
