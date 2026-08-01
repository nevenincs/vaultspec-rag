---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:c0aba29c75e43acba29502fef3bdcfa6bdfd14edb6a0ae8779c16128cee9bf91'
step_id: 'S18'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Add document collection locks, upsert, delete, scroll, and count operations

## Scope

- `src/vaultspec_rag/store.py`
- `src/vaultspec_rag/_store_locks.py`

## Description

- Add a dedicated document collection lock and deterministic multi-lock close order.
- Ensure document vectors and payload indexes independently from vault and code.
- Add document-native upsert, targeted delete, bounded scroll, ID scan, and count operations.

## Outcome

Local Qdrant operations serialize per document collection while server operations
remain backend-concurrent. Document lifecycle methods mutate only the document
collection and expose bounded administrative reads.

## Notes

Formatting, lint, and type checks passed. Real local/server Qdrant verification
is intentionally serialized at the phase boundary.
