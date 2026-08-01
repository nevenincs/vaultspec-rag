---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:810e1be2b0f2d97a5af7b5184882fa6e3139ada0b3e87f057ddb70f7ecb17a55'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `s17 execution`

## Scope

Reviewed the complete S17 diff in
`src/vaultspec_rag/tests/integration/test_index_job_control.py` against the accepted
service job-control plan, ADR, research and reference, the S16 production dispatch in
`src/vaultspec_rag/jobs.py` and `src/vaultspec_rag/job_manager.py`, and the applicable
service-domain, GPU-consumer, GPU-lock, CPU-worker, backend-aware storage-lock, singleton
isolation, and bounded-operability rules. The audit covered manager-owned pause, resume,
cancel and application-failure behavior; physical and reported task, worker, limiter,
lease, writer and producer-consumer release; post-acknowledgement write cessation;
deterministic synchronization; failure cleanup; and the prohibition on fake, mock, stub,
patch, monkeypatch, skip, xfail, mirrored business logic, or shadow production imports.

## Findings

### s17 execution | high | No managed paused code job proves pipeline release before acknowledgement

The new manager-owned pause/resume case exercises only vault indexing, which has no code
producer processes or dedicated consumer pipeline. The managed code case requests
cancellation, not pause. The earlier direct-indexer parameterization proves that a raw
`PauseRequested` unwinds code processes and the consumer, and the new vault case proves
the manager's pause state transition separately, but their composition does not exercise
the S17 acceptance scenario: a real code attempt reaching canonical `paused` only after
its limiter, lease, writer, worker, process pool and sole GPU consumer are released. A
pause-specific regression in the facade/manager/code integration could therefore pass the
suite.

### s17 execution | high | Teardown can close project stores after a failed bounded join

The `managed_job_manager` finalizer requests cancellation, awaits
`wait_for_attempt`, ignores whether it returned `attempt_join_timeout`, and then closes
every project before resetting the manager and limiter. The module-scoped registry
finalizer also unconditionally resets the registry. If the behavior under test fails to
unwind, these cleanup paths can close a store beneath the still-live worker and replace
limiter ownership while its token remains borrowed, directly violating the resource
ordering the tests are meant to protect and potentially poisoning later tests. Cleanup
must branch on the structured join outcome and must never close/reset resources that a
surviving attempt can still reach.

### s17 execution | medium | Real-work polling deadlines have insufficient runtime margin

Every stage poll and manager join uses a 20-second bound even though each new managed test
has a 300-second timeout. On the review host, the managed vault and managed code control
cases took approximately 18.8 and 19.2 seconds respectively. Although an individual poll
may consume only part of that total, the margin is too small for ordinary model, process
spawn, Qdrant, antivirus, or CI load variance and risks intermittent failures before the
test-level safety bound. Retain bounded waits but give real startup and first-publication
conditions a materially larger deterministic budget.

## Recommendations

Add a manager-owned code pause/resume scenario that observes the real producer pool and
sole consumer while live, reaches canonical `paused`, proves all reported and physical
resources are released, and then verifies same-ID reconciliation. Keep the existing code
cancellation stability assertions; they provide strong evidence that no manager progress,
points, payloads, or metadata change after acknowledgement.

Make fixture teardown inspect every structured join outcome. Close project slots and reset
manager/limiter/registry state only after every attempt reports release; on timeout, fail
with the surviving snapshot without closing resources reachable by the worker. Increase
the stage deadline while preserving the 300-second outer timeout and short polling
interval.

The private collection lock in the application-failure case is acceptable: it uses the
real backend-aware lock as a physical synchronization barrier and does not replace or
mutate production behavior. Together with the deliberately incompatible real Qdrant
collection, post-GPU checkpoint ordering, pending cancellation, and observed non-control
failure, it provides sufficient causal evidence for application-error precedence.

Verification performed: `git diff --check` passed; Ruff passed; collection found all ten
tests; the three new managed tests passed with seven prior cases deselected. No prohibited
test doubles, patches, skips, expected failures, or mirrored business logic were found.

Review verdict: REVISION REQUIRED. Severity counts: Critical 0, High 2, Medium 1, Low 0.

## Remediation disposition

Re-review verified that both High findings and the Medium finding are closed.

- The new manager-owned clean code scenario observes the production process pool and sole
  consumer thread while the canonical attempt owns its task, worker, limiter, project
  lease, writer and pipeline. It observes real publication, requests pause, requires
  canonical `paused` only after the named attempt task and every reported and physical
  resource are released, and then proves a distinct attempt 2 reconciles successfully
  under the same job ID with `resumed_from_attempt=1` and
  `resume_strategy="reconcile"`.
- Function teardown now records every structured join result and checks for surviving
  active jobs before closing project slots or resetting manager and limiter ownership.
  Module teardown independently checks the current manager and raises before registry
  closure or any reset if a survivor remains. Both paths therefore fail closed instead
  of closing stores beneath reachable work.
- Managed stage polling and joins now use a distinct 60-second bound while the managed
  tests retain their 300-second outer timeout. The prior 20-second boundary remains only
  for the smaller direct-indexer cases.

The failure-precedence test still uses the real backend-aware point lock only as a
physical synchronization barrier, creates an actually incompatible local Qdrant
collection, and releases the lock so the pending cancellation races a real storage
failure. No production mutation, replacement implementation, or mirrored decision logic
was introduced by the test harness.

Independent verification reran the new managed code pause/reconciliation scenario
successfully, along with `git diff --check`, Ruff, and the prohibited-pattern scan. The
executor additionally reported four managed cases passing in 85.60 seconds, ten boundary
cases passing in 23.02 seconds, and green type and diff checks. The complete current diff
contains no fake, mock, stub, patch, monkeypatch, skip, xfail, shadow import, or test-owned
business implementation.

Re-review verdict: APPROVED. Current severity counts: Critical 0, High 0, Medium 0,
Low 0.
