---
tags:
  - '#adr'
  - '#large-index-resilience'
date: '2026-07-21'
modified: '2026-07-21'
related:
  - "[[2026-07-21-large-index-resilience-research]]"
  - "[[2026-07-21-large-index-resilience-reference]]"
  - "[[2026-06-02-index-gpu-pipeline-adr]]"
  - "[[2026-06-02-index-perf-hardening-adr]]"
  - "[[2026-06-02-rag-index-performance-adr]]"
  - "[[2026-06-18-watcher-targeted-reindex-adr]]"
  - "[[2026-07-21-index-backpressure-storage-hygiene-adr]]"
  - "[[2026-07-21-service-job-control-adr]]"
---

# `large-index-resilience` adr: `durable resumable and resource-bounded indexing` | (**status:** `accepted`)

## Problem Statement

Large codebase indexing has operation-level timeouts and bounded storage retries, but the
workflow remains unbounded. A failed watcher attempt becomes eligible on the next idle tick,
a restarted full build has no authoritative record of storage-committed work, and incremental
paths retain whole-corpus chunks and vectors. Memory probes report growth without enforcing a
limit, and no-progress detection is an operator hint rather than a termination policy.

The incident corpus contained 21,567 files and 250,872 chunks, yet repeated attempts
restarted from zero, grew host RSS and CUDA allocation until the machine became unsafe,
exposed no cooperative stop point, and did not complete. This corpus is below the accepted
large-repository target, so silently rejecting it would reduce an existing capability.

This ADR decides durable checkpointing, bounded streaming, workflow retry, no-progress,
memory-ceiling, corpus-admission, and control-safe-point contracts. The service-job-control
ADR continues to own job lifecycle and operator APIs.

## Considerations

- Stable point IDs make replayed upserts idempotent, but do not prove which work reached
  storage or prevent recomputation after restart.
- Storage mutation and a local checkpoint cannot form one cross-system transaction. Recovery
  must record completion after confirmed storage mutation and tolerate replay after a crash
  between those operations.
- The full-build queue bounds item count, not retained bytes, and does not cover incremental
  paths, metadata accumulation, vector-bearing chunks, or oversized files.
- Sentence Transformers 5.6.0 sparse document encoding retains results on GPU unless CPU
  transfer is requested. CUDA cache release cannot release live tensors or enforce a ceiling.
- The service shares one GPU between indexing and search. Enforcement preserves the single
  consumer and does not widen `gpu_lock` over conversion, instrumentation, retries,
  checkpointing, or storage I/O.
- A healthy 250,000-chunk run may be long. Liveness must measure time since durable progress,
  not total duration.
- Watcher pending sets are a continuing convergence obligation. Failure preserves intent,
  but an idle tick cannot bypass backoff.
- Cooperative pause and cancellation are acknowledged only where no indivisible mutation is
  active and execution resources can be released.
- Explicit clean rebuilds drop the current collection before replacement. Without a shadow
  collection, their destructive interval remains longer than a normal failure-safe rebuild.
- The GPU pipeline, CPU-only workers, targeted reindex, drift epochs, and bounded storage
  writes are stable accepted parents. Service job control is accepted but not yet implemented;
  this ADR supplies its checkpoint and safe-point behavior.

## Considered options

- **Reduce batch size and flush CUDA cache more often.** Rejected as the architecture: it
  leaves whole-corpus retention, restart-from-zero behavior, immediate watcher retries, and
  no enforceable ceiling.
- **Keep idempotent replay and persist display counters.** Rejected: a counter is not evidence
  of a completed storage mutation.
- **Run each job in a killable process.** Rejected: it adds GPU contexts, cross-process writer
  ownership, and ambiguous in-flight commits while violating the single-consumer model.
- **Build every run in a shadow collection.** Deferred: it shortens the clean-rebuild
  destructive interval but doubles peak storage and needs backend-specific publication.
