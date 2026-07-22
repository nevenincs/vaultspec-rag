---
tags:
  - '#plan'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
tier: L3
related:
  - '[[2026-07-21-service-job-control-adr]]'
  - '[[2026-07-21-service-job-control-research]]'
  - '[[2026-07-21-service-job-control-reference]]'
---

<!-- LINK RULES:
     - [[wiki-links]] are ONLY for .vault/ documents in the
       related: field above.
     - The related: field carries the AUTHORISING documents
       (ADR, research, reference, prior plan) for every Step in
       this plan. Steps inherit this chain; per-row reference
       footers do not exist.
     - NEVER use [[wiki-links]] or markdown links in the
       document body. -->

<!-- RETIRED: P09 -->

# `service-job-control` plan

Build truthful, durable CRUD and cooperative lifecycle control for service-owned indexing
jobs without violating the single-GPU, storage-lock, bounded-view, or watcher-freshness
contracts.

## Wave `W01` - job state authority

Establish the durable service-domain state machine, control primitives, admission bounds, and compatibility seam required by every downstream indexing, watcher, and adapter change.

### Phase `W01.P01` - control and configuration contracts

Define the reusable cooperative-control protocol and bounded service settings before the manager and indexers consume them.

- [x] `W01.P01.S01` - Define the thread-safe run-control token, checkpoint signals, protected spans, and no-control implementation using vaultspec-high-executor; `src/vaultspec_rag/job_control.py`.
- [x] `W01.P01.S02` - Add bounded nonterminal admission and cooperative shutdown timing settings using vaultspec-standard-executor; `src/vaultspec_rag/config.py`.
- [x] `W01.P01.S03` - Verify control primitives and configuration through imported production behavior using vaultspec-standard-executor; `src/vaultspec_rag/tests/test_job_control_unit.py`.

### Phase `W01.P02` - durable job manager

Replace the evictable record ring and unkeyed task set with exact-addressable lifecycle ownership, persistence, transitions, and compatibility functions.

- [x] `W01.P02.S04` - Define immutable job specifications, canonical states, capabilities, revisions, attempt lineage, and structured outcomes using vaultspec-high-executor; `src/vaultspec_rag/jobs.py`.
- [x] `W01.P02.S05` - Implement exact-ID active and runtime ownership, bounded terminal history, admission, active-work deduplication, and idempotency keys using vaultspec-high-executor; `src/vaultspec_rag/jobs.py`.
- [x] `W01.P02.S06` - Implement revisioned pause, resume, cancellation, retry, terminal deletion, first-terminal-writer-wins, and deterministic races using vaultspec-high-executor; `src/vaultspec_rag/jobs.py`.
- [x] `W01.P02.S07` - Implement atomic durable-before-dispatch persistence and queued, paused, and interrupted restart recovery using vaultspec-high-executor; `src/vaultspec_rag/jobs.py`.

### Phase `W01.P03` - state authority verification

Prove transition races, idempotency, admission, persistence, retry, deletion, and strong task ownership against production behavior.

- [x] `W01.P03.S08` - Verify the transition matrix, idempotency, stale revisions, admission, deduplication, retry, deletion, and terminal immutability using vaultspec-standard-executor; `src/vaultspec_rag/tests/test_jobs_unit.py`.
- [x] `W01.P03.S09` - Verify real-filesystem persistence, exact task ownership, atomic replacement, paused restoration, and interrupted recovery using vaultspec-standard-executor; `src/vaultspec_rag/tests/integration/test_jobs_registry.py`.

### Phase `W01.P18` - job domain modularization

Split the canonical job domain out of the legacy compatibility module before cooperative
indexing and adapters add more behavior to the boundary.

