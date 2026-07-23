---
generated: true
tags:
  - '#index'
  - '#machine-discovery-recovery'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-S01]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-S02]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-S03]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P01-summary]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P02-S04]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P02-S05]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P03-S06]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P03-S07]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P03-S08]]'
  - '[[2026-07-21-machine-discovery-recovery-W01-P04-S09]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P05-S10]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P05-S11]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P05-S12]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P06-S13]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P06-S14]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P06-S15]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P06-S16]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P07-S17]]'
  - '[[2026-07-21-machine-discovery-recovery-W02-P07-S18]]'
  - '[[2026-07-21-machine-discovery-recovery-W03-P08-S19]]'
  - '[[2026-07-21-machine-discovery-recovery-W03-P08-S20]]'
  - '[[2026-07-21-machine-discovery-recovery-W03-P08-S21]]'
  - '[[2026-07-21-machine-discovery-recovery-W03-P08-S22]]'
  - '[[2026-07-21-machine-discovery-recovery-W03-P09-S23]]'
  - '[[2026-07-21-machine-discovery-recovery-W04-P10-S27]]'
  - '[[2026-07-21-machine-discovery-recovery-W04-P10-S28]]'
  - '[[2026-07-21-machine-discovery-recovery-W04-P10-S29]]'
  - '[[2026-07-21-machine-discovery-recovery-W04-P10-S30]]'
  - '[[2026-07-21-machine-discovery-recovery-W04-P10-S31]]'
  - '[[2026-07-21-machine-discovery-recovery-W04-P10-S32]]'
  - '[[2026-07-21-machine-discovery-recovery-W04-P10-S33]]'
  - '[[2026-07-21-machine-discovery-recovery-adr]]'
  - '[[2026-07-21-machine-discovery-recovery-plan]]'
  - '[[2026-07-21-machine-discovery-recovery-reference]]'
  - '[[2026-07-21-machine-discovery-recovery-research]]'
  - '[[2026-07-21-machine-discovery-recovery-s01-test-isolation-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s02-containment-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s03-isolation-tests-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s04-owner-lease-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s05-owner-proof-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s06-heartbeat-snapshot-audit]]'
  - '[[2026-07-22-machine-discovery-recovery-s07-lifecycle-lease-audit]]'
  - '[[2026-07-23-machine-discovery-recovery-closing-review-audit]]'
---

# `machine-discovery-recovery` feature index

Auto-generated index of all documents tagged with `#machine-discovery-recovery`.

## Documents

### adr

- `2026-07-21-machine-discovery-recovery-adr` - `machine-discovery-recovery` adr: `owner-authenticated, self-healing service discovery` | (**status:** `accepted`)

### audit

- `2026-07-21-machine-discovery-recovery-s01-test-isolation-audit` - `machine-discovery-recovery` audit: `W01.P01.S01 singleton test isolation`
- `2026-07-22-machine-discovery-recovery-s02-containment-audit` - `machine-discovery-recovery` audit: `W01.P01.S02 containment guard`
- `2026-07-22-machine-discovery-recovery-s03-isolation-tests-audit` - `machine-discovery-recovery` audit: `W01.P01.S03 managed singleton isolation regressions`
- `2026-07-22-machine-discovery-recovery-s04-owner-lease-audit` - `machine-discovery-recovery` audit: `W01.P02.S04 retained owner lease`
- `2026-07-22-machine-discovery-recovery-s05-owner-proof-audit` - `machine-discovery-recovery` audit: `W01.P02.S05 real owner proof`
- `2026-07-22-machine-discovery-recovery-s06-heartbeat-snapshot-audit` - `machine-discovery-recovery` audit: `W01.P03.S06 heartbeat snapshots`
- `2026-07-22-machine-discovery-recovery-s07-lifecycle-lease-audit` - `machine-discovery-recovery` audit: `s07 lifecycle lease`
- `2026-07-23-machine-discovery-recovery-closing-review-audit` - `machine-discovery-recovery` audit: `independent closing review — passed, two low follow-ups`

### exec

