---
tags:
  - '#research'
  - '#index-perf-hardening'
date: '2026-06-02'
related:
  - "[[2026-03-06-codebase-indexer-tech-stack-research]]"
---

# `index-perf-hardening` research: `codebase indexing performance: parallelism, GPU pipelining, hardware acceleration`

## Problem

`vaultspec-rag index` on a large tree (~84k files) spends over an hour in the `chunk files` stage (~21 files/s) while the GPU sits idle the entire time. The originating bug
report is `#154`; the umbrella rework is `#155`. This document grounds every candidate
optimization against both the current source and current upstream documentation, so the
sibling ADR can choose an architecture with evidence rather than guesswork.

## Current pipeline (code findings)

`CodebaseIndexer._full_index_locked` runs seven stages strictly sequentially
(`src/vaultspec_rag/indexer/_codebase_indexer.py`):

1. `scan codebase` — `os.walk` with gitignore pruning (`:218`).
1. `hash files` — serial blake2b over every file (`:457-467`).
1. `chunk files` — `ThreadPoolExecutor` fan-out of `_chunk_file` (`:471`).
1. `prepare collection` — snapshot existing ids (`:496`).
1. `embed + upsert` — streaming slices via `_stream_encode_and_upsert_codebase`
   (`:515`).
1. `purge stale chunks` (`:526`).
1. `write metadata` (`:543`).

### Finding C1 — chunking is GIL-bound; the thread pool gives no parallelism

`_chunk_file` -> `ASTChunker.chunk` -> `_collect_chunks` is pure-Python recursive AST
traversal with a per-node `source_bytes[start:end].decode("utf-8")`
(`_ast_chunker.py:148`, `:211`). tree-sitter's `Parser.parse()` and every `Node`
attribute access hold the GIL (see online finding O1), so the `ThreadPoolExecutor` at
`_codebase_indexer.py:471` serializes on a single core. This is the dominant cost and the
root cause of the "multithreading isn't working" symptom: the pool is real but the GIL
neutralizes it.

### Finding C2 — chunk and embed stages never overlap

`full_index` materializes every chunk into `all_chunks` (`:470-482`) before the first
embed call (`:515`). The two heaviest stages — CPU chunking and GPU encoding — run back
to back, so the GPU is idle for the full ~1h chunk phase and the CPU cores are idle for
the embed phase. The full chunk list (millions of `CodeChunk`s for 84k files) is also
resident at once.

### Finding C3 — redundant per-node UTF-8 decode

`_collect_chunks` decodes the whole node at `_ast_chunker.py:148`, re-decodes each child
in the loop at `:211`, and the recursion decodes that child again at its own `:148`. The
same byte ranges are decoded O(depth) times.

### Finding C4 — double full-tree file I/O

`hash files` (`:457-467`) and `chunk files` (`:471`) each open all 84k files
independently — two full-tree read passes on a cold cache.

### Finding C5 — small encode sub-batch; per-slice cache flush

