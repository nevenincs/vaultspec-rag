---
tags:
  - '#reference'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:14c1ca728024e703a2cbaed29e1f5e2a2b61a06a17921d4e08d7c1aaf032219e'
related:
  - "[[2026-09-08-adaptive-watcher-control-research]]"
  - "[[2026-09-07-explicit-reindex-authority-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
---

# `adaptive-watcher-control` reference: `current convergence topology`

## Summary

The automatic watcher is a per-root intake coroutine with independent vault, code, and
document convergence slots. It preserves exact scope in a live process, coalesces concurrent
edits, flushes quiet-tree trailing work, deduplicates through canonical jobs, and persists
retry/circuit intent. It is not an adaptive controller: timing is fixed, pending paths are
not durable, admission consumes no service pressure, and controller facts have no canonical
status projection.

### Collection and exact scope

- `watcher_intake.py:195-383` owns the watch loop; fixed debounce and one-second idle yield
  feed every real batch and idle tick through persistence and reconciliation.
- `watcher_policy.py:25-103` is the canonical event-to-source classification boundary.
- `watcher_intake.py:79-142` records additions, modifications, and deletions; deleted paths
  use prior durable content ownership because their current content cannot be inspected.
- `watcher_runtime.py:133-219` owns pending, held, and immutable per-attempt path sets. Later
  events remain pending while an attempt runs.
- `watcher_runtime.py:289-334` retires only captured paths after success and restores held
  paths after other terminal outcomes. `watcher_runtime.py:447-474` does the same when bounded
  job history no longer contains the exact owner.
- `watcher_execution.py:69-230` preflights exact scope, creates or attaches to the canonical
  job, and binds the batch. `watcher_execution.py:581-679` revalidates and passes it as
  `changed_paths`.
- `watcher_retry.py:241-284`, `watcher_retry.py:794-842`, and
  `watcher_retry.py:902-922` refuse full discovery when scope is lost.

### Convergence and durability

- `watcher_intake.py:441-536` sequences quiesce, settlement, job observation, retry refresh,
  fixed cooldown/replacement eligibility, circuit admission, and submission.
- `watcher_runtime.py:39-43` and `watcher_runtime.py:172-188` own a separate capped 1-30 second
  orchestration-replacement backoff.
- `watcher_execution.py:114-178` attaches to equivalent canonical jobs while retaining dirty
  scope for conservative follow-up.
- `watcher_retry.py:98-120` defines versioned per-root/source durable state;
  `watcher_retry.py:323-539` advances intent and admits single-flight attempts;
  `watcher_retry.py:575-722` settles outcomes; and `watcher_retry.py:1127-1318` writes
  atomically and bounds/validates reads.
- `watcher_durability.py:43-223` centralizes cancellation-safe persistence transactions.
  `watcher_durability.py:316-429` durably records observed sources and admission.
- `server/_watcher.py:202-932` owns watcher lifecycle and managed-attempt shutdown.

### Service telemetry and presentation seams

- `job_models.py:347-715` exposes canonical initiator, source, attempts, cost class, timing,
  progress, process resources, GPU-lock waits, and resilience.
- `server/_routes_jobs.py:222-527` and `server/_routes_jobs.py:786-926` derive canonical queue,
  runtime, stall, degradation, and pressure summaries.
- `pressure.py:87-339` owns hysteretic machine pressure over GPU saturation, encode backlog,
  backend latency, and storage failures.
- `server/_search_activity.py:86-313` owns bounded search-demand and latency evidence;
  `server/_routes_storage.py:285-365` exposes storage survey evidence.
- `server/_routes_registry.py:58-76` currently exposes only watched roots and static timing.
  `cli/_service_watcher.py:100-124` and `cli/_service_watcher.py:244-272` adapt that service
  payload without recomputing scheduling.

### Blueprint and missing proof

Keep classification pure in `watcher_policy.py`; make one per-root/source controller the
exact-scope, timestamps, state, transition, and deadline owner; extend the existing bounded
durability transaction rather than creating another ledger; use a service-owned fair
automatic-work arbiter to consume canonical measurements; leave execution and deduplication
with `JobManager`; and project one controller snapshot through service, HTTP, CLI, and MCP.

Existing tests cover retry/circuit/restart refusal in `tests/test_watcher_retry.py:102-967`,
quiesce in `tests/test_watcher_quiesce_intake.py:51-161`, routing in
`tests/integration/test_document_watcher.py:176-215`, scoped admission in
`tests/integration/test_watcher_content_admission.py:75-154`, control/coalescing in
`tests/integration/test_service_job_control_watcher.py:129-286`, and quiet-tree/failure
recovery in `tests/integration/test_server_stress_and_watcher.py:847-1285`. Missing proof
includes a virtual-clock state model, randomized no-loss/no-starvation properties, durable
exact-path restart, sustained-churn freshness bounds, multi-root/source fairness,
pressure-driven admission, and cross-surface telemetry conformance.