- **Resumable weighted streaming with a transactional run ledger and service-owned safety
  policy.** Chosen: it bounds every index mode, records confirmed mutations, supports
  idempotent recovery, and turns retry, liveness, and memory failures into typed outcomes.

## Constraints

- Exactly one in-process GPU consumer performs indexing forward passes. No second consumer,
  CUDA-stream parallelism, or process-local GPU worker is introduced.
- Spawned chunk workers remain CPU-only, keep torch imports lazy, and never open the vector
  store or checkpoint ledger.
- `gpu_lock` wraps model forward calls only. CPU transfer, conversion, sampling, cache release,
  queues, retries, checkpoint writes, and Qdrant I/O remain outside it.
- Existing backend-aware storage leases and the indexer writer lock remain mutation authority.
  The ledger adds no competing global lock.
- Queue waits, consumer joins, storage calls, and retry sleeps are interruptible and bounded.
  Shutdown cannot close a store reachable by a surviving worker.
- Recovery never mixes model dimensions, schemas, epochs, preprocessing identities,
  namespaces, or incompatible pipeline configurations.
- A checkpoint may lag storage by one unit and cause safe replay, but never lead storage by
  claiming an unconfirmed mutation.
- The default support contract cannot set a file limit below approximately 84,000 files or a
  chunk limit below 250,872. A host that misses the profile fails hardware admission rather
  than relabeling an in-profile corpus as unsupported.
- Retry, checkpoint, memory, deadline, and circuit state originate in the service domain.
- Explicit clean rebuilds retain a protected interval from collection drop until valid
  publication. Control may remain pending; safety failures leave a resumable degraded state.
- Acceptance uses real Qdrant, subprocess restart, and real CUDA. Lower test ceilings may
  exercise production paths but cannot replace behavior with fakes, mocks, patches, skips, or
  mirrored logic.

This ADR supersedes no prior record. It amends accepted decisions narrowly:

- Index performance now defines bounded memory as an end-to-end weighted lifetime contract
  across full, unscoped incremental, and scoped incremental paths, not merely a bounded queue.
- The GPU pipeline keeps one consumer while gaining resource checks, checkpoints, and control
  polling outside forward passes.
- Targeted watcher idle ticks dispatch only when persistent retry policy permits.
- Index backpressure keeps operation timeout, error taxonomy, and bounded retry; this ADR adds
  workflow liveness, persistent circuits, and enforceable RSS/CUDA termination.
- Service job control retains desired-state and API ownership. Matching indexing generations
  replay at most the last unrecorded commit unit rather than all prior work; this remains
  reconciliation, not a suspended stack or instruction pointer.
- Drift content and membership epochs become mandatory checkpoint-signature inputs.

## Implementation

**D1 — Durable run ledger.** Each root and source type receives a transactional SQLite ledger
in the managed per-root index-data area beside existing metadata. Standard-library SQLite
provides atomic local transactions, indexed lookup, and bounded row-wise iteration without
rewriting an ever-growing JSON document after every slice.

A generation records canonical root and collection identity, source type, operation and clean
mode, model and dimension, schemas, content and membership epochs, preprocessing identity,
relevant configuration fingerprint, timestamps, terminal classification, and finalization
phase. An incompatible signature invalidates the generation before further mutation;
compatible retries and daemon recovery resume it.

The durable commit unit is a bounded file segment identified by relative path, source digest,
segment ordinal, and deterministic point IDs. Oversized files use the same weighted
chunk/byte budget as the queue. A file is complete only after every segment commits; deleted
files use explicit deletion units.

Storage mutation completes first and the ledger transaction records completion second. A
crash in between replays only that unit; stable IDs and idempotent deletion make replay safe.
Job progress advances only after the ledger commit. Modified files upsert new segments before
obsolete IDs are deleted and become complete only after both operations return.

