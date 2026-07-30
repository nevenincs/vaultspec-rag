---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S13'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---
# Token-local control separation

## Description

Completed token-local cancellation and shutdown separation from global quiesce.

## Outcome

Cancellation and shutdown stay token-local and absorbing, while global quiesce is a distinct safe-checkpoint unwind signal that preserves protected-mutation deferral.

## Evidence

`test_job_control_unit.py` passed its precedence, cancellation, pause, protected-region, and configuration coverage in the focused CPU-only suite.

## Notes

No service process, CUDA allocation, or GPU test was run.
