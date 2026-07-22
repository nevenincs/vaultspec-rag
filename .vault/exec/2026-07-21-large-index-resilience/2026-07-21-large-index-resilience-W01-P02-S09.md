---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S09'
related:
  - '[[2026-07-21-large-index-resilience-plan]]'
---

# Convert unscoped incremental indexing to bounded production

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `src/vaultspec_rag/indexer/_chunk_worker.py`
- `src/vaultspec_rag/tests/test_chunk_worker_parity.py`
- `src/vaultspec_rag/tests/integration/test_codebase_integration.py`

## Description

- Route changed files from the unscoped incremental scan through the shared weighted code
  producer instead of building and retaining one vector-bearing `all_new_chunks` list.
- Snapshot every attempted path before the first upsert, including new and deleted files.
  Upsert bounded slices synchronously, delete only snapshotted identities absent from the
  successful publication, and publish metadata last.
- Replace detection hashes for changed files with hashes returned by the exact source reads
  that produced their chunks. Batch passthrough now recomputes its hash from the second read
  whose bytes it chunks.
- On a settled producer, encode, or store failure, query the attempted paths and remove IDs
  introduced by that attempt before re-raising. If the bounded shutdown wait expires while
  the consumer is still live, raise a distinct unsettled-consumer error and do not race that
  thread with destructive rollback.
- Generalize full-only helper and diagnostic names now shared by full and unscoped indexing;
  no compatibility alias was introduced, and the unscoped outer `embedding_batch_size` path
  is removed.

## Outcome

Unscoped incremental vector-bearing retention is bounded by the configured file segment,
weighted queue, active slice, inner model batch, and one non-vector pull-ahead segment. A
large change set no longer creates a second corpus-sized chunk list or sorts all changed
chunks at once. Storage-confirmed IDs are accumulated only after synchronous writes, and
metadata describes the same file reads as the successfully stored chunks.

Ordinary failures leave the prior metadata in place and remove points introduced by a
partially completed attempt, so retry reclassifies the affected files and converges. A truly
unsettled consumer is deliberately not queried or deleted concurrently; durable generation
recovery and blocked-consumer acceptance remain owned by W02 and `S19`.

## Verification

- 127 focused CPU tests pass across real chunk parsing, file segmentation, weighted queue
  backpressure, weighted slicing, vector cleanup, and indexer behavior.
- A real batch-passthrough worker test proves the returned hash covers the exact second-read
  bytes used to create chunks.
- Two production-entrypoint integration tests were added: one forces one-chunk segments and
  a two-chunk queue and compares exact Qdrant IDs plus metadata; the other uses a real failing
  preprocess subprocess after an earlier file is queued, verifies rollback and unchanged
  metadata, then retries successfully with balanced progress phases.
- Independent Terra verification reports both focused real GPU/model/Qdrant integrations
  passing. The primary executor did not launch a duplicate run while the shared GPU remained
  occupied by the managed daemon and another indexer. Full sparse-retention and enforced
  ceiling acceptance remain explicitly assigned to `S11` and `S18`.
- Ruff formatting and lint, BasedPyright, compileall, and diff checks pass for the changed
  implementation and tests.
- Independent final review reports no actionable Critical, High, or Medium finding.

## Notes

The unscoped path still retains corpus-sized path and hash maps plus change-set ID sets, all
non-vector state. W02 owns streaming those rows through the durable run ledger. Successful
external preprocessors still execute after the source hash read and therefore retain a
pre-existing source-mutation window; deterministic generation inputs and restart-safe
finalization belong to the ledger wave.

`S10` still owns replacing the scoped incremental chunk accumulator and deleting its obsolete
private publication branch. `S19` owns the acceptance contract for a consumer that remains
blocked beyond the shutdown deadline.
