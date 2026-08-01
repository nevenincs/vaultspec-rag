---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-07-31'
body_schema: 'body-v1'
body_hash: 'sha256:34a45013021e80fef4463b0d703a7f06e9f49b4e8e5e1c1f1131ac5b63019ce8'
step_id: 'S32'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Repair GPU pytest coordination by capturing the opaque host-service authority before root registration, passing it unchanged through the guarded coordinator, and validating runner Qdrant only for selected fixture closures that require an isolated child

## Scope

- `conftest.py`
- `src/vaultspec_rag/tests/test_gpu_session_lock.py`

## Description

- Commit `a25bfb03` captures the typed borrower target only before singleton-path isolation when a slow tier remains selectable.
- Ran the stock per-item pytest protocol inside one acknowledged borrower lease.
- Required manifest-verified runner Qdrant only when a selected item closes over the required isolated-child fixture.

## Outcome

Five CPU-only coordinator tests passed, including real loopback pause and resume, cross-process lease contention, retained lease on unacknowledged resume, torch-free import, and Qdrant prerequisite refusal before the test body.

## Notes

The proof used only no-lifespan loopback routes and OS locks. No live GPU, Qdrant child, model, or resident daemon was started.
