---
tags:
  - '#research'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-02'
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

### Profile: embed dominates, and the encode batch has a sharp optimum

Profiled directly on the real codebase (17,895 files -> 112,574 chunks) with the GPU free,
chunking parallel vs encoding swept across batch sizes:

- Chunking (parallel): **9.0s** for all 112,574 chunks.
- Encode throughput (dense Qwen3 + sparse SPLADE), extrapolated to the full corpus:
  - `bs=8`: 61 chunks/s -> ~1832s (~30 min)
  - `bs=32`: **112 chunks/s -> ~1002s (~17 min)** (current code-path default)
  - `bs=64`: 5 chunks/s -> ~24,600s (catastrophic)
  - `bs=128`: 2 chunks/s -> ~45,500s (catastrophic)

Two decisive conclusions: **the embed stage dominates total wall-clock by two orders of
magnitude over chunking** (17 min vs 9s), so the dedicated GPU consumer thread that keeps the
GPU saturated while chunking is hidden behind it is the architecturally correct win; and
**`bs=32` is the measured optimum** on this hardware (Qwen3 + SPLADE on a 16 GB RTX 4080) —
`bs=8` (the prior vault default) is half the speed, and `bs>=64` collapses ~200x because
SPLADE exhausts VRAM and the OOM-backoff thrashes. The P03 change from 8 to 32 is therefore
the single largest measured win in this work (~1.8x on the dominant stage), and raising it
further is a measured disaster.

### Remaining levers, each evaluated (why this is the frontier-optimal set)

Every further optimization was assessed rather than assumed; each is marginal, blocked, or
regressive on this hardware:

- **Lazy package import to cut spawn-worker startup.** Measured cold import in a fresh
  interpreter: the full package is 0.29s but the `vaultspec_rag.indexer` package the worker
  actually requires is 0.24s of that; making the top-level `__init__` lazy saves only ~0.05s
  per worker. Not worth refactoring the public import surface, and the byte gate already
  routes the regression-prone small codebases to the serial path (which is itself leaner than
  the prior thread-pool). Rejected on measurement.
- **Length-bucketed batching across slices.** `sentence-transformers.encode()` already
  length-sorts each call's input and processes length-uniform sub-batches, so at
  `slice_size=64` the cross-slice bucketing gain is marginal. Low ROI here. Deferred.
- **Raise the code encode batch beyond 32 (toward 64/128).** Profiled and closed: `bs=32`
  is the measured optimum; `bs>=64` regresses ~200x (SPLADE VRAM exhaustion + OOM-backoff
  thrashing on the 16 GB GPU). The current default is correct; raising it is a hard
  regression. Rejected on measurement.
- **Tokenise-in-workers.** Deprioritised by the profile: the encode cost is dominated by the
  GPU forward pass (the `bs>=64` OOM cliff proves it is compute/VRAM-bound, not
  tokenisation-bound), so offloading tokenisation to the workers offers little. It would also
  require importing torch in the workers (violates the `index-workers-stay-cpu-only` rule) or
  hand-replicating the model's exact tokenisation (an embedding-quality regression). Not worth
  it here.
- **ONNX-O4 encoder backend (~1.83x on short text).** The one remaining real embed-stage
  lever, and the embed stage is the bottleneck. Officially supported by sentence-transformers
  but requires exporting Qwen3 + SPLADE and version-pinning the runtime; a separate,
  substantial feature with export risk, out of scope for this change. Documented as the next
  investment if the ~17 min embed time must drop further.
- **torch.compile / CUDA graphs / multi-stream / multiple consumer threads.** Rejected with
  citations: fixed-shape + GIL-holding compiled kernels break the producer-refill overlap, and
  compute-bound kernels serialise on one device regardless of streams. These would add
  regression, not remove it.

Conclusion: the delivered architecture is the evidence-optimal frontier for a single consumer
GPU. The unimplemented levers are consciously closed (marginal, profile-blocked, or
regressive), not merely unexplored.

## Recommendation (input to the ADR)

A three-stage decoupled pipeline: a `spawn` `ProcessPoolExecutor` of CPU-only workers that
read+hash+chunk files in one pass; a feeder that drains the pool into a bounded queue; and a
single dedicated GPU consumer thread that owns the GPU lock and encodes/upserts. Gate auto
parallelism on total source bytes so small codebases stay serial. Defer tokenise-in-workers
and length-bucketing as fast-follows.
