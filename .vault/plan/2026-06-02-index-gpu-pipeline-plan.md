---
tags:
  - '#plan'
  - '#index-gpu-pipeline'
date: '2026-06-02'
tier: L2
related:
  - '[[2026-06-02-index-gpu-pipeline-adr]]'
  - '[[2026-06-02-index-gpu-pipeline-research]]'
---

# `index-gpu-pipeline` `dedicated gpu consumer thread pipeline` plan

### Phase `P01` - dedicated gpu consumer thread

Replace the inline encode with a dedicated GPU consumer thread draining a bounded queue so the GPU stays saturated while CPU workers chunk.

- [ ] `P01.S01` - Add a bounded-queue feeder plus a single dedicated GPU consumer thread that owns the gpu_lock and runs dense then sparse encoding, replacing the inline drain; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `P01.S02` - Shut the consumer down with a sentinel and re-raise any consumer-thread exception in the main thread, and move stale-purge and metadata accounting after the join; `src/vaultspec_rag/indexer/_codebase_indexer.py`.
- [ ] `P01.S03` - Preserve the serial byte-gate path and the BrokenProcessPool fallback as the single-threaded inline form under the two-thread structure; `src/vaultspec_rag/indexer/_codebase_indexer.py`.

### Phase `P02` - verify

Prove parity and no regression on real GPU.

- [ ] `P02.S04` - Add a real-GPU test asserting consumer-thread pipeline chunk-id and metadata parity with the serial path and that consumer exceptions propagate; `src/vaultspec_rag/tests/integration/`.
- [ ] `P02.S05` - Validate no regression on the real codebase end to end with the resident service stopped; `src/vaultspec_rag/tests/benchmarks/`.

## Description

Implements the architecture accepted in the index-gpu-pipeline ADR (stage one): replace the
inline encode in the codebase indexer's chunk-to-embed pipeline with a dedicated GPU
consumer thread draining a bounded queue, so the single GPU stays saturated while the
`spawn` worker pool chunks. The only overlap available on one GPU is CPU-produce versus
GPU-consume (research A1 to A3); a single consumer thread suffices because torch releases
the GIL during async CUDA. Behaviour parity (chunk identity, failure-safe rebuild,
stale-purge, byte-gate serial path, BrokenProcessPool fallback) is a hard constraint.
Tokenise-in-workers and length-bucketed batching are deferred fast-follows named in the ADR.

## Steps

## Parallelization

`P01` is strictly ordered before `P02`. Within `P01`, `S01` (the consumer thread + feeder)
lands first; `S02` (shutdown, exception propagation, post-join accounting) and `S03`
(serial / fallback preservation) build on it and must follow in order on the same file.
`P02` `S04` (parity test) and `S05` (end-to-end no-regression check) can be authored in
parallel but both require `P01` complete.

## Verification

- Every Step `P01.S01` through `P02.S05` is closed (`- [x]`).
- A real-GPU test asserts the consumer-thread pipeline produces a chunk-id set and metadata
  identical to the serial path on the same corpus, and that an exception raised in the
  consumer aborts (does not hang) the index.
- The full codebase + indexer integration suite stays green on real GPU; no mocks/skips.
- `ruff` and `ty` clean on changed files; pre-commit green.
- The byte-gate serial path and BrokenProcessPool fallback remain covered.
- `vaultspec-code-review` signs off.
