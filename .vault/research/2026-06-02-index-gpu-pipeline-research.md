---
tags:
  - '#research'
  - '#index-gpu-pipeline'
date: '2026-06-02'
modified: '2026-06-02'
related:
  - "[[2026-06-02-index-perf-hardening-adr]]"
  - "[[2026-06-02-index-perf-hardening-research]]"
---

# `index-gpu-pipeline` research: `gpu pipeline saturation: decoupled chunk-tokenize-encode architecture`

## Problem

The index-perf-hardening rework (#155) introduced a chunk-to-embed pipeline, but the
question stands: can chunking feed *directly* into GPU encoding so the two run fully
concurrently, and is the GPU kept saturated? This document grounds the exact architecture
against the current code and authoritative upstream sources, so the sibling ADR can pick a
frontier design with evidence rather than intuition.

## Findings

### Code findings (current pipeline)

`CodebaseIndexer._pipeline_chunk_and_embed` runs the GPU encode (`_drain` ->
`encode_and_upsert_code_slice`) inline on the orchestrator thread — the same thread that
runs `wait(pending)`, collects worker results, and resubmits. Consequences:

- **G1 — partial overlap.** CPU chunking runs in separate worker processes, so it does
  overlap GPU encoding (workers are not GIL-bound against the consumer, and torch releases
  the GIL during CUDA kernels). This is real CPU-produce vs GPU-consume concurrency.
- **G2 — GPU idle gaps.** Because encode and pool-bookkeeping share one thread, the GPU is
  idle during `wait()` / result-collection / resubmission, and workers can starve during a
  long encode if the in-flight window drains before the orchestrator returns to refill it.
  The GPU is not pinned at ~100%.
- **G3 — tokenization on the consumer.** `model.encode_documents` tokenizes on the GPU /
  orchestrator thread, stealing time the GPU could be fed.

The design deviates from the project's own prior research (the index-perf-hardening
research, finding O7), which prescribed "a single GPU consumer thread pulls completed
batches off the queue" — a dedicated consumer, not an interleaved orchestrator.

### Online findings (verified 2026-06-02)

**A1 — Dedicated GPU consumer thread + bounded queue is canonical.** Structurally identical
to `torch.utils.data.DataLoader`: worker processes produce, a thread in the main process
consumes. A single bounded queue gives backpressure (a full queue blocks the feeder, which
stops draining the pool, propagating back to the CPU workers and bounding memory). Shutdown
via a unique sentinel object; consumer-thread exceptions must be captured and re-raised in
the main thread. Source: PyTorch CUDA semantics
(docs.pytorch.org/docs/2.11/notes/cuda.html), torch.utils.data
(docs.pytorch.org/docs/2.12/data.html). Confidence: high.

