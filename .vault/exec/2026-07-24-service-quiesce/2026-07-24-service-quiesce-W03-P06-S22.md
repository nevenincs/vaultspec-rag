---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-30'
modified: '2026-08-02'
body_schema: 'body-v1'
body_hash: 'sha256:40933171f9b64e5c702bb3411e0c533d6e53d0262262aeb315119d44456be4a4'
step_id: 'S22'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---

# Prove through the authenticated production routes, real registry, real manager writer, and real filesystem that an unpublished resume write returns resume_recovery_failed in closed warming, then directory repair and a second resume return running with the same logical job ID and one recovered generation

## Scope

- `src/vaultspec_rag/tests/test_service_quiesce_routes.py`

## Description

Exercise authenticated production resume routing with a real registry, real
manager persistence writer, real filesystem failure, and an adopted service
loop. Retain the failed desired-running job, repair the directory, and recover
one next attempt under the same logical identifier.

## Outcome

Satisfied by `0df85c2c`. The checked-in proof asserts exact failure and success
body shapes, closed warming admission after the unpublished write, same-ID
attempt progression from one to two, one recovered generation, and no pending
dispatch claim.

## Notes

The proof contains no fake, mock, stub, patch, monkeypatch, skip, or xfail. Its
recorded negative mutation targets the `retryable` assertion. The test was not
rerun during this static acceptance.
