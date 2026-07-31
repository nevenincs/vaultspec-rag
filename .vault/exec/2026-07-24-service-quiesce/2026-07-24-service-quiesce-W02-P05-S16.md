---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S16'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Search quiescence HTTP 503 remediation

## Status

Satisfied by the landed search-route mapping and reconciled source inspection. No runtime or test command was executed during this acceptance review.

## Description

Search admission closes before project or compute ownership and raises the controller admission error. The service search boundary catches only that typed refusal and returns the canonical retryable structured HTTP 503 response.

## Outcome

All four public search source types preserve one envelope with `ok: false`, error `quiesce_admission_closed`, `retryable: true`, request identity, and the controller state, admission epoch, and GPU-safety snapshot. The response status is 503, while unrelated search errors and availability classification retain their existing paths.

## Evidence

The landed route catches `QuiesceAdmissionClosedError` around search execution, renders the typed quiesce snapshot, records the unavailable outcome, and returns status 503 directly. The checked-in route test exercises `vault`, `code`, `document`, and `combined` through the production Starlette route and asserts the exact response and activity-ledger truth. The final ownership assertion was strengthened in `18977d3c`.

## Notes

S18 owns the retained-resource proof. No service process, RAG endpoint, CUDA allocation, GPU test, or CPU test was run during this reconciliation.
