---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
body_hash: 'sha256:e89cc2814e468207b8798fe7cb6d180306688125696ed4222145ca06db119474'
step_id: 'S04'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# adopt the bucket planner and token ceiling on the sparse encode path through the shared ceiling class

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- adopt `plan_encode_buckets` and the shared token-denominated ceiling on the sparse encode path; `_encode_sparse_batch` takes a bucket and derives its batch size; the sparse count ladder is deleted
- extract `_BucketPlanContext` and `_shrink_after_bucket_oom` as the one shared replan implementation for dense and sparse
- delete the sparse ladder tests and doubles from the hygiene file in the same commit; add `TestBucketedSparseEncode` coverage including the sparse bucket-scoped OOM retry guard

## Outcome

Commit `f75743ff`. Gates each exit 0; pytest 35 passed. Sparse guard proven able to fail on its named assertion (exit 1 broken, exit 0 restored), mutation documented in a test comment.

## Notes

No second planner and no count-denominated remnant remain.
