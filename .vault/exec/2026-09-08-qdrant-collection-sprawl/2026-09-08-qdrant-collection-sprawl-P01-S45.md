---
tags:
  - '#exec'
  - '#qdrant-collection-sprawl'
date: '2026-09-09'
modified: '2026-09-09'
body_schema: 'body-v2'
body_hash: 'sha256:d488a47e43e4e15a5424f8f2398f4db8803cb5906722d38d46f00fe2edba02f0'
step_id: 'S45'
related:
  - "[[2026-09-08-qdrant-collection-sprawl-plan]]"
---

# Add a guard test faulting the drop loop with a non-2xx server response rather than a programming error, so the class boundary is asserted at its ambiguous member

## Scope

- `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`

## Changes

- `M` `src/vaultspec_rag/tests/test_storage_ops_reclaim.py`
- `verify:` `just check-python` -> `pass`
- `verify:` `just check-type` -> `pass`
- `verify:` `uv run --no-sync pytest src/vaultspec_rag/tests/test_storage_ops.py src/vaultspec_rag/tests/test_storage_ops_reclaim.py` -> `pass`