- `2026-07-21-machine-discovery-recovery-W01-P01-S01` - Force status and Qdrant storage paths beneath one session-owned temporary root and reset cached configuration at every test boundary
- `2026-07-21-machine-discovery-recovery-W01-P01-S02` - Enforce the session-owned containment root before singleton writes and process control whenever pytest is active
- `2026-07-21-machine-discovery-recovery-W01-P01-S03` - Prove ambient and in-test path changes cannot redirect singleton writers into a test-owned trap outside the session root
- `2026-07-21-machine-discovery-recovery-W01-P01-summary` - `machine-discovery-recovery` `W01.P01` summary
- `2026-07-21-machine-discovery-recovery-W01-P02-S04` - Define a retained machine-lock lease and owner-checked atomic pointer publish and delete primitives
- `2026-07-21-machine-discovery-recovery-W01-P02-S05` - Verify a real foreign lock holder blocks pointer publication and deletion while the retained owner succeeds
- `2026-07-21-machine-discovery-recovery-W01-P03-S06` - Build heartbeat snapshots from daemon-owned state and repair both discovery views independently
- `2026-07-21-machine-discovery-recovery-W01-P03-S07` - Thread the retained lease through startup and quiesce heartbeat before owner cleanup and lock release
- `2026-07-21-machine-discovery-recovery-W01-P03-S08` - Verify deleted records self-heal and shutdown cannot resurrect discovery after cleanup
- `2026-07-21-machine-discovery-recovery-W01-P04-S09` - Prove a losing real HTTP daemon exits nonzero before listener, Qdrant, pointer, watcher, or maintenance startup
- `2026-07-21-machine-discovery-recovery-W02-P05-S10` - Define typed machine resolution with holder and pointer identity, freshness, source, and reasoned degraded states
- `2026-07-21-machine-discovery-recovery-W02-P05-S11` - Export typed discovery without widening the torch-free service-client import surface
- `2026-07-21-machine-discovery-recovery-W02-P05-S12` - Verify ready, absent, missing, invalid, stale, foreign-PID, and legacy fallback resolution against real locks
- `2026-07-21-machine-discovery-recovery-W02-P06-S13` - Define the canonical discovery status and health-composition model shared by operator adapters
- `2026-07-21-machine-discovery-recovery-W02-P06-S14` - Adapt server status rendering and exit semantics to ready, degraded, and absent discovery verdicts
- `2026-07-21-machine-discovery-recovery-W02-P06-S15` - Adapt server doctor to the canonical discovery status without duplicating resolution logic
- `2026-07-21-machine-discovery-recovery-W02-P06-S16` - Verify human and JSON status and doctor outcomes preserve typed discovery evidence
- `2026-07-21-machine-discovery-recovery-W02-P07-S17` - Propagate typed degraded discovery through service-dependent transport errors without compatibility fallback
- `2026-07-21-machine-discovery-recovery-W02-P07-S18` - Verify service clients fail fast with holder and pointer evidence for every degraded resolution
- `2026-07-21-machine-discovery-recovery-W03-P08-S19` - Implement bounded owner-driven reconcile over repeated typed resolution and identity-confirmed health
- `2026-07-21-machine-discovery-recovery-W03-P08-S20` - Expose an idempotent non-destructive server reconcile command with structured outcomes
- `2026-07-21-machine-discovery-recovery-W03-P08-S21` - Register the reconcile adapter without changing existing lifecycle command contracts
- `2026-07-21-machine-discovery-recovery-W03-P08-S22` - Verify real-daemon recovery from deleted, stale, and foreign pointers without PID change or process termination
- `2026-07-21-machine-discovery-recovery-W03-P09-S23` - Revise the public discovery schema, ownership, degraded-state, and reconcile contract through vaultspec-documentation
- `2026-07-21-machine-discovery-recovery-W04-P10-S27` - Bound the late-spawn cleanup process-control waits so the cleanup honours its timeout: bound the process-table discovery scan by the caller's remaining deadline, and stop sending a Windows console-group break to arbitrary discovered pids that are not process-group leaders
- `2026-07-21-machine-discovery-recovery-W04-P10-S28` - Bound the daemon shutdown store teardown so a wedged consumer's writer lock cannot hold the daemon in an unbounded shutdown: acquire the store's collection locks under a finite deadline at shutdown and force-close the client past a lock still held past that deadline
- `2026-07-21-machine-discovery-recovery-W04-P10-S29` - Backstop the daemon shutdown with a gated os._exit so a wedged periodic to_thread worker cannot hang the interpreter-exit executor join
- `2026-07-21-machine-discovery-recovery-W04-P10-S30` - Bound the discovery-publisher guard acquisitions at shutdown so a heartbeat worker wedged mid-publish cannot strand teardown before any shutdown line is logged, and bound the pre-exit log flush
- `2026-07-21-machine-discovery-recovery-W04-P10-S31` - Make the authoritative RUNNING-phase publication fail-loud so a machine-singleton daemon that cannot record its running-owner claim rolls back instead of serving
- `2026-07-21-machine-discovery-recovery-W04-P10-S32` - Correct the server stop path documentation to state that on Windows the stop degrades to a TerminateProcess force-kill because the daemon is spawned detached and cannot receive a cross-console CTRL_BREAK from a separate stop process, which is bounded and safe but not a graceful in-daemon shutdown
- `2026-07-21-machine-discovery-recovery-W04-P10-S33` - Route the real-daemon test cleanup graceful signal to the spawned group-leader process rather than the discovered descendant daemon pid so a relaunched daemon receives the console break and shuts down gracefully, escalating to a pid-targeted force-kill on both when the graceful drain does not complete

### plan

- `2026-07-21-machine-discovery-recovery-plan` - `machine-discovery-recovery` plan

### reference

- `2026-07-21-machine-discovery-recovery-reference` - `machine-discovery-recovery` reference: `ownership, resolution, and recovery seams`

### research

- `2026-07-21-machine-discovery-recovery-research` - `machine-discovery-recovery` research: `self-healing owner-authenticated discovery`
