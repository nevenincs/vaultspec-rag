---
tags:
  - '#plan'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-02'
tier: L2
related:
  - '[[2026-06-02-rag-index-performance-adr]]'
  - '[[2026-06-02-rag-index-performance-research]]'
---

# `rag-index-performance` `rag index performance` plan

### Phase `P01` - parallel process-pool chunking

Break the GIL ceiling on chunking with a spawn process pool.

- [x] `P01.S01` - Extract a CPU-only chunk worker that reads, hashes, and chunks each file in one pass and never imports CUDA; `src/vaultspec_rag/indexer/_chunk_worker.py`.
- [x] `P01.S02` - Replace the ThreadPoolExecutor fan-out with a spawn ProcessPoolExecutor across full, incremental, and scoped paths with a serial fallback and a worker-count knob; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P02` - dedicated gpu consumer pipeline

Overlap CPU chunking with GPU encoding via a single dedicated consumer thread.

- [x] `P02.S03` - Add a single dedicated GPU consumer thread draining a bounded queue that owns the gpu_lock, with sentinel shutdown, exception re-raise, and bounded waits; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P03` - throughput and gating

Tune encode batch and cache flush and gate auto parallelism on workload size.

- [x] `P03.S04` - Decouple the code-path encode batch size, throttle the per-slice CUDA cache flush, and gate auto parallelism on total source bytes; `src/vaultspec_rag/config.py`.

### Phase `P04` - verify

Prove parity, fail-loud shutdown, and no regression on real GPU.

- [x] `P04.S05` - Add real-GPU parity and consumer-failure tests plus a chunk-stage benchmark, and validate the integration suite on GPU; `src/vaultspec_rag/tests/integration/`.

## Description

Implements the rag-index-performance ADR. `P01` breaks the GIL ceiling on chunking by moving
the fan-out to a spawn process pool with a CPU-only single-read worker. `P02` overlaps CPU
chunking with GPU encoding via one dedicated GPU consumer thread draining a bounded queue.
`P03` tunes the code-path encode batch and cache flush and gates auto parallelism on total
source bytes so small codebases do not regress. `P04` proves parity, fail-loud shutdown, and
no regression on real GPU. Behaviour parity (chunk identity, failure-safe rebuild,
stale-purge, serial fallback) is a hard constraint throughout.

## Steps

## Parallelization

The phases are strictly ordered `P01 -> P02 -> P03 -> P04`: the pipeline (`P02`) consumes the
process pool from `P01`, tuning (`P03`) is measured against the pipelined baseline, and
verification (`P04`) follows the implementation.

## Verification

- Every Step `P01.S01` through `P04.S05` is closed.
- A real-GPU test asserts the parallel pipeline produces the same chunk-id set and metadata
  as the serial path, and that a genuine consumer-side failure propagates without hanging.
- The codebase and indexer integration suites stay green on real GPU; no mocks or skips.
- A chunk-stage benchmark shows a parity-preserving wall-clock win on a large tree.
- `ruff` and `ty` are clean; pre-commit and `vault check all` are green.