- [x] `W01.P18.S38` - Extract canonical enums, immutable resources, outcomes, and serialization into a focused model module while preserving public imports using vaultspec-standard-executor; `src/vaultspec_rag/job_models.py, src/vaultspec_rag/jobs.py`.
- [x] `W01.P18.S39` - Extract the versioned state codec and atomic filesystem store into a focused persistence module using vaultspec-standard-executor; `src/vaultspec_rag/job_persistence.py, src/vaultspec_rag/jobs.py`.
- [x] `W01.P18.S40` - Extract JobManager ownership and lifecycle orchestration, leave jobs.py as the legacy compatibility and dispatch facade, and verify unchanged public behavior using vaultspec-standard-executor; `src/vaultspec_rag/job_manager.py, src/vaultspec_rag/jobs.py, src/vaultspec_rag/tests/test_jobs_unit.py, src/vaultspec_rag/tests/integration/test_jobs_registry.py`.

## Wave `W02` - cooperative indexing execution

Thread the accepted control contract through vault and code indexing so attempts unwind only at safe checkpoints and release scarce resources before the orchestration and API waves depend on them.

### Phase `W02.P04` - vault and streaming checkpoints

Place control checks at vault phase, batch, and GPU-slice boundaries while protecting clean rebuild publication.

- [x] `W02.P04.S10` - Thread run control through streaming embedding and check before and after bounded GPU slices outside gpu_lock using vaultspec-high-executor; `src/vaultspec_rag/indexer/_streaming.py`.
- [x] `W02.P04.S11` - Add checkpoints around vault phases and batches while protecting collection drop through valid publication using vaultspec-high-executor; `src/vaultspec_rag/indexer/_vault_indexer.py`.
- [x] `W02.P04.S12` - Verify real streaming and vault indexing observe control between slices without exposing partial rebuilds using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.

### Phase `W02.P05` - code pipeline checkpoints

Place control checks around code scanning, process-pool work, producer-consumer flow, GPU slices, and file replacement spans.

- [x] `W02.P05.S13` - Propagate run control through code producers, process-pool work, the single GPU consumer, bounded queues, and consumer shutdown using vaultspec-high-executor; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W02.P05.S14` - Protect code clean rebuild and per-file replacement spans from cooperative interruption until published state is valid using vaultspec-high-executor; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `W02.P05.S15` - Verify real code indexing unwinds producer-consumer resources, preserves mutation safety, and converges after resume using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.

### Phase `W02.P06` - attempt dispatch and reconciliation

Make manager-owned attempts translate cooperative unwind into truthful pause, cancel, resume, failure, and resource-release outcomes.

- [ ] `W02.P06.S16` - Implement manager-owned dispatch, token propagation, reconciliation attempts, truthful acknowledgement, completion callbacks, and bounded joins using vaultspec-high-executor; `src/vaultspec_rag/jobs.py, src/vaultspec_rag/job_manager.py`.

### Phase `W02.P07` - cooperative execution verification

Exercise real vault and code indexing attempts to prove safe unwind, convergence on resume, and absence of post-acknowledgement writes.

- [ ] `W02.P07.S17` - Verify paused attempts release limiter, lease, writer ownership, thread, and pipeline resources and cancelled attempts make no later writes using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_index_job_control.py`.

## Wave `W03` - automatic orchestration and shutdown

Move watcher convergence and daemon shutdown onto the manager lifecycle after cooperative execution is available, preserving freshness and store safety.

### Phase `W03.P08` - watcher convergence ownership

Route automatic indexing through the manager, coalesce later dirtiness into paused work, and retain replacement intent after cancellation.

- [ ] `W03.P08.S18` - Submit watcher indexing through JobManager, retain paused convergence slots, coalesce later dirtiness, and schedule cancelled replacements with bounded backoff using vaultspec-high-executor; `src/vaultspec_rag/watcher.py`.
- [ ] `W03.P08.S19` - Keep watcher enablement separate from job cancellation and wait for manager-owned cleanup on watcher stop using vaultspec-high-executor; `src/vaultspec_rag/server/_watcher.py`.

### Phase `W03.P10` - shutdown resource ordering

Stop dispatch, cooperatively drain workers, persist recoverable intent, and prevent stores from closing beneath live indexing threads.

- [ ] `W03.P10.S20` - Restore the single manager, resume durable queues, preserve pauses, drain workers before store closure, and report unclean shutdown truthfully using vaultspec-high-executor; `src/vaultspec_rag/server/_lifespan.py`.

