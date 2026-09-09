---
tags:
  - '#audit'
  - '#adaptive-watcher-control'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:68ddd9dec28dbe3fb783175e31cbe7abd6addc7a042ba15caeae32a531b4f7e8'
related: []
---

# `adaptive-watcher-control` audit: `whole-branch final review`

## Scope

The complete `origin/main...HEAD` change set for issue 470 was reviewed against the
accepted research, reference, ADR, and L3 plan. The audit covered controller policy,
exact-scope persistence, admission fencing, restart and settlement behavior, scheduler
lifecycle, canonical service measurements, HTTP/CLI/MCP projections, configuration,
operator documentation, and the associated deterministic, integration, load,
conformance, and architectural-guard tests. The review focused on safety, single-owner
architecture, bounded convergence, restart durability, and whether production wiring
actually exercises the behavior proved by isolated tests.

## Findings

### telemetry-clock-domain | medium | Controller projections mix monotonic and wall-clock timestamps

`controller_scope_from_retry_state` deliberately translates persisted wall timestamps to
the process monotonic clock, and controller deadlines and measurement timestamps remain in
that clock domain. `controller_snapshot_envelope` then subtracts those values from
`time.time()` and publishes the raw monotonic observations and deadlines as operator
timestamps. On a real process this reports an `oldest_age_seconds` near the Unix epoch and
emits `first_observed_at`, `next_decision_at`, `freshness_deadline`, measurement
`observed_at`, and transition `deadline` values that are not wall timestamps. The public
telemetry therefore cannot truthfully explain freshness or the next decision, despite the
isolated projection tests passing because they supply an `observed_at` in the same synthetic
clock domain.

### unused-service-measurements | high | Production admission ignores canonical service pressure

The scheduler's production `reevaluate` callback constructs
`ControllerMeasurement(generation=0, observed_at=time.monotonic())` with every service
field absent. The new `compose_watcher_measurement` adapter has no production caller; it is
referenced only by its own unit tests. Consequently backlog, active search, GPU pressure,
storage availability, quiesce state, effective cost, and measurement generations never
influence a real watcher controller. Storage unavailability and quiesce are especially
unsafe omissions because the ADR permits those safety conditions to exceed the freshness
deadline, whereas the empty production measurement allows admission. This leaves the core
"service-aware" requirement implemented as an unused parallel path rather than canonical
production behavior.

### captured-scope-preflight-failure | high | Preflight exceptions strand a durable admission fence

`submit_watcher_job` durably moves pending paths into captured scope and records a proposed
job ID before running code/document preflight and before calling `JobManager.create`.
Exceptions from either operation escape without settling the fenced attempt. The scheduler
logs the callback failure, but subsequent admissions find no `pending_paths` and return,
while the durable record retains captured paths and an attempt/job identity for a job that
was never created. That root/source can no longer converge in the live process and can
remain beyond maximum freshness; after restart it is conservatively refused because the
fenced job is absent. No integration test covers a preflight or manager exception after the
durable capture boundary.

## Recommendations

- For `telemetry-clock-domain`, preserve wall-clock observation/deadline equivalents in the
  canonical snapshot or convert monotonic values at the service projection boundary using
  one captured wall/monotonic pair. Add a real-clock projection test that asserts plausible
  ages and wall timestamps.
- For `unused-service-measurements`, wire the service scheduler to capture existing
  canonical job, limiter, search, pressure, storage, quiesce, retry, and cost facts and pass
  the composed measurement into every production reevaluation. Remove any unused parallel
  measurement path, and add an integration test proving pressure and safety changes alter
  admission without adapter recomputation.
- For `captured-scope-preflight-failure`, make every failure after durable scope capture
  settle the exact generation before returning or raising, restoring captured paths for a
  retryable failure and preserving typed refusal where policy requires it. Cover both
  preflight exceptions and `JobManager.create` exceptions with restart-aware tests.

## Resolution verification

### telemetry-clock-domain | resolved

`ControllerSnapshot` now retains the monotonic instant paired with its wall-clock
`observed_at`, and every controller transition refreshes both values from the injected
clocks. `controller_snapshot_envelope` uses that pair to calculate ages in the monotonic
domain and converts observation, measurement, decision, freshness, retry, and transition
deadlines to wall time before publication. The focused real-clock regression exercises the
default production projection path and verifies plausible age and converted timestamps.

### unused-service-measurements | resolved

The production controller registration now captures a fresh, incrementing service
measurement on a worker thread for every reevaluation and passes its controller projection
to `WatcherController.evaluate`. `capture_watcher_measurement` reads the canonical manager,
limiter, search-activity, machine-pressure/backend, quiesce, retry, and incremental-cost
owners before composing the immutable snapshot. The prior empty generation-zero production
measurement no longer exists. The focused production-binding regression injects unavailable
storage through this capture seam and verifies the real reevaluation callback enters typed
`storage_pressure` backpressure with the captured generation.

### captured-scope-preflight-failure | resolved

The complete interval after durable capture and before confirmed job creation is now
protected. When scoped preflight or `JobManager.create` raises and the proposed job does not
exist, `_restore_uncreated_admission` durably settles the exact generation as interrupted,
restores its captured paths, re-observes that scope in the controller, and wakes the
scheduler before the original exception is re-raised. Parameterized focused regressions
exercise both exception sites and verify pending paths, cleared capture/fence identity, and
the live controller state.

The focused controller projection, production intake binding, measurement composition, and
pre-creation recovery suite passed 12 tests. No unresolved critical, high, or medium finding
remains in this audit.