**A2 — torch releases the GIL during async CUDA, so one consumer thread suffices.** "GPU
operations are asynchronous ... enqueued to the device, but not necessarily executed until
later." The kernel runs while the Python thread returns, freeing the GIL for the producer
to refill concurrently. Multiple consumer threads on one GPU would only serialize on GIL
launch overhead and the SMs. Caveat: `torch.compile` kernels hold the GIL during launch
(pytorch#163061, pytorch#109074); eager `encode` does not. Confidence: high.

**A3 — No intra-GPU compute/compute overlap to exploit.** Overlapping a transfer with a
kernel needs concurrent copy+execute, both ops in different non-default streams, and pinned
host memory. Two compute-bound kernels do not reliably run in parallel on one device — a
forward pass that saturates the SMs serializes against another. So "feeding chunking into
encoding" yields no intra-GPU overlap; the only real parallelism is CPU-produce vs
GPU-consume. Source: NVIDIA "How to Overlap Data Transfers in CUDA C/C++" (2012-12-13);
PyTorch CUDA semantics. Confidence: high.

**A4 — Length-bucketed / token-budget batching is the top throughput lever.** Inference
servers (Triton dynamic batching; BucketServe length-bucketing) accumulate items into
size-homogeneous, full batches to minimise padding waste. Offline this is easier (the whole
corpus is available to sort). `sentence-transformers.encode()` already sorts within a call;
the win is making each accumulated GPU batch length-homogeneous and full to a token budget.
Continuous batching (vLLM) is generation-specific and does not transfer. Source: BentoML
batching handbook; BucketServe (arXiv:2507.17120). Confidence: high.

**A5 — spawn producer -> single-GPU consumer gotchas.** CUDA must stay out of workers (the
fork/spawn CUDA-context rule, already honoured). Return batched per-file payloads, not
per-chunk objects, to amortise pickling/IPC. Returning token-ID arrays instead of raw text
is viable and moves tokenization into the parallel workers; under spawn the HF-tokenizer
fork-deadlock is avoided, but set `TOKENIZERS_PARALLELISM=false` per worker. Stream results
lazily (`imap_unordered` / windowed submission) for bounded memory. Source: PyTorch forums
(fork/spawn CUDA rule); transformers#5486. Confidence: high.

**A6 — ROI ranking of further levers (offline bulk index, single GPU).**

1. Tokenize in the CPU workers (Rust fast-tokenizer releases the GIL) so the GPU thread does
   only the forward pass — highest ROI; natural extension of A1+A5.
1. Length-bucketed / token-budget batching (A4) — high ROI, cheap offline.
1. Dense + sparse sequentially on the same batch — separate streams do not overlap on one
   saturated GPU (A3); sequential amortises one tokenization/transfer.
1. `torch.compile` / CUDA graphs — DEFER. Fixed-shape requirement fights variable-length
   text, and the compiled path holds the GIL, undermining the producer-refill overlap the
   design depends on (A2 caveat).

Source: HF Tokenizers docs; "Accelerating PyTorch with CUDA Graphs" (pytorch.org/blog).
Confidence: high on 1-3; medium-high on deferring 4.

### Measurements

Chunk-stage A/B (serial vs parallel chunking in isolation, 24-core, parity verified):

- Real codebase (aeat worktree): 17,872 files / 50.5 MiB — 22.3s -> 11.6s (1.9x). Chunking
  here is already fast (800 files/s); not the bottleneck.
- Heavy synthetic: 8,000 files / 75.8 MiB — 37.0s -> 10.2s (3.6x). Speedup grows with
  per-file chunking cost; #154's ~21 files/s regime sits deeper in the chunk-bound zone.

End-to-end `full_index` (chunk + embed) wall-clock was attempted on the real codebase but a
clean isolated number could not be obtained on the live machine: a second
`EmbeddingModel` + index run contends with the resident RAG service for the single GPU
(they share the device, serialised by `gpu_lock`), so the figure would conflate the rework
with service contention. This contention is itself a design input — the consumer thread
must hold `gpu_lock` across encode, exactly as today. The architectural decision does not
hinge on the precise balance: the decoupled consumer is net-positive in both regimes (it
saturates the GPU when encode dominates and idles harmlessly when chunking dominates), so
the chunk-stage A/B above plus the upstream evidence are sufficient grounding. A clean
end-to-end figure should be captured during execution with the resident service stopped.

## Synthesis: recommended architecture (input to the ADR)

A three-stage decoupled pipeline that captures the only available overlap (CPU-produce vs
GPU-consume) and keeps the single GPU saturated:

1. Producer — `ProcessPoolExecutor(spawn)` CPU-only workers parse + chunk (and, in a later
   rollout stage, tokenize) and return batched per-file payloads. Never touch CUDA.
1. Feeder thread — drains the pool with windowed/lazy submission, accumulates chunks into
   length-bucketed, token-budget-sized batches, and pushes onto a bounded queue (the single
   backpressure + memory bound).
1. Single GPU consumer thread — pulls batches, runs dense then sparse on the same batch
   sequentially, upserts to Qdrant, loops. Sentinel shutdown; exceptions re-raised in the
   main thread; holds the existing `gpu_lock` across encode.

Reject: multiple GPU consumer threads; CUDA streams for compute/compute overlap;
pinned-memory / non-blocking copies as a primary lever (token-ID payloads are tiny);
`torch.compile` / CUDA graphs now (GIL-holding + fixed-shape, fights the overlap).

## Open questions for the ADR

- Tokenize-in-workers now or as a fast-follow? It requires the worker to hold a tokenizer
  and return token IDs, enlarging the worker import surface — weigh against the no-CUDA /
  lazy-torch discipline (rule `index-workers-stay-cpu-only`).
- Whether the dedicated-consumer design replaces the interleaved orchestrator outright, and
  how the serial fallback and BrokenProcessPool semantics map onto a two-thread structure.
- Batch sizing: token-budget vs fixed `slice_size`; interaction with the existing
  `embedding_code_encode_batch_size` and the length-sort already in the streaming helper.
- Whether the same pipeline should back the vault-document index path for symmetry.
