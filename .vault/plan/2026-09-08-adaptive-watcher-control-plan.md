---
tags:
  - '#plan'
  - '#adaptive-watcher-control'
date: '2026-09-08'
tier: L3
related:
  - '[[2026-09-08-adaptive-watcher-control-adr]]'
  - '[[2026-09-08-adaptive-watcher-control-research]]'
  - '[[2026-09-08-adaptive-watcher-control-reference]]'
modified: '2026-09-08'
body_schema: body-v2
body_hash: 'sha256:ab09e8d045a2e96a97bb11a65d578671aa577965dc44ceaae96e37d5e5374a73'
---

<!-- RETIRED: S21, S22 -->

# `adaptive-watcher-control` plan

Replace fixed watcher timing with durable, adaptive, fair service-domain convergence.

## Description

Execute the accepted adaptive convergence decision grounded by the linked research and
reference. Wave W01 establishes the pure controller, policy bounds, and exact-scope durable
authority. Wave W02 integrates that authority with service scheduling, canonical jobs,
measurements, status, HTTP, CLI, and MCP. Wave W03 proves bounded convergence, fairness,
restart safety, pressure recovery, adapter conformance, architectural guards, and operator
documentation.

## Steps

## Wave `W01` - controller and durable scope

Build the pure state machine, validated policy envelope, and versioned exact-scope persistence that all later service integration depends on.

### Phase `W01.P01` - state machine and policy

Define deterministic controller states, decisions, deadlines, measurements, and relational policy validation.

- [x] `W01.P01.S01` - Define controller state, reason, transition, measurement, scope, and snapshot models; `src/vaultspec_rag/watcher_controller.py`.
- [x] `W01.P01.S02` - Implement virtual-clock adaptive coalescing, cooling, pressure, refusal, and convergence decisions; `src/vaultspec_rag/watcher_controller.py`.
- [x] `W01.P01.S03` - Replace free watcher timing settings with validated policy bounds and compatibility mapping; `src/vaultspec_rag/config`.

### Phase `W01.P02` - exact-scope durability

Persist bounded canonical paths and controller fencing so restart recovery is deterministic and fail-closed.

- [x] `W01.P02.S04` - Extend watcher durable state with versioned path observations, bounds, and refusal validation; `src/vaultspec_rag/watcher_retry.py`.
- [x] `W01.P02.S05` - Make event merge, admission fencing, settlement, and cancellation handoff atomic; `src/vaultspec_rag/watcher_durability.py`.
- [x] `W01.P02.S06` - Add virtual-clock and generated-sequence proofs for transitions, deadlines, scope safety, and restart; `src/vaultspec_rag/tests/test_watcher_controller.py`.

## Wave `W02` - service admission and projections

Integrate durable controllers with fair service scheduling, canonical jobs and measurements, then project one fact model through every adapter.

### Phase `W02.P03` - fair scheduler and measurements

Add earliest-deadline fair admission and event/deadline wakeups using canonical service-owned telemetry.

- [x] `W02.P03.S07` - Implement earliest-deadline admission with rotating root and source ties; `src/vaultspec_rag/watcher_admission.py`.
- [x] `W02.P03.S08` - Own controller registration, deadline scheduling, wakeups, and bounded reevaluation in the service; `src/vaultspec_rag/server/_watcher.py`.
- [x] `W02.P03.S09` - Expose immutable job, search, GPU, storage, limiter, and quiesce measurement snapshots to admission; `src/vaultspec_rag/server`.

### Phase `W02.P04` - intake and job lifecycle

Route watcher events and canonical job transitions through the new controller without losing exact scope or authority.

- [x] `W02.P04.S10` - Replace fixed-timing slot reconciliation with durable controller collection and decisions; `src/vaultspec_rag/watcher_intake.py`.
- [x] `W02.P04.S11` - Bind controller generations to canonical watcher job creation, coalescing, and settlement; `src/vaultspec_rag/watcher_execution.py`.
- [x] `W02.P04.S12` - Reconcile restart, cancellation, failure, and terminal rebuild refusal without duplicate admission; `src/vaultspec_rag/watcher_runtime.py`.

