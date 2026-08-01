---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:a049556bf3c65901172bdb1947995c1c4e8771d3deb47f76f5828731f422ecef'
step_id: 'S20'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Implement the per-root SQLite run generation, signature, commit-unit, finalization, and compaction schema

## Scope

- `src/vaultspec_rag/indexer/_run_ledger.py`

## Description

- Add a versioned per-root SQLite schema for generations, commit units, and explicit file outcomes.
- Canonicalize model, schema, policy, epoch, preprocessing, operation, and content-kind compatibility identity.
- Record storage-confirmed upsert and deletion segments transactionally with idempotent replay.
- Enforce ordered external finalization, immutable terminal generations, bounded row iteration, and post-publication compaction.
- Reject incompatible schemas, invalid transitions, and corrupt database state without authorizing skipped work.

## Outcome

Indexing now has a CPU-only transactional authority that can lag storage by one safely replayable unit but cannot claim an unconfirmed mutation. Compatible attempts resume their active generation; drift invalidates the prior generation before a replacement begins.

## Notes

The production pipeline integration remains owned by the subsequent resumable-pipeline phase. This step establishes the ledger contract without opening storage or importing GPU dependencies.
