---
tags:
  - '#adr'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
related:
  - "[[2026-07-23-index-job-backend-resilience-research]]"
  - '[[2026-06-30-qdrant-store-resilience-adr]]'
  - '[[2026-07-21-index-backpressure-storage-hygiene-adr]]'
---

# `index-job-backend-resilience` adr: `bounded transient retry across all store operations` | (**status:** `accepted`)

## Problem Statement

Background index jobs fail hard when the managed vector store is briefly unreachable - a restart, a corrupt-collection quarantine cycle, or a runner outliving its backend - even though the store already knows how to retry a transient failure. As grounded in `2026-07-23-index-job-backend-resilience-research`, that bounded retry wraps only the upsert write, while the connection-establishment, collection-ensure, and read operations a job runs first are single-shot and die immediately on a refused connection. A decision is needed on how store operations survive a transient unavailability window without abandoning the job.

## Considerations

- Connection-refused is already classified transient by the existing policy; only the upsert is wrapped in it (`2026-07-23-index-job-backend-resilience-research`).
- A job reaches ensure and read operations before its first retried write, so those are the first to fail on a refused backend (`2026-07-23-index-job-backend-resilience-research`).
- The client connects lazily, so the refusal surfaces on the first operation, not at construction (`2026-07-23-index-job-backend-resilience-research`).
- Ensure, read, and delete operations are naturally idempotent and safe to replay under a bounded retry (`2026-07-23-index-job-backend-resilience-research`).
- The durable no-progress budget owned by the run policy must remain the ceiling on total wait, so extending retry to more operations cannot extend a job unboundedly.
- This decision is independent of orphaned-daemon reaping (issue #256); that is one observed trigger, not a prerequisite (`2026-07-23-index-job-backend-resilience-research`).

## Considered options

- **Add a pre-job connection-health gate that waits for the backend.** Rejected as sufficient: it does not cover a restart that lands between two operations mid-job, and it duplicates readiness logic the retry already expresses.
- **Catch `unavailable` in the job runner and reschedule the whole job.** Rejected: it re-implements backoff the store already owns, discards in-run progress, and reacts at the coarsest possible grain.
- **Generalise the existing bounded transient retry from the upsert to every store operation.** Chosen: reuses the proven transient/unrecoverable classification and capped backoff, covers both first-operation and mid-run refusals at operation grain, and stays under the run policy's no-progress budget.

## Constraints

- Parent `qdrant-store-resilience` owns corrupt-collection detect/quarantine/retry on supervised start; this decision adds client-side operation retry and must not duplicate or contradict that server-lifecycle recovery. That parent is accepted and stable.
- Parent `index-backpressure-storage-hygiene` established the operation timeout, the `unavailable`/`disk_full`/`timeout` error taxonomy, and the write-only bounded retry; this decision widens the retry scope only, keeping the taxonomy and the unrecoverable-raises-immediately rule intact. That parent is accepted and stable.
- The unrecoverable classification (storage exhaustion) must keep raising immediately for every wrapped operation - a full disk must not be retried on a read any more than on a write.
- The retry must consume the caller-owned durable no-progress budget where one is supplied (managed index runs) and fall back to a self-bounded attempt count for direct callers, matching the existing write-path contract.
- Maintenance import-graph inertness and the torch-free, CLI-free store boundary are preserved; the change stays within the store and its existing store-writes helper.

## Implementation

The bounded transient-retry helper that today wraps only the upsert is generalised into a store-operation retry that any store call can run under, keeping the same transient-versus-unrecoverable classification and capped exponential backoff. The store's connection-establishment, collection-ensure (existence check and index creation), and read operations (count, scroll, retrieve) - and its point deletes - execute under this bounded retry so a refused or restarting backend becomes a bounded wait rather than an immediate job failure. Unrecoverable failures (storage exhaustion) continue to raise on the first attempt for every operation. When a managed run supplies its durable no-progress policy the retry clamps every wait to the remaining budget and surfaces the typed no-progress outcome on expiry, exactly as the write path does today; direct callers outside a managed run use the self-bounded attempt count. The commit-unit and ledger contracts are untouched. A guard test drives a store operation against a backend that refuses then accepts the connection and asserts the operation completes after a bounded retry rather than failing, and is shown to fail (immediate hard error) against the pre-change single-shot path so the guard is proven to bind.

## Rationale

Extending the existing bounded retry is the only option that closes the gap at operation grain for both the first-operation and the mid-run refusal, and it does so by reusing classification and backoff already proven on the write path (`2026-07-23-index-job-backend-resilience-research`). The rejected gate and reschedule options each leave a real refusal window unhandled while adding parallel machinery. Because the run policy's no-progress budget remains the ceiling, widening retry scope cannot turn a genuinely-down backend into an unbounded hang - it converts a brief blip into a short wait and a sustained outage into the same typed no-progress outcome the write path already produces.

## Consequences

A restart, quarantine cycle, or brief unavailability of the managed store no longer aborts in-flight index jobs; they wait out the window and continue. The cost is that a truly-down backend is now retried on reads and ensures too, so a job takes its full no-progress budget before failing instead of failing instantly - the failure is slower but correctly classified, and the budget bounds it. Operators see fewer spurious `unavailable` job failures, which also reduces noise that previously masked genuine faults. A pitfall is that any store operation added in future must opt into the wrapper to stay resilient; centralising the retry in the store-writes helper and covering it with the guard test keeps that visible. This decision pairs with but does not depend on orphaned-daemon reaping; when that lands, the combination removes both the trigger and the fragility.