### Phase `W02.P05` - canonical observability

Publish controller truth once in the service domain and adapt it without scheduling recomputation.

- [x] `W02.P05.S13` - Add canonical controller snapshots and structured transition evidence to service state, jobs, and logs; `src/vaultspec_rag/api.py`.
- [x] `W02.P05.S14` - Project identical controller facts through watcher and job HTTP routes; `src/vaultspec_rag/server`.
- [x] `W02.P05.S15` - Adapt controller state and stable reasons through CLI and MCP clients; `src/vaultspec_rag/cli`.

## Wave `W03` - convergence proof and operator policy

Prove bounded liveness, fairness, restart safety, pressure behavior, and surface parity, then document the validated policy contract.

### Phase `W03.P06` - integration and load proof

Exercise real watcher events, restarts, sustained churn, multiple roots, service pressure, and adapter parity.

- [ ] `W03.P06.S16` - Cover create, modify, delete, rename, active-job, cooldown, cancellation, failure, and restart convergence; `src/vaultspec_rag/tests/integration`.
- [ ] `W03.P06.S17` - Demonstrate bounded batch frequency, maximum freshness, fair progress, and pressure recovery under load; `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`.
- [ ] `W03.P06.S18` - Assert service, HTTP, CLI, and MCP controller telemetry conformance; `src/vaultspec_rag/tests/integration/test_service_state.py`.

### Phase `W03.P07` - guards and documentation

Mutation-prove architectural invariants and document policy defaults, bounds, refusal, and operator interpretation.

- [ ] `W03.P07.S19` - Add mutation-proved guards for trailing flush, freshness, refusal, exact recovery, fair rotation, and adapter ownership; `src/vaultspec_rag/tests/test_adr_regression.py`.
- [ ] `W03.P07.S20` - Document adaptive policy defaults, validation, telemetry, and rebuild-required remediation; `docs`.

## Parallelization

Waves are strictly ordered. Within W01, S03 may proceed alongside S01-S02, but P02 depends on
the state and policy contracts from P01. Within W02, S07 and S09 may proceed together after
W01; S08 depends on both, P04 depends on the scheduler contract, and P05 depends on canonical
controller snapshots from P04. Within W03, S17 and S18 may proceed after S16 establishes the
integration harness; S19 and S20 may proceed together after behavior and public schemas are
stable. Any parallel work must keep one owner per listed scope and must not duplicate
controller decisions in adapters.

## Verification

- Ruff format and lint pass over every touched Python package and test file, with separate
  captured exit codes.
- Pyright strict checking passes over every changed production and test module.
- Deterministic unit and model/property tests pass without wall-clock sleeps and prove every
  state, deadline, reason, no-loss, no-duplicate, no-unscoped-escalation, and fairness bound.
- Integration tests pass for create, modify, delete, rename, running attempts, cooldown,
  cancellation, failure, restart, corrupt scope, and rebuild-required refusal.
- Multi-root/source load tests demonstrate materially fewer tiny generations while ordinary
  pressure never exceeds the configured maximum freshness age.
- Service, jobs, logs, HTTP, CLI, and MCP expose identical canonical controller facts and
  stable reason codes without adapter-owned scheduling logic.
- Each negative architectural guard is mutation-proved in one uninterrupted fail/restore/pass
  sequence, with the intended assertion recorded in the test.
- Configuration documentation states derived defaults, relational validation, deprecated
  compatibility mapping, visible SLO exceptions, and explicit rebuild remediation.
- Vaultspec plan/check gates pass, all 20 Steps and their execution records are complete, and
  formal `vaultspec-code-review` reports no unresolved blocking findings.
