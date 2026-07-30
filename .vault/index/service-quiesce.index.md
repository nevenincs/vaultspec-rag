---
generated: true
tags:
  - '#index'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-30'
body_schema: 'body-v1'
related:
  - '[[2026-07-24-service-quiesce-P01-S01]]'
  - '[[2026-07-24-service-quiesce-P01-S02]]'
  - '[[2026-07-24-service-quiesce-P01-S03]]'
  - '[[2026-07-24-service-quiesce-P02-S04]]'
  - '[[2026-07-24-service-quiesce-P02-S05]]'
  - '[[2026-07-24-service-quiesce-P02-S06]]'
  - '[[2026-07-24-service-quiesce-P03-S08]]'
  - '[[2026-07-24-service-quiesce-P03-S09]]'
  - '[[2026-07-24-service-quiesce-W02-P04-S10]]'
  - '[[2026-07-24-service-quiesce-W02-P04-S11]]'
  - '[[2026-07-24-service-quiesce-W02-P04-S12]]'
  - '[[2026-07-24-service-quiesce-W02-P05-S13]]'
  - '[[2026-07-24-service-quiesce-W02-P05-S14]]'
  - '[[2026-07-24-service-quiesce-W02-P05-S15]]'
  - '[[2026-07-24-service-quiesce-W02-P05-S16]]'
  - '[[2026-07-24-service-quiesce-W02-P05-S17]]'
  - '[[2026-07-24-service-quiesce-W02-P05-S18]]'
  - '[[2026-07-24-service-quiesce-W03-P06-S19]]'
  - '[[2026-07-24-service-quiesce-W03-P06-S20]]'
  - '[[2026-07-24-service-quiesce-W03-P06-S21]]'
  - '[[2026-07-24-service-quiesce-W03-P06-S22]]'
  - '[[2026-07-24-service-quiesce-W03-P06-summary]]'
  - '[[2026-07-24-service-quiesce-W03-P07-S23]]'
  - '[[2026-07-24-service-quiesce-W03-P07-S25]]'
  - '[[2026-07-24-service-quiesce-W03-P07-S28]]'
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-24-service-quiesce-plan]]'
  - '[[2026-07-24-service-quiesce-research]]'
  - '[[2026-07-29-service-quiesce-w02-audit]]'
  - '[[2026-07-29-service-quiesce-w02-remediation-audit]]'
  - '[[2026-07-30-service-quiesce-w02-resume-recovery-audit]]'
  - '[[2026-07-30-service-quiesce-w03-acceptance-audit]]'
---

# `service-quiesce` feature index

Auto-generated index of all documents tagged with `#service-quiesce`.

## Documents

### adr

- `2026-07-24-service-quiesce-adr` - `service-quiesce` adr: `Acknowledged global resource quiescence` | (**status:** `accepted`)

### audit

- `2026-07-29-service-quiesce-w02-audit` - `service-quiesce` audit: `W02 resource-quiesce implementation review`
- `2026-07-29-service-quiesce-w02-remediation-audit` - `service-quiesce` audit: `w02 remediation`
- `2026-07-30-service-quiesce-w02-resume-recovery-audit` - `service-quiesce` audit: `w02 resume recovery`
- `2026-07-30-service-quiesce-w03-acceptance-audit` - `service-quiesce` audit: `w03 acceptance`

### exec

