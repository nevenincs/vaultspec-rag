---
generated: true
tags:
  - '#index'
  - '#index-cuda-shared-device'
date: '2026-07-25'
modified: '2026-07-25'
related:
  - '[[2026-07-24-index-cuda-shared-device-P01-S01]]'
  - '[[2026-07-24-index-cuda-shared-device-P01-S02]]'
  - '[[2026-07-24-index-cuda-shared-device-P01-S03]]'
  - '[[2026-07-24-index-cuda-shared-device-P01-S04]]'
  - '[[2026-07-24-index-cuda-shared-device-P01-S05]]'
  - '[[2026-07-24-index-cuda-shared-device-P02-S06]]'
  - '[[2026-07-24-index-cuda-shared-device-P03-S07]]'
  - '[[2026-07-24-index-cuda-shared-device-P03-S08]]'
  - '[[2026-07-24-index-cuda-shared-device-P03-S09]]'
  - '[[2026-07-24-index-cuda-shared-device-adr]]'
  - '[[2026-07-24-index-cuda-shared-device-plan]]'
  - '[[2026-07-24-index-cuda-shared-device-research]]'
---

# `index-cuda-shared-device` feature index

Auto-generated index of all documents tagged with `#index-cuda-shared-device`.

## Documents

### adr

- `2026-07-24-index-cuda-shared-device-adr` - `index-cuda-shared-device` adr: `derive the ceiling from free device memory and drop the runtime peak from corpus admission` | (**status:** `accepted`)

### exec

- `2026-07-24-index-cuda-shared-device-P01-S01` - add a guarded cuda_free_memory_mb probe returning mem_get_info free in MiB or None off the GPU path
- `2026-07-24-index-cuda-shared-device-P01-S02` - change resolve_index_cuda_ceiling_mb to derive the absolute auto ceiling as min(baseline + free - headroom, total - headroom) with the operator override and profile fallback unchanged
- `2026-07-24-index-cuda-shared-device-P01-S03` - pass the resident baseline into the ceiling derivation and move it after the admission cache flush in the codebase indexer budget builder
- `2026-07-24-index-cuda-shared-device-P01-S04` - pass the resident baseline into the ceiling derivation and keep it after the admission cache flush in the document indexer budget builder
- `2026-07-24-index-cuda-shared-device-P01-S05` - carry the free-derived ceiling through the dispatch admission snapshot as a point-in-time diagnostic without changing enforcement
- `2026-07-24-index-cuda-shared-device-P02-S06` - remove cuda_bytes from the code indexer corpus-dimension rejection while keeping the measured field and its JSON reporting
- `2026-07-24-index-cuda-shared-device-P03-S07` - prove the double-count guard fails when the ceiling reverts to bare free-minus-headroom and passes at baseline-plus-free-minus-headroom, both directions recorded
- `2026-07-24-index-cuda-shared-device-P03-S08` - prove the corpus-rejection guard fails when a runtime CUDA peak above the profile is re-admitted and rejects again if reinstated, both directions recorded
- `2026-07-24-index-cuda-shared-device-P03-S09` - run the full unit suite and the citation-gate lint over every changed file

### plan

- `2026-07-24-index-cuda-shared-device-plan` - `index-cuda-shared-device` plan

### research

- `2026-07-24-index-cuda-shared-device-research` - `index-cuda-shared-device` research: `the indexing CUDA ceiling ignores non-torch device consumers and mis-rejects a runtime peak as corpus size`
