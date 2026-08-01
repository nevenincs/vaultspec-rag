---
tags:
  - '#exec'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
body_hash: 'sha256:82505b0260fff4c1f51eacde79bce063d4ef9dcec6fc9c719487af8a6c2fc381'
step_id: 'S08'
related:
  - "[[2026-07-24-index-cuda-ceiling-plan]]"
---

# replace the one-way min-clamp in the document indexer budget builder with the derived ceiling

## Scope

- `src/vaultspec_rag/indexer/_document_indexer.py`

## Description

- Replaced the min-clamp in the document indexer's `_begin_resource_budget`
  with `resolve_index_cuda_ceiling_mb`; the rss clamp is unchanged.

## Outcome

The enforcing document-index budget now carries the derived/overridden ceiling.

## Notes

None.
