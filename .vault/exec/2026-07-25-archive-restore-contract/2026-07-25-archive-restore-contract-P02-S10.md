---
tags:
  - '#exec'
  - '#archive-restore-contract'
date: '2026-07-25'
modified: '2026-08-14'
body_schema: 'body-v1'
body_hash: 'sha256:13fcac5655f6052050836a60d5fd07af3e1e9122ade67d766eeaa17ecfa4ab84'
step_id: 'S10'
related:
  - "[[2026-07-25-archive-restore-contract-plan]]"
---

# Support a dry-run that returns the exact destination collection list and mutates nothing, matching the other storage operations

## Scope

- `src/vaultspec_rag/storage_ops.py`

## Description

Support a dry run that returns the exact list of destination collections an applied restore would create, and writes nothing, matching the preview the other storage operations offer.

## Outcome

Delivered. `RestoreRequest.dry_run` short-circuits before the recovery loop and returns `would_restore` with the exact destination collection list the applied run would create, matching the preview shape of the other storage operations.

The preview is the only opportunity to check that list, since an applied restore into a populated destination is refused outright rather than merged.

Guarded by `test_a_dry_run_names_the_destination_and_creates_nothing`, which asserts both the re-keyed names and that no collection was created.

## Notes

The preview carries more weight here than in the sibling operations. An applied restore into a populated destination is refused outright rather than merged, so the dry run is the only way an operator learns the destination list before committing to it.
