---
tags:
  - '#exec'
  - '#service-job-control'
date: '2026-07-22'
modified: '2026-07-22'
step_id: 'S26'
related:
  - "[[2026-07-21-service-job-control-plan]]"
---

# Verify authenticated real-ASGI job CRUD, exact mutations, revisions, idempotency, capacity, force rejection, retry linkage, deletion conflicts, and Location headers using vaultspec-standard-executor

## Scope

- `src/vaultspec_rag/tests/integration/test_service_jobs.py`

## Description

- Exercise authenticated canonical creation and exact detail through the real
  Starlette application.
- Verify idempotent replay, idempotency conflict, and active-work
  deduplication.
- Verify exact-ID-only lookup, force rejection, stale revision conflict, and
  active deletion conflict.
- Verify immediate cancellation, linked retry, terminal deletion, and
  post-deletion absence.
- Verify bounded nonterminal capacity and create and retry `Location` headers.

## Outcome

The focused real-ASGI matrix covers every S26 acceptance dimension through
imported production routes and manager behavior. Both focused lifecycle and
capacity scenarios pass. Ruff, Ruff format, and BasedPyright pass for the
changed test module.

Independent review found three medium-severity coverage and isolation gaps.
Exact mutation prefixes, desired-state replay, and temporary manager
persistence now close them; final Ruff and BasedPyright checks pass.

## Notes

Tests isolate manager persistence and capacity configuration in temporary
directories and restore process configuration. No fake, mock, stub, patch,
monkeypatch, skip, expected failure, destructive Git operation, or data loss
occurred.
