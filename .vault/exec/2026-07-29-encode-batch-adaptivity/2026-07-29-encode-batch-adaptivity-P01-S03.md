---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S03'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# rework the dense encode output path to execute one library encode call per planned bucket, retaining completed bucket outputs and scoping OOM discard, split, and cache flush to the failing bucket

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- rework `_encode_documents_output` to plan buckets under the clamped token budget and run one library encode call per length-homogeneous bucket
- retain completed bucket outputs across an OOM; on a CUDA OOM flush the cache, lower the ceiling by the failing bucket's footprint, and replan only the failing bucket plus the unstarted tail; single-text buckets re-raise
- expose the `on_bucket` callback seam (`EncodeBucketProgress`; phases before/after; fires outside any GPU-lock hold) on `encode_documents_on_device`
- remove the dense count-ladder tests with the path they exercised; add bucketed dense encode coverage including the bucket-scoped OOM retry guard

## Outcome

Commit `0f346bd1`. Gates each exit 0; pytest 30 passed. Guard proven able to fail: a slice-wide-retry mutation fails `test_oom_discards_only_the_failing_bucket` on its named call-log assertion (exit 1); restored it passes alone (exit 0); mutation removed before commit and documented in a test comment.

## Notes

Transitional: the constructor read the token-budget knobs before they existed in settings; the window was closed by the settings commit landing before the lock-bracket step.
