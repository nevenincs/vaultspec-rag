---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S27'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Add explicit HTTP method handling and typed create, detail, desired-state, retry, and delete client operations using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/serviceclient/_transport.py`
- `src/vaultspec_rag/serviceclient/__init__.py`

## Description

- Carry explicit GET, POST, PUT, and DELETE methods through token recovery and
  authenticated retry.
- Preserve bounded response reads, whole-call deadlines, and structured
  connection outcomes.
- Add typed create, exact detail, desired-state, retry, and deletion helpers.
- Quote exact job identifiers and forward idempotency keys safely.
- Export the client operations through the import-light serviceclient surface.

## Outcome

The shared client transport no longer infers every method from body presence.
Canonical job operations select their wire method explicitly while retaining
the existing authentication recovery, response-size ceiling, timeout budget,
and unreachable-service contract. Ruff, Ruff format, and BasedPyright pass.

Independent review passed with no critical, high, or medium findings.

## Notes

S28 owns real-server method and conflict verification. No model, store, or
Torch import was added. No destructive Git operation or data loss occurred.
