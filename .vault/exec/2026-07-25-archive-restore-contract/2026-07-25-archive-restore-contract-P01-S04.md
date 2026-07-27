---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
step_id: 'S04'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# `P01.S04` completed archive integrity gate

## Scope

`src/vaultspec_rag/storage_reclamation.py`
`src/vaultspec_rag/tests/test_storage_ops.py`
`src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`

## Description

- Record each collection's point count before creating its snapshot.
- Re-read the persisted completed manifest before returning an archive.
- Reject missing, empty, unsafe, malformed, or live-count-divergent snapshot records as archive failures.
- Add a real-Qdrant concurrent-writer regression that advances a collection after its first real snapshot while later snapshots are still being created.

## Outcome

An archive cannot be handed to the destructive caller unless its persisted records, snapshot artifacts, and live collection counts still agree.

Focused validation passed: four archive guard paths plus the real-Qdrant race (8 passed), Ruff, Ty, and scoped whitespace validation. Independent review approved the implementation and real-client proof.

## Notes

The integration test module contains unrelated shared import-migration work. This record's commit stages only the dedicated S04 race-test hunk.
