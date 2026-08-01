---
tags:
  - '#exec'
  - '#index-job-backend-resilience'
date: '2026-07-23'
modified: '2026-07-23'
body_hash: 'sha256:eaf5ed8f6954e88c5255717ee9387aa9a6ffd955b140cf7a1c6d0277a90ee23b'
step_id: 'S05'
related:
  - "[[2026-07-23-index-job-backend-resilience-plan]]"
---

# Confirm the unrecoverable storage-exhaustion path still raises on the first attempt for a wrapped read as for a write

## Scope

- `src/vaultspec_rag/_store_writes.py`

## Description

- Added `TestUnrecoverableOnReadOperations` with two negative assertions covering read-shaped operations: one raising the managed server's disk-full text, one raising an `ENOSPC` `OSError`.
- Both assert the operation was attempted exactly once, since the attempt count is the only thing distinguishing "raised immediately" from "raised after exhausting the budget".

## Outcome

Confirmed: widening the retry to reads did not make storage exhaustion retryable. Both read-shaped unrecoverable failures raise on the first attempt with a call count of exactly one, matching the write path's existing guarantee. A full disk is as futile to repeat on a read as on an upsert, and the classification is shared, so the property holds by construction and is now asserted for the read shape explicitly.

## Notes

The class docstring names the narrow property the assertions bind to - the attempt count - so a future reader does not relax it into a bare "it raised" check, which would pass whether or not the unrecoverable short-circuit still fired.
