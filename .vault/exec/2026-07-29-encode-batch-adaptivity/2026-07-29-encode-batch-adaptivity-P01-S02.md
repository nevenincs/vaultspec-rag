---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S02'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# re-denominate the learned encode ceiling from item count to token footprint, recording the failing footprint on OOM and probing recovery in token units

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- re-denominate `EncodeBatchCeiling` from item count to estimated token footprint: `record_oom(failing_tokens)` halves the failing bucket's footprint, resets the recovery count, and returns the new budget; `record_success` banks at-budget completions; the recovery probe doubles in token units

## Outcome

Commit `d416547f`. Gates each exit 0; pytest 27 passed.

## Notes

`record_oom` returns the new ceiling so the caller replans without a second `clamp`, which could otherwise probe mid-call.
