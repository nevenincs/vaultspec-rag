---
generated: true
tags:
  - '#index'
  - '#index-gpu-pipeline'
date: '2026-06-02'
related:
  - '[[2026-06-02-index-gpu-pipeline-P01-S01]]'
  - '[[2026-06-02-index-gpu-pipeline-P01-S02]]'
  - '[[2026-06-02-index-gpu-pipeline-P01-S03]]'
  - '[[2026-06-02-index-gpu-pipeline-P02-S04]]'
  - '[[2026-06-02-index-gpu-pipeline-P02-S05]]'
  - '[[2026-06-02-index-gpu-pipeline-adr]]'
  - '[[2026-06-02-index-gpu-pipeline-plan]]'
  - '[[2026-06-02-index-gpu-pipeline-research]]'
---

# `index-gpu-pipeline` feature index

Auto-generated index of all documents tagged with `#index-gpu-pipeline`.

## Documents

### adr

- `2026-06-02-index-gpu-pipeline-adr` - `index-gpu-pipeline` adr: `decoupled producer-consumer indexing pipeline with dedicated gpu consumer thread` | (**status:** `accepted`)

### exec

- `2026-06-02-index-gpu-pipeline-P01-S01` - Add a bounded-queue feeder plus a single dedicated GPU consumer thread that owns the gpu_lock and runs dense then sparse encoding, replacing the inline drain
- `2026-06-02-index-gpu-pipeline-P01-S02` - Shut the consumer down with a sentinel and re-raise any consumer-thread exception in the main thread, and move stale-purge and metadata accounting after the join
- `2026-06-02-index-gpu-pipeline-P01-S03` - Preserve the serial byte-gate path and the BrokenProcessPool fallback as the single-threaded inline form under the two-thread structure
- `2026-06-02-index-gpu-pipeline-P02-S04` - Add a real-GPU test asserting consumer-thread pipeline chunk-id and metadata parity with the serial path and that consumer exceptions propagate
- `2026-06-02-index-gpu-pipeline-P02-S05` - Validate no regression on the real codebase end to end with the resident service stopped

### plan

- `2026-06-02-index-gpu-pipeline-plan` - `index-gpu-pipeline` `dedicated gpu consumer thread pipeline` plan

### research

- `2026-06-02-index-gpu-pipeline-research` - `index-gpu-pipeline` research: `gpu pipeline saturation: decoupled chunk-tokenize-encode architecture`
