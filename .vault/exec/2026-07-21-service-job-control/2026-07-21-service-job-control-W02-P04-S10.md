---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-21'
modified: '2026-07-22'
body_hash: 'sha256:9a7fbffa8a6ca0b6f6954751084d43bda5951499bdbe1acd1de329f4a6b3e14a'
step_id: 'S10'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Thread run control through streaming embedding and check before and after bounded GPU slices outside gpu_lock using vaultspec-high-executor

## Scope

- `src/vaultspec_rag/indexer/_streaming.py`

## Description

- Add no-op-default run-control parameters to the vault, code-slice, and codebase
  streaming helpers.
- Check cooperative control immediately before and after each bounded GPU encode
  slice, outside `gpu_lock` and before vector or storage mutation.
- Forward codebase stream control into the reusable single-slice encoder while
  preserving every existing caller.
- Verify formatting, static types, torch-free import behavior, control primitives,
  cleanup safety, and the focused source diff.
- Obtain an independent concurrency and safety review.

## Outcome

Streaming embedding now exposes the accepted cooperative control seam without
changing unmanaged indexing behavior. A pending pause or cancellation is delivered
before GPU acquisition or after the bounded forward slice has released `gpu_lock`;
post-encode delivery occurs before chunks are mutated or upserted.

Ruff, Ruff formatting, ty, and strict BasedPyright passed. All 17 production
run-control tests passed, the fresh-interpreter import remained torch-free, signature
defaults resolved to `NO_RUN_CONTROL`, and `git diff --check` passed. Independent
review found no Critical or High issues.

## Notes

Semantic discovery reported that this worktree had no indexed source sections, so
the step was grounded through full-file inspection and targeted source search. The
known CUDA OOM refresh was not retried. Real streaming interruption scenarios remain
assigned to S12 by the approved plan.
