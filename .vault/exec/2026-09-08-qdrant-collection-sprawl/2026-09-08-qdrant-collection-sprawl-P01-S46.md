---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:7b6f431ba7c7a60410226f954e9b1022ad64f63c26dfd9281eac15417a287b52'
step_id: 'S46'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Merge the archive of a retried partial drop into the snapshot manifest already on disk instead of overwriting it, so the first attempt's artifacts stay named

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `M` `src/vaultspec_rag/tests/integration/test_storage_ops_integration.py`
- `M` `src/vaultspec_rag/tests/test_adr_regression.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_adr_regression.py src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_restore.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`
- `M` `src/vaultspec_rag/tests/test_storage_ops.py`
- `M` `src/vaultspec_rag/tests/test_storage_restore.py`

## Notes

A follow-up commit on this Step's file closes a defect this Step's merge and its
sibling refusal introduced together, found by re-reading the pair rather than by a
test. An archive attempt that raises after moving at least one snapshot leaves that
file in the destination under no manifest, and the next attempt takes a fresh
snapshot under a fresh name rather than adopting it. The refusal then rejected an
otherwise complete archive, permanently, over a file that was never published - and
a server too slow to finish an archive is the exact condition this work exists for,
so the sequence is expected rather than exotic.

The archiver now sweeps its destination to exactly what its published manifest names,
which subsumes the superseded-artifact removal the merge did inline. The shared cycle
stand-in was given per-snapshot names, matching what qdrant writes: with one name per
collection a later attempt silently overwrote the residue and the condition could not
be expressed at all.

One mutation note in the restore suite was corrected to the failure now observed
rather than the one observed before the sweep existed.