After ingestion, an idempotent finalization state machine reconciles stale identities,
atomically replaces metadata from row-wise ledger data, publishes the generation, and compacts
obsolete rows. Each external step advances ledger phase only after success. A clean rebuild
records destructive intent before replacement, checkpoints committed segments normally, and
remains `rebuild_incomplete` until publication; recovery resumes rather than restarting.

**D2 — Bounded full and incremental streaming.** Full, unscoped incremental, and scoped
incremental indexing converge on one production pipeline. CPU-only workers emit deterministic
file segments. The feeder uses a bounded submission window and a weighted queue accounting for
source bytes, chunk text, dense dimensions, sparse entries, and payload overhead.

The single GPU consumer handles one bounded segment or slice at a time. Dense and sparse
outputs transfer to CPU immediately after their forward calls; sparse encoding explicitly
requests CPU retention. Store points exist only for the active unit. After confirmed upsert
and checkpoint, arrays, tensors, point objects, and chunk vector fields are released.

No path materializes or sorts the whole vector-bearing corpus. The ledger carries the durable
manifest and metadata rows, and final metadata streams from it to an atomic replacement file.
Serial and process-pool fallbacks use the same unit, checkpoint, and lifetime rules.

**D3 — Persistent watcher retry and circuit.** Each watcher target, keyed by canonical root
and source, persists consecutive failure count, classified error, last durable progress,
`next_retry_at`, circuit state, and a coalesced convergence marker.

Retryable failures use exponential backoff with bounded jitter and a maximum delay. The
circuit opens after a finite configured count; non-retryable storage, schema, admission, and
memory outcomes open it immediately. While open, changes continue to coalesce but idle ticks
do not dispatch. After delay, one half-open convergence attempt is admitted. Success closes
and resets; another qualifying failure reopens. Manual retry uses the same policy and cannot
erase checkpoint, dirty intent, or history.

**D4 — Durable no-progress deadline.** Runs use a configurable no-progress deadline, not a
total deadline. Only a storage-confirmed, ledger-committed unit or completed finalization phase
advances the clock. Heartbeats, logs, queue motion, encoding without commit, and retries do
not. Storage retry is clamped to the remaining budget; queue waits, sleeps, and shutdown poll
the same deadline. Expiry stops production, requests cooperative unwind, preserves the last
checkpoint, returns `no_progress_timeout`, and opens a watcher circuit. Healthy progressing
runs may continue indefinitely.

**D5 — RSS and CUDA ceilings.** Admission freezes run ceilings from the selected profile and
operator configuration. Snapshots expose current, peak, and ceiling values for RSS and CUDA
allocated/reserved bytes.

Weighted queues and unit-local vector lifetime are the primary RSS bound. RSS is sampled
before dispatch, after committed units, and during prolonged waits. Crossing the stop threshold
halts production, releases queued and active references, commits any already-confirmed unit,
and fails with `rss_memory_ceiling`. Because native allocation can overshoot instantly, bounded
unit size is part of enforcement.

A process-wide allocator limit is configured before model loading to preserve device headroom
for search. The indexer enforces a lower per-run budget relative to admitted baseline, checking
allocated and reserved bytes outside `gpu_lock` before and after each forward slice. On
pressure it reduces the next slice through the finite OOM ladder. If pressure persists, it
transfers completed output to CPU where possible, releases live tensors, empties unused cache,
stops production, preserves the last checkpoint, and fails with `cuda_memory_ceiling`.
Allocator OOM follows the same typed path and never becomes unbounded retry.

Memory termination is a safety failure, not pause or cancellation. During clean rebuild it
may leave a visible resumable `rebuild_incomplete` generation.

**D6 — Corpus admission profiles.** The service publishes named profiles containing backend
mode, minimum host and GPU resources, maximum source bytes, files, generated chunks, and
weighted unit/queue limits. The default managed-service profile admits at least approximately
84,000 files and 250,872 chunks; the incident corpus is an end-to-end acceptance fixture.

