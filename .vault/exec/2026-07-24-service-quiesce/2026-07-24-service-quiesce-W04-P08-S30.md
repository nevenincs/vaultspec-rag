---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:1c09a47e1fd531aa0270d88a09a1b6d836f966809781a021888b7f8db46f540f'
step_id: 'S30'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Repair captured service targeting with typed pre-isolation machine-pointer capture and revalidation, then use typed initial-bearer transport with one same-token authenticated 401 retry

## Scope

- `src/vaultspec_rag/cli/_gpu_lease.py`
- `src/vaultspec_rag/serviceclient/_discovery.py`
- `src/vaultspec_rag/serviceclient/_transport.py`
- `src/vaultspec_rag/tests/test_gpu_borrow_captured_target.py`
- `src/vaultspec_rag/tests/test_gpu_borrow_cli.py`

## Description

- Commit `6fd2aa35` captures and revalidates a typed pre-isolation machine pointer.
- Bound the initial bearer and one authenticated same-token retry to that revalidation path.
- Preserved token-digest identity checks and fail-closed target rotation handling.

## Outcome

Focused CPU-only captured-target and borrower-route coverage passed. The target retains opaque authority and redacted identity evidence rather than a raw borrower anchor or service token.

## Notes

No live GPU, Qdrant child, model, or resident daemon was started.
