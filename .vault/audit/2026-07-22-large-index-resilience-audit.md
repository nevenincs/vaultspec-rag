---
tags:
  - '#audit'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# `large-index-resilience` audit: `Final implementation review`

## Scope

Reviewed commit `994ce2d00e2bab7422da5a641b83510f5241bec2` and the
current checkpoint, retry, finalization, service-operability, GPU-discipline,
and acceptance paths against the accepted research, ADR, implementation plan,
repository rules, and audit template. The review covered bounded producer and
consumer shutdown, storage-before-ledger ordering, replay granularity,
no-progress enforcement, finalization cost, canonical service projections,
single-consumer GPU locking, and real-behavior test integrity.

## Findings

### replay-granularity | medium | One store mutation can leave many ledger units to replay

`CodebaseIndexer._spawn_weighted_consumer` now passes all chunks from a
`WeightedCodeSlice` to one synchronous store upsert, then calls
`CodeRunCheckpoint.record_confirmed_segment` separately for every segment in
that slice. A process loss after the upsert and before or during that loop can
therefore leave multiple storage-confirmed file segments absent from the
ledger. The compatible retry safely re-upserts stable IDs, but it can replay
every unrecorded segment in the slice rather than at most the single
architecture-defined commit unit. The new small-file batching test proves that
multiple file segments share one store mutation, but no interruption test
covers the gap between that mutation and the sequence of ledger transactions.

### resilience-projection | medium | Canonical job snapshots omit the decided resilience state

The service-domain `JobSnapshot` and `JobResourceSnapshot` expose lifecycle,
point-in-time start and finish memory, and resource ownership, but they carry
no generation ID, committed or replayed units, checkpoint compatibility, last
durable progress, retry or circuit state, memory peaks or ceilings, selected
profile, or typed resilience outcome. `jobs.resource_snapshot` likewise
samples only current RSS and CUDA values. Consequently jobs, health, and CLI
cannot project one canonical checkpoint, retry, circuit, memory, and admission
account as required by ADR D8; the corresponding P09 and P11 plan steps remain
open.

### finalization-liveness | high | Large-run reconciliation is neither scale-bounded nor deadline-aware

Commit `994ce2d0` invokes `reconcile_generation_storage` before every code
generation publication. Its same-kind purge classifies each stored point and
calls `_ledger_file_state`, which starts a fresh ordered iteration of the
generation's file-state rows for that point. At the supported floor this can
degrade toward point-count times file-count ledger work. The subsequent
cross-kind reconciliation also performs at least one opposite-collection
lookup per converged file. Neither loop receives the `RunPolicy`, polls a safe
point, clamps storage work to the remaining no-progress budget, or records a
durable finalization phase. A large run can therefore finish ingestion and
then spend an unbounded period in reconciliation, ignoring cancellation and
the no-progress deadline and repeating the same work on resume before metadata
publication.

### acceptance-floor | high | The declared large-corpus completion gate has not been exercised

The new harness defaults to the required 83,624-file and 250,872-chunk corpus,
but the committed automated evidence only runs production indexing at 192 and
384 files for N/two-N memory comparison and at 256 files for search headroom.
The previously recorded 250,872-chunk evidence exercises the producer,
segmenter, queue, and slice packer without model forwards, checkpoint writes,
finalization, or the real backend. There is no retained report from a complete
default harness run, and plan steps S44 through S47 plus the final W05 matrix
remain open. The managed-service completion floor, real-CUDA high-water at
representative scale, concurrent search headroom across a sustained index,
and the newly activated finalization path are therefore not acceptance-proven.

## Recommendations

- Restore one-to-one storage mutation and ledger commit-unit recovery, or add a
  transactional ledger representation whose replay guarantee explicitly
  matches the bounded multi-segment store mutation, then interrupt that exact
  post-store boundary with real storage.
- Replace per-point file-state rescans with a bounded merge or indexed lookup,
  batch cross-kind ownership checks, and thread `RunPolicy` checkpoints and
  durable phase transitions through all reconciliation work.
- Project generation, checkpoint, replay, deadline, retry, circuit, memory
  high-water and ceilings, profile, and typed terminal state from the service
  domain to every adapter without recomputing policy.
- Keep the feature open until the default real-backend harness completes the
  declared floor, N/two-N and concurrent-search CUDA evidence is retained, and
  focused, full-suite, lint, type, and policy gates pass.
