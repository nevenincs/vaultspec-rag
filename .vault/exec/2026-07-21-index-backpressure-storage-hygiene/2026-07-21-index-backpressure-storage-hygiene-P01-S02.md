---
tags:
  - '#exec'
  - '#index-backpressure-storage-hygiene'
date: '2026-07-21'
modified: '2026-07-21'
step_id: 'S02'
related:
  - "[[2026-07-21-index-backpressure-storage-hygiene-plan]]"
---

# bound the CUDA-OOM encode recovery in encode_documents and encode_documents_sparse to a halving ladder with floor batch size 1 that raises the underlying error on persistent failure

## Scope

- `src/vaultspec_rag/tests/test_encode_hygiene_unit.py`

## Description

Verification found research finding W4 partially wrong: the CUDA-OOM
recovery in `encode_documents` / `encode_documents_sparse` is already
floor-bounded - the halving ladder raises the underlying
`torch.cuda.OutOfMemoryError` once batch size 1 fails, so no production
change was needed. The step was re-scoped (via `vault plan step edit`)
to pin that invariant with regression tests: dense and sparse ladders
halve 8-4-2-1 then raise, and recovery at a smaller batch returns real
output.

## Outcome

Committed as `test(embeddings): pin the floor-bounded CUDA-OOM encode
ladder (#242)`; `TestOomLadderIsFloorBounded` (3 tests) green.

## Notes

The plausible incident wedge is therefore the timeout-less client (fixed
in S01), not an unbounded encode loop; host-commit allocation failures
raise `RuntimeError` and already propagate.
