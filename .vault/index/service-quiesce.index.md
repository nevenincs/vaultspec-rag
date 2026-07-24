---
generated: true
tags:
  - '#index'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - '[[2026-07-24-service-quiesce-P01-S01]]'
  - '[[2026-07-24-service-quiesce-P01-S02]]'
  - '[[2026-07-24-service-quiesce-P01-S03]]'
  - '[[2026-07-24-service-quiesce-P02-S04]]'
  - '[[2026-07-24-service-quiesce-P02-S05]]'
  - '[[2026-07-24-service-quiesce-P02-S06]]'
  - '[[2026-07-24-service-quiesce-P03-S08]]'
  - '[[2026-07-24-service-quiesce-P03-S09]]'
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-24-service-quiesce-plan]]'
  - '[[2026-07-24-service-quiesce-research]]'
---

# `service-quiesce` feature index

Auto-generated index of all documents tagged with `#service-quiesce`.

## Documents

### adr

- `2026-07-24-service-quiesce-adr` - `service-quiesce` adr: `Cooperative zero-CPU GPU quiesce gate` | (**status:** `accepted`)

### exec

- `2026-07-24-service-quiesce-P01-S01` - Create the torch-free QuiesceGate primitive over a threading.Event with set equals running and clear equals paused, exposing wait, pause, resume and is_paused plus an absorbing-open latch so that once latched open wait returns immediately and pause and clear become no-ops, with positive unit tests that pause blocks a waiter and resume releases it
- `2026-07-24-service-quiesce-P01-S02` - Integrate the gate into RunControlToken as an optional injected reference where request_cancel and request_shutdown latch the gate open, checkpoint consults the gate first but only when protected depth is zero and re-checks absorbing signals after the gate releases, and a gateless token and NullRunControl stay no-op
- `2026-07-24-service-quiesce-P01-S03` - Add the both-direction guard tests covering worker blocks when quiesced with a bounded join timeout, worker resumes when released, shutdown wins over a concurrent re-pause, and a checkpoint inside a protected span never parks, each proven red-then-green in one sequence
- `2026-07-24-service-quiesce-P02-S04` - Give ServiceRegistry one process-global QuiesceGate constructed beside its GPU lock and expose it through an accessor mirroring the existing gpu_lock property so a single gate governs the whole daemon process
- `2026-07-24-service-quiesce-P02-S05` - Thread the registry gate into JobManager and inject it into each RunControlToken built at both dispatch construction sites so every in-flight job shares the one process-global gate, with a unit test asserting a dispatched token observes the shared gate
- `2026-07-24-service-quiesce-P02-S06` - Inject the gate into VaultSearcher like gpu_lock at each construction site in the registry and wait on the gate at search admission before acquiring gpu_lock in the GPU section, never parking while holding gpu_lock and preserving the torch-free path, with a unit test of admission gating for gpu_lock None and an injected gate
- `2026-07-24-service-quiesce-P03-S08` - Add the server pause and server resume CLI verbs that call the route and emit exactly one structured JSON envelope on every exit path, mirroring the start-success and fail-start helper pattern, with already-paused and already-running returning success exit 0 carrying an already_* status
- `2026-07-24-service-quiesce-P03-S09` - Add guard tests for the pause and resume envelope contract proving both directions of the idempotent already_* path, where already-paused and already-running return exit 0 with the already_* status and a genuine state change returns the changed status, each proven red-then-green

### plan

- `2026-07-24-service-quiesce-plan` - `service-quiesce` plan

### research

- `2026-07-24-service-quiesce-research` - `service-quiesce` research: `Cooperative contention-aware GPU quiesce for the resident service`
