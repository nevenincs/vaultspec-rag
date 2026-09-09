---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:4816257039bf335b7956c2dee1b0bb5740d25b10a98343f793308f811e4a2122'
step_id: 'S52'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# State the constraint directly in the two reclaim guard-test docstrings that cite a development record instead

## Scope

- `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_ops_reclaim.py` -> `pass`
