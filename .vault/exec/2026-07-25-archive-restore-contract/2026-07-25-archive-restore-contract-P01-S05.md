---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:397deee7dddfb12aa2cbdc8eb30774f4fb6f850b0dcb8258c3dfb30fe8e4f780'
step_id: 'S05'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# `P01.S05` archive guard coverage

## Scope

`src/vaultspec_rag/tests/test_storage_ops.py`
`src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`

## Description

- Exercise whole-archive age and byte-cap eviction with real filesystem artifacts and manifests.
- Exercise completed-manifest count validation against a real concurrent Qdrant writer.
- Exercise completed-manifest artifact validation after removing a real archived snapshot.

## Outcome

The regression set proves the sweep keeps manifests with their snapshots and that both integrity checks reject their respective missing guard conditions.

Focused validation passed: seven unit archive paths and two real-Qdrant integration guards (9 passed), Ruff, Ty, and scoped whitespace validation.

## Notes

The integration test module has unrelated shared import-migration work. The S05 commit stages only the dedicated missing-artifact guard hunk; the whole-sweep and live-count regressions were committed with their owning implementation steps.
