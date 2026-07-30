---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S18'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---
# CPU search HTTP 503 proof remediation

## Status

Satisfied by the checked-in CPU route proof strengthened in `18977d3c`. No test command was rerun during this acceptance review.

## Description

The CPU-only proof exercises the production service search route against a real quiesced registry for every public search source. It proves both the canonical structured HTTP 503 contract and rejection before any project or compute resource is retained.

## Outcome

For `vault`, `code`, `document`, and `combined`, the route returns the exact typed retryable 503 envelope and records one matching unavailable activity. After all refusals, the same registry has no project slots, no model, no reranker, no CUDA state, no active compute ticket, and an unchanged quiesced snapshot that remains VRAM-released and safe to borrow.

## Evidence

The checked-in test constructs a real `ServiceRegistry`, drives it to quiesced, installs it as the route's live registry, and sends authenticated requests through Starlette's production route. Commit `18977d3c` adds the complete health and controller-snapshot assertions and records the guard mutation that turns the named 503 assertion red when the typed route handling is replaced by a runtime error.

## Notes

The broader W02 ownership audit also inspected `cf9a0b1e` and `85fa25f2`: capped project construction is serialized under registry admission, and cleanup uses the registry's exclusive maintenance-store lease rather than bypassing registry ownership. These commits preserve the resource-ownership premise exercised by the closed-admission proof; they are not substitutes for its direct route assertions. No service process, RAG endpoint, CUDA allocation, GPU test, or CPU test was run during this reconciliation.
