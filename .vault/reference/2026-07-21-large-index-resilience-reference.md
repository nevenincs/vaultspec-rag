---
tags:
  - '#reference'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-27'
body_hash: 'sha256:7d8232aaa8581f40b35f6b313eaac369987ef284c071db6afc66f47ece93d6e7'
related:
  - "[[2026-06-02-index-gpu-pipeline-adr]]"
  - "[[2026-06-02-index-perf-hardening-adr]]"
  - "[[2026-06-02-rag-index-performance-adr]]"
  - "[[2026-06-18-watcher-targeted-reindex-adr]]"
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
  - "[[2026-07-21-service-job-control-reference]]"
---

# `large-index-resilience` reference: `retry, checkpoint, and memory-control seams`

## Summary

This reference maps incident items B7 through B10 to the current index, watcher, job,
and embedding implementation. It records concrete change and real-test seams without
starting the poisoned workload or attributing unmeasured CUDA growth to one mechanism.

### Failure and retry topology

- `src/vaultspec_rag/jobs.py:542-665` launches vault and code reindex work in unbounded
  background tasks or threads. The global task set at line 75 is not keyed by exact job
  ID, so it cannot support targeted control.
- `src/vaultspec_rag/store.py:59,218,707` applies a hard-coded 120-second Qdrant
  operation timeout.
- `src/vaultspec_rag/_store_writes.py:49-134` adds five-attempt exponential retry. A
  blocked write can therefore consume roughly five operation timeouts plus backoff.
- `src/vaultspec_rag/watcher.py:307-377` and `:401-494` clear pending vault/code work
  only on success. Failure leaves it eligible on the next idle tick, with no persisted
  backoff, circuit state, or error classification.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1035-1044` has a nominal 300-second
  consumer shutdown deadline, but `:1238-1243` can loop forever trying to enqueue while
  a blocked consumer remains alive.

Keep operation-level retries, but expose their parameters. Add a no-progress deadline
rather than a total job deadline, because a healthy 250,000-chunk run is legitimately
long. Persist consecutive failures, classification, `next_retry_at`, and circuit state
per watcher target; coalesce pending paths while open.

### Checkpoint gap

- `src/vaultspec_rag/jobs.py:82-131` persists active-job display state and converts
  abandoned jobs to interrupted, but not committed indexing progress.
- `src/vaultspec_rag/jobs.py:304-347` persists progress mainly when the named step
  changes, not after each committed storage slice.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1381-1450` upserts a full rebuild
  before committing final metadata.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1447,1665,1847,1895` commits durable
  code metadata only on successful completion.
- `src/vaultspec_rag/indexer/_code_meta.py:96-109` treats a nonempty collection without
  that final sidecar as an embedding rebuild. The dispatch at
  `src/vaultspec_rag/indexer/_codebase_indexer.py:1568-1583` then returns to a clean
  rebuild rather than resuming partial work.

Add a durable run generation keyed by root, source type, content/embedding/membership
epochs, and configuration fingerprint. Journal only storage-committed slices. A file is
complete only when all its chunks commit. Stable point IDs permit replay to skip work
already committed under the same signature; incompatible signatures invalidate the run
safely. Compact the journal only after atomic final metadata and purge completion.

### Host-memory amplification

The full build has a bounded producer/consumer queue, but both incremental paths retain
the corpus and its vectors:

- `src/vaultspec_rag/indexer/_codebase_indexer.py:1544-1651` materializes unscoped
  incremental `all_new_chunks` before streaming.
- `src/vaultspec_rag/indexer/_codebase_indexer.py:1764-1829` does the same for scoped
  incremental work.
- `src/vaultspec_rag/indexer/_streaming.py:233-244` attaches dense and sparse Python
  lists to every `CodeChunk`; deleting temporary arrays does not clear fields on retained
  chunks.
- `src/vaultspec_rag/indexer/_streaming.py:275-290` also creates a sorted full-corpus
  list before slicing.

At 250,000 chunks by 1,024 dense dimensions, Python float-list retention alone can grow
to tens of gigabytes before sparse vectors and object overhead. Stream incremental
scan/chunk/encode/upsert, use weighted backpressure by estimated bytes/chunks, and clear
vector fields immediately after a successful upsert.

### CUDA retention and safety controls

- `src/vaultspec_rag/embeddings.py:492-541` and `:600-638` have finite dense and sparse
  CUDA-OOM batch-halving ladders, but OOM recovery is not a proactive ceiling.
- `src/vaultspec_rag/indexer/_streaming.py:223-240` correctly keeps Qdrant I/O outside
  the GPU gate.
- `src/vaultspec_rag/indexer/_streaming.py:273-290` flushes the CUDA cache periodically;
  `src/vaultspec_rag/config.py:407,442-449` defaults that to every eight slices.
- `src/vaultspec_rag/memory_probe.py:206-236` records and logs memory but cannot stop
  unsafe growth.
- The locked Sentence Transformers version is 5.6.0. Its sparse document encoding API
  defaults to tensor output with `save_to_cpu=False`; the current sparse path omits that
  argument. Moving completed sparse batches to CPU is a concrete mitigation, but not a
  substitute for bounded live data and a hard ceiling.

PyTorch distinguishes live tensor bytes (`memory_allocated`) from allocator-managed
bytes (`memory_reserved`); `empty_cache` releases only unoccupied cache and does not free
live tensors. Its per-process memory-fraction API can force an allocator OOM at a
configured fraction. Primary API locators are
`https://docs.pytorch.org/docs/stable/cuda`,
`https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.memory_allocated.html`,
`https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.memory_reserved.html`,
and
`https://docs.pytorch.org/docs/stable/generated/torch.cuda.memory.set_per_process_memory_fraction.html`.
The Sentence Transformers API locator is
`https://www.sbert.net/docs/package_reference/sparse_encoder/SparseEncoder.html`.

