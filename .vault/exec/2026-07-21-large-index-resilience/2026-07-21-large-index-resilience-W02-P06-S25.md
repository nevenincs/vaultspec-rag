---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S25'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Stream metadata rows and deterministic point identities through the ledger contract

## Scope

- `src/vaultspec_rag/indexer/_code_meta.py`

## Description

- Stream ordered, converged ledger file states into an fsynced atomic metadata replacement.
- Stamp published metadata with the generation, membership epoch, and content epoch.
- Publish a generation only after metadata publication succeeds.
- Carry compatible published manifests across operational pipeline-sizing changes while retaining exact attempt-resume compatibility.
- Record storage-confirmed stale deletions after replacement upserts complete.

## Outcome

Full, unscoped incremental, and scoped incremental code indexing now publish deterministic file and point evidence through the ledger contract. Operational queue and segment tuning starts a fresh attempt without discarding a content-compatible published manifest, and replacement recovery records stale-ID deletion after the new path is durably indexed.

## Notes

The initial phase boundary exposed two compatibility-ordering defects: pipeline sizing prevented manifest carry-forward, and stale-deletion evidence was rejected after a replacement path reached its indexed state. Both were corrected and covered by real SQLite and real storage/embedding behavior. Final verification passed 19 tests; no tests were skipped or marked as expected failures.
