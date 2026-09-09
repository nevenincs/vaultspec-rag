---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:b8e8d11f4dab2fa14b4e60b2b27dbd43403d30455bcd38079164d2a7458f9610'
step_id: 'S49'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Narrow a namespace's recorded collections to what survived when a drop reports partial, so the manifest stops naming what is gone

## Scope

- `src/vaultspec_rag/storage_survey_ops.py`

## Changes

- `M` `src/vaultspec_rag/storage_manifest.py`
- `M` `src/vaultspec_rag/storage_survey_ops.py`
- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_donor_candidates.py src/vaultspec_rag/tests/test_storage_manifest.py src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py src/vaultspec_rag/tests/test_storage_restore.py src/vaultspec_rag/tests/test_storage_safety.py src/vaultspec_rag/tests/test_storage_survey.py src/vaultspec_rag/tests/test_store_donor_reads.py` -> `pass`
