---
tags:
  - '#adr'
  - '#index-perf-hardening'
date: '2026-06-02'
modified: '2026-06-30'
related:
  - "[[2026-06-02-index-perf-hardening-research]]"
---

# `index-perf-hardening` adr: `parallel chunking + chunk-to-embed pipeline for codebase indexing` | (**status:** `accepted`)

## Problem Statement

Full codebase indexing does not scale. On a ~84k-file tree the `chunk files` stage runs
over an hour at ~21 files/s while the GPU is idle, making first-index and clean-rebuild
unviable on large repositories (bug `#154`, umbrella `#155`). The research document
establishes two structural root causes: chunking is GIL-bound despite a thread pool
(finding C1 / O1), and the CPU chunk stage never overlaps the GPU embed stage (finding
C2). This ADR decides the architecture that removes both.

## Considerations

The chunk workload is CPU-bound pure-Python tree-sitter traversal. Research finding O1
verified — against the `tree_sitter/binding/parser.c` source — that both `Parser.parse()`
and `Node` attribute access hold the GIL, so the existing `ThreadPoolExecutor` cannot use
more than one core. Multi-core parallelism therefore requires process-level parallelism,
not threads.

The embed workload is GPU-bound and single-writer: one CUDA device, already serialized
behind a `gpu_lock` shared with search. Running two compute-bound encoders (dense Qwen3
and sparse SPLADE) on separate CUDA streams does not help — research O5 confirmed they
serialize on the tensor cores regardless of stream. The only available overlap is
CPU-vs-GPU: keep the GPU fed while CPU workers chunk.

This points at a producer/consumer pipeline (research O7): a process pool produces chunks,
a single in-process GPU consumer drains them. The hard constraint is that CUDA must be
initialized only in the consumer; worker processes must stay CPU-only, and the pool must
use the `spawn` start method so no forked process inherits a CUDA context.

## Constraints

- **No free-threading.** Research O4: PyTorch is dropping CPython 3.13t and tree-sitter
  ships no free-threaded wheels. The no-GIL escape hatch is deferred to a future 3.14t
  world and is explicitly out of scope.
- **`spawn` startup cost on Windows.** The reporting platform is win32, where `spawn` is
  the only start method and re-imports the interpreter per worker. Grammar/parser
  construction must be amortized once per worker via a pool `initializer` (research O3),
  not per file, or worker startup dominates on small trees.
- **Pickling boundary.** Worker results cross a process boundary, so `CodeChunk`
  production must return pickle-friendly, compact per-file batches (research O3). The
  current `_chunk_file` already returns plain dataclasses; it must avoid returning
  thousands of tiny objects where one batched result suffices.
- **Single-GPU serialization preserved.** The consumer must hold the existing `gpu_lock`
  across encode so concurrent searches on the resident service are not corrupted. The
  pipeline changes who produces chunks, not how the GPU is shared.
- **Bounded memory.** The current code holds every chunk resident (C2). The pipeline must
  bound in-flight work (a queue cap or a bounded submit window) so a large tree cannot
  exhaust RAM.
- **Behavior parity.** Chunk identity, line tracking, stale-chunk purge semantics, and the
  failure-safe rebuild contract from `#68` must be preserved exactly; this is a throughput
  change, not a correctness change.

## Implementation

The change layers in four parts, smallest blast radius first.

The **chunking executor** moves from `ThreadPoolExecutor` to a `ProcessPoolExecutor`
created with the `spawn` context and an `initializer` that constructs the per-language
parser/chunker once per worker and stores it in a module global. Workers receive file
paths, not contents, and each worker reads, parses, and chunks its file, returning a
single compact per-file result. This is the change that breaks the GIL ceiling.

The **chunk-to-embed pipeline** replaces the "materialize all chunks, then stream embed"
sequence with a bounded producer/consumer: the process pool is the producer; a single GPU
consumer (the existing streaming embed/upsert path) drains completed per-file chunk
batches off a bounded queue, accumulates them to the encode batch size, encodes dense then
sparse sequentially, and upserts. CUDA initializes only in the consumer. Backpressure is a
bounded queue (or a bounded in-flight submit window over `executor.map` with a tuned
`chunksize`) so resident memory is capped regardless of tree size.

The **encode batch tuning** introduces a code-path-specific encode batch size decoupled
from the vault path's small value, defaulting higher (a swept value in the 64–128 band)
because code chunks are short and length-uniform; the per-slice `empty_cache()` becomes a
periodic flush every N slices to drop the per-iteration device sync.

The **I/O and decode cleanups** fold hashing into the single worker read so the tree is
read once instead of twice, and decode the source once per file in the AST chunker rather
than O(depth) times. These are independent and can land incrementally.

A configuration knob governs worker count (defaulting to `os.process_cpu_count()`), and a
fallback to in-process serial chunking is retained for environments where a process pool
cannot start (and for small trees where `spawn` overhead would dominate).

## Rationale

Process-pool chunking is not a preference but a consequence: research O1 proved threads
cannot scale this workload, so processes are the only multi-core path while free-threading
is unavailable (O4). The pipeline is the only way to reclaim the GPU-idle hour, since the
two heavy stages are on different hardware (CPU vs GPU) and cannot otherwise overlap (C2,
O7). Batch tuning and the I/O/decode cleanups are lower-risk multipliers grounded in C3,
C4, C5 and O5. The accel ladder beyond fp16 (ONNX-O4, torch.compile, TensorRT) is
deliberately deferred (O6) until profiling after the structural fixes proves the encoder,
not chunking, is the remaining bottleneck — spending that integration risk now would be
premature.

## Consequences

Gains: the chunk stage scales with cores instead of pinning one; the GPU works during
chunking instead of after it; peak memory is bounded; the tree is read once. Together
these target the order-of-magnitude wall-clock reduction the umbrella issue requires.

Costs and risks: `spawn` worker startup adds fixed latency that hurts small trees, so the
in-process fallback and a worker-count floor matter. Multiprocessing complicates error
propagation and progress reporting — the reporter must advance from the consumer side as
batches complete, and worker exceptions must surface rather than vanish. Debugging a
process pool is harder than a thread pool. The `spawn`/CUDA discipline is a sharp edge: any
accidental CUDA import in worker code reintroduces the fork-CUDA crash class, which is why
it becomes a codification candidate below.

Pathways opened: once the pipeline exists, the incremental and scoped-reindex paths can
adopt the same producer/consumer for consistency, and the ONNX-O4 encoder upgrade (O6)
plugs into the consumer without touching the producer.

## Codification candidates

- **Rule slug:** `index-workers-stay-cpu-only`.
  **Rule:** Codebase-index worker processes must never import or initialize CUDA/torch;
  the embedding GPU is touched only by the single in-process consumer, and the worker pool
  must use the `spawn` start method.
