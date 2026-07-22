---
tags:
  - '#audit'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
related:
  - "[[2026-07-21-service-job-control-adr]]"
  - "[[2026-07-21-service-job-control-plan]]"
  - "[[2026-07-21-service-job-control-W02-P04-S11]]"
---

# `service-job-control` audit: `S11 vault run control`

## Scope

Audited S11 control propagation through full, incremental, scoped, and helper
vault indexing paths; phase and batch checkpoint safety; writer-lock unwind;
storage and metadata mutation boundaries; clean rebuild publication protection;
GPU and CPU import discipline; and backend-aware store lock ordering.

## Findings

### parse-unwind | high | Unbounded queued parsing delayed writer-lock release

The initial implementation submitted every document before consuming results.
`ThreadPoolExecutor` context shutdown would therefore run the whole queued corpus
after a pause or cancellation signal. The revision uses a bounded in-flight
window, periodic control polling, incremental refill, pending-future cancellation,
and explicit shutdown that waits only for already-running tasks. Full indexing
retains log-and-skip worker failures; incremental parsing retains propagation.

## Recommendations

Keep parse submission bounded and cancellation-aware as vault concurrency evolves.
Retain the clean protected span from immediately before collection drop through
stale cleanup and atomic metadata publication. Exercise the complete real GPU and
Qdrant interruption lifecycle in S12.

## Status

PASS. The High parse-unwind finding was resolved, and independent re-review found
no remaining Critical or High issues. Static gates, 18 focused production tests,
and real-file control/publication probes passed.
