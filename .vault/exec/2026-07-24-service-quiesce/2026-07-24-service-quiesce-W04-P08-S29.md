---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:0825c7d774012a13d9025640526926461e226ea289c5d12a946e83f50a17679b'
step_id: 'S29'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Repair borrower authority with an opaque captured machine-lock witness, remove raw-path minting, add no-create momentary original-path observation, and make the service machine-lock owner PID durably recoverable

## Scope

- `src/vaultspec_rag/gpu_borrow_lease.py`
- `src/vaultspec_rag/_test_isolation.py`
- `src/vaultspec_rag/_anchor_claim.py`
- `src/vaultspec_rag/_machine_lock.py`
- `src/vaultspec_rag/tests/test_gpu_borrow_lease.py`
- `src/vaultspec_rag/tests/test_existing_anchor_observation.py`

## Description

- Commit `8584c656` bound borrower minting to a registry-backed opaque machine-lock witness.
- Removed raw-path authority minting and added no-create observation of an existing contended owner record.
- Made production machine-lock owner recording durable and fail-closed.

## Outcome

Focused CPU-only borrower and discovery coverage passed. The authority is one-shot, private to the captured witness, and cannot select a caller path.

## Notes

No live GPU, Qdrant child, model, or resident daemon was started.
