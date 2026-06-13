---
generated: true
tags:
  - '#index'
  - '#rag-index-performance'
date: '2026-06-08'
modified: '2026-06-08'
related:
  - '[[2026-06-02-rag-index-performance-P01-S01]]'
  - '[[2026-06-02-rag-index-performance-P01-S02]]'
  - '[[2026-06-02-rag-index-performance-P02-S03]]'
  - '[[2026-06-02-rag-index-performance-P03-S04]]'
  - '[[2026-06-02-rag-index-performance-P04-S05]]'
  - '[[2026-06-02-rag-index-performance-adr]]'
  - '[[2026-06-02-rag-index-performance-plan]]'
  - '[[2026-06-02-rag-index-performance-research]]'
---

# `rag-index-performance` feature index

Auto-generated index of all documents tagged with `#rag-index-performance`.

## Documents

### adr

- `2026-06-02-rag-index-performance-adr` - `rag-index-performance` adr: `parallel process-pool chunking with a dedicated gpu consumer pipeline` | (**status:** `accepted`)

### exec

- `2026-06-02-rag-index-performance-P01-S01` - Extract a CPU-only chunk worker that reads, hashes, and chunks each file in one pass and never imports CUDA
- `2026-06-02-rag-index-performance-P01-S02` - Replace the ThreadPoolExecutor fan-out with a spawn ProcessPoolExecutor across full, incremental, and scoped paths with a serial fallback and a worker-count knob
- `2026-06-02-rag-index-performance-P02-S03` - Add a single dedicated GPU consumer thread draining a bounded queue that owns the gpu_lock, with sentinel shutdown, exception re-raise, and bounded waits
- `2026-06-02-rag-index-performance-P03-S04` - Decouple the code-path encode batch size, throttle the per-slice CUDA cache flush, and gate auto parallelism on total source bytes
- `2026-06-02-rag-index-performance-P04-S05` - Add real-GPU parity and consumer-failure tests plus a chunk-stage benchmark, and validate the integration suite on GPU

### plan

- `2026-06-02-rag-index-performance-plan` - `rag-index-performance` `rag index performance` plan

### research

- `2026-06-02-rag-index-performance-research` - `rag-index-performance` research: `parallel chunking and gpu pipeline`
