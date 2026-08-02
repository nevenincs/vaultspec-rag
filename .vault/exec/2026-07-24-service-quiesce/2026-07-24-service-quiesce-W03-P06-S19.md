---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:ddc02116b78a56a7d5485af01b5d5fb3a4c318e3c1b17d9a04d3bd02dc8a6178'
step_id: 'S19'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Map typed resume recovery failure to the canonical authenticated retryable lifecycle envelope while warming admission remains closed, and return a repaired retry as running without changing the logical job identity

## Scope

- `src/vaultspec_rag/server/_routes.py`

## Description

Map every unachieved lifecycle transition to the canonical HTTP 200 body with
`error` equal to `status`, an operator message, `retryable: true`, and the exact
controller snapshot. Preserve the typed `resume_recovery_failed` state while
admission remains closed in `warming`.

## Outcome

Satisfied by `0df85c2c`. The authenticated production resume route exposes an
unpublished persistence failure as retryable `resume_recovery_failed`, and a
repaired retry returns `running` without replacing the logical job identity.

## Notes

This acceptance is based on static inspection of the named commit and its
checked-in real-registry and real-filesystem proof. No test, service, RAG, CUDA,
GPU, lint, or type-check command was run during reconciliation.
