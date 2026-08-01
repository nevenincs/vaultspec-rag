---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:e1eb87b8cd84587205c3262c75699ec6820302c3cbd06eb24051a92f1555b7a9'
step_id: 'S17'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify bounded watcher failure and recovery

## Scope

- `src/vaultspec_rag/tests/integration/test_server_stress_and_watcher.py`
- `src/vaultspec_rag/tests/integration/test_qdrant_server_mode.py`
- `src/vaultspec_rag/tests/integration/test_watcher_config.py`
- `src/vaultspec_rag/tests/test_watcher_retry.py`

## Description

- Drive a physical source edit through the real watchfiles loop, real model,
  and real local Qdrant store after the store becomes unavailable.
- Verify that idle ticks do not increase failures before the retry deadline and
  that repeated edits coalesce while the circuit is open.
- Restart the watcher, retain unknown prior intent, admit one half-open attempt,
  and confirm a same-file event during that attempt advances the generation.
- Confirm the final physical Qdrant payload, closed circuit, cleared failure
  count, cleared pending intent, and durable-progress timestamp.
- Hold the real state lock from a child process past one transaction deadline;
  verify event-loop responsiveness, durable retry, watcher survival, and final
  physical Qdrant convergence.
- Cancel a watcher with a real admitted claim waiting on the production index
  limiter and verify the claim becomes pending, unscoped, and retryable.
- Cancel a transaction while a child process holds the admission lock, then
  prove the late commit is interrupted and the next admission succeeds.
- Commit dirty state through a retiring policy after its replacement cached a
  clean view, then prove idle refresh performs physical Qdrant convergence.
- Reject a permanent lock-file error without entering the transient retry loop.
- Hold the state lock beyond the cancellation budget, verify bounded shutdown
  leaves a recovery marker, then prove the next owner consumes it and requires
  unscoped convergence.
- Start a replacement while another process holds its state lock and prove
  transient construction retry keeps the watcher alive through final Qdrant
  convergence.
- Write a retiring policy's recovery marker after replacement admission and
  prove fenced consumption preserves the replacement claim and newer intent.
- Cancel persistence for a mixed vault/code batch while both source state locks
  are indefinitely held and prove both obligations receive concurrent bounded
  durable handoff.
- Release a real state lock after admission has reached its hard cancellation
  deadline and prove the detached operation consumes its own fence without
  committing an orphaned claim.
- Remove an abandoned marker temporary only after its filesystem timestamp is
  older than the one-hour danglingness grace.
- Consume a completed same-process fence through the exact active-admission
  registry instead of deferring it until process exit.
- Reserve admission ownership before native scheduling, then prove a pre-start
  handoff cancels that reservation and cannot leave an orphaned claim.
- Saturate all four ordinary transaction slots and prove cancellation still
  publishes durable intent through independent bounded handoff capacity.
- Retain real pinned-Qdrant server-mode watcher deletion coverage.

## Outcome

The real recovery scenarios prove bounded failure reporting, durable intent,
restart recovery, half-open admission, in-flight event preservation, lock
contention recovery, cancellation settlement, and final store convergence
without fakes, mocks, patches, skips, or xfails. The focused policy, watcher,
local-Qdrant, and pinned server-mode suites passed. Static lint and strict type
checks passed for the implementation and tests. The combined focused watcher,
retry, local-Qdrant, and configuration suite passed 48 tests; the pinned real
Qdrant server-mode watcher suite passed two more tests.

## Notes

Transient timeout and unavailable classification, threshold opening, capped
exponential delay, live-owner exclusion, dead-process recovery, malformed state,
and cancellation settlement are exercised with real clocks, files, locks, and
processes in the focused policy suite. The local store outage supplies the
end-to-end dispatcher failure; pinned server-mode tests retain a real supervised
Rust Qdrant child for transport and watcher behavior.
