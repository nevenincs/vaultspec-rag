---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
---

# `service-job-control` audit: `s36 http transport cli matrix`

## Scope

Audited `W05.P16.S36`: live route serving, authenticated discovery, typed
transport, CLI envelopes, exact identifiers, optimistic concurrency,
idempotency, stable conflicts, force rejection, and teardown restoration.

## Findings

### loopback-cleanup | medium | resolved restoration ordering

The first draft asserted Uvicorn shutdown before restoring process-global test
state. Teardown now records the shutdown result, restores all globals
unconditionally, and asserts the result last.

Final review status: pass with no open findings.

## Recommendations

Accept S36. Keep JSON exact-ID behavior and unconditional global restoration as
the transport boundary evolves.
