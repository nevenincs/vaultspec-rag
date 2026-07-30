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

Final reconciliation of committed W04 S29-S33 against the accepted service-quiesce decision and implementation plan. The reviewed implementation commits are `8584c656`, `6fd2aa35`, `d08edec6`, `a25bfb03`, and `af6e1292`. Detailed S31 evidence is recorded in the linked S31 identity-binding acceptance audit.

## Findings

### s29-s33-contract | low | W04 implementation matches the accepted borrower boundary

S29 derives borrower authority only from an opaque registry-backed machine-lock witness; the production owner PID is durable and recoverable, and no-create observation refuses absent, free, unreadable, or mismatched ownership. S30 carries a typed pre-isolation pointer and redacted target evidence, revalidates it after lease acquisition, and performs the permitted first-bearer plus one authenticated retry. S31 binds remote preflight observation to one discovered identity and remains non-authorizing. S32 captures only before singleton registration for slow-capable selection, evaluates device admission only inside the acknowledged borrower callback, and applies the exact selected-fixture Qdrant predicate. S33 routes CI through one guarded `just test gpu` invocation and does not install Qdrant, preflight a GPU, or start a service.

### implementation-plan-complete | low | All 33 implementation steps are checked

The plan now records 33 of 33 checked implementation steps. Completion means the approved code and CPU/static acceptance work is complete; it does not assert that external release prerequisites or a live GPU maintenance-window run were completed.

### strict-type-baseline | medium | Repository-wide configured BasedPyright remains blocked by external Core stubs

Full configured BasedPyright reports the established missing-stub baseline for `vaultspec_core` imports. Scoped checks found no W04-specific type regression, but the repository-wide strict-type gate is not green and is not represented as passing.

### delegated-gpu-live-integration | low | Live self-hosted GPU acceptance remains outside this review

The plan expressly excludes live GPU runs and co-scheduled end-to-end tests without a separately authorized maintenance window. That delegated integration proof remains outstanding and was not attempted.

### s07-exec-trace | low | An earlier checked step still lacks its execution record

Plan status reports S07 as checked without an execution record. This predates W04 and does not invalidate the closed implementation plan, but it remains a traceability warning to repair separately.

## Recommendations

- Resolve the external Core stub baseline before claiming a passing repository-wide configured BasedPyright gate.
- In an authorized maintenance window, run the delegated self-hosted GPU integration tier against its resident-service and runner-image prerequisites.
- Restore the missing S07 execution record to remove the remaining plan traceability warning.
