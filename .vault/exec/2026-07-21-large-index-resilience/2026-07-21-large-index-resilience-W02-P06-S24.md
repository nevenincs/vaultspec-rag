---
tags:
  - '#exec'
  - '#large-index-resilience'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:b802cfcc7dc0cd328f36108e6107c0f6d724f1bc15df303c3fe2092cc110d413'
step_id: 'S24'
related:
  - "[[2026-07-21-large-index-resilience-plan]]"
---

# Drive scoped incremental indexing from compatible generation and deletion records

## Scope

- `src/vaultspec_rag/indexer/_codebase_indexer.py`

## Description

- Open scoped incrementals with their exact validated path authority.
- Resume compatible scoped segment evidence without re-embedding confirmed units.
- Replay unrecorded path or stale-point deletions with canonical identities.
- Escalate legacy or incompatible state to failure-safe full reconciliation.

## Outcome

Scoped incremental reconciliation now uses the same storage-confirmed generation contract as
full and unscoped work, including deterministic deletion recovery.

## Notes

The production implementation was preserved by shared-main integration commit `c9b485b6` and
its follow-up preservation commit `8d462ec4`. Runtime verification is consolidated at the S25
phase boundary.
