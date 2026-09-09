---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:a0039fb8e42af01460432a309e9a391ec6c577e6270f2b480844f813a8af15ae'
step_id: 'S40'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Bind the three grace windows to a positive number with a documented floor so no window can authorise a drop on the cycle that first observes a namespace

## Scope

- `src/vaultspec_rag/config/_schema.py`

## Changes

- `M` `src/vaultspec_rag/config/_schema.py`
- `M` `src/vaultspec_rag/tests/test_config.py`
- `M` `docs/configuration.md`
- `M` `.env.example`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `just check-type-strict` -> `pass`
- `verify:` `just check-markdown` -> `pass`
- `verify:` `just check-links` -> `pass`
- `verify:` `pytest test_config.py test_storage_ops_reclaim.py` -> `pass`