### Phase `W03.P11` - orchestration verification

Exercise watcher and service-lifespan behavior to prove freshness, replacement, interruption, and shutdown safety.

- [ ] `W03.P11.S21` - Verify real watcher pause coalescing, cancellation dirtiness, replacement expectations, explicit watcher stop, and cleanup joining using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`.
- [ ] `W03.P11.S22` - Verify real daemon restart and shutdown preserve queued and paused intent, mark interrupted attempts, and close stores only after worker release using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_service_lifecycle.py`.

## Wave `W04` - operator resource surface

Expose the proven lifecycle through exact-ID HTTP resources, service-client verbs, and CLI commands while preserving bounded views, structured outcomes, MCP scope, and reindex compatibility.

### Phase `W04.P12` - HTTP job resources

Expose create, exact detail, desired-state, retry, and terminal-only deletion while keeping collection views bounded and health semantics accurate.

- [ ] `W04.P12.S23` - Extend job shaping, filtering, ordering, stall classification, control age, capabilities, and canonical state summaries using vaultspec-standard-executor; `src/vaultspec_rag/server/_routes_jobs.py`.
- [ ] `W04.P12.S24` - Add create, exact detail, desired-state update, retry, and terminal deletion routes and retain reindex as a validated compatibility adapter using vaultspec-standard-executor; `src/vaultspec_rag/server/_routes.py`.
- [ ] `W04.P12.S25` - Update service health rollups so paused and transitional jobs remain visible without false stall signals using vaultspec-standard-executor; `src/vaultspec_rag/server/_lifespan.py`.
- [ ] `W04.P12.S26` - Verify authenticated real-ASGI job CRUD, exact mutations, revisions, idempotency, capacity, force rejection, retry linkage, deletion conflicts, and Location headers using vaultspec-standard-executor; `src/vaultspec_rag/tests/integration/test_service_jobs.py`.

### Phase `W04.P13` - service client transport

Add explicit HTTP methods and typed job operations without changing established read behavior or structured outcomes.

- [ ] `W04.P13.S27` - Add explicit HTTP method handling and typed create, detail, desired-state, retry, and delete client operations using vaultspec-standard-executor; `src/vaultspec_rag/serviceclient/_transport.py`.
- [ ] `W04.P13.S28` - Verify GET, POST, PUT, and DELETE client operations and structured conflicts against a real server using vaultspec-standard-executor; `src/vaultspec_rag/tests/integration/test_service_job_control.py`.

### Phase `W04.P14` - CLI job controls

Add singular server job commands with exact mutations, human-only prefix resolution, and one structured JSON outcome per exit path.

- [ ] `W04.P14.S29` - Register the singular server job command group while preserving the server jobs collection command using vaultspec-low-executor; `src/vaultspec_rag/cli/_app.py`.
- [ ] `W04.P14.S30` - Implement show, pause, resume, stop, retry, and delete commands with unique-prefix resolution before exact mutation using vaultspec-standard-executor; `src/vaultspec_rag/cli/_service_jobs.py`.
- [ ] `W04.P14.S31` - Verify human and JSON CLI controls, ambiguous prefixes, idempotent requests, stable errors, retry, deletion, and force rejection against a real server using vaultspec-standard-executor; `src/vaultspec_rag/tests/integration/test_service_job_control.py`.

### Phase `W04.P15` - adapter compatibility verification

Verify authentication, idempotency, conflict codes, reindex compatibility, CLI behavior, and the unchanged MCP administration boundary.

- [ ] `W04.P15.S32` - Verify reindex compatibility and the unchanged MCP incremental-refresh-only administration boundary using vaultspec-standard-executor; `src/vaultspec_rag/tests/integration/test_service_job_control.py`.

## Wave `W05` - system verification and review

Prove the full lifecycle across indexing, restart, watcher, shutdown, HTTP, client, and CLI boundaries, then run the mandatory architecture and safety review before completion.

### Phase `W05.P16` - complete lifecycle scenarios

