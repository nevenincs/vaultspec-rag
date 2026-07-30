---
tags:
  - '#audit'
  - '#service-quiesce'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
related:
  - "[[2026-07-24-service-quiesce-adr]]"
  - "[[2026-07-24-service-quiesce-plan]]"
---
# `service-quiesce` audit: `W04 S29-S33 final acceptance`

## Scope

Final reconciliation of committed W04 S29, S30, S32, and S33 against the accepted service-quiesce decision and its implementation plan. The reviewed commits are `8584c656`, `6fd2aa35`, `a25bfb03`, and `af6e1292`. The review checked commit ownership, the opaque captured-authority boundary, typed captured-target revalidation, guarded pytest ordering, and the CI and Just no-bypass route.

## Findings

### s29-s33-contract | low | Committed implementation matches the accepted borrower boundary

S29 derives borrower authority only from an opaque registry-backed machine-lock witness; the production owner PID is durable and recoverable, and no-create observation refuses absent, free, unreadable, or mismatched ownership. S30 carries a typed pre-isolation pointer and redacted target evidence, revalidates it after lease acquisition, and performs the permitted first-bearer plus one authenticated retry. S32 captures only before singleton registration for slow-capable selection, evaluates device admission only inside the acknowledged borrower callback, and applies the exact selected-fixture Qdrant predicate. S33 routes CI through one guarded `just test gpu` invocation and does not install Qdrant, preflight a GPU, or start a service.

### cpu-static-evidence | low | Focused evidence is green within the authorized no-live boundary

Thirty-five focused CPU-only tests passed across existing-anchor observation, machine discovery, borrower lease, captured target, borrower CLI, and pytest coordination. Ruff, Ty, Actionlint, and diff checks passed. The test proof used real OS locks and approved no-lifespan loopback routes only; it did not allocate a GPU, start a resident daemon, start Qdrant, or load a model.

### strict-type-baseline | medium | Full configured BasedPyright remains blocked by external Core stubs

Full configured BasedPyright reports the established missing-stub baseline for `vaultspec_core` imports. This review found no S29-S33-specific type regression in the scoped checks, but the repository-wide strict-type gate is not green and is not represented as passing.

### w04-s31 | medium | Preflight remains the only unimplemented W04 plan step

S31 remains unchecked. It must make service preflight a torch-free remote observation of typed quiescence and capacity without authorizing GPU work or falling back to a local probe. The plan therefore remains implementation-incomplete after S29, S30, S32, and S33 are closed.

### delegated-gpu-live-integration | low | Live self-hosted GPU acceptance remains outside this review

The plan expressly excludes live GPU runs and co-scheduled end-to-end tests without a separately authorized maintenance window. That delegated integration proof remains outstanding and was not attempted.

### s07-exec-trace | low | An earlier checked step lacks its execution record

Plan status reports S07 as checked without an execution record. This predates the W04 reconciliation and does not undermine the S29-S33 commit boundary, but it leaves one traceability warning in the plan.

## Recommendations

- Implement and accept S31 before claiming W04 or the service-quiesce plan complete.
- Restore a passing repository-wide configured BasedPyright gate by resolving the external Core stub baseline.
- In an authorized maintenance window, run the delegated self-hosted GPU integration tier against its resident-service and runner-image prerequisites.
- Restore the missing S07 execution record to remove the remaining plan traceability warning.
