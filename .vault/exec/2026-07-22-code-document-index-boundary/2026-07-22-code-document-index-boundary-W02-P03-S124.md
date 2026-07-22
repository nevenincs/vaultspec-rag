---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S124'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify document prefix pruning, debris classification, and maintenance routes against real storage

## Scope

- `src/vaultspec_rag/tests/integration/test_service_storage_migration.py`

## Description

- Prune a manifest-attributed orphan document namespace from the real server.
- Verify a live document namespace in the bounded maintenance route.
- Classify real on-disk config-less document debris without deleting it.

## Outcome

Document collections participate safely in pruning and maintenance visibility.

## Notes

Phase-boundary gate: 8 real-store tests passed.
