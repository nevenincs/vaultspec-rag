---
tags:
  - '#adr'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-service-job-control-research]]"
  - "[[2026-07-21-service-job-control-reference]]"
  - "[[2026-06-04-async-service-index-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
---

# `service-job-control` adr: `desired-state control for indexing jobs` | (**status:** `accepted`)

## Problem Statement

The resident service can submit and observe indexing jobs, but it cannot address an exact
job to pause, resume, cancel, retry, or remove its terminal history. The current asynchronous
task is only a wrapper around synchronous work running in a worker thread; cancelling that
wrapper cannot stop the thread and can falsely report completion while storage mutation
continues.

Job control must add an honest resource lifecycle without violating the accepted bounded
operator view, dedicated indexing capacity, single-GPU consumer, storage-lock, watcher
freshness, and interrupted-job recovery contracts. It must also distinguish graceful
cancellation from hard termination: the current execution boundary cannot safely kill one
indexing job.

## Considerations

- A paused Python stack would retain its worker thread, index-capacity token, project lease,
  writer lock, and producer/consumer resources. Paused work must release these resources.
- Pause and cancellation are cooperative requests whose acknowledgement can lag until a safe
  checkpoint. Observed state must remain distinct from desired state.
- A job may be controlled while a preceding request is still unwinding. Pause/resume and
  pause/cancel races need revisioned, deterministic transitions.
- Index attempts contain destructive intervals. A control checkpoint is safe only where
  stopping cannot leave a published collection or file replacement half-mutated.
- A paused job has no live execution and can survive daemon restart, while an execution that
  was active when the daemon died cannot be reported as paused or cancelled without
  acknowledgement.
- Watcher-originated work shares the same indexing resources but carries a continuing
  freshness obligation after one attempt is cancelled.
- Nonterminal jobs cannot be silently evicted, so retained paused and queued jobs require an
  explicit admission bound rather than an unbounded active registry.
- The accepted MCP boundary keeps administration out of MCP. Job lifecycle control belongs
  to the service domain and its operator-facing HTTP and CLI adapters.

## Considered options

- **Cancel the asynchronous wrapper and report the job stopped.** Rejected because the
  worker thread may continue mutating storage after the reported terminal transition.
- **Block the worker stack on a condition variable while paused.** Rejected because it pins
  leases, locks, threads, and index capacity for the duration of the pause.
- **Cooperatively unwind each attempt and reconcile on resume.** Chosen because it provides
  truthful acknowledgement, releases scarce resources, preserves one logical job identity,
  and works within the current thread and GPU architecture.
- **Run every indexing job in a killable process.** Deferred because safe termination
  requires a parent-owned GPU execution boundary or equivalent IPC, cross-process writer
  ownership, and orphan recovery. It is a separate architectural decision.

## Constraints

- The accepted asynchronous-indexing decision remains binding: submission stays
  non-blocking and the service retains strong references to live work. `JobManager` becomes
  that strong-reference owner rather than introducing a second runtime path.
- The accepted jobs-operability decision remains binding: active work is actionable and
  exact-addressable, terminal history and collection views remain bounded, and progress has
  one service-domain authority.
- The accepted concurrency and codified GPU/storage rules remain binding. Control checks run
  outside `gpu_lock`, CPU workers remain GPU-free, and pause acknowledgement requires release
  of the index limiter, project lease, writer lock, worker thread, and producer/consumer
  resources.
- The interrupted-job persistence contract is stable but may still be in flight. This
  feature absorbs it into the manager's one persistence mechanism instead of adding a
  parallel active-job file.
- The accepted MCP scope remains binding: MCP may submit an incremental refresh but receives
  no pause, resume, cancel, delete, retry, or force-termination tools.
- Python has no supported safe per-thread kill. Every current indexing job reports
  `force_killable=false`; a force request must fail rather than masquerade as task
  cancellation.
- Because nonterminal records are non-evictable, the manager enforces a configured admission
  limit and refuses excess creation with a structured capacity outcome.

## Implementation

Indexing jobs become durable desired-state resources owned by one service-domain
`JobManager`. Pause and cancellation cooperatively unwind the current execution attempt;
resume creates a new convergence attempt under the same logical job ID.

**Ownership and representation.** The manager owns immutable job specifications, revisioned
status snapshots, exact-ID runtime handles, thread-safe run-control tokens, a non-evictable
bounded set of nonterminal jobs, and separately bounded terminal history. Each resource
exposes its specification, observed and desired states, revision, attempt lineage, progress,
initiator, runtime and resource state, timestamps, structured result or error, and computed
capabilities. Progress remains one stream shared by routes, CLI, health, and logs.

**Lifecycle.** Observed states are `queued`, `running`, `pausing`, `paused`, `cancelling`,
`cancelled`, `succeeded`, `failed`, and `interrupted`. Desired state is `running`, `paused`,
or `cancelled`.

- Pausing queued work acknowledges `paused` immediately. Pausing running work records the
  desired state and `pausing`; it acknowledges `paused` only after the attempt has unwound
  and released all execution resources.
- Resuming `pausing` work restores the current attempt if safe unwind has not committed.
  Otherwise cleanup completes and a new attempt is queued without acknowledging a stale
  transient `paused` state. Resuming paused work queues a convergence attempt under the same
  job ID and records attempt lineage.
- Cancelling queued or paused work acknowledges `cancelled` immediately. Cancelling running
  or pausing work records `cancelling` and acknowledges `cancelled` only after safe unwind.
  Cancellation is absorbing and supersedes a pending pause.
