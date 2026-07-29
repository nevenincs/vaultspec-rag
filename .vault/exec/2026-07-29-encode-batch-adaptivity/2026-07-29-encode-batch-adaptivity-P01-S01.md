---
tags:
  - '#exec'
  - '#encode-batch-adaptivity'
date: '2026-07-29'
modified: '2026-07-29'
body_schema: 'body-v1'
step_id: 'S01'
related:
  - "[[2026-07-29-encode-batch-adaptivity-plan]]"
---

# implement the token-estimate bucket planner partitioning length-sorted texts under a token budget with the chars-per-token calibration constant and the item-count cap

## Scope

- `src/vaultspec_rag/embeddings.py`

## Description

- implement `plan_encode_buckets` and the frozen `EncodeBucket` dataclass in `src/vaultspec_rag/embeddings.py`: pure, torch-free, greedy, order-preserving partition of length-sorted texts under a token budget with a chars-per-token estimate and the item-count cap; an over-budget single item isolates into its own bucket
- create `src/vaultspec_rag/tests/test_encode_bucket_planner.py` with planner unit coverage (budget respected, cap respected, oversize isolation, order preserved)

## Outcome

Commit `f3cc83ae` on branch `encode-batch-adaptivity-p01`. Gates each exit 0: ruff check, ruff format --check, ty check, pytest (27 passed).

## Notes

None.
