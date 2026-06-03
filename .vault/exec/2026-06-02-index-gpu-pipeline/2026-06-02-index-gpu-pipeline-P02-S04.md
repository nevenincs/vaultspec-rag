---
tags:
  - '#exec'
  - '#index-gpu-pipeline'
date: '2026-06-02'
step_id: 'S04'
related:
  - "[[2026-06-02-index-gpu-pipeline-plan]]"
---

# Add a real-GPU test asserting consumer-thread pipeline chunk-id and metadata parity with the serial path and that consumer exceptions propagate

## Scope

- `src/vaultspec_rag/tests/integration/`

## Description

- Add a real-GPU test asserting the parallel consumer-thread pipeline produces an identical chunk-id set, count, and content-hash metadata to the serial path.
- Add a test that a genuine Qdrant dimension-mismatch consumer failure propagates and does not hang.

## Outcome

Both tests pass on real GPU; parity and fail-loud-not-hang are locked down with no mocks.

## Notes

The BrokenProcessPool-fallback transition is not unit-tested (a real broken pool needs a production hook or monkeypatch, both barred); its serial target is covered by the workers=1 parity path.
