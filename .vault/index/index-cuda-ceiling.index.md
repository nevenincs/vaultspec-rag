---
generated: true
tags:
  - '#index'
  - '#index-cuda-ceiling'
date: '2026-07-24'
modified: '2026-07-24'
related:
  - '[[2026-07-24-index-cuda-ceiling-P01-S01]]'
  - '[[2026-07-24-index-cuda-ceiling-P01-S02]]'
  - '[[2026-07-24-index-cuda-ceiling-P01-S03]]'
  - '[[2026-07-24-index-cuda-ceiling-adr]]'
  - '[[2026-07-24-index-cuda-ceiling-plan]]'
  - '[[2026-07-24-index-cuda-ceiling-research]]'
---

# `index-cuda-ceiling` feature index

Auto-generated index of all documents tagged with `#index-cuda-ceiling`.

## Documents

### adr

- `2026-07-24-index-cuda-ceiling-adr` - `index-cuda-ceiling` adr: `size the indexing CUDA ceiling to real device headroom and scope it per job` | (**status:** `accepted`)

### exec

- `2026-07-24-index-cuda-ceiling-P01-S01` - add embedding_document_encode_batch_size to config defaults and the env-var mapping with a window-appropriate default
- `2026-07-24-index-cuda-ceiling-P01-S02` - have the document indexer read the document encode batch instead of falling through to embedding_encode_batch_size
- `2026-07-24-index-cuda-ceiling-P01-S03` - add a test asserting document embedding uses the document sub-batch and is independent of the vault and code sub-batches

### plan

- `2026-07-24-index-cuda-ceiling-plan` - `index-cuda-ceiling` plan

### research

- `2026-07-24-index-cuda-ceiling-research` - `index-cuda-ceiling` research: `the indexing CUDA ceiling is unraisable and charged process-wide across concurrent jobs`
