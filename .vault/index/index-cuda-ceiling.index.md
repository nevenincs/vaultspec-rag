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
  - '[[2026-07-24-index-cuda-ceiling-P02-S04]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S05]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S06]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S07]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S08]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S09]]'
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
- `2026-07-24-index-cuda-ceiling-P02-S04` - add a GPU-gated device-capacity query that returns total CUDA memory and is unreachable from torch-free service-client and worker paths
- `2026-07-24-index-cuda-ceiling-P02-S05` - derive the effective ceiling as device-capacity minus a reserved headroom margin with the config value overriding in either direction
- `2026-07-24-index-cuda-ceiling-P02-S06` - replace the one-way min-clamp at the dispatch admission site with the bidirectional derived ceiling
- `2026-07-24-index-cuda-ceiling-P02-S07` - replace the one-way min-clamp in the codebase indexer budget builder with the derived ceiling
- `2026-07-24-index-cuda-ceiling-P02-S08` - replace the one-way min-clamp in the document indexer budget builder with the derived ceiling
- `2026-07-24-index-cuda-ceiling-P02-S09` - add a test asserting the config override raises the ceiling above the profile floor and still lowers it below

### plan

- `2026-07-24-index-cuda-ceiling-plan` - `index-cuda-ceiling` plan

### research

- `2026-07-24-index-cuda-ceiling-research` - `index-cuda-ceiling` research: `the indexing CUDA ceiling is unraisable and charged process-wide across concurrent jobs`