Sample process RSS and CUDA allocated/reserved high-water marks outside the GPU lock.
Enforce configured ceilings with a typed `memory_limit` or `gpu_memory_ceiling` terminal
outcome after cleanup and checkpointing. Do not extend the global GPU lock over tensor
conversion, cache release, instrumentation, or storage I/O.

### Supported-corpus boundary

`src/vaultspec_rag/store.py:63` suppresses the local Qdrant collection-size warning but
does not replace it with an honest support contract. Admission should declare explicit
file, chunk, byte, and backend limits. The incident corpus of 21,567 files and 250,872
chunks is below the previously accepted approximately 84,000-file capability target, so
it is the acceptance floor rather than input to reject. Limits above that floor must be
derived from benchmarks; a larger profile may require external Qdrant.

### Cancellation boundary

The sibling service-job-control research owns the operator API decision. Relevant seams
for this feature are the cooperative checkpoints it requires:

- `src/vaultspec_rag/server/_routes.py:241-308,973-990` has listing and reindex routes
  but no mutation route.
- `src/vaultspec_rag/server/_routes_jobs.py:167-170` accepts job-ID prefixes for lookup;
  mutation must require exact IDs.
- `src/vaultspec_rag/server/_watcher.py:150-160` can cancel the AnyIO wrapper without
  stopping its synchronous worker.
- `src/vaultspec_rag/server/_lifespan.py:426-446` closes stores after watcher shutdown
  without first cooperatively cancelling and joining all indexing jobs.

Cancellation checks belong at phase, file, queue, retry, and slice boundaries, before or
after the GPU forward-pass critical section. `cancelled` is terminal only after writes
cease and writer/GPU resources are released.

### Real-behavior regression matrix

- Interrupt a deterministic multi-slice isolated run after committed slices, restart on
  the same storage, and verify resume begins above zero with exact final IDs/counts.
- Change an epoch or configuration fingerprint and verify the prior checkpoint is
  rejected safely.
- Stop real isolated Qdrant mid-upsert or use a genuinely incompatible collection;
  verify increasing watcher retry intervals, pending-path coalescing, circuit opening,
  bounded termination, and recovery after the backend is restored.
- On real CUDA, compare incremental runs at `N` and `2N`; RSS and CUDA high-water growth
  must remain slice-bounded. A deliberately low configured ceiling must yield the typed
  terminal outcome.
- Run scheduled/local acceptance at the actual 250,872-chunk floor. Routine CI may run
  the identical production path with a lower configured test ceiling.
- Cancel a real long-running job by exact ID, wait for writes to stop, and prove a second
  job acquires the same writer lock. Repeated cancellation must be idempotent.
