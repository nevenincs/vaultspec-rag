---
tags:
  - '#research'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-reference]]"
  - "[[2026-06-04-async-service-index-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
---

# `service-job-control` research: `CRUD and lifecycle control for indexing jobs`

The resident service can create and observe indexing jobs but cannot address a running
job to pause, resume, or stop it. This research compares the viable control models and
defines an HTTP and service-domain contract that preserves the accepted bounded-view,
single-GPU, worker-thread, watcher-freshness, and interrupted-job decisions.

## Findings

### F1 - The current task handle is not a cancellation boundary

Manual and watcher indexing both dispatch synchronous indexers through AnyIO worker
threads. The async tasks are unkeyed, the indexer protocol has no control token, and a
job holds its project lease, corpus writer lock, worker-thread limiter token, and
possibly a producer/consumer pipeline for the run. AnyIO documents that cancellation
of `to_thread.run_sync()` either waits for the thread or abandons a thread that still
runs unchecked; Python futures likewise cannot cancel work that is already running.
Cancelling the async wrapper would therefore let the job keep mutating storage after
the API reported it stopped. Sources: `src/vaultspec_rag/jobs.py:542-665`,
`src/vaultspec_rag/indexer/_codebase_indexer.py:1003-1270`, `anyio@4.14.0`,
https://anyio.readthedocs.io/en/latest/api.html#running-code-in-worker-threads,
https://docs.python.org/3/library/concurrent.futures.html#concurrent.futures.Future.cancel.

### F2 - A blocking pause is mechanically simple but operationally wrong

A condition variable checked from the worker could block and later continue the same
Python stack. It would also retain the project lease, writer lock, OS thread, and one of
four default index-limiter tokens for the entire pause. Four paused jobs would prevent
all indexing, and a paused clean rebuild could leave its collection empty indefinitely.
This option is rejected even though it requires the smallest code change. Sources:
`src/vaultspec_rag/concurrency.py:54-65`, `src/vaultspec_rag/config.py:497-498`,
`src/vaultspec_rag/indexer/_vault_indexer.py:108-139`,
`src/vaultspec_rag/indexer/_codebase_indexer.py:1273-1303`.

### F3 - Cooperative unwind plus convergence restart is the viable pause model

The recommended model treats pause as desired state, not as a suspended Python stack.
A thread-safe run-control token is checked at safe boundaries. A pause request changes
the observed state to `pausing`; the next checkpoint raises a dedicated control signal,
the attempt unwinds, and only after the writer lock, project lease, limiter token, GPU
queue, and worker thread are released does the manager acknowledge `paused`. Resume
queues a new attempt under the same logical job ID and converges from persisted index
state. This is analogous to controllers that retain a Job object while terminating its
active execution units on suspension and creating new ones on resume. Source:
https://kubernetes.io/docs/concepts/workloads/controllers/job/#suspending-a-job.

The new attempt is a logical resume, not instruction-pointer or batch-offset recovery.
That distinction must be visible as `attempt`, `resume_strategy="reconcile"`, and
`resumed_from_attempt`. Incremental upserts are naturally convergent, but two destructive
spans need explicit protection: a clean rebuild's collection drop and code incremental's
delete-before-replacement sequence. Control checkpoints must not split either span; a
clean attempt that crossed the drop boundary resumes in non-clean convergence mode, and
the delete/replacement ordering should be made interruption-safe or treated as one
uninterruptible unit. Sources: `src/vaultspec_rag/indexer/_vault_indexer.py:182-194`,
`src/vaultspec_rag/indexer/_codebase_indexer.py:1346-1354`, `:1817-1837`.

### F4 - True per-job kill requires process isolation and is not a valid first increment

Python offers no safe supported operation that kills one running worker thread. A hard
termination model needs a process boundary, as production task systems terminate the
worker process rather than the task and warn that this is a last-resort administrative
operation. Source: https://docs.celeryq.dev/en/latest/userguide/workers.html#revoke-revoking-tasks.

Moving today's indexer into a killable process is not a local change: GPU encoding must
still flow through exactly one consumer and one lock shared with search, CPU chunk
workers must remain GPU-free, and a second model copy risks GPU-memory exhaustion. A
safe process design would require a parent-owned GPU actor or equivalent IPC boundary,
cross-process writer ownership, and explicit orphan cleanup. That is a separate ADR.
The first increment must expose `force_killable=false`; it must never relabel task
cancellation as a kill. Whole-daemon termination remains an explicit blast-radius
escape hatch and interrupts every active job.

### F5 - Recommended service-domain model

Replace the module-global deque/task set with one `JobManager` that owns:

- an exact-ID, non-evictable map of nonterminal jobs and runtimes;
- separately bounded terminal history, preserving the 256-record operator limit;
- immutable job specifications and mutable status snapshots;
- job-ID-to-task and job-ID-to-run-control ownership;
- atomic, revisioned transition validation with first-terminal-writer-wins;
- an atomic persisted snapshot of queued and paused specifications plus prior active
  attempts for interrupted-job recovery;
- the one canonical progress stream already used by route, CLI, health, and logs.

The control token is separate from `ProgressReporter`. Checkpoints belong before phases
and loop batches; before and after each GPU slice, outside `gpu_lock`; around producer
and consumer queue operations; and around, never inside, storage mutations. Pause and
cancel requests are asynchronous: the API returns `202` while state is `pausing` or
`cancelling`, and clients poll detail until the request is acknowledged. A control-age
field makes a stuck acknowledgement visible without an unsafe watchdog kill.

Paused jobs persist because they have no live execution. On daemon startup, genuinely
queued jobs may be requeued only if the queued transition was durably recorded before
dispatch; paused jobs remain paused; prior `running`, `pausing`, and `cancelling`
attempts become `interrupted`, preserving the accepted recovery contract. Retrying an
interrupted job creates a new job linked by `parent_job_id`; it does not rewrite the
terminal record.

