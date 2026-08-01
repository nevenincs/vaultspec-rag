---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:585240cff4f3bc18cf5e910ae627871613eaca5d7ae86323638e97f87bd3db22'
step_id: 'S26'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Implement idempotent stale-identity reconciliation and generation publication phases

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Resume ingestion-complete generations directly at their durable finalization phase.
- Make metadata and generation publication idempotent across stale-reconciled, metadata-published, generation-published, and compacted phases.
- Prevent full, unscoped incremental, and scoped incremental retries from re-entering storage ingestion after finalization begins.

## Outcome

Interrupted code generations now continue from the ledger's exact publication phase without replaying completed ingestion or attempting illegal file-state mutations. Generation success and compaction remain ordered after durable metadata publication.

## Notes

Focused verification passed seven checkpoint cases, including real SQLite recovery from each interruptible finalization phase. Ruff and ty passed for all changed modules.