Exercise realistic cross-boundary pause, resume, cancel, restart, watcher, shutdown, and operator-control scenarios against production components.

- [ ] `W05.P16.S33` - Exercise a real large-corpus pause, resume, and cancel lifecycle proving convergence, attempt lineage, resource release, and no post-cancellation writes using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`.
- [ ] `W05.P16.S34` - Exercise a real restart lifecycle proving durable queued dispatch, persistent pause, interrupted attempts, linked retry, and terminal-history deletion using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`.
- [ ] `W05.P16.S35` - Exercise a real watcher and shutdown lifecycle proving dirtiness coalescing, replacement scheduling, separate watcher control, and safe store closure using vaultspec-high-executor; `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`.
- [ ] `W05.P16.S36` - Exercise the end-to-end HTTP, transport, and CLI outcome matrix for exact IDs, stale revisions, already-satisfied requests, conflicts, and force rejection using vaultspec-standard-executor; `src/vaultspec_rag/tests/integration/test_service_job_control_e2e.py`.

### Phase `W05.P17` - architecture and safety audit

Review the completed implementation against the accepted ADR and codified concurrency, storage, operability, and test-integrity constraints.

- [ ] `W05.P17.S37` - Audit ADR conformance, truthful acknowledgement, bounded views, GPU ownership, storage safety, shutdown ordering, MCP scope, and test integrity and apply required corrections using vaultspec-code-reviewer; `src/vaultspec_rag/`.

## Description

Implement the accepted service-job-control architecture as five ordered Waves. The work first
creates one durable service-domain authority for job specifications, state transitions,
runtime ownership, persistence, and cooperative control. It then threads safe checkpoints
through vault and code indexing, moves watcher and shutdown orchestration onto that authority,
and exposes exact-ID HTTP, client, and CLI resources.

The final Wave verifies complete lifecycles against production components and performs the
mandatory architecture and safety review. Per-job hard termination remains outside this plan;
current resources report `force_killable=false` and reject force requests truthfully.

## Steps

The canonical Step rows are grouped under the five Waves above and are updated only through
the plan CLI during execution.

## Parallelization

Waves execute in order. Within W01, the control primitive and configuration Steps may proceed
in parallel, but the manager Steps and their verification remain ordered. Within W02, the
vault/streaming and code checkpoint Phases may proceed in parallel after W01; manager dispatch
integration follows both, then cooperative execution verification follows dispatch.

Within W03, watcher integration and service-lifespan integration may proceed in parallel after
W02, followed by orchestration verification. W04 is mostly sequential because the service
client consumes the HTTP contract and the CLI consumes the client contract. The independent
W05 lifecycle scenarios may be dispatched in parallel only when their isolated storage and
status directories cannot contend; the final audit waits for every scenario.

## Verification

- `vaultspec-core vault plan check` and the feature-specific vault check pass with every Step
  closed through the CLI.
- Imported-production unit tests cover the complete transition matrix, revision and replay
  semantics, admission, immutable terminals, retry, deletion, and restart persistence without
  fakes, mocks, stubs, patches, monkeypatching, skips, or expected failures.
- Real local-storage integration tests prove pause and cancellation acknowledge only after
  worker, limiter, lease, writer-lock, and producer-consumer release, with no later writes.
- GPU checkpoints execute only outside `gpu_lock`; process-pool workers remain CPU-only and
  the service retains one GPU consumer.
- Watcher and shutdown tests prove dirtiness is preserved, cancellation does not disable the
  watcher, active attempts restore as interrupted, and stores never close beneath live work.
- HTTP, transport, and CLI tests prove exact-ID mutations, stable structured outcomes,
  idempotent desired-state requests, terminal-only deletion, retry linkage, bounded views,
  and `409 force_termination_unavailable`.
- Existing `/reindex` and MCP incremental refresh continue to submit jobs, while MCP exposes
  no lifecycle administration tools.
- Project lint, strict type checks, targeted and full test suites, the full vault check, and
  the mandatory code review pass with no unresolved critical or high findings.
