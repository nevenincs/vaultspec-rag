---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S23'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Drive unscoped incremental indexing from compatible generation and file completion records

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Open unscoped incrementals against a compatible published manifest.
- Preserve ledger-confirmed additions across failure cleanup and retries.
- Delete obsolete identities path by path and checkpoint each confirmed mutation.
- Fall back to a failure-safe full reconciliation when no compatible manifest exists.

## Outcome

Unscoped incremental indexing now resumes compatible file segments and deletion units while
keeping storage-confirmed work durable across failed attempts.

## Notes

The implementation landed through shared-main integration commit `c9b485b6`; this record also
captures the final strict checkpoint arguments and exact one-mutation-per-unit hardening.
Runtime verification is consolidated at the S25 phase boundary.
