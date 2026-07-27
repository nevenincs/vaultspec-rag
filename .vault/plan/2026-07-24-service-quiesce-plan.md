---
tags:
  - '#plan'
  - '#service-quiesce'
date: '2026-07-24'
modified: '2026-07-27'
tier: L2
related:
  - '[[2026-07-24-service-quiesce-adr]]'
  - '[[2026-07-24-service-quiesce-research]]'
---
# `service-quiesce` plan

## Description

This plan executes only Phase 1 of the governing decision: the in-process,
zero-CPU cooperative quiesce gate that lets the resident daemon stand down for a
short-lived external GPU consumer and resume afterward, honoured at every
unprotected indexer checkpoint and at search admission, with a `server pause` /
`server resume` operator surface. The whole Phase-1 boundary is pure `threading`
and OS code, GPU-free, and fully green on any host. `P01` builds the primitive and
the token latch, `P02` wires one process-global gate into the service, jobs, and
search, and `P03` adds the structured-idempotent operability verbs. The decision
and its research back every Step and are named in `related:`.

The load-bearing correctness point is the absorbing-open latch: an absorbing
shutdown or cancel request must always win over a hold, with no lost wakeup even
when a `pause()` races a pending absorbing request, so a quiesced worker can never
block forever. The gate primitive must carry no torch import so it stays importable
from the spawn-worker chain and from search, and its wait must never sit inside a
`gpu_lock`, a `protected()` span, or a held store write.

Phase 2 is explicitly deferred and is NOT planned as Steps here. Its work - the
second OS advisory lock quiesce lease held by the external actor, the daemon-side
observer and wakeup design that turns a held lease into an actual quiesce and frees
idle resident VRAM, the `torch.cuda.empty_cache()` VRAM release driven from the
pause path behind the centralized GPU gate, and the GPU-live end-to-end
verification that the daemon frees VRAM and a co-scheduled consumer succeeds - all
require a coordinated GPU maintenance window because any GPU-live test co-schedules
against the resident service that holds several GiB, the exact 16 GiB OOM hazard
this feature exists to prevent. Phase 1 `server pause` is the honest synchronous
interim for the idle-daemon case and the natural future site for `empty_cache()`.
Phase 2 is sequenced after this plan and is out of its scope.

## Steps

### Phase `P01` - QuiesceGate primitive and RunControlToken latch integration

Deliver the torch-free QuiesceGate (Event set=running/clear=paused, absorbing-open latch) and wire it into RunControlToken so checkpoint() consults the gate first, protected-aware, with absorbing shutdown/cancel latching the gate open irreversibly; proven by both-direction guard tests.

- [x] `P01.S01` - Create the torch-free QuiesceGate primitive over a threading.Event with set equals running and clear equals paused, exposing wait, pause, resume and is_paused plus an absorbing-open latch so that once latched open wait returns immediately and pause and clear become no-ops, with positive unit tests that pause blocks a waiter and resume releases it; `src/vaultspec_rag/job_control.py`.
- [x] `P01.S02` - Integrate the gate into RunControlToken as an optional injected reference where request_cancel and request_shutdown latch the gate open, checkpoint consults the gate first but only when protected depth is zero and re-checks absorbing signals after the gate releases, and a gateless token and NullRunControl stay no-op; `src/vaultspec_rag/job_control.py`.
- [x] `P01.S03` - Add the both-direction guard tests covering worker blocks when quiesced with a bounded join timeout, worker resumes when released, shutdown wins over a concurrent re-pause, and a checkpoint inside a protected span never parks, each proven red-then-green in one sequence; `src/vaultspec_rag/tests/test_job_control_unit.py`.

### Phase `P02` - Process-global wiring into the service and search

Give ServiceRegistry one process-global QuiesceGate beside its GPU lock, inject it into every RunControlToken the JobManager builds so all in-flight jobs share one gate, and gate search at admission before the GPU section without parking under the GPU lock.