The streaming helper uses `embedding_encode_batch_size = 8` (`config.py:122`) and calls
`torch.cuda.empty_cache()` every slice (`_streaming.py:118`, `:182`). The small batch was
chosen to fight padding waste on 8000-char vault docs (#68), but code chunks are capped at
1500 chars and length-sorted (`_streaming.py:150`) — short and uniform — so the batch is
needlessly small for the code path, and the per-slice flush forces a device sync each
iteration.

### Finding C6 — duplicate warmup (to confirm)

The `#154` trace shows `open store` (0:35) and `load embedding model` (0:21) running
twice (~112s) before `scan vault`. The current in-process path opens the store and loads
the model once (`cli/_index.py:330-369`), so this is likely a service-delegation-then-
fallback double warmup; confirm on the reporter's installed version.

## Online research findings (verified 2026-06-02)

### O1 — py-tree-sitter holds the GIL for parse and traverse

`Parser.parse()` runs without `Py_BEGIN_ALLOW_THREADS` (verified against
`tree_sitter/binding/parser.c`), and all `Node` attribute access is GIL-bound Python.
Threads cannot achieve multi-core parallelism for AST work; `ProcessPoolExecutor` /
multiprocessing is required. Free-threaded wheels do not exist
([py-tree-sitter #458](https://github.com/tree-sitter/py-tree-sitter/issues/458), open
2026-05-22). Confidence: high.

### O2 — Query API shrinks the constant, not the concurrency model

A compiled `Query` + `QueryCursor` runs the S-expression match loop in C and avoids a
Python call per visited node, but still does not release the GIL and still materializes
one Python object per captured node. It reduces per-file Python time but does not remove
the need for processes. Thread-safety contract: a `Query` is immutable and shareable
across threads; a `QueryCursor` and a `Parser` are not — one per worker.
[Tree-sitter Query API](https://tree-sitter.github.io/tree-sitter/using-parsers/queries/4-api.html).
Confidence: high on contract, medium on magnitude.

### O3 — ProcessPoolExecutor best practices (Python 3.13)

Use `initializer=` to build the parser/grammar once per worker (module global); pass
file **paths** not contents (avoid pickling bytes both ways); raise `chunksize` above 1
for many small files; return one compact per-file result (a `slots=True` dataclass holding
lists, not thousands of tiny objects). `max_workers` defaults to `os.process_cpu_count()`
in 3.13.
[concurrent.futures docs](https://docs.python.org/3/library/concurrent.futures.html).
Confidence: high.

### O4 — defer free-threaded CPython 3.13t

PyTorch announced (2026-05-14) it is dropping 3.13t support in nightlies and the upcoming
2.13 release; the path forward is 3.14t. tree-sitter has no free-threaded wheels. Both
hard native deps are unready — defer, revisit on 3.14t.
[PyTorch dev-discuss](https://dev-discuss.pytorch.org/t/dropping-python-3-13t-free-threaded-support-in-nightlies-and-in-the-future-pytorch-2-13-release/3386).
Confidence: high.

### O5 — raise encode batch_size; do not multi-stream dense+sparse

For short, length-uniform inputs (code chunks ≤1500 chars), `batch_size=8` leaves
throughput unused; sweep 32 -> 64 -> 128 on the 16GB RTX 4080 (ample headroom over ~1.9GB
resident weights). Overlapping dense and SPLADE on separate CUDA streams is
counterproductive: two compute-bound matmul kernels serialize on the tensor cores
regardless of stream. Keep them sequential on the default stream and get overlap from the
CPU/GPU pipeline instead.
[SBERT efficiency](https://sbert.net/docs/sentence_transformer/usage/efficiency.html),
[single-GPU stream serialization](https://discuss.pytorch.org/t/using-cuda-stream-to-perform-parallel-inference/206071).
Confidence: high on direction, medium on the exact optimum (benchmark).

### O6 — accel ladder: fp16/bf16 (have it) -> ONNX-O4 -> torch.compile/TensorRT

fp16/bf16 is the cheap win and already in use. ONNX with O4 optimization is the
highest documented short-text GPU speedup (~1.83x) and is officially supported by
sentence-transformers — the next lever if needed. `torch.compile` and TensorRT are
unofficial for SBERT, carry recompile/export risk, and should wait until profiling proves
the encoder dominates.
[SBERT efficiency](https://sbert.net/docs/sentence_transformer/usage/efficiency.html).
Confidence: high on ordering.

### O7 — bounded-queue producer/consumer; CUDA only in the consumer

Glue the stages with a bounded queue: a CPU-only `ProcessPoolExecutor` producer
(read+parse+chunk) feeds a single GPU consumer thread in the main process that accumulates
to the encode batch size and upserts. Critical gotchas: workers must never initialize
CUDA; use the `spawn` start method if any worker could touch CUDA; bound the queue (or use
lazy `map`/a bounded submit window) so memory stays capped; keep a single GPU consumer so
device access stays serialized.
[CUDA fork/spawn](https://discuss.pytorch.org/t/runtimeerror-cannot-re-initialize-cuda-in-forked-subprocess-to-use-cuda-with-multiprocessing-you-must-use-the-spawn-start-method/14083).
Confidence: high.

## Synthesis — recommended architecture (input to the ADR)

The two structural changes attack the whole hour; the rest are tuning on top.

- **Parallel chunking via process pool (addresses C1, O1, O3).** Move `_chunk_file`
  fan-out from `ThreadPoolExecutor` to `ProcessPoolExecutor` with a per-worker grammar
  initializer, passing paths and returning compact per-file chunk batches. Threads are a
  dead end here by O1.
- **Chunk -> embed pipeline (addresses C2, O7).** A bounded queue between the process-pool
  producers and a single in-process GPU consumer overlaps CPU parsing with GPU encoding
  and caps resident memory. CUDA stays out of the workers (spawn).
- **Encode batch tuning (addresses C5, O5).** Decouple the code path's encode batch size
  from the vault path and sweep to 64–128; keep dense+SPLADE sequential.
- **Single-read I/O (addresses C4).** Hash from the bytes already read for chunking.
- **Throttle `empty_cache()` (addresses C5).** Flush every N slices, not every slice.
- **Decode once (addresses C3).** Decode source once per file and slice the `str`, or
  adopt Query-based span extraction (O2) to cut per-file Python cost.

Deferred / experimental: free-threaded 3.13t (O4 — defer to 3.14t), tree-sitter Query
rewrite (O2 — secondary), ONNX-O4 / torch.compile / TensorRT (O6 — only if the encoder
proves dominant after the structural fixes).

## Open questions for the ADR

- Process-pool sizing default and override knob (env var vs config); interaction with the
  resident HTTP service which already holds a GPU and per-root locks.
- Whether the pipeline replaces both `full_index` and the incremental/scoped paths, or
  only `full_index` initially.
- Backpressure policy: bounded `queue.Queue(maxsize=K)` vs lazy `executor.map` streaming;
  how K trades memory against producer stall.
- Windows `spawn` worker startup cost (the reporter's platform is win32) and grammar
  re-import amortization.
- Benchmark methodology and the corpus used to demonstrate the "dramatic" speedup
  acceptance bar.
