---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:556d45fae285499673836538a007a5ec99f308765bf1f44fce54c9e2f8f1b4f4'
step_id: 'S10'
related:
  - '[[2026-07-21-large-index-resilience-plan]]'
---

# Convert scoped incremental indexing to bounded production

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`
- `src/vaultspec_rag/indexer/_streaming.py`
- `src/vaultspec_rag/indexer/__init__.py`
- `src/vaultspec_rag/tests/integration/test_codebase_integration.py`

## Description

- Route watcher-style `changed_paths` indexing through the shared weighted file-segment
  producer and rollback-safe incremental publisher introduced for the full and unscoped
  paths.
- Remove scoped retention of `all_new_chunks`, whole-change-set chunk sorting, and the legacy
  outer `embedding_batch_size` publisher.
- Replace scoped detection hashes with hashes from the exact worker reads that produced
  stored chunks before the final partial metadata update.
- Delete the obsolete `_publish_incremental_chunks` branch and its unused
  `_stream_encode_and_upsert_codebase` implementation and package export. No compatibility
  shim remains.
- Extend real weighted and failure/retry integration coverage over both scoped and unscoped
  entrypoints. Repair seeded-partial recovery tests whose missing metadata baseline had
  previously redirected them through a clean rebuild instead of the named incremental path.

## Outcome

Full, unscoped incremental, and scoped incremental code indexing now share one bounded
vector-bearing production path. Scoped memory is proportional to the configured segment,
weighted queue, active slice, inner encode batch, and one non-vector pull-ahead segment rather
than the number of changed chunks. Scoped deletion-only work retains zero vector objects,
snapshots and removes the requested path identities, and publishes metadata last.

The old fixed-count code publisher and its private package export are removed instead of kept
as a fallback. Failure cleanup, unsettled-consumer handling, synchronous storage boundaries,
same-read hashes, and progress phases are identical across both incremental modes.

## Verification

- 126 focused CPU tests pass across the weighted primitives and indexer behavior.
- Scoped weighted production and real preprocess failure/rollback/retry parameters pass with
  the production model and Qdrant store.
- Seeded partial-ID tests now establish a valid full-index metadata baseline, compare exact
  final path IDs and hashes, and assert that scoped reconciliation does not enter the clean
  collection-preparation phase.
- Independent verification reports five focused real GPU/model/Qdrant cases passing and no
  actionable Critical, High, or Medium finding.
- Ruff formatting and lint, BasedPyright, compileall, and diff checks pass for the changed
  implementation and tests.

## Notes

Changed-path and ID/hash sets remain change-set-sized non-vector state; W02 owns driving those
rows from storage-confirmed ledger units. A consumer still live after the shutdown deadline
remains intentionally outside destructive rollback, with convergence and bounded-lock
acceptance assigned to the durable ledger and `S19`.

`S11` and `S18` still own full sparse CPU-retention and enforced memory-ceiling acceptance on
real CUDA. With S10 complete, no code incremental path retains a whole change set of
vector-bearing chunks.
