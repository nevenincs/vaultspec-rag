---
tags:
  - '#exec'
  - '#code-document-index-boundary'
date: '2026-07-22'
modified: '2026-07-22'
body_hash: 'sha256:59faa4a1130572ee904d2fbaeeb74bdb481bc251736fc42122ff8025e73cca4f'
step_id: 'S123'
related:
  - "[[2026-07-22-code-document-index-boundary-plan]]"
---

# Verify real local-to-service document migration is idempotent

## Scope

- `src/vaultspec_rag/tests/integration/test_service_storage_migration.py`

## Description

- Create a real local document collection and point.
- Migrate it through the production collection-copy path.
- Replay migration and verify the existing service target remains unchanged.

## Outcome

Local-to-service document migration is count-verified and idempotent.

## Notes

Phase-boundary gate: 8 real-store tests passed.
