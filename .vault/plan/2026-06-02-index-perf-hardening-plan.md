---
tags:
  - '#plan'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-02'
tier: L2
related:
  - '[[2026-06-02-index-perf-hardening-adr]]'
  - '[[2026-06-02-index-perf-hardening-research]]'
---

# `index-perf-hardening` `codebase indexing parallelism + GPU pipeline rework` plan

### Phase `P01` - parallel process-pool chunking

Replace the GIL-bound ThreadPoolExecutor chunk fan-out with a spawn-based ProcessPoolExecutor so AST chunking scales across cores.

- [x] `P01.S01` - Extract a module-level chunk worker plus a pool initializer that builds the per-language parser once per worker and decodes source once per file; `src/vaultspec_rag/indexer/_ast_chunker.py`.
- [x] `P01.S02` - Swap the ThreadPoolExecutor chunk fan-out for a spawn-based ProcessPoolExecutor in the full-index path with an in-process serial fallback and a worker-count config knob; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [x] `P01.S03` - Apply the same process-pool chunking to the incremental and scoped-incremental paths; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P02` - chunk-to-embed pipeline

Overlap CPU chunking with GPU encoding via a bounded producer/consumer so the GPU is never idle and memory stays capped.

- [x] `P02.S04` - Wire a bounded producer/consumer so process-pool chunk batches feed a single in-process GPU consumer that advances the reporter and preserves stale-purge and failure-safe rebuild semantics; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P03` - throughput and io tuning

Raise the code-path encode batch, throttle the per-slice cache flush, read each file once, and decode source once per file.

- [x] `P03.S05` - Decouple a code-path encode batch size in config with a higher default and throttle the per-slice empty_cache to a periodic flush; `src/vaultspec_rag/config.py`.
- [x] `P03.S06` - Fold file hashing into the single worker read so the tree is read once instead of twice; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P04` - benchmark and verification

Prove a dramatic, reproducible speedup with a before/after benchmark and real-GPU tests.

- [x] `P04.S07` - Add a benchmark that captures chunk and embed wall-clock before and after on a large synthetic tree; `src/vaultspec_rag/tests/benchmarks/`.
- [x] `P04.S08` - Add real-GPU tests for parallel chunking correctness and pipeline chunk-identity parity; `src/vaultspec_rag/tests/integration/`.

## Description

This plan implements the architecture accepted in the index-perf-hardening ADR, grounded
in the index-perf-hardening research (code findings C1 to C6, online findings O1 to O7).
It targets the codebase-index path only; the vault-index path is unchanged. Phase `P01`
breaks the GIL ceiling on chunking by moving the fan-out from a thread pool to a
spawn-based process pool, since tree-sitter holds the GIL for both parse and traverse and
free-threading is deferred. Phase `P02` overlaps the CPU chunk stage with the GPU embed
stage through a bounded producer/consumer so the GPU stops idling through the chunk phase,
with CUDA confined to the single consumer. Phase `P03` applies lower-risk throughput
multipliers: a code-path-specific encode batch raised into the 64 to 128 band, a throttled
cache flush, and a single full-tree read. Phase `P04` proves the result with a
before/after benchmark and real-GPU correctness tests. Behavior parity (chunk identity,
line tracking, stale-purge, and the failure-safe rebuild from the `#68` work) is a hard
constraint throughout.

## Steps

## Parallelization

The Phases carry hard ordering. `P01` (process-pool chunking) must land before `P02`,
because the pipeline consumes the process pool the first Phase introduces. `P02` must land
before `P03` so batch and cache tuning is measured against the pipelined baseline rather
than the old sequential one. Within `P01`, `S01` (worker plus initializer extraction)
blocks both `S02` and `S03`; `S02` and `S03` then share the new worker and should land in
sequence to keep the full and incremental paths consistent. `P03` `S05` (config batch
plus cache flush) and `S06` (single-read I/O) are independent of each other and may land in
either order. `P04` is sequenced last; the benchmark (`S07`) and the correctness tests
(`S08`) can be authored in parallel but both require `P01` to `P03` complete to produce
meaningful numbers.

## Verification

- Every Step row `P01.S01` through `P04.S08` is closed (`- [x]`).
- `vaultspec-rag test` passes with real GPU and real Qdrant; no mocks, skips, or stubs are
  introduced.
- Chunk-identity parity: the set of chunk ids produced by the process-pool path equals the
  set produced by the prior serial path for the same corpus (asserted by a real-GPU test).
- The benchmark records chunk-stage and embed-stage wall-clock before and after on the
  same large synthetic tree, and demonstrates a dramatic reduction in total wall-clock
  (target: an order-of-magnitude reduction in the chunk stage and meaningful overlap of the
  embed stage).
- `ruff` and `ty` report no new violations on the changed files; the pre-commit suite is
  green.
- `vaultspec-code-review` signs off on the changes.
