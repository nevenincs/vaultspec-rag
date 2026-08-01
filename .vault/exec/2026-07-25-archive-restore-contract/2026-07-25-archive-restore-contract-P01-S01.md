---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-27'
modified: '2026-07-27'
body_hash: 'sha256:550debed292968e999f02aef1cbb06916788b88004ac193d7b355b187d74c8ea'
step_id: 'S01'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Record the pre-change baseline of the storage suite so any later regression stays attributable

## Scope

- `src/vaultspec_rag/tests/test_storage_ops.py`

## Description

- Run the storage operations suite before archive-contract changes.
- Preserve the terminal test count as the Phase P01 comparison baseline.

## Outcome

`uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_ops.py -q` completed with 78 passed in 2.72 seconds.

## Notes

The live archive owner is `storage_reclamation.py` following the active storage split; no compatibility module was restored.
