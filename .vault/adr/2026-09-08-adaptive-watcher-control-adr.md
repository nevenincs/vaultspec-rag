---
tags:
  - '#adr'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:f67f30785cbf6bc05abd6d26766b2a9aeb51d697d34e05332d92ec2d942330b6'
related:
  - "[[2026-09-08-adaptive-watcher-control-research]]"
  - "[[2026-09-08-adaptive-watcher-control-reference]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
---

# `adaptive-watcher-control` adr: `durable adaptive automatic convergence` | (**status:** `accepted`)

## Problem Statement

Automatic convergence preserves scoped changes and canonical job ownership but makes
fixed, process-local, workload-blind timing decisions. Long jobs followed by continuing
edits can therefore create repeated small generations without accounting for freshness,
cost, fairness, demand, backlog, or service pressure. This decision replaces accumulated
timing logic with one durable controller per canonical root/source and one service-owned
fair admission arbiter; `JobManager` remains the sole execution owner. The evidence and
existing topology are grounded by `2026-09-08-adaptive-watcher-control-research` and
`2026-09-08-adaptive-watcher-control-reference`.

## Considerations

- Exact-scope automatic work and terminal rebuild refusal from
  `2026-09-07-explicit-reindex-authority-adr` remain binding.
- Scoped deletion routing and quiet-tree trailing flush from the accepted watcher decisions
  remain binding.
- Job lifecycle, deduplication, persistence, and resource release remain service-domain job
  behavior under `2026-07-21-service-job-control-adr`.
- Canonical pressure, search, storage, GPU, limiter, and job measurements are consumed as
  immutable service snapshots, never independently reimplemented by the controller.
- Durable scope overflow cannot truncate paths; it must stop automatic admission with an
  actionable typed refusal while preserving the last complete generation.
- Persisted wall time supports restart and operator age; injected monotonic time governs
  in-process deadlines, with bounded clock-skew recovery.

## Considered options

- **Increase debounce and cooldown.** Rejected: larger constants provide neither adaptive
  fairness nor restart durability, pressure awareness, or a maximum freshness guarantee.
- **Extend each watcher task and convergence slot independently.** Rejected: admission
  remains distributed across roots and unavailable as canonical service truth.
- **Move convergence policy into `JobManager`.** Rejected: filesystem scope and churn are
  source-specific control concerns, not generic job lifecycle behavior.
- **Durable per-root/source controllers plus a service-owned fair arbiter.** Chosen: local
  exact-scope ownership and global admission fairness compose without duplicating execution.

## Constraints

Controller states are `idle`, `collecting`, `ready`, `admitted`, `running`,
`cooling_down`, `backpressured`, `retrying`, `refused`, and `converged`. Every transition
records source and destination, wall time, stable reason code, relevant deadline, and the
measurement generation used.

Reason codes cover observation/coalescing (`change_observed`, `coalesce_window_active`,
`quiet_tree_deadline`, `batch_limit_reached`, `maximum_freshness_due`), admission/execution
(`fair_turn_selected`, `job_admitted`, `job_started`, `job_completed`, `job_cancelled`,
`job_superseded`), backpressure (`post_success_cost_delay`, `job_backlog`,
`search_pressure`, `gpu_pressure`, `storage_pressure`, `service_quiesced`), retry
(`retry_delay_active`, `retry_admitted`, `circuit_open`), refusal
(`full_reindex_required`, `scope_state_invalid`, `scope_capacity_exceeded`,
`controller_schema_unsupported`), and `converged`. They are additive public API; adapters
may label but not replace them.

Pending scope is root-relative, source-qualified, deduplicated, and records first/latest
observation, event kinds, and generation. Deletes remain first-class; unproven renames remain
delete plus add. The default maximum automatic freshness age is 300 seconds. Ordinary search,
GPU, backlog, churn, and cost pressure may defer only to that deadline. Quiesce, unavailable
storage, open safety circuits, and typed refusal may exceed it and must expose the breach.

Fair selection is earliest-deadline-first with rotating root/source order for equal
deadlines. A selection owns an admission claim, not a global execution lock. Automatic work
always requests incremental cost; effective rebuild cost or unknown scope enters `refused`.
Only a later exact-scope event in the same authority generation, or explicit rebuild followed
by reconciliation, may clear rebuild refusal. The accepted parent features are stable and are
refined only by adding this controller layer.

## Implementation

Introduce a pure controller state machine with injected clocks for each canonical
`(root, source)`. Intake durably merges paths before acknowledging an event batch. Running
attempts capture an immutable generation while later changes accumulate separately.

Persist versioned controller records atomically in the project data directory, bounded by
default limits of 100,000 paths and 8 MiB per controller. Foreign roots, escaping paths,
malformed events, unsupported schemas, invalid timestamps, oversize state, and incomplete
attempt fencing fail closed; corrupt records remain available for diagnosis and never become
empty or unscoped work.

Derive coalescing from arrival rate, repeated-path ratio, pending cardinality, and prior
successful duration, clamped by default between 2 and 30 seconds. Derive post-success cooling
from run/publication duration, clamped between 0 and 120 seconds. Both are capped by the
oldest-event freshness deadline. Existing durable retry/circuit policy handles failures;
cancellation and supersession restore captured scope before reevaluation.

One service scheduler owns controller deadlines. Filesystem events, job transitions,
pressure/quiesce changes, and operator actions wake it; otherwise it sleeps until the earliest
deadline, with a bounded five-second reevaluation for measurements lacking notifications.
The arbiter consumes timestamped, generation-stamped service snapshots and treats absent
measurements as unavailable rather than grounds for indefinite delay.

Admission creates or joins an incremental watcher job through `JobManager`, durably fencing
controller attempt and job identity before dispatch. Settlement is durable before captured
paths are consumed. Restart reconciles fenced attempts with durable job history and either
restores exact work, recognizes settlement, or refuses unsafe recovery.

Expose one canonical snapshot containing state/reason, pending count and age, observations,
captured generation, next decision, freshness deadline, selected measurements, backpressure,
last transition, job identity, retry/circuit state, and remediation. Service status, jobs,
logs, HTTP, CLI, and MCP project it without scheduling calculations. Replace free timing
overrides with relationally validated policy bounds; retain a documented deprecated mapping
for existing debounce/cooldown inputs.

Verification uses virtual-clock transition tests, randomized model properties, real watcher
restart/integration tests, multi-root/source load tests, pressure scenarios, projection
conformance, and mutation-proved guards for quiet flush, freshness, refusal, recovery scope,
fair rotation, and absence of adapter scheduling.

## Rationale

This separation gives each fact one owner: controllers own durable local convergence, the
arbiter owns cross-controller fairness, and `JobManager` owns execution. Deadline-capped
adaptivity can reduce small repeated generations without sacrificing a testable freshness
obligation. Earliest-deadline selection gives bounded progress without a global execution
lock, and typed refusal preserves explicit full-reindex authority. Persisted measurement
evidence makes recovery deterministic and every operator surface explainable, as required by
the gaps identified in the linked research and reference.

## Consequences

Automatic convergence gains cost-aware batching, bounded ordinary-pressure deferral, fair
multi-root/source progress, deterministic exact-scope restart, and stable explanations across
all service surfaces. Execution concurrency, GPU locking, storage locking, and job capacity
remain unchanged.

The cost is a new durable schema, scheduler, admission arbiter, compatibility migration, and
crash-reconciliation model. Oversized or invalid scope intentionally produces an actionable
refusal and visible freshness breach instead of truncation or accidental full discovery.