- `2026-07-24-service-quiesce-P01-S01` - Create the torch-free QuiesceGate primitive over a threading.Event with set equals running and clear equals paused, exposing wait, pause, resume and is_paused plus an absorbing-open latch so that once latched open wait returns immediately and pause and clear become no-ops, with positive unit tests that pause blocks a waiter and resume releases it
- `2026-07-24-service-quiesce-P01-S02` - Integrate the gate into RunControlToken as an optional injected reference where request_cancel and request_shutdown latch the gate open, checkpoint consults the gate first but only when protected depth is zero and re-checks absorbing signals after the gate releases, and a gateless token and NullRunControl stay no-op
- `2026-07-24-service-quiesce-P01-S03` - Add the both-direction guard tests covering worker blocks when quiesced with a bounded join timeout, worker resumes when released, shutdown wins over a concurrent re-pause, and a checkpoint inside a protected span never parks, each proven red-then-green in one sequence
- `2026-07-24-service-quiesce-P02-S04` - Give ServiceRegistry one process-global QuiesceGate constructed beside its GPU lock and expose it through an accessor mirroring the existing gpu_lock property so a single gate governs the whole daemon process
- `2026-07-24-service-quiesce-P02-S05` - Thread the registry gate into JobManager and inject it into each RunControlToken built at both dispatch construction sites so every in-flight job shares the one process-global gate, with a unit test asserting a dispatched token observes the shared gate
- `2026-07-24-service-quiesce-P02-S06` - Inject the gate into VaultSearcher like gpu_lock at each construction site in the registry and wait on the gate at search admission before acquiring gpu_lock in the GPU section, never parking while holding gpu_lock and preserving the torch-free path, with a unit test of admission gating for gpu_lock None and an injected gate
- `2026-07-24-service-quiesce-P03-S08` - Add the server pause and server resume CLI verbs that call the route and emit exactly one structured JSON envelope on every exit path, mirroring the start-success and fail-start helper pattern, with already-paused and already-running returning success exit 0 carrying an already\_\* status
- `2026-07-24-service-quiesce-P03-S09` - Add guard tests for the pause and resume envelope contract proving both directions of the idempotent already\_\* path, where already-paused and already-running return exit 0 with the already\_\* status and a genuine state change returns the changed status, each proven red-then-green
- `2026-07-24-service-quiesce-W02-P04-S10` - Create the serialized resource-quiesce controller with state transitions, epoch-scoped compute tickets, bounded drain acknowledgement and truthful safety snapshots
- `2026-07-24-service-quiesce-W02-P04-S11` - Registry transition coordinator remediation
- `2026-07-24-service-quiesce-W02-P04-S12` - CPU transition-coordinator proof remediation
- `2026-07-24-service-quiesce-W02-P05-S13` - Token-local control separation
- `2026-07-24-service-quiesce-W02-P05-S14` - Managed quiesce reconciliation remediation
- `2026-07-24-service-quiesce-W02-P05-S15` - Streaming safe checkpoint boundaries
- `2026-07-24-service-quiesce-W02-P05-S16` - Search quiescence HTTP 503 remediation
- `2026-07-24-service-quiesce-W02-P05-S17` - CPU managed-job recovery proof remediation
- `2026-07-24-service-quiesce-W02-P05-S18` - CPU search HTTP 503 proof remediation
- `2026-07-24-service-quiesce-W03-P06-S19` - Map typed resume recovery failure to the canonical authenticated retryable lifecycle envelope while warming admission remains closed, and return a repaired retry as running without changing the logical job identity
- `2026-07-24-service-quiesce-W03-P06-S20` - Publish the canonical quiesce block through existing health, jobs, and lifecycle heartbeat cadence without adding a poller, duplicating controller computation, or importing GPU dependencies
- `2026-07-24-service-quiesce-W03-P06-S21` - Add the exact canonical quiesce block to read-only service-state output by projecting the registry controller snapshot once
- `2026-07-24-service-quiesce-W03-P06-S22` - Prove through the authenticated production routes, real registry, real manager writer, and real filesystem that an unpublished resume write returns resume_recovery_failed in closed warming, then directory repair and a second resume return running with the same logical job ID and one recovered generation
- `2026-07-24-service-quiesce-W03-P06-summary` - `service-quiesce` `W03.P06` summary
- `2026-07-24-service-quiesce-W03-P07-S23` - Pass quiesce transition and service-state payloads through the single service-client transport unchanged, including retryable recovery failure, without local GPU behavior
- `2026-07-24-service-quiesce-W03-P07-S25` - Hard-refuse in-process GPU indexing whenever delegation does not succeed and render truthful human and JSON remediation, because neither --allow-fallback nor a quiesced service block authorizes local compute until verified borrower-lease evidence exists
- `2026-07-24-service-quiesce-W03-P07-S28` - Replace server globals with an immutable app-scoped runtime that owns token registry and port, and prove isolated CPU lifecycle behavior

### plan

- `2026-07-24-service-quiesce-plan` - `service-quiesce` plan

### research

- `2026-07-24-service-quiesce-research` - `service-quiesce` research: `Cooperative contention-aware GPU quiesce for the resident service`
