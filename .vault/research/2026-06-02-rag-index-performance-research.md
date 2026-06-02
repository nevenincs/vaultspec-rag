---
tags:
  - '#research'
  - '#rag-index-performance'
date: '2026-06-02'
related: []
---

# `rag-index-performance` research: `parallel chunking and gpu pipeline`

## Problem

`vaultspec-rag index` on a large codebase spends over an hour in the `chunk files` stage
(~21 files/s) while the GPU sits idle the entire time (bug #154). Two questions drive this
research: why is the parallelism ineffective, and can chunking feed directly into GPU
encoding so the two overlap?

## Findings

### Root causes (verified against the source)

- **Chunking is GIL-bound.** The chunk fan-out used a `ThreadPoolExecutor`, but
  `_chunk_file` drives tree-sitter parsing plus a recursive pure-Python AST walk. The
  py-tree-sitter binding holds the GIL for both `Parser.parse()` and every `Node` attribute
  access (verified against `tree_sitter/binding/parser.c`: no `Py_BEGIN_ALLOW_THREADS`
  around the parse). CPython threads cannot run Python bytecode in parallel, so the thread
  pool gave no multi-core speedup. Multi-core requires `ProcessPoolExecutor`; free-threaded
  3.13t is not viable (PyTorch dropped it, 2026-05-14).
- **No CPU/GPU overlap.** `full_index` materialised every chunk before the first embed, so
  the GPU idled through the whole chunk phase.
- **Double file I/O.** The `hash files` stage and the `chunk files` stage each read every
  file, so the tree was read twice.

### GPU overlap is CPU-vs-GPU only

On a single GPU there is no compute/compute overlap to exploit: two compute-bound kernels
serialise on the SMs regardless of CUDA streams (NVIDIA, "How to Overlap Data Transfers in
CUDA C/C++"). The only real parallelism is CPU-produce vs GPU-consume. PyTorch releases the
GIL during async CUDA kernels (PyTorch CUDA semantics docs), so a single dedicated GPU
consumer thread fed by a separate producer keeps the GPU busy — the pattern
`torch.utils.data.DataLoader` uses (worker processes produce, a thread consumes). Multiple
consumer threads only serialise on GIL launch overhead and the SMs.

### Throughput levers (ranked, offline bulk index, single GPU)

1. Move tokenisation into the CPU workers (Rust fast-tokeniser releases the GIL) so the GPU
   thread does only the forward pass — highest ROI; deferred fast-follow.
1. Length-bucketed / token-budget batching to minimise padding waste (BucketServe) —
   deferred fast-follow.
1. Dense + sparse run sequentially on the same batch (separate streams do not overlap on one
   saturated GPU).
1. `torch.compile` / CUDA graphs — rejected for now: fixed-shape requirement fights
   variable-length text and the compiled path holds the GIL, breaking the producer-refill
   overlap.

### spawn-worker discipline

CUDA must never be initialised in workers (the fork/spawn CUDA-context rule); workers stay
CPU-only and the pool uses the `spawn` start method. Workers return batched per-file payloads
(not per-chunk objects) to amortise pickling.

### Measurements (chunk stage, serial vs parallel, parity verified)

- Real codebase (17,872 files / 50.5 MiB): 22.3s -> 11.6s (1.9x). Chunking here is already
  fast (800 files/s), so it is not the bottleneck.
- Heavy synthetic (8,000 files / 75.8 MiB): 37.0s -> 10.2s (3.6x). The speedup grows with
  per-file chunking cost; #154's 21 files/s regime sits deeper in the chunk-bound zone.
- A naive always-parallel policy regressed small trees (spawn startup ~0.3s/worker dominates
  when chunking is cheap), motivating a workload gate.

A clean end-to-end (chunk + embed) wall-clock on the live machine could not be isolated: a
second model + index run contends with the resident RAG service for the single GPU. The
architectural decision does not hinge on the exact balance — the dedicated consumer is
net-positive in both regimes (saturates the GPU when encode dominates, idles harmlessly when
chunking dominates).

## Recommendation (input to the ADR)

A three-stage decoupled pipeline: a `spawn` `ProcessPoolExecutor` of CPU-only workers that
read+hash+chunk files in one pass; a feeder that drains the pool into a bounded queue; and a
single dedicated GPU consumer thread that owns the GPU lock and encodes/upserts. Gate auto
parallelism on total source bytes so small codebases stay serial. Defer tokenise-in-workers
and length-bucketing as fast-follows.