### F6 - Canonical states and transitions

The canonical observed states are `queued`, `running`, `pausing`, `paused`,
`cancelling`, `cancelled`, `succeeded`, `failed`, and `interrupted`. The job also carries
`desired_state` as `running`, `paused`, or `cancelled`.

| Current state | Request | Immediate outcome | Acknowledged outcome |
| --- | --- | --- | --- |
| `queued` | pause | `paused` | `paused` |
| `running` | pause | `pausing` | `paused` after safe unwind |
| `pausing` | resume | desired state returns to running | `running` if not unwound, otherwise `queued` |
| `paused` | resume | `queued`, attempt increments | `running` |
| `queued` or `paused` | cancel | `cancelled` | `cancelled` |
| `running` or `pausing` | cancel | `cancelling` | `cancelled` after safe unwind |
| terminal | same terminal request | structured already-satisfied success where possible | unchanged |
| terminal | incompatible request | `409 invalid_transition` | unchanged |

Repeated desired-state writes are idempotent. Mutations require exact IDs and optionally
accept an expected revision so two operators cannot unknowingly race. Paused work is not
stalled; `pausing` or `cancelling` past the control acknowledgement threshold is.

### F7 - HTTP resource contract

The service owns the behavior and the CLI adapts it. MCP retains only incremental index
submission under the accepted search-scope decision; it gains no pause, cancel, delete,
or force-termination tools.

- `POST /jobs` creates a vault or code indexing job and returns `202`, an exact ID,
  `Location: /jobs/{id}`, revision, capabilities, and the canonical snapshot. Body:
  `operation="index"`, `source="vault"|"code"`, absolute `project_root`,
  `mode="incremental"|"rebuild"`, optional `start_paused`, and initiator metadata.
  Unknown values are `400`; the current `/reindex` route remains a compatibility adapter.
- `GET /jobs` retains bounded, filterable, actionable ordering and adds canonical state,
  desired state, and controllability filters.
- `GET /jobs/{id}` is exact-ID detail. Prefix matching remains a CLI convenience and is
  never accepted by a mutation.
- `PUT /jobs/{id}/desired-state` accepts
  `state="running"|"paused"|"cancelled"`, optional `mode="graceful"|"force"`, and
  `expected_revision`. It is the single idempotent pause/resume/stop surface. `force`
  returns `409 force_termination_unavailable` while `force_killable=false`.
- `DELETE /jobs/{id}` removes terminal history only. Active or paused work returns
  `409 job_not_terminal`; deletion never doubles as cancellation and never hides a
  still-running worker.

Success and failure use one structured envelope with command, stable status/error code,
message, and current job snapshot. Already-satisfied desired state returns success.
Create supports an idempotency key, while per-root/source active-job deduplication avoids
two equivalent refreshes competing for the same writer lock.

### F8 - Job representation

The stable resource separates specification from status. Required fields are `id`,
`revision`, `spec`, `state`, `desired_state`, `capabilities`, `attempt`, `created_at`,
`state_changed_at`, `started_at`, `finished_at`, `control_requested_at`,
`control_acknowledged_at`, `progress`, `result`, `error_kind`, `initiator`, `runtime`,
`resources`, and optional `parent_job_id`. Capabilities are computed from job kind and
state: index jobs are pausable/resumable/cancellable, maintenance records are read-only,
terminal records are deletable, and all current jobs are non-force-killable.

### F9 - Watcher and shutdown behavior must join the manager

Watcher-originated indexing must submit through `JobManager` rather than retaining a
second execution path. A paused watcher job owns the root/source slot and coalesces new
paths until resume. Cancelling it leaves the watcher enabled, marks the root dirty, and
allows a later convergence job after bounded backoff; the response states
`watcher_enabled=true` and `replacement_expected=true`. To halt future automatic work,
the operator must stop the watcher separately.

Daemon shutdown first requests cooperative cancellation for every controlled runtime,
waits a bounded interval for acknowledgements, records any survivor as interrupted, and
only then closes project stores. This closes the existing path where worker threads can
outlive registry teardown.

### F10 - Adapter and verification scope

CLI additions should live under a singular `server job` group so the existing
`server jobs` list command remains compatible: `job show`, `job pause`, `job resume`,
`job stop`, `job retry`, and terminal-only `job delete`. Human commands may accept a
unique prefix after resolving it through exact detail; JSON and HTTP always use the
full ID. Every JSON exit path emits one envelope and treats already-satisfied state as
success.

Verification must use imported production behavior and real service/indexer plumbing:
pure transition tests over the real manager; isolated daemon integration against real
Qdrant and GPU with a sufficiently large temporary corpus; progress-driven pause,
resume, cancel, restart, and duplicate-request assertions; proof that paused jobs release
the index limiter and writer lock; proof that no progress or storage write occurs after
`cancelled`; watcher coalescing; shutdown ordering; and exact response/exit-code matrices.
No fake indexer, monkeypatch, skip, or xfail is an acceptable substitute.

## Options

- **O1 - Block the worker stack on pause.** Rejected: pins leases, locks, threads, and
  limiter capacity, and cannot support force kill.
- **O2 - Cooperative unwind and reconcile on resume.** Recommended: bounded control
  latency at existing work-unit boundaries, releases scarce resources, preserves the
  single GPU architecture, and can persist logical pause across restarts.
- **O3 - One killable process per indexing job.** Deferred: enables real force kill but
  requires a parent-owned GPU/IPC architecture, cross-process locking, and new recovery
  semantics. It must not be smuggled into the CRUD implementation.
