---
tags:
  - '#exec'
  - '#service-quiesce'
date: '2026-07-29'
modified: '2026-07-30'
body_schema: 'body-v1'
step_id: 'S18'
related:
  - "[[2026-07-24-service-quiesce-plan]]"
---
# CPU search ticket drain proof

## Description

Completed CPU-only search ticket drain and fail-closed admission proof.

## Outcome

Search admission is fail-closed while quiescing: an outstanding controller ticket prevents quiescence, and a closed `SearchLease` rejects before project or compute construction.

## Evidence

`test_search_quiesce_admission.py` passed its two CPU-only real-behavior tests in the focused W02 suite. The test asserts no loaded model, reranker, CUDA state, or project slot after rejection.

## Notes

No service process, CUDA allocation, or GPU test was run.
