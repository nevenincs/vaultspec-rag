---
generated: true
tags:
  - '#index'
  - '#index-cuda-ceiling'
date: '2026-07-31'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:3268af862698f54c0503d704f58f2a1b0c5b8a175ea00254134c98143cffac26'
related:
  - '[[2026-07-24-index-cuda-ceiling-P01-S01]]'
  - '[[2026-07-24-index-cuda-ceiling-P01-S02]]'
  - '[[2026-07-24-index-cuda-ceiling-P01-S03]]'
  - '[[2026-07-24-index-cuda-ceiling-P01-summary]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S04]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S05]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S06]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S07]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S08]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-S09]]'
  - '[[2026-07-24-index-cuda-ceiling-P02-summary]]'
  - '[[2026-07-24-index-cuda-ceiling-P03-S10]]'
  - '[[2026-07-24-index-cuda-ceiling-P03-S11]]'
  - '[[2026-07-24-index-cuda-ceiling-P03-S12]]'
  - '[[2026-07-24-index-cuda-ceiling-P03-S13]]'
  - '[[2026-07-24-index-cuda-ceiling-P03-S14]]'
  - '[[2026-07-24-index-cuda-ceiling-P03-S15]]'
  - '[[2026-07-24-index-cuda-ceiling-P03-summary]]'
  - '[[2026-07-24-index-cuda-ceiling-P04-S16]]'
  - '[[2026-07-24-index-cuda-ceiling-P04-S17]]'
  - '[[2026-07-24-index-cuda-ceiling-P04-S18]]'
  - '[[2026-07-24-index-cuda-ceiling-P04-S19]]'
  - '[[2026-07-24-index-cuda-ceiling-P04-summary]]'
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
- `2026-07-24-index-cuda-ceiling-P01-summary` - `index-cuda-ceiling` `P01` summary
- `2026-07-24-index-cuda-ceiling-P02-S04` - add a GPU-gated device-capacity query that returns total CUDA memory and is unreachable from torch-free service-client and worker paths
- `2026-07-24-index-cuda-ceiling-P02-S05` - derive the effective ceiling as device-capacity minus a reserved headroom margin with the config value overriding in either direction
- `2026-07-24-index-cuda-ceiling-P02-S06` - replace the one-way min-clamp at the dispatch admission site with the bidirectional derived ceiling
- `2026-07-24-index-cuda-ceiling-P02-S07` - replace the one-way min-clamp in the codebase indexer budget builder with the derived ceiling
- `2026-07-24-index-cuda-ceiling-P02-S08` - replace the one-way min-clamp in the document indexer budget builder with the derived ceiling
- `2026-07-24-index-cuda-ceiling-P02-S09` - add a test asserting the config override raises the ceiling above the profile floor and still lowers it below
- `2026-07-24-index-cuda-ceiling-P02-summary` - `index-cuda-ceiling` `P02` summary
- `2026-07-24-index-cuda-ceiling-P03-S10` - add a bare peak reset-and-read helper that resets peak stats without flushing the allocator cache
- `2026-07-24-index-cuda-ceiling-P03-S11` - sample the resident-model baseline after every model including the lazily-loaded reranker is resident
- `2026-07-24-index-cuda-ceiling-P03-S12` - capture the allocation high-water inside the gpu_lock forward bracket in the shared encode path
- `2026-07-24-index-cuda-ceiling-P03-S13` - thread the captured per-job forward peak into the memory budget as the maximum across the job's brackets
- `2026-07-24-index-cuda-ceiling-P03-S14` - enforce every sample checkpoint against the captured baseline-net peak so no path reads max_memory_allocated directly
- `2026-07-24-index-cuda-ceiling-P03-S15` - make the ceiling comparison baseline-consistent by subtracting the baseline from the captured peak and from the derived ceiling on the same side
- `2026-07-24-index-cuda-ceiling-P03-summary` - `index-cuda-ceiling` `P03` summary
- `2026-07-24-index-cuda-ceiling-P04-S16` - prove the cross-job contamination guard fails when enforcement reads the process-global counter and passes when it reads the captured peak, recording both directions
- `2026-07-24-index-cuda-ceiling-P04-S17` - prove the double-count guard fails when the baseline is subtracted from only one side of the ceiling comparison, recording both directions
- `2026-07-24-index-cuda-ceiling-P04-S18` - run the full unit suite and the citation-gate lint over every changed file
- `2026-07-24-index-cuda-ceiling-P04-S19` - restart the service on the built code and confirm a live feature-profile corpus rebuild completes with no spurious cuda_memory_ceiling failures under concurrency
- `2026-07-24-index-cuda-ceiling-P04-summary` - `index-cuda-ceiling` `P04` summary

### plan

- `2026-07-24-index-cuda-ceiling-plan` - `index-cuda-ceiling` plan

### research

- `2026-07-24-index-cuda-ceiling-research` - `index-cuda-ceiling` research: `the indexing CUDA ceiling is unraisable and charged process-wide across concurrent jobs`