- [x] `P02.S04` - Give ServiceRegistry one process-global QuiesceGate constructed beside its GPU lock and expose it through an accessor mirroring the existing gpu_lock property so a single gate governs the whole daemon process; `src/vaultspec_rag/service.py`.
- [x] `P02.S05` - Thread the registry gate into JobManager and inject it into each RunControlToken built at both dispatch construction sites so every in-flight job shares the one process-global gate, with a unit test asserting a dispatched token observes the shared gate; `src/vaultspec_rag/job_manager.py`.
- [x] `P02.S06` - Inject the gate into VaultSearcher like gpu_lock at each construction site in the registry and wait on the gate at search admission before acquiring gpu_lock in the GPU section, never parking while holding gpu_lock and preserving the torch-free path, with a unit test of admission gating for gpu_lock None and an injected gate; `src/vaultspec_rag/search/_searcher.py`.

### Phase `P03` - server pause / server resume operability surface

Add service-domain pause/resume behavior over the gate and the server pause / server resume CLI verbs mirroring the structured-idempotent JSON envelope pattern, treating already-paused/already-running as success exit 0 with an already\_\* status.

- [x] `P03.S07` - Add service-domain pause and resume behavior driving the registry gate and expose it through a localhost server route returning a structured status of paused, already_paused, running or already_running so the CLI adapts to service-owned behavior rather than owning it; `src/vaultspec_rag/server/_routes.py`.
- [x] `P03.S08` - Add the server pause and server resume CLI verbs that call the route and emit exactly one structured JSON envelope on every exit path, mirroring the start-success and fail-start helper pattern, with already-paused and already-running returning success exit 0 carrying an already\_\* status; `src/vaultspec_rag/cli/_service_quiesce.py`.
- [x] `P03.S09` - Add guard tests for the pause and resume envelope contract proving both directions of the idempotent already\_\* path, where already-paused and already-running return exit 0 with the already\_\* status and a genuine state change returns the changed status, each proven red-then-green; `src/vaultspec_rag/tests/test_service_quiesce_cli.py`.

## Parallelization

The Phases carry hard ordering and run sequentially. `P02` cannot begin until
`P01` lands, because `P02` injects the `P01` gate and latched token into the
service, jobs, and search. `P03` cannot begin until `P02` exposes the
process-global gate on the registry that the pause and resume behavior drives.
Within `P01`, `S01` (primitive) precedes `S02` (token integration), and `S03`
(guards) follows both. Within `P02` the three wiring Steps `S04`, `S05`, `S06`
touch independent modules and may proceed in parallel once `S04` exposes the gate
accessor. Within `P03`, `S07` (service behavior and route) precedes `S08` (CLI
verbs), and `S09` (envelope guards) follows both.

## Verification

The plan is complete when every Step is closed (`- [x]`) and the following hold:

- No busy-loop or sleep-poll exists anywhere in the gate path: the wait is
  `Event.wait` and the latch only, and a reviewer confirms no sleep-poll on any
  worker, admission, or observer path.
- The gate primitive and every module on the spawn-worker import chain and the
  search path remain torch-free: no new module-scope or function-local `torch`
  import is introduced by the gate, and the existing lazy-import regression guard
  stays green.
- The gate wait never sits inside a `gpu_lock`, a `protected()` span, or a held
  store write at any checkpoint or admission site, and the streaming checkpoints
  stay outside `gpu_lock` as they are today.
- The three both-direction guards (worker blocks when quiesced, worker resumes when
  released, shutdown wins over a concurrent re-pause) and the protected-aware guard
  are each proven red-then-green in one uninterrupted sequence and recorded in the
  respective Step Record.
- The `server pause` and `server resume` envelope contract emits exactly one
  structured envelope per exit path and treats already-paused and already-running
  as success exit 0 with an `already_*` status, with both directions of the
  idempotent path proven red-then-green and recorded in the Step Record.
- Green gate per Step where sensible: `uv run --no-sync ruff check src tools`
  wholesale, `ty check`, and the relevant unit and guard tests pass.

For tier-specific verification cadence, see the authorizing documents linked in the
`related:` frontmatter.
