---
generated: true
tags:
  - '#index'
  - '#index-perf-hardening'
date: '2026-06-06'
related:
  - '[[2026-06-02-index-perf-hardening-P01-S01]]'
  - '[[2026-06-02-index-perf-hardening-P01-S02]]'
  - '[[2026-06-02-index-perf-hardening-P01-S03]]'
  - '[[2026-06-02-index-perf-hardening-P02-S04]]'
  - '[[2026-06-02-index-perf-hardening-P03-S05]]'
  - '[[2026-06-02-index-perf-hardening-P03-S06]]'
  - '[[2026-06-02-index-perf-hardening-P04-S07]]'
  - '[[2026-06-02-index-perf-hardening-P04-S08]]'
  - '[[2026-06-02-index-perf-hardening-adr]]'
  - '[[2026-06-02-index-perf-hardening-plan]]'
  - '[[2026-06-02-index-perf-hardening-research]]'
---

# `index-perf-hardening` feature index

Auto-generated index of all documents tagged with `#index-perf-hardening`.

## Documents

### adr

- `2026-06-02-index-perf-hardening-adr` - `index-perf-hardening` adr: `parallel chunking + chunk-to-embed pipeline for codebase indexing` | (**status:** `accepted`)

### exec

- `2026-06-02-index-perf-hardening-P01-S01` - Extract a module-level chunk worker plus a pool initializer that builds the per-language parser once per worker and decodes source once per file
- `2026-06-02-index-perf-hardening-P01-S02` - Swap the ThreadPoolExecutor chunk fan-out for a spawn-based ProcessPoolExecutor in the full-index path with an in-process serial fallback and a worker-count config knob
- `2026-06-02-index-perf-hardening-P01-S03` - Apply the same process-pool chunking to the incremental and scoped-incremental paths
- `2026-06-02-index-perf-hardening-P02-S04` - Wire a bounded producer/consumer so process-pool chunk batches feed a single in-process GPU consumer that advances the reporter and preserves stale-purge and failure-safe rebuild semantics
- `2026-06-02-index-perf-hardening-P03-S05` - Decouple a code-path encode batch size in config with a higher default and throttle the per-slice empty_cache to a periodic flush
- `2026-06-02-index-perf-hardening-P03-S06` - Fold file hashing into the single worker read so the tree is read once instead of twice
- `2026-06-02-index-perf-hardening-P04-S07` - Add a benchmark that captures chunk and embed wall-clock before and after on a large synthetic tree
- `2026-06-02-index-perf-hardening-P04-S08` - Add real-GPU tests for parallel chunking correctness and pipeline chunk-identity parity

### plan

- `2026-06-02-index-perf-hardening-plan` - `index-perf-hardening` `codebase indexing parallelism + GPU pipeline rework` plan

### research

- `2026-06-02-index-perf-hardening-research` - `index-perf-hardening` research: `codebase indexing performance: parallelism, GPU pipelining, hardware acceleration`
