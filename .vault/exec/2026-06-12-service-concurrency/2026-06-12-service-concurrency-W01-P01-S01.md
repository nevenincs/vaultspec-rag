---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S01'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Create a concurrency benchmark harness driving N parallel searches (same-root, cross-root, vault+code mixed, optional concurrent reindex) against the live service, reporting throughput, p50/p95 latency, and per-phase timings

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_concurrency.py`

## Description

- Add `bench_concurrency.py` standalone saturation harness: discovers the live
  service via its status file (port + bearer token), fires N parallel `POST /search`
  requests through a bounded thread pool, and aggregates client latency
  (p50/p95/max), throughput, and the service's own per-phase timings
  (embedding, qdrant, rerank, postprocess, project lease, GPU queue wait).
- Build a four-scenario matrix: same-root vault, same-root code, same-root mixed,
  cross-root mixed; optional `--with-reindex` kicks an incremental codebase reindex
  before the matrix so contention with a live index run is measurable.
- Emit a human summary plus a machine-readable JSON report (`--json`) used as the
  cross-wave comparison artifact.
- Fix a cycling defect found during the first capture: equal-length root and type
  lists ran in lockstep, pinning each root to one search type; the type cycle now
  advances once per full root cycle.

## Outcome

- Module is ruff/ty clean and not collected by pytest (operator-invoked: saturating
  a live shared service is not a unit-test side effect).
- Smoke run (8 requests, c=4, 120s timeout) validated mechanics end to end and
  immediately surfaced the pathology: 476-corpus code searches exceeded the client
  timeout while the server logged 401-406s completions, and a concurrent
  watcher-triggered embed job starved at 0/43 chunks for 8+ minutes behind the GPU
  lock convoy.

## Notes

- The harness measures a live shared service; another agent was editing the
  476-corpus worktree during early runs, so watcher index jobs occasionally overlap
  scenarios. Baseline runs are taken with the jobs view confirming no running jobs.
