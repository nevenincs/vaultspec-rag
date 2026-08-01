---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:c55d9bde5c9c9e658c8173d6512c9a0c87f54e9d2c5328d8203c14eb63e9f0c2'
step_id: 'S11'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Verify sparse CPU retention and bounded slice cleanup on real CUDA

## Scope

- `src/vaultspec_rag/tests/integration/test_embeddings.py`

## Description

- Confirm sparse document outputs stay on CPU and slice cleanup is bounded, by
  running the verify test against clean committed HEAD on real CUDA
  (`src/vaultspec_rag/tests/integration/test_embeddings.py`).

## Outcome

The sparse-retention and bounded-cleanup verify passes on real CUDA against
committed HEAD. The test measures retained device memory after encoding one
slice versus many and asserts the retained allocation does not grow in
proportion to the number of slices - the property that keeps sparse output on
CPU and bounded by a single slice rather than accumulating on the GPU. It was
run on the development GPU and passed.

## Notes

Confirmed against a clean extract of committed HEAD, not the shared working
tree. This is recorded deliberately: the tree carries several efforts'
uncommitted work, and an earlier verify run of this phase was contaminated by
that uncommitted state - a test file had been modified by another effort, and
running against the working tree reported a failure that did not exist in
committed HEAD. The authoritative result is the clean-archive run, and every
verify in this phase was re-confirmed that way. This test's file was not among
the contaminated ones, but it was still run clean to hold one standard.
