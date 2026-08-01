---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:67bc78410cbafb6d419d03e842d3a093dc7c30bc22d2a32473a5f726edbc2ee0'
step_id: 'S02'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# have the document indexer read the document encode batch instead of falling through to embedding_encode_batch_size

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`

## Description

- Repointed both document `encode_batch_size` call sites from
  `embedding_encode_batch_size` to `embedding_document_encode_batch_size`.

## Outcome

The document indexer imports cleanly and both the per-slice encode call and the
run-configuration carry the document sub-batch.

## Notes

The neighbouring `slice_max_chunks=int(config.embedding_batch_size)` was left
unchanged: it is the outer queue slice count, a different knob from the inner
encode sub-batch this step retargets.
