---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:1a56a602899cf2c4a24d06f9ee0dbb1d90d13560d05c01cbf3aec8aeb880f14f'
step_id: 'S18'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Raise the archive size cap default so a full ephemeral drain does not evict the evidence it writes

## Scope

- `src/vaultspec_rag/config/_settings.py`

## Changes

- `M` `src/vaultspec_rag/config/_settings.py`
- `M` `.env.example`
- `M` `docs/configuration.md`
- `M` `docs/storage-maintenance.md`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `pytest src/vaultspec_rag/tests/test_configuration_doc.py src/vaultspec_rag/tests/test_env_example_coverage.py` -> `pass`
