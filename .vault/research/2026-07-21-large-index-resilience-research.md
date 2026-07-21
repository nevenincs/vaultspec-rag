---
tags:
  - '#research'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-large-index-resilience-reference]]"
  - "[[2026-06-02-index-gpu-pipeline-adr]]"
  - "[[2026-06-02-index-perf-hardening-adr]]"
  - "[[2026-06-02-rag-index-performance-adr]]"
  - "[[2026-06-18-watcher-targeted-reindex-adr]]"
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
  - "[[2026-07-21-service-job-control-research]]"
---

# `large-index-resilience` research: `resumable and resource-bounded bulk indexing`

The incident's 21,567-file, 250,872-chunk code index repeatedly timed out, restarted
from zero, grew host RSS from about 2 GB to 19 GB, and reported CUDA allocator growth
from about 3.6 GB to 30 GB on a 16 GB GPU. It exposed no cancellation route and could not
complete a corpus below the project's accepted large-repository target.

Primary incident evidence is
`C:/Users/hello/AppData/Local/Temp/claude/copy.markdown:42-131`, with B7 through B10 at
lines 94, 99, 105, and 109.

## Findings

### F1. Retry is operation-bounded but workflow-unbounded

Qdrant calls have a timeout and finite write retry, yet watcher failures preserve
pending work and make it immediately eligible on the next idle tick. There is no
persisted failure count, next-retry time, error-keyed circuit, or overall no-progress
deadline. A blocked consumer can also keep the producer's queue loop alive beyond the
nominal shutdown bound.

### F2. Partial storage work is not a resumable transaction

Point IDs make repeated upsert idempotent, but successful slices are not journaled as a
run generation. Final code metadata is written only after the whole job. A crash or
terminal write failure leaves points without the completion sidecar; the next dispatch
classifies that state as needing a clean embedding rebuild. This is the observed
restart-from-zero contract, not merely missing progress UI.

### F3. Incremental indexing is not memory-bounded

Both incremental paths materialize all new chunks. Streaming then attaches dense and
sparse Python lists to those retained objects and creates another sorted corpus list.
Even if CUDA were perfectly flat, retaining 250,000 lists of 1,024 Python floats readily
explains multi-tens-of-gigabytes of host RSS. The bounded full-build queue does not
protect this path.

### F4. CUDA cleanup is observability, not admission control

Batch-halving reacts to allocator failure and periodic `empty_cache` can release only
unused cached blocks. Neither constrains live tensors or aborts sustained growth before
the machine is destabilized. Sparse document encoding also defaults to retaining result
tensors on the device unless `save_to_cpu=True` is requested. The exact incident CUDA
retention source remains to be proved with a controlled GPU profile; safety cannot wait
for perfect attribution.

### F5. The corpus is within the promised capability

Prior performance decisions targeted repositories of roughly 84,000 files. Rejecting
the 21,567-file incident corpus would redefine an accepted capability downward. The
250,872-chunk corpus is the acceptance floor. Honest admission limits above it should be
benchmarked and may distinguish embedded from external Qdrant.

### F6. Cancellation depends on safe points but is a separate API decision

The indexer needs cooperative checks at file, queue, retry, and slice boundaries. The
service-job-control feature should own exact-ID APIs, lifecycle states, bounded history,
and CLI semantics. Keeping it separate lets memory and retry safety ship before the
broader operator contract while preventing incompatible cancellation mechanics.

## Options considered

### Lower batch size and flush the CUDA cache more often

This reduces transient pressure but leaves whole-corpus Python retention, non-resumable
metadata, immediate watcher retries, and no hard ceiling. It is a mitigation, not a
completion contract.

### Put each index job in a killable process

Force termination is tempting but duplicates GPU contexts, bypasses centralized GPU
gating, and cannot establish whether a slice committed before death. It conflicts with
the single-consumer architecture and does not solve restart correctness.

### Persist only job progress counters

Counters improve display but are not authoritative storage checkpoints. Resume needs a
run signature and storage-committed file or slice records, otherwise the counter can
claim progress that Qdrant never accepted.

### Resumable streaming with resource and retry policies

This is the recommended direction: bounded full and incremental pipelines; durable run
generations; committed-slice journaling; idempotent replay; persistent backoff and
circuit state; process and CUDA high-water ceilings; and explicit supported-corpus
profiles. Cooperative cancellation consumes the same safe points through its sibling
ADR.

## Recommended decision boundary

The ADR should decide:

- a durable checkpoint identity, atomicity boundary, invalidation rules, and final
  metadata/purge commit;
- bounded incremental scanning and vector lifetime, with weighted queue capacity;
- operation timeout, no-progress deadline, persistent exponential backoff, retryable
  error taxonomy, and circuit transitions;
- process RSS and CUDA allocated/reserved ceilings, cleanup order, and typed terminal
  outcomes;
- admission profiles whose default includes the incident corpus;
- cancellation-safe checkpoints and bounded queue/consumer shutdown behavior shared
  with service job control;
- real storage, subprocess, and CUDA acceptance tests.

The ADR should not define the job-control HTTP/CLI surface, extend the GPU lock over
post-processing or I/O, introduce additional GPU consumer threads, or silently lower the
accepted corpus capability.

## Safety tranche

Before the large-root daemon is restarted, the first executable tranche should provide:

- bounded incremental vector lifetime;
- sparse result transfer off GPU after forward completion;
- enforceable RSS and CUDA ceilings with a structured failure;
- a no-progress deadline and persistent watcher backoff/circuit breaker;
- a durable checkpoint written before the circuit opens or memory termination returns.

Full operator cancellation may follow, but shutdown must already be able to request
cooperative stop and boundedly join indexing before store teardown.

## Acceptance floor

- Failure after several committed slices resumes with at most the last uncommitted unit
  replayed, not from zero.
- Configuration or epoch drift invalidates a checkpoint without mixing generations.
- Incremental memory stays bounded by slice/queue configuration as corpus size doubles.
- A configured low memory ceiling fails predictably, checkpoints, releases resources,
  and prevents immediate watcher retry.
- The 250,872-chunk corpus completes on the declared supported profile.
- Cancel or shutdown acknowledgement occurs only after storage writes stop and the next
  job can acquire the writer lock.

## Remaining unknowns

- The exact live-tensor, allocator, or library contribution to incident CUDA growth.
- The benchmark-derived ceiling above the incident corpus.
- The optimal file-versus-slice journal granularity and compaction cadence.
- The retry taxonomy for each Qdrant transport and schema failure.
- Whether local Qdrant can meet the accepted floor after memory bounding, or the profile
  must require server mode.
