---
tags:
  - '#exec'
  - '#service-concurrency'
date: '2026-06-12'
step_id: 'S02'
related:
  - "[[2026-06-12-service-concurrency-plan]]"
---

# Capture pre-rework baseline numbers on the two-root corpus and persist them in the step record

## Scope

- `.vault/exec/2026-06-12-service-concurrency`

## Description

- Run the saturation matrix (8 requests, concurrency 4, 600s timeout) against the
  live pre-rework service on the two-root corpus: the 6.3 GB
  `chore-476-restructure-execution` index (primary) plus the `main` worktree index.
- Persist the machine-readable report to
  `src/vaultspec_rag/tests/benchmarks/baselines/w01_baseline.json` as the comparison
  artifact for the final validation wave.

## Outcome

Frozen pre-rework baseline (all requests succeeded; phase means/maxima from the
service's own timing instrumentation):

- same-root-vault: 0.95 rps, p50 4.20s, p95 4.27s; gpu_queue_wait mean 2.20s -
  over half of warm vault-search latency at concurrency 4 is queueing on the
  global GPU lock.
- same-root-code: 0.019 rps, p50 195s, p95 249s; qdrant phase mean 136.8s, max
  193.7s - the sparse brute-force scan of the 6.3 GB code collection runs under
  the exclusive per-root store lock, fully serializing concurrent code searches.
- same-root-mixed: 0.041 rps, p50 94.8s; vault searches (4.2s alone) are dragged
  to ~95s because both collections share one store lock - the direct measurement
  motivating per-collection locking.
- cross-root-mixed: 0.082 rps, p50 46.9s, gpu_queue_wait max 20.5s - searches on
  the small root stall behind the big root's scans via the global GPU lock and
  shared thread pool.

## Notes

- Adversarial live observation during the smoke run: a watcher-triggered 43-chunk
  embed job made zero progress for 8+ minutes while 4 concurrent searches cycled
  the GPU lock - lock acquisition has no fairness, so index slices starve under
  search load.
- The first capture of the cross-root scenario suffered the root/type lockstep
  cycling defect; the committed baseline uses the corrected harness.
