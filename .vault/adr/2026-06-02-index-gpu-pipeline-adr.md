---
tags:
  - '#adr'
  - '#index-gpu-pipeline'
date: '2026-06-02'
related:
  - "[[2026-06-02-index-gpu-pipeline-research]]"
  - "[[2026-06-02-index-perf-hardening-adr]]"
---

# `index-gpu-pipeline` adr: `decoupled producer-consumer indexing pipeline with dedicated gpu consumer thread` | (**status:** `accepted`)

## Problem Statement

The index-perf-hardening pipeline (#155) overlaps CPU chunking with GPU encoding, but the
encode runs inline on the orchestrator thread that also drives the process pool. The GPU
therefore idles during pool bookkeeping (`wait` / collect / resubmit), workers can starve
during a long encode, and tokenisation runs on the consumer thread (research findings G1 to
G3). This ADR decides the architecture that keeps the single GPU saturated and removes the
remaining serialisation, answering directly the question "can chunking feed straight into
encoding so the two run fully concurrently?".

## Considerations

The research establishes the governing physics: on one GPU there is no compute/compute
overlap to exploit — two compute-bound kernels serialise regardless of CUDA streams (A3).
The only real parallelism is CPU-produce versus GPU-consume. PyTorch releases the GIL while
an async CUDA kernel runs (A2), so a single dedicated consumer thread is sufficient to keep
the GPU busy provided a separate producer keeps its input queue non-empty — which is exactly
how `torch.utils.data.DataLoader` is built (worker processes produce, a thread consumes,
A1). Multiple consumer threads would only serialise on GIL launch overhead and the SMs.

Beyond the thread split, two levers raise throughput further: moving tokenisation into the
CPU worker processes (Rust fast-tokenisers release the GIL) so the GPU thread does only the
forward pass (A6.1), and accumulating chunks into length-bucketed, token-budget-sized
batches to minimise padding waste (A4). Both are offline-friendly. `torch.compile` / CUDA
graphs are explicitly out of scope: they require fixed shapes (fighting variable-length
text) and hold the GIL during launch, which would undermine the producer-refill overlap the
whole design depends on (A6.4).

## Constraints

- **Single GPU shared with the resident service.** The consumer thread must acquire the
  existing `gpu_lock` across each encode so it serialises correctly with live search; the
  GPU is never touched off that thread.
- **No CUDA in workers.** The `spawn` worker pool stays CPU-only; the lazy-torch / no-CUDA
  discipline (rule `index-workers-stay-cpu-only`) is unchanged and, if tokenisation moves
  into workers, must extend to "tokenizer yes, torch/CUDA no".
- **Bounded memory.** A single bounded queue between feeder and consumer is the sole
  backpressure knob; a full queue must stall the feeder, which stalls pool draining, which
  stalls the workers. No unbounded buffering of chunks or futures.
- **Behaviour parity (hard).** Chunk identity, the failure-safe rebuild and stale-purge
  contract (#68), idempotent upsert, the byte-gate serial path, and the BrokenProcessPool
  fallback must all survive the move to a two-thread structure. This is a throughput change,
  not a correctness change.
- **Exception propagation.** A consumer-thread exception does not surface in the main thread
  automatically; it must be captured and re-raised so a GPU/Qdrant failure aborts the index
  rather than hanging it.

## Implementation

The interleaved orchestrator in the codebase indexer's pipeline is replaced by a
three-stage decoupled pipeline.

The **producer** remains the `spawn` `ProcessPoolExecutor` of CPU-only workers that read,
hash, and chunk files, returning batched per-file results. The **feeder** — the main thread
— drains the pool with a bounded in-flight submission window (as today), but instead of
encoding inline it accumulates chunks into length-bucketed, token-budget batches and pushes
them onto a bounded queue. A **single GPU consumer thread** pulls batches, runs dense then
sparse encoding on the same batch sequentially, upserts to the store, and loops; it owns the
`gpu_lock` and is the only code that touches CUDA. Shutdown is a sentinel object enqueued
once the feeder is done; the feeder joins the consumer and re-raises any captured
consumer-thread exception. The stale-purge, metadata write, and IndexResult accounting move
after the join so they observe the full upserted set.

Tokenisation-in-workers is staged: stage one lands the consumer-thread split (the primary
GPU-saturation win) with tokenisation still inside `encode`; stage two moves tokenisation
into the workers (returning token-ID payloads) once the split is proven, keeping the change
surface reviewable and the no-CUDA discipline auditable. The serial path (byte gate or
`index_chunk_workers=1`) and the BrokenProcessPool fallback are preserved by running the
single-threaded inline form when the pool is not used, so the two-thread structure exists
only on the parallel path.

## Rationale

The decoupled consumer is not a preference but the canonical resolution: it is the
DataLoader pattern, it is what this project's own prior research prescribed (O7) and the
current code under-built, and it captures the only overlap that physically exists on one GPU
(A1 to A3). It is net-positive in both regimes — it saturates the GPU when encoding
dominates and idles harmlessly when chunking dominates — so it carries no downside that
would require the (contended, deferred) end-to-end balance measurement to justify it.
Length-bucketing and tokenise-in-workers are the highest-ROI throughput levers that remain
after the split (A4, A6), and the rejected options (multi-stream compute overlap,
pinned-memory as a primary lever, `torch.compile` now) are rejected on cited evidence rather
than taste.

## Consequences

Gains: the GPU runs continuously while CPU workers chunk and (stage two) tokenise; padding
waste drops via length-bucketed batches; the architecture matches the well-trodden
DataLoader model, easing future maintenance. Costs and risks: a two-thread structure is
harder to reason about than an inline loop — exception propagation across the thread
boundary, clean sentinel shutdown, and `gpu_lock` ownership must be exact or the index can
hang or deadlock; the serial/fallback paths now have a different shape from the parallel
path and must be tested independently. The win is regime-dependent: codebases where chunking
is already cheap (measured: the real aeat tree at 800 files/s) see little end-to-end change,
while chunk-bound codebases (the #154 profile) gain the most — the byte gate already ensures
no regression on small trees. Pathways opened: the same producer/consumer can back the
vault-document index for symmetry, and tokenise-in-workers sets up a future where the GPU
thread is a pure forward-pass loop amenable to further batching work.

## Codification candidates

- **Rule slug:** `gpu-consumer-single-thread`.
  **Rule:** GPU encoding in the indexing pipeline runs on exactly one dedicated consumer
  thread that owns `gpu_lock`; never add a second GPU consumer thread or CUDA streams to
  parallelise compute on the single device (they serialise on the SMs and the GIL), and
  never run the encode inline on the pool-draining thread (it idles the GPU during
  bookkeeping).