- A real execution failure remains `failed`; a control request cannot overwrite it with a
  false cancellation. First terminal writer wins.
- Same-target replays, including requests whose acknowledgement is pending, return structured
  already-satisfied success. A stale expected revision conflicts only when it would change
  the current desired state. Incompatible terminal transitions return
  `409 invalid_transition`.
- Failed, cancelled, and interrupted work can be retried as a new linked job. Terminal
  history is immutable; succeeded work uses ordinary job creation rather than retry.

**Control boundary.** A run-control token, separate from progress reporting, is checked
before phases and bounded batches, before and after GPU slices while outside `gpu_lock`,
around producer/consumer queue operations, and around storage mutations. No checkpoint
occurs inside an indivisible mutation.

For a clean rebuild, the protected destructive interval begins before collection drop and
ends only when a valid replacement collection is published. Pause or cancellation may
therefore remain pending for the whole interval. Per-file delete-and-replacement work is
similarly protected until replacement is durable. Cooperative control must not deliberately
create a partial state; crash recovery continues through non-clean convergence.

**Persistence and restart.** The manager atomically persists queued and paused specifications
plus enough active-attempt metadata to recover an unacknowledged execution. Dispatch occurs
only after the queued transition is durable. On startup, durably queued jobs are requeued,
paused jobs remain paused under the same ID, and prior `running`, `pausing`, and `cancelling`
attempts become terminal `interrupted`. Retrying an interrupted record creates a linked job
instead of rewriting history. Watcher-originated paused work also persists a durable
dirty/convergence marker; transient path sets need not become instruction-level checkpoints,
but restart must retain enough intent to converge the affected root.

**HTTP resource contract.** `POST /jobs` creates a vault or code indexing job and returns
`202`, its exact ID and revision, capabilities, snapshot, and `Location`. It supports an
idempotency key, validated operation/source/mode values, optional start-paused behavior, and
service-domain deduplication of equivalent active work. `GET /jobs` remains a bounded,
filterable collection and `GET /jobs/{id}` returns exact-ID detail.

`PUT /jobs/{id}/desired-state` sets `running`, `paused`, or `cancelled`, with optional
graceful/force mode and expected revision. Pending cooperative control returns `202`;
immediate and already-satisfied transitions return structured success.
`POST /jobs/{id}/retry` creates a linked resource from a retryable terminal job.
`DELETE /jobs/{id}` removes terminal history only; nonterminal work returns
`409 job_not_terminal`. A force request returns `409 force_termination_unavailable` while
`force_killable=false`. Mutations require full IDs. The existing `/reindex` route remains a
compatibility adapter to job creation.

**Watcher behavior.** Watchers submit through `JobManager`; they do not retain a second
execution path. A paused watcher job owns its root/source convergence slot and coalesces later
dirtiness. Cancelling that job releases the slot but does not disable the watcher: the root
remains dirty and a replacement convergence job may be submitted after bounded backoff.
Responses expose `watcher_enabled` and `replacement_expected`. Stopping future automatic
indexing remains a separate watcher lifecycle operation.

**Shutdown.** Shutdown first stops new dispatch while preserving durable queued and paused
intent. Running attempts receive a cooperative shutdown signal and unfinished attempts are
recorded as `interrupted`, not operator-requested cancellation. Stores close only after every
worker that can touch them releases its resources. If the bounded acknowledgement window
expires, the daemon cannot report a clean stop or close a store still reachable by a
surviving worker; whole-daemon termination is the only safe escalation.

**Adapters.** Operator commands live under singular `server job`: `show`, `pause`, `resume`,
`stop`, `retry`, and terminal-only `delete`; existing `server jobs` remains the collection
view. Human prefix resolution must resolve to one exact ID before mutation. JSON and HTTP use
full IDs and one structured outcome envelope. MCP remains limited to incremental refresh
submission.

## Rationale

Cooperative unwind and reconciliation is the only option that both tells the truth about
execution and fits the existing runtime. It avoids the false safety of cancelling an
asynchronous wrapper, releases resources that a blocking pause would retain, and preserves
the accepted single-GPU and storage-lock architecture.

Separating desired state from observed state makes control latency explicit and permits
deterministic race handling. Persisting logical pause rather than a suspended Python stack
provides restart continuity without pretending to preserve an instruction pointer or batch
offset. Per-job hard kill remains deferred because process isolation changes GPU ownership,
storage ownership, and failure recovery enough to require its own ADR.

## Consequences

- Operators gain exact-ID create, inspect, pause, resume, graceful stop, retry, and
  terminal-history deletion with honest capability discovery.
- Paused and cancelled states are acknowledged only when no worker can continue making
  progress or storage writes.
- Paused jobs release scarce resources and can survive restart, but resumption may repeat
  already converged work and does not preserve an instruction pointer.
- Pause and cancellation latency is bounded only by the next safe checkpoint. Clean rebuilds
  may defer acknowledgement for a long protected interval; control-age fields make that
  visible.
- The manager, durable transitions, attempt lineage, watcher dirtiness, and race handling
  materially increase lifecycle complexity.
- Nonterminal admission can be exhausted by retained paused jobs. The service rejects new
  jobs explicitly instead of evicting controllable work.
- Per-job hard kill remains unavailable. Operators requiring immediate termination accept
  whole-daemon blast radius until process-isolated indexing is separately designed.
- The capability model leaves a future process-isolation pathway open without redefining
  current graceful semantics.
