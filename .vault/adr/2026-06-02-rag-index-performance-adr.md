---
tags:
  - '#adr'
  - '#rag-index-performance'
date: '2026-06-02'
modified: '2026-06-30'
related:
  - "[[2026-06-02-rag-index-performance-research]]"
---

# `rag-index-performance` adr: `parallel process-pool chunking with a dedicated gpu consumer pipeline` | (**status:** `accepted`)

## Problem Statement

Codebase indexing does not scale (bug #154): the chunk stage runs over an hour on a large
tree while the GPU idles. The research established that chunking is GIL-bound (so threads
give no speedup), that the chunk and embed stages never overlap, and that on a single GPU
the only available parallelism is CPU-produce vs GPU-consume. This ADR fixes the architecture.

## Considerations

tree-sitter holds the GIL for parse and traverse, so multi-core chunking requires a
`ProcessPoolExecutor` (free-threading is not viable). The GPU stage is single-writer and
shares the device with the resident search service via a GPU lock. torch releases the GIL
during async CUDA, so one dedicated consumer thread, fed by a separate producer, saturates
the GPU (the DataLoader pattern); more consumer threads or CUDA streams do not help because
compute-bound kernels serialise on one device.

## Constraints

- Workers stay CPU-only; the pool uses `spawn`; CUDA is touched only by the single consumer
  thread, which holds the existing GPU lock.
- Behaviour parity is mandatory: chunk identity, the failure-safe rebuild and stale-purge
  contract, idempotent upsert, and a serial fallback must all be preserved.
- Memory is bounded by a single bounded queue (backpressure) and a bounded submission window.
- Shutdown must never hang: every wait on the consumer is liveness-guarded and time-bounded,
  escalating to a raise rather than blocking the indexer writer lock forever.
- Parallelism must not regress small codebases, where spawn-pool startup exceeds the chunking
  work.

## Implementation

Codebase indexing becomes a three-stage decoupled pipeline. CPU-only `spawn` workers read,
hash, and chunk each file in a single pass and return batched per-file results (the content
hash travels with the chunks, so the tree is read once). The producer (main thread) drains
the pool over a bounded submission window and feeds completed chunk batches onto a bounded
queue. A single dedicated GPU consumer thread drains that queue, encodes dense then sparse on
the same batch, upserts to the store, and loops; it owns the GPU lock and is the only code
that touches CUDA. Shutdown uses a sentinel, captures and re-raises consumer-thread
exceptions in the main thread, and bounds every wait. Auto worker selection is gated on total
source bytes; below the threshold the path stays serial. An explicit worker-count knob and a
serial fallback (also used when the pool cannot start) are retained. A code-path encode batch
size and a throttled CUDA cache flush are tuned for short, uniform code chunks.

## Rationale

This is the only architecture that captures the available overlap and removes the GIL
ceiling, grounded in the research: processes for chunking (GIL), one consumer thread for the
GPU (async-CUDA GIL release), no stream tricks (compute/compute serialises), and a byte gate
because a benchmark proved always-parallel regresses small trees. Tokenise-in-workers and
length-bucketed batching are the next ROI levers but are deferred until profiling proves the
encoder dominates, to keep the change reviewable.

## Consequences

The chunk stage scales with cores, the GPU works during chunking instead of after it, the
tree is read once, and small codebases see no regression. Costs: a two-thread structure is
harder to reason about (exception propagation, sentinel shutdown, and lock ownership must be
exact) and is the subject of dedicated tests; the win is regime-dependent (largest on
chunk-heavy codebases). The pipeline opens the door to tokenise-in-workers and to backing the
vault-document index path with the same structure.

## Codification candidates

- **Rule slug:** `gpu-consumer-single-thread`. GPU encoding runs on exactly one dedicated
  consumer thread that owns the GPU lock; never add a second GPU consumer thread or CUDA
  streams to parallelise compute on one device, never encode inline on the pool-draining
  thread, and bound every shutdown wait so a wedged consumer aborts rather than hangs.
- **Rule slug:** `index-workers-stay-cpu-only`. Codebase-index workers never import or
  initialise CUDA/torch; the pool uses `spawn`, and every module on the worker import chain
  keeps its torch import lazy.
