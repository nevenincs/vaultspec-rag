---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S92'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Route ordinary added and modified watcher paths through the shared disposition and active policy snapshot

## Scope

- `src/vaultspec_rag/watcher.py`

## Description

- Resolve one watcher-generation policy snapshot.
- Classify ordinary added and modified paths through that snapshot.
- Advance policy only on control-file changes while retaining the last valid snapshot on error.

## Outcome

Watcher filtering no longer mirrors extension or preprocessing rules and ordinary events share
the service/index admission authority.

## Notes

Reconciled from production commit `3602ee9`; no additional code change was required.
