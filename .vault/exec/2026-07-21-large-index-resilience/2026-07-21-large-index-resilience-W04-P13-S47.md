---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-26'
modified: '2026-07-26'
body_hash: 'sha256:3a08e7893a87ec650bedf49f03764c794bd6d40de82a2c65ede44fce80c7636b'
step_id: 'S47'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Complete the 250872-chunk incident floor on the declared default managed-service profile

## Scope

- `src/vaultspec_rag/tests/benchmarks/bench_large_index_resilience.py`

## Description

- Prepare the 83,624-file acceptance corpus and verify chunk cardinality file-by-file through the production AST chunker.
- Confirm the default support profile resolves to `managed-service` on the `server` backend before loading the model.
- Run the acceptance harness as a clean build against the prepared root on an uncontended device.
- Record the published chunk count, resource high-water marks, and wall time from the emitted report.

## Outcome

The run completed on the declared default `managed-service` profile with the `server` backend and published exactly 250,872 chunks from 83,624 files, meeting the incident floor.

Measured on device `cuda` as a clean build (250,872 added, 0 updated, 0 removed):

- Wall time 3,969.09 s; reported index duration 3,947,002 ms.
- Peak resident 10,347.98 MB, growth 6,762.68 MB.
- Peak CUDA allocated 1,637.77 MB, growth 283.58 MB.
- Peak CUDA reserved 2,156.00 MB, growth 790.00 MB.
- Weighted bytes 25,570,295,848; source bytes 202,453,704.

Every figure sits inside the profile ceilings: 83,624 of 500,000 permitted source files, 250,872 of 5,000,000 permitted generated chunks, 11.38 GB resident against the 16 GiB bound, and 1.72 GB CUDA against the 12 GiB bound.

The harness enforces its own acceptance and raises unless processed files equal the corpus size, stored chunks equal the reported total, the generated-chunk measurement equals the published collection, and the total meets the declared floor. All four conditions held.

## Notes

An earlier attempt aborted with a no-progress timeout after reaching 170 durable segments, having gone 921.95 s without storage-confirmed durable progress. An unrelated concurrent test run held the device at 100 percent utilisation with under 1 GiB free for the duration. The liveness guard behaved correctly under starvation; that abort reflects device contention rather than any defect in the indexing path under measurement, and its numbers are not recorded here.

The reported run was sampled at 60-second intervals throughout. No competing suite process was observed in any sample across the full 66 minutes, so the recorded figures were taken on an uncontended device.