Preflight distinguishes `profile_requirements_not_met`, `corpus_limit_exceeded`, and existing
disk-preflight outcomes. Chunk count is measured during streaming; reaching a limit stops
before accepting the next unit, preserves the checkpoint, and returns the structured result.
Limits above the floor and any narrower embedded-local profile require benchmark evidence and
cannot silently redefine the managed-service default.

**D7 — Control safe points.** The service-job-control token is polled before phases and CPU
submission, during bounded queue waits, before and after GPU forward outside `gpu_lock`, before
storage units, and after checkpoint commit. No transition is acknowledged inside a forward
pass, Qdrant operation, metadata replacement, or file replacement.

Normal pause or cancellation stops new production and acknowledges only after the active unit
commits and checkpoints or fails, queues drain without further writes, the consumer terminates,
and writer/GPU resources release. Resume uses a compatible generation and replays at most the
last unrecorded unit. Clean-rebuild control remains pending from drop through completed
publication; this ADR never presents a partial collection as safely paused.

**D8 — Operability and real validation.** The service-domain job snapshot owns generation ID,
committed/replayed units, last durable progress, checkpoint compatibility, retry and circuit
state, memory high-water and ceiling data, profile, and terminal outcome. Adapters do not
recompute policy.

Acceptance interrupts a real multi-unit run and resumes against the same store, invalidates a
checkpoint by changing an epoch, opens and recovers a watcher circuit by stopping and restoring
real Qdrant, exercises low production memory ceilings, proves resource release after control,
compares memory high-water as corpus size doubles, and completes the 250,872-chunk incident
corpus on the declared default profile.

## Rationale

We will mutate storage first and checkpoint second because that provides the strongest recovery
guarantee available without a distributed transaction: a checkpoint cannot claim nonexistent
points, and the only ambiguity replays one deterministic idempotent unit.

We will bound retained bytes across the entire pipeline because queue length alone does not
constrain Python vector lists, sparse tensors, oversized files, metadata, or incremental
materialization. One shared streaming path removes the divergence that let full indexing
appear bounded while incremental indexing exhausted memory.

We will use a no-progress deadline and persistent watcher circuit because operation retry and
a visual stall flag do not bound the workflow. Durable progress distinguishes a legitimately
long index from a stuck one.

We will enforce RSS and CUDA limits because cache flushing and reactive OOM reduction do not
protect the host. CPU transfer and unit-local lifetimes remove known amplification; ceilings
provide an independent stop condition while exact CUDA attribution continues.

We preserve the single-consumer, forward-only GPU lock architecture because the failure is
retained state and missing workflow control, not insufficient GPU concurrency. We preserve the
corpus floor because the incident input is within the capability already promised.

## Consequences

- Interrupted and failed runs resume from storage-confirmed work, replaying at most one
  unrecorded unit instead of restarting from zero.
- Full and incremental memory become functions of unit, queue, and model bounds rather than
  corpus size.
- Watcher failures no longer create immediate retry loops; convergence intent survives behind
  an observable circuit.
- Long progressing jobs remain valid while jobs without durable progress terminate.
- Operators receive one checkpoint, retry, circuit, memory, and admission account everywhere.
- Sparse CPU transfer, SQLite transactions, sampling, and per-unit ledger writes add overhead
  in exchange for bounded memory and recoverability.
- SQLite adds a schema and compaction lifecycle. Corrupt ledgers become explicit
  non-resumable states and never authorize skipping work.
- Modified files may briefly expose old and new IDs together; recovery converges without a
  gap where neither exists.
- Clean rebuilds can retain long control latency and remain visibly incomplete after safety
  failure. Shadow publication is the path to shorten that interval.
- Process-wide CUDA enforcement also constrains search, so profiles reserve search headroom
  and validation covers concurrent search plus indexing.
- Lower-resource machines may reject the default profile explicitly even when corpus counts
  fit; the outcome describes missing resources rather than unsupported corpus.
- Benchmark-derived ceilings above the required floor remain operational data. Reducing the
  floor requires a superseding ADR.
