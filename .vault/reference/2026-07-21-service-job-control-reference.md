---
tags:
  - '#reference'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-21'
body_hash: 'sha256:20f3667817dfb91b5d508b7bdc3763496fb87adf6dcad36d79fb55e77e1992ce'
related:
  - "[[2026-06-04-async-service-index-adr]]"
  - "[[2026-06-11-service-jobs-operability-adr]]"
  - "[[2026-06-12-service-concurrency-adr]]"
  - "[[2026-06-30-mcp-search-scope-adr]]"
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
---

# `service-job-control` reference: `current indexing job runtime and control seams`

This audit maps the current service job registry, HTTP and CLI surfaces, worker
execution, indexer safe points, watcher integration, and restart behavior at commit
`02f34ed1a4d5bedd9ecc0da68a4dd1afd31d6d43`. The worktree was already dirty; the
relevant uncommitted service-lifespan edits do not add per-job control.

## Summary

### Service-domain job state

- `src/vaultspec_rag/jobs.py:69-76` owns a module-global bounded deque, one lock,
  an unkeyed set of background tasks, and completion callbacks. There is no manager,
  exact-ID runtime map, or per-job control token.
- `record_start()` creates a mutable record directly in phase `running`; the waiting
  state is represented indirectly by progress step `queued`
  (`src/vaultspec_rag/jobs.py:229-301`, `:542-553`, `:600-614`).
- `_finish_record()` is already first-terminal-writer-wins, and `record_finish()`
  already admits `cancelled` and `interrupted` outcomes
  (`src/vaultspec_rag/jobs.py:352-458`). This idempotence is a useful invariant to
  retain.
- `JobProgressReporter` is the canonical progress writer
  (`src/vaultspec_rag/jobs.py:510-539`). The indexer-owned `ProgressReporter`
  protocol has no control checkpoint (`src/vaultspec_rag/progress.py:39-58`), so
  progress callbacks alone cannot stop work that does not report between slices.
- The bounded deque can evict a nonterminal record after 256 newer inserts. Its later
  finish then becomes an unknown-ID no-op, and the next active snapshot omits it.
  Controlled runtimes therefore need a non-evictable active map separate from bounded
  terminal history.

### Execution boundary and cancellation gap

- Manual indexing runs as `asyncio.create_task()` to AnyIO `run_sync()` to a
  synchronous indexer (`src/vaultspec_rag/jobs.py:542-665`). The async tasks are kept
  alive but are not keyed by job ID. Cancelling an async wrapper cannot address a
  particular worker and does not safely terminate the worker thread.
- The index limiter defaults to four jobs (`src/vaultspec_rag/concurrency.py:54-65`,
  `src/vaultspec_rag/config.py:497-498`). Each run also retains a project lease, and
  each corpus indexer holds its writer lock across the full operation
  (`src/vaultspec_rag/service.py:307-343`,
  `src/vaultspec_rag/indexer/_vault_indexer.py:108-139`,
  `src/vaultspec_rag/indexer/_codebase_indexer.py:1273-1303`). A blocking pause would
  pin all of these resources; four paused jobs could exhaust indexing capacity.
- GPU work is already sliced and the GPU lock is limited to forward calls
  (`src/vaultspec_rag/indexer/_streaming.py:103-155`, `:223-240`, `:281-303`). These
  slice boundaries are the natural cooperative control points, outside the GPU lock
  and storage mutations.
- Full code indexing has a separate GPU-consumer thread and bounded queue
  (`src/vaultspec_rag/indexer/_codebase_indexer.py:1003-1050`, `:1091-1118`). That
  consumer has no reporter callback around each slice, so a real control token must
  reach the producer and consumer. Its shutdown can currently drain for up to 300
  seconds (`src/vaultspec_rag/indexer/_codebase_indexer.py:67-72`).
- Explicit clean rebuilds drop their collection before repopulating it; interruption
  can leave it empty (`src/vaultspec_rag/indexer/_vault_indexer.py:182-194`,
  `src/vaultspec_rag/indexer/_codebase_indexer.py:1346-1354`). Code incremental
  indexing also deletes old modified-file chunks before embedding replacements
  (`src/vaultspec_rag/indexer/_codebase_indexer.py:1817-1837`). Control checkpoints
  must not split these destructive spans unless the ordering is made interruption-safe.

### HTTP, transport, and adapters

- The only jobs resource is token-gated `GET /jobs`, with bounded filtering and
  prefix lookup (`src/vaultspec_rag/server/_routes.py:241-308`, `:975`). Creation is a
  separate `POST /reindex` route (`src/vaultspec_rag/server/_routes.py:525-560`,
  `:979`). An unknown reindex type currently falls through to code indexing instead
  of returning a validation error.
- Liveness, stall detection, filtering, summaries, and running-first ordering are
  service-domain transforms in `src/vaultspec_rag/server/_routes_jobs.py:121-287`.
  Any new state must update this one shared shaping layer; paused work must not be
  reported as stalled.
- CLI detail mode accepts ambiguous ID prefixes and resolves ambiguity client-side
  (`src/vaultspec_rag/cli/_service_jobs.py:879-893`). Mutating routes must require
  exact IDs.
- The shared transport infers GET versus POST from whether a body exists
  (`src/vaultspec_rag/serviceclient/_transport.py:133-147`) and only maps job reads
  (`:349-407`). PATCH, PUT, or DELETE require an explicit method parameter. Per the
  accepted MCP scope decision, administration and job controls remain CLI-only; MCP
  keeps only incremental index submission.

### Persistence, watcher, and shutdown

- Only phase-`running` records are persisted to `jobs-active.json`; startup turns
  them into terminal `interrupted` records (`src/vaultspec_rag/jobs.py:79-194`,
  `src/vaultspec_rag/server/_lifespan.py:382-392`). Completed history is memory-only,
  and there is no durable computation checkpoint.
- Watcher pending sets and active job IDs are coroutine locals
  (`src/vaultspec_rag/watcher.py:207-227`). Watcher jobs use the same registry and
  limiter (`:307-494`). Root-level watcher stop cancels the async task without waiting
  for its synchronous worker (`src/vaultspec_rag/server/_watcher.py:150-165`), so the
  record may say cancelled while writes continue.
- Cancelling a watcher-originated job requires an explicit pending-batch policy:
  retaining the batch retries it on an idle tick, while dropping it sacrifices index
  freshness. Job control and watcher enable/disable control must remain distinct.
- Service shutdown does not cancel or await the general background job set before
  closing project stores (`src/vaultspec_rag/server/_lifespan.py:426-452`,
  `src/vaultspec_rag/service.py:651-698`). A job manager must request cooperative
  cancellation and boundedly join runtimes before registry teardown.

### Implementation seams

- Replace the unkeyed globals with a service-domain manager that owns an exact-ID
  active map, bounded terminal history, job-to-runtime handles, atomic state
  transitions, capabilities, and a persisted nonterminal snapshot.
- Add an explicit thread-safe run-control protocol. Check it before phases and loop
  batches, before and after each GPU slice, around producer/consumer queue boundaries,
  and around but never inside GPU or store critical sections.
- Preserve one progress authority and first-terminal-writer-wins. Expose control
  request and acknowledgement timestamps so asynchronous pause/cancel latency is
  observable.
- A targeted force kill cannot be implemented by cancelling the current async task.
  Honest choices are cooperative cancellation, whole-daemon termination, or a
  separate process-isolated indexing architecture with a compatible single-GPU gate.
