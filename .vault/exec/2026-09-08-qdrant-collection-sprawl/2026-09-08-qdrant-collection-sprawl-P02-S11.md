---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-08'
modified: '2026-09-08'
body_schema: 'body-v2'
body_hash: 'sha256:5d3a5bcfa0c20ce893d8ed4196754a356a66a37907bbd064774b73a80478ba66'
step_id: 'S11'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Select the ephemeral window in the orphan decision when the namespace root was temp-rooted, keeping point count as the tier selector

## Scope

- `src/vaultspec_rag/storage_reclamation.py`

## Changes

- `M` `src/vaultspec_rag/storage_reclamation.py`
- `M` `docs/storage-maintenance.md`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-markdown` -> `pass`
- `verify:` `just check-links` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_safety.py` -> `pass`
