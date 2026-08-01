---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:8b27281a6908d9f867ea287cb84dc1cb6ee7fc1c7104dd7e805afacf3c80e2e1'
step_id: 'S22'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify document identities, schema, locks, and lifecycle against real local and server Qdrant stores

## Scope

- `src/vaultspec_rag/tests/integration/test_document_store.py`

## Description

- Exercise document upsert, scroll, count, source deletion, and ID deletion.
- Verify independent local locks and lock-free server point operations.
- Verify server payload indexes and deterministic normalized identities.

## Outcome

The independent document store lifecycle passed against QdrantLocal and the
pinned resident server.

## Notes

Phase-boundary gate: 8 real-store tests passed.
