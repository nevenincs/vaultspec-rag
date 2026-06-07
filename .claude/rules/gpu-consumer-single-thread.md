---
name: gpu-consumer-single-thread
trigger: always_on
---

# Single dedicated GPU consumer thread for indexing

Promoted from the `2026-06-02-index-gpu-pipeline` ADR codification candidate and its code
review.

## Rule

GPU encoding in the indexing pipeline runs on exactly one dedicated consumer thread that
owns `gpu_lock`. Never add a second GPU consumer thread or use CUDA streams to parallelise
compute on the single device, and never run the encode inline on the thread that drains the
process pool. Every wait involved in shutting that consumer down (the end-of-stream sentinel
put and the join) must be liveness-guarded and time-bounded so a wedged CUDA/Qdrant call
aborts the run rather than hanging it under the indexer's writer lock.

## Why

On a single GPU there is no compute/compute overlap to exploit: two compute-bound kernels
serialise on the SMs regardless of CUDA streams (research A3). The only real parallelism is
CPU-produce versus GPU-consume, captured by a process-pool producer feeding one consumer
thread that the GIL-releasing async-CUDA path keeps busy (A1/A2) — the `DataLoader` pattern.
Running the encode inline on the pool-draining thread idles the GPU during pool bookkeeping.
A second consumer thread only serialises on GIL launch overhead and the SMs. And because the
codebase index runs under `self._writer_lock`, any unbounded wait on the consumer escalates a
single GPU/Qdrant stall into a permanently wedged indexer (review C1/H1/H2).

## How

- **Good:** one `threading.Thread` consumer drains a bounded `queue.Queue`, holds `gpu_lock`
  across `encode_and_upsert_code_slice`, and is the only code that touches CUDA; the producer
  refills the queue while the GPU runs.
- **Good:** shutdown sends the `None` sentinel only while `consumer.is_alive()`, with a
  timed `put`, and `join(timeout=...)`; if the thread does not terminate within the bound,
  log and raise rather than block forever.
- **Bad:** calling `encode` inline in the `wait()`/collect/submit loop (idles the GPU during
  bookkeeping).
- **Bad:** a second GPU consumer thread, or separate CUDA streams for dense and sparse, to
  "parallelise" GPU work — they serialise on one saturated device.
- **Bad:** an unguarded blocking `queue.put(sentinel)` or unbounded `join()` on shutdown —
  a dead-without-draining or wedged consumer then hangs the producer and holds the writer
  lock indefinitely.

## Source

ADR `2026-06-02-index-gpu-pipeline-adr` (codification candidate `gpu-consumer-single-thread`)
and its code review (findings C1/H1/H2). Research `2026-06-02-index-gpu-pipeline-research`
(A1 to A3). Related rule `index-workers-stay-cpu-only`.
