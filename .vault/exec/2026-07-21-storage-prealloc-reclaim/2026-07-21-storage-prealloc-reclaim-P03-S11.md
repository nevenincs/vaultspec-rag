---
tags:
  - '#exec'
  - '#storage-prealloc-reclaim'
date: '2026-07-21'
modified: '2026-07-22'
step_id: 'S11'
related:
  - "[[2026-07-21-storage-prealloc-reclaim-plan]]"
---

# Test the verb's structured outcomes including the no-drift success and the dry-run no-mutation guarantee

## Scope

- `src/vaultspec_rag/tests/test_cli_service_storage.py`

## Description

- Add `TestReconcileRendering` (4 tests) to `src/vaultspec_rag/tests/test_storage_adversarial.py`.
- Assert `--json` without `--yes` is refused, a converged backend renders as an `already_converged` success, a converging entry carries a null `bytes_after` and zero `reclaimed_bytes`, and human mode states a converged backend plainly.

## Outcome

The CLI envelope and rendering contract are pinned, including the rule that an unwaited or unfinished convergence never renders a reclaim figure. All 18 tests in the module pass.

## Notes

No incidents.
