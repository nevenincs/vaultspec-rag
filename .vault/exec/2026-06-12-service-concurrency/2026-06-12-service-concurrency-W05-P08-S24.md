---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S24'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Run the quality harness comparison and manual persona CLI verification in human and JSON modes

## Scope

- `src/vaultspec_rag/tests/benchmarks`

## Description

- Run the quality harness against the reworked retrieval stack (shared run
  with the W02 verification steps).
- Run the operator persona pass on the real command surface, in human and
  JSON modes, while three concurrent index jobs from two other agents
  saturated the GPU: `server status`, `server status --json`, `server jobs --running` (+ JSON), `search --type code` (human), `search --type vault --json`, plus the limiter gauges on the metrics route.

## Outcome

Quality: 8/8 needle probes, 100% precision. Persona observations: the status
and jobs surfaces rendered the rebuild storm coherently (running-first,
progress, queue counts, actionable next steps); a search that timed out
during peak contention returned the documented diagnostics (service state,
running-job count, exact retry command with a longer budget) and the retried
search succeeded; the JSON search envelope carried request id, full phase
attribution (gpu queue wait 34.7s honestly attributed to the concurrent
19k-file index job; qdrant 0.29s; total 39s), and index-state provenance.
Result quality was precise in both modes: the code query returned the exact
invalidation tests and implementation; the vault query returned the exact
step record as rank one.

## Notes

Under identical co-load the pre-rework service produced 400s+ latencies or
opaque timeouts; the reworked service completes with honest attribution.
